# Klume Platform — Dicionário de Dados

Complementar a `docs/ARQUITETURA.md` (desenho e fluxo) — aqui o foco é tabela por
tabela, coluna por coluna: o que cada uma significa e o que acontece com o dado
entre uma fase do pipeline e a próxima. Escopo: as três camadas do fluxo Bronze →
Silver → Gold.

---

## Bronze

Dado bruto da fonte, sem conversão de tipo — texto como veio, uma tabela por ano de
emplacamento. Cobertura por ano/mês é irregular por histórico de ingestão, não por
perda de dado — ver seção de retenção em `docs/ARQUITETURA.md`.

Schema compartilhado entre os anos (~46 colunas):

| Coluna (fonte) | Observação |
|---|---|
| Data de Emplacamento | dois formatos observados na fonte ao longo dos anos — normalizado no Silver |
| Número do Chassi / Placa do Veículo | identificadores do veículo físico — não usados na chave de negócio |
| Tipo do Faturado / Identificação do Faturado | quando `Tipo do Faturado = 'CNPJ'`, dispara a extração do CNPJ raiz no Silver |
| Tipo de Venda | confiável só a partir de ~2020 — anos anteriores têm essa coluna majoritariamente vazia |
| UF do Faturado / Tipo do Proprietário / UF de Jurisdição | atributos cadastrais do comprador |
| Código do Município / Município do Emplacamento / Estado do Emplacamento | geografia da venda — o código é o código IBGE, chave natural da dimensão de geografia no Gold |
| Ano de Fabricação / Ano Modelo | ano do veículo, não da venda |
| Código DENATRAN / Marca / Modelo / Versão | identidade do veículo — `Marca + Versão + Ano Modelo + Combustível` compõem a chave de negócio (`vehicle_key`) usada para reconciliar o mesmo veículo entre vendas e entre fontes |
| Tipo de Veículo Principal / Tipo de Veículo DENATRAN | grafia pode variar por ano da fonte — preservado como veio no Bronze, normalizado a partir do Silver/Gold |
| Segmentação Atualizada / Segmentação Original | classificação de segmento como veio na fonte daquele ano |
| Espécie de Veículo / Cód. Carroceria / Carroceria / Cor Predominante / Combustível / Potência / Cilindradas | atributos técnicos do veículo |
| Número de Lugares / Capacidade de Carga / Peso Bruto Total / Capacidade Máxima de Tração / Número de Eixos | atributos técnicos de capacidade |
| Procedência / Situação do Chassi / Restrições / Veículo cadastrado BIN | atributos cadastrais/restritivos |
| Quantidade | medida — base do volume agregado no Gold |
| FIPE / Preço | código FIPE e preço **já vindos na própria linha da fonte** — é o match "tier 1" de preço, distinto do enriquecimento por catálogo FIPE feito no Gold |

Existe também uma fonte Bronze separada para o catálogo de preços FIPE (grão:
código FIPE × ano-modelo × mês de referência), usada para o enriquecimento de preço
no Gold.

---

## Silver

### Tabela principal de emplacamentos

Uma linha por linha original do Bronze (sem agregação ainda), com tipos reais e três
colunas derivadas:

| Coluna derivada | Descrição |
|---|---|
| `cnpj_basico_faturado` | só preenchida quando faturado por CNPJ — 8 primeiros dígitos (raiz) do CNPJ, normalizado a partir do texto da fonte |
| `vehicle_key` | hash determinístico de `marca + versão + ano_modelo + combustível` — chave de negócio que identifica "o mesmo veículo" entre vendas diferentes e entre a fonte de emplacamentos e o catálogo FIPE (mesmo domínio de hash nos dois lados, permite reconciliar por igualdade em vez de comparação de texto) |
| `match_tier` | `1` = preço/código FIPE já veio na própria linha de origem; `3` = achado via crosswalk manual (marca/versão → código FIPE); `NULL` = nenhum dos dois |

Registros anteriores ao ano 2000 (ou sem data parseável) ficam numa tabela separada,
com o mesmo schema **menos** as 3 colunas derivadas acima — deliberadamente fora do
contrato de chave de negócio, não alimentam o Gold hoje.

### Catálogo de preços FIPE

Grão: código FIPE × ano-modelo × mês de referência — histórico completo, não
colapsado para "preço mais recente" (essa decisão fica a cargo de quem consome no
Gold). Tem a mesma coluna `vehicle_key` (hash), permitindo o join com a tabela
principal de emplacamentos.

