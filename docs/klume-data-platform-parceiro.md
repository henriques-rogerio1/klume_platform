# Klume Data Platform — Visão Técnica

*Stack, composição de dados por módulo e pontos de atenção na integração — documento de referência para o time de produto do K.LUME ONE.*

Agosto de 2026 · Revisão contínua

---

## 1. Stack tecnológico e por quê

Cada escolha abaixo foi calibrada pro tamanho real do time (poucos engenheiros de dados, sem equipe de plataforma dedicada) e pro tipo de carga que a plataforma tem — analítica, agregada, em lote —, não por preferência genérica de ferramenta.

### Camada de dados: MotherDuck (DuckDB na nuvem)

DuckDB é um motor OLAP embarcado com armazenamento colunar e execução vetorizada. Numa consulta como `SUM(quantidade) GROUP BY marca`, o motor lê só as colunas `quantidade` e `marca` — não as outras ~20 colunas de cada linha, que um motor orientado a linha leria de qualquer jeito. Execução vetorizada processa lotes de ~2048 linhas por vez em vez de linha a linha, reduzindo overhead de interpretação e aproveitando melhor cache de CPU e SIMD.

MotherDuck estende isso com uma camada de computação hospedada que sobe sob demanda por sessão e suspende quando ociosa — é o que viabiliza pagar por computação usada, não por instância ligada 24/7. Na prática: o dialeto SQL e o motor são idênticos entre a versão local (embarcada, roda direto num processo Python) e a versão na nuvem — o mesmo SQL testado localmente roda em produção sem tradução.

**Comparado às alternativas na mesma faixa de uso:**

- **PostgreSQL** — armazenamento orientado a linha (heap): ótimo pra "buscar este veículo pelo ID", ruim pra "somar 10 milhões de linhas agrupado por marca" (lê todas as colunas de todas as linhas mesmo usando só duas). Viabilizar essa carga em Postgres exigiria índices de cobertura, visões materializadas ou uma extensão colunar — mais peças pra uma equipe pequena manter. Sem modelo serverless nativo: paga-se por instância provisionada, ociosa ou não.
- **ClickHouse** — comparação tecnicamente mais justa: também colunar, também vetorizado. Sua família MergeTree é de fato melhor pra ingestão contínua em volume muito alto — não é nosso caso, já que o dado DENATRAN chega em arquivo mensal, não como fluxo em tempo real. A favor do DuckDB: dialeto SQL mais próximo do padrão Postgres (ClickHouse diverge mais), e menos desenho manual de schema (motor de tabela, ORDER BY/PARTITION BY) pro nosso volume de milhões — não bilhões — de linhas.

**Resumo comparativo — dimensões adicionais:**

| Dimensão | MotherDuck | PostgreSQL | ClickHouse |
|---|---|---|---|
| Performance analítica | Forte | Fraca sem otimização manual | Forte |
| Busca vetorial indexada (IA/RAG) | Não disponível no servidor hoje* | Sim — pgvector, maduro | Sim — HNSW nativo |
| Custo na nossa escala atual | Faixa comparável ao ClickHouse | Mais barato — resolve outro problema | Faixa comparável ao MotherDuck |

*A extensão de busca vetorial (`vss`, HNSW) existe no DuckDB, mas não está habilitada no lado servidor do MotherDuck hoje. Uma opção prática pra fechar essa lacuna sem trocar o motor analítico principal: complementar com Postgres gerenciado (pgvector incluso em todos os planos, a partir de ~$25/mês) como serviço dedicado só pra esse workload — não como substituto do MotherDuck.

### Orquestração de ingestão externa: Mage AI

Responsável especificamente pelo pipeline de aquisição de preços FIPE — chamar a API pública da FIPE, validar e testar o resultado antes de entrar na plataforma. Mantido como pipeline dedicado e desacoplado do resto: a plataforma principal consome o resultado já processado, não a orquestração em si.

### Pipeline: Python — arquitetura em camadas (Bronze → Silver → Gold)

Dado bruto entra sem alteração (Bronze), é normalizado e ganha uma chave de identidade única por veículo via hash determinístico (Silver), e só então vira modelo dimensional pronto pra consumo (Gold). A chave de identidade é calculada por uma macro SQL — não uma função Python — porque funções Python registradas numa conexão não sobrevivem à execução híbrida do MotherDuck quando a consulta final grava numa tabela remota. Cada camada tem responsabilidade única: corrigir um problema de qualidade na fonte não exige tocar no modelo final, e vice-versa.

### Modelagem: esquema estrela (dimensional, Kimball)

Fatos (volumes de venda) separados de dimensões (veículo, geografia, tempo, empresa) com chaves substitutas inteiras — join por inteiro pequeno é ordens de magnitude mais rápido que join por hash de 64 bits em ferramentas como Tableau/Power BI. Grão de cada tabela documentado formalmente via metadado de catálogo, e testes de determinismo (construir o modelo duas vezes, comparar linha a linha) garantem que o mesmo dado de entrada sempre produz exatamente o mesmo resultado.