### Crosswalk manual FIPE

Tabela de correspondência marca/versão → código FIPE, mantida manualmente, usada
como fallback (tier 3) quando o match automático por hash não encontra
correspondência.

---

## Gold

Star schema — 4 dimensões + fato + uma view de compatibilidade em formato plano
(usada pelo app interno de consulta). Toda tabela tem grão e colunas documentados
diretamente no catálogo do banco (`COMMENT ON TABLE`/`COMMENT ON COLUMN`).

### Dimensão de veículo — histórico observado

**Grão**: uma linha por combinação de atributos de veículo que realmente coexistiu
em pelo menos um registro do Silver — histórico fiel, sem inferir quando a
classificação mudou.

| Coluna | Descrição |
|---|---|
| chave surrogate (inteira, 64 bits) | ver nota sobre chaves surrogate ao final |
| `vehicle_key` | chave de negócio (hash) que agrupa as versões históricas do mesmo veículo |
| marca, modelo, versão, ano_modelo, combustível_normalizado, segmentação_atualizada, segmentação_original, tipo_veículo | atributos como registrados naquela venda específica — não são a classificação atual |

### Dimensão de veículo — entendimento atual

**Grão**: uma linha por `vehicle_key` — melhor entendimento atual (Type 1),
atributos da venda mais recente, selecionados como linha completa.

| Coluna | Descrição |
|---|---|
| chave surrogate | ver nota sobre chaves surrogate ao final |
| marca, modelo, versão, ano_modelo, combustível_normalizado | atributos atuais |
| segmentação (Klume) | classificação mais recente conhecida para esse veículo, independente de quando foi vendido |
| código FIPE, preço FIPE, tier de match, mês de referência | enriquecimento por catálogo FIPE — tier 2 (match por hash contra o catálogo) tem prioridade sobre tier 3 (crosswalk manual); mês de referência pode ficar parado no último mês em que o veículo existiu no catálogo, caso ele tenha saído de linha |

### Dimensão de empresa

**Grão**: uma linha por CNPJ raiz observado como faturador de algum emplacamento,
mais duas linhas sentinela (venda não faturada por CNPJ / CNPJ sem correspondência
cadastral encontrada).

| Coluna | Descrição |
|---|---|
| razão social, natureza jurídica, porte, capital social | atributos cadastrais |
| nome fantasia, situação cadastral, CNAE principal, município/UF do estabelecimento | vêm do estabelecimento matriz |
| categoria | classificação por CNAE: concessionária/comércio de veículos, locadora (aluguel de veículos, deliberadamente mais estreito que aluguel de máquinas/equipamentos em geral), ou "outro" |

Escopo deliberadamente restrito aos CNPJs que já aparecem nos emplacamentos — não a
base cadastral completa da Receita Federal.

### Dimensão de geografia

**Grão**: uma linha por código de município (código IBGE) — nome mais recentemente
observado. ~23% dos registros de origem não têm código IBGE informado (mas têm o
nome do município em texto, preservado direto na fato).

### Dimensão de calendário

**Grão**: uma linha por dia do calendário contínuo entre a menor e a maior data de
emplacamento observada — inclui dias sem venda.

### Fato de volumes

**Grão**: soma de `quantidade` para uma combinação única de data, veículo
(observado), veículo (atual), município, cor, tipo de venda, tier de match e CNPJ
faturado — não existe grão de venda individual.

Medida principal é sempre aditiva (soma), nunca contagem de linhas. Existe uma
medida auxiliar (`quantidade com tipo de venda conhecido`) para cálculos de
participação varejo-vs-direta sem precisar repetir a exclusão de nulos em cada
consulta — a coluna de tipo de venda só é confiável a partir de ~2020.

### Nota sobre chaves surrogate

As chaves inteiras das dimensões (veículo observado, veículo atual, empresa) são
hash determinístico de 64 bits da respectiva chave de negócio, não um inteiro
sequencial — escolha deliberada para que a chegada de dado novo nunca desloque a
chave de uma entidade já existente (propriedade de estabilidade referencial, testada
contra produção). Ferramentas de BI que conectam direto ao banco tendem a ter
desempenho de join um pouco pior com chave hash do que com inteiro sequencial
pequeno — se uma integração desse tipo entrar em pauta, vale revisitar se uma camada
de apresentação com inteiro compacto compensa nesse momento específico.