### API externa: FastAPI (Python), EC2 (AWS) sob systemd

Interface REST dedicada pra consumo por terceiros, com contrato versionado (`/v1/`), autenticação por chave de API e limite de requisições — desenhada especificamente pra parceiros de produto, como o K.LUME ONE, consumirem dado sem acesso a SQL livre. A conexão com o banco é compartilhada por processo, não uma por requisição, seguindo a orientação da própria MotherDuck pra esse padrão de uso. Documentação gerada automaticamente a partir do próprio código (OpenAPI/Swagger), reduzindo erro de integração do lado do parceiro.

### Armazenamento de origem: S3 (AWS)

Fonte durável dos dados brutos antes de entrarem no pipeline — separado do banco analítico por design, permite reprocessar histórico sem depender de retenção do banco principal.

---

## 2. Composição dos dados por módulo do produto e risco de junção

Cada módulo visível no K.LUME ONE combina fontes de dado com estágios de maturidade diferentes — de completo e verificado a inexistente. O risco concreto não é abstrato: é o que acontece tecnicamente quando uma tela faz `JOIN` entre uma fonte completa e uma parcial (ou inexistente) sem tratar isso explicitamente.

### Radar Nacional de Emplacamentos — Completo e verificado

Junção de veículo (identidade + atributos) com volume vendido, agregado por fabricante e canal (varejo/direta). Não depende de nenhuma outra fonte externa pra existir. O risco de junção aqui já é conhecido e documentado: a janela de confiabilidade do campo de tipo de venda — o dado não tem cobertura de campo estável ano a ano, e "ausente" (arquivo daquele ano não tinha a coluna) é tecnicamente diferente de "presente mas não disponível" (a fonte declarou que não sabe). Por isso o modelo expõe duas medidas aditivas separadas em vez de uma porcentagem única — porcentagem não é aditiva entre grãos diferentes. **Ver também a nota sobre cobertura de anos na seção 3.**

### Simulador de Custo Estratégico (TCO) — Parcial, risco alto

Caso real de junção de risco alto: a própria tela apresenta "Preço Tabela" **e** "FIPE" lado a lado pro mesmo veículo, não um valor só — porque a cobertura de preço FIPE por casamento automático cobre cerca de metade do volume total. A outra metade fica sem preço por dois motivos, não um só: (1) o cadastro de origem não registra o mesmo nível de detalhe técnico do veículo — cilindrada do motor, por exemplo — que a FIPE usa pra diferenciar entre versões; e (2) mesmo com uma tradução perfeita de nomenclatura, parte do gap não fecharia de qualquer forma, porque a própria FIPE só precifica por combinação de motor/câmbio/combustível, não por pacote de acabamento — e constrói esse catálogo por pesquisa de mercado mensal, não por contagem exaustiva, então uma versão de edição limitada pode genuinamente não ter entrada na FIPE, independente do método de casamento. Fechar isso com um dicionário de tradução de abreviação foi avaliado e descartado deliberadamente: o risco de atribuir silenciosamente o preço de uma versão errada é pior que não ter o dado, e o teto estrutural do item (2) reduz o ganho esperado.

Além do preço, o cálculo de TCO em si (depreciação, manutenção, seguro) depende de tabelas de taxa que não existem em nenhum lugar da plataforma hoje — ausência total de fonte, não cobertura parcial. Uma tela que junta volume + FIPE + manutenção/seguro num cálculo único sem tratar cada peça com o nível de confiança certo mistura dado bem verificado, dado parcialmente confiável e dado que simplesmente não existe do nosso lado.

### Identificação do Mercado de Locadoras — Parcial

Depende de ligar o veículo vendido à empresa que faturou a compra (via CNPJ) e classificar essa empresa por ramo de atividade. Cobertura de identificação alta (96%+) mas não total — existe uma fração real de vendas sem CNPJ associado, e outra com CNPJ sem correspondência em nenhuma base de referência disponível, duas situações tecnicamente diferentes entre si e de "empresa identificada mas não é locadora". Se a tela filtra só `categoria = Locadora`, o volume real fica sistematicamente subestimado: parte do volume de locadoras pode estar dentro do grupo "não identificado" por quebra na cadeia CNPJ → empresa → classificação, não por não ser locadora de fato.

### Incentivos Comerciais — Em desenvolvimento, equipe interna

Em desenvolvimento por outra frente da equipe Klume. Usa como chave de identificação do veículo a mesma nomenclatura/código FIPE que já aparece no módulo de TCO — um ponto real de integração entre os dois módulos no futuro, não uma fonte isolada.

### Preço Transacionado & Itens de Especificações — Não existe

Ainda sem fonte de dado nenhuma do nosso lado. Preço Transacionado depende de dado de terceiro ainda não licenciado; Especificações depende de um histórico de versão/geração de veículo que exige um desenho de modelo diferente do atual — nossa dimensão de veículo guarda "o que sabemos agora", não "o que era válido em cada momento". Qualquer tela que pareça mostrar algo nesses dois módulos hoje está usando dado de demonstração, não dado real da plataforma.

---

## 3. Notas

O maior objetivo estrutural da base Klume não é ter cada fonte de dado isolada e correta — é conseguir **reconciliar todas elas por uma identidade de veículo comum**. Cada módulo do K.LUME ONE (seção 2) só entrega valor de verdade na medida em que consegue juntar fontes diferentes sobre o mesmo veículo sem erro silencioso. Três riscos concretos pra essa meta, já testados contra dado real, valem antecipar:

### Câmbio no campo `versao` da DENATRAN não é peculiaridade da FIPE

Medido contra dado real (carros, ano/modelo 2020+): só ~10% das versões DENATRAN carregam algum token de câmbio reconhecível — e mesmo esses vêm às vezes colados a outro código sem separador (`10TMT`, `16CVT`). A FIPE declara câmbio de forma consistente (sufixo `Aut.`/`Mec.`); a DENATRAN, na maioria dos casos, não declara nada. Isso não é um problema exclusivo do casamento com a FIPE — o roadmap interno já registra o mesmo risco pro futuro módulo de Preço Transacionado, que também vai depender de mapear a identidade do veículo contra uma fonte de terceiro que não chega no formato DENATRAN. Mitigação real já em uso (não hipotética): o módulo de Incentivos Comerciais, em desenvolvimento, chaveia por código FIPE em vez de texto de versão — reconciliar por código compartilhado sempre que possível. Mas isso só resolve pros veículos que já têm esse código resolvido; onde não têm, a mesma lacuna reaparece com qualquer fonte nova.

### Mesmo quando o casamento funciona, a própria FIPE pode ficar dúbia

A FIPE monta o catálogo a partir de pesquisa de mercado mensal em parceria com concessionárias e revendedores em todo o Brasil — não uma contagem exaustiva de venda —, por isso um veículo pode simplesmente não ter código FIPE atribuído. Motivos mais comuns, confirmados: o modelo é muito recente (menos de 6 meses no mercado), é uma versão especial de produção limitada, o modelo foi descontinuado há muitos anos, ou há erro na seleção de marca/modelo de quem consulta. Pra edições limitadas especificamente — o caso mais relevante pra montadoras/locadoras que usam o K.LUME ONE — isso significa que a ausência de preço FIPE nem sempre é falha nossa de casamento: às vezes o preço genuinamente não existe na fonte.

Consequência prática: crescer o cruzamento manual (tier 3, curado por pessoa) continua sendo a alavanca certa pra fechar essas lacunas — matching automático melhor não resolve nem o problema de câmbio ausente (a fonte não declara) nem o teto da própria FIPE (a fonte não cataloga).

### 2016, 2020 e 2025 foram escolhidos de propósito — não é amostra aleatória

Essas três safras representam três formatos genuinamente diferentes que a fonte DENATRAN já usou ao longo do tempo — testar o pipeline contra as três valida que ele lida com a variação real da fonte, não só com o formato mais recente. Diferenças de formato confirmadas entre elas:

- **Data de emplacamento**: `'2016-01-02'` (ISO, com traço) em 2016 vs. `'20250130'` (compacto, sem separador) em 2025.
- **Combustível**: `'Álcool / Gasolina'` (acentuado, com espaçamento) em 2016 vs. `'ALCOOL/GASOLINA'` (limpo) em 2025.
- **Sentinela de ausência do código FIPE**: string `'nan'` nas safras mais antigas vs. `'-'` em 2025 — dois sentinelas diferentes pra "sem match", tratados explicitamente cada um no seu formato.

Consequência direta dessas diferenças de formato — a completude de campo também varia entre as três safras, mesmo padrão já visto isoladamente no campo `tipo_venda`, agora confirmado em mais três:

| Campo | 2016 | 2020 | 2025 |
|---|---|---|---|
| Canal de venda (`tipo_venda`) | 100% ausente | completo | completo |
| Município (`codigo_municipio`) | 100% ausente | ~100% presente | 100% presente |
| CNPJ faturado | 0% | 99,9% | 100% |
| FIPE embutido (tier 1) | 0% | 0% | 32,5% |

Consequência prática: um filtro de período que inclua 2016 perde geografia e canal de venda inteiramente nesse ano — não é ruído, é 100%. Qualquer leitura que dependa de preço FIPE já vindo embutido na própria linha de origem (tier 1, sem precisar de casamento) só funciona de fato a partir de 2025.

---

*Klume Data Platform · Documento técnico de integração · K.LUME ONE*
