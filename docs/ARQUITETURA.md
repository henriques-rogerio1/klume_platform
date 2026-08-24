# Klume Platform — Arquitetura e Modelagem

Resumo do que existe hoje, as decisões que definiram o desenho, e o que ainda falta.
Documento vivo — atualizar conforme a plataforma evolui.

## Visão geral

Arquitetura medalhão (Bronze → Silver → Gold), tudo hospedado no **MotherDuck**
(`Klume_DB_Cloud`), consumido por um app interno (Vanna + Streamlit) e, no futuro,
por um MCP para clientes externos e por ferramentas de BI (Tableau/Power BI) direto
no Gold.

```
Bronze (staging.*)  →  Silver (silver.*)  →  Gold (gold.*)  →  App / BI / MCP
DENATRAN bruto           canonical key         star schema      Vanna+Streamlit
CNPJ Receita              tipado                fato + dims      Tableau/Power BI
```

## Bronze

- **DENATRAN**: tabelas `staging.bronze_2000`...`bronze_2025` no MotherDuck (ingestão
  manual via DBeaver, cobertura irregular — vários anos vazios/parciais). Fonte
  original em Parquet local (`data/bronze/veiculos_raw`), organizada por
  `{ano}/{YYYYMM}/`. Schema bruto: 44-48 colunas, tudo `VARCHAR`, com deriva de
  formato por safra (data com/sem traço, combustível com/sem acento e padding).
- **CNPJ (Receita Federal)**: `staging.bronze_master_cnpj` (Empresas, 40,4M linhas) e
  `staging.bronze_master_estabelecimentos` (Estabelecimentos, com `nome_fantasia` e
  CNAE, 63,8M linhas) — já limpos, usados como referência externa (não duplicados no
  Silver/Gold).
- **FIPE**: `staging.raw_json_fipe` (2026-08-24), populado por um bulk loader
  próprio a partir dos CSVs já extraídos em
  `s3://klume-volumes-s3-platform/Fipe_Csv/` (~354 mil linhas, Cars/Bikes/Trucks,
  ~11 meses de histórico) — não pelo script linha-a-linha do repo separado
  `fipe_api` (levaria horas pra esse volume). `fipe_api` (orquestrado por Mage AI)
  continua sendo a fonte de verdade pra *chamar* a API FIPE; só a ingestão pro
  MotherDuck foi refeita aqui.

## Silver

- **`silver/vehicle_key/canonical.py`** — contrato de chave canônica: `canonical_str`
  (string normalizada `marca|modelo|ano|combustível`) → `vehicle_key` (hash UBIGINT).
  Junto: `COMBUSTIVEL_MAP`, normalização de texto (acento, espaço), e um mapa de
  crosswalk pra códigos de combustível (`G`, `A`, `D`, `E`, `GNV`, `H`, `N`, `X`).
- **`silver/vehicle_key/canonical_sql.py`** — a mesma lógica reimplementada como
  **macro SQL do DuckDB**, gerada a partir do `COMBUSTIVEL_MAP` (nunca dessincroniza
  das duas versões). Motivo: funções Python (`create_function`) não sobrevivem à
  execução híbrida do MotherDuck — uma query que grava numa tabela remota perde a
  referência à função Python no meio do caminho. Macro SQL não tem esse problema.
  **Lição geral: qualquer lógica que precise rodar numa escrita pro MotherDuck deve
  ser SQL puro, não UDF Python.**
- **`silver/normalizers/denatran.py`** — pipeline Bronze → Silver: renomeia colunas
  (utilitário genérico `silver/utils/columns.py`, nunca hardcoded), normaliza
  sentinelas de "ausente" (`'nan'`, `'-'`, `''` → NULL de verdade, `silver/utils/sentinels.py`),
  tipagem real, parser de data que aceita os dois formatos observados, gera
  `canonical_str`/`vehicle_key`/`match_tier`.
- **Split por era**: `silver.veiculos` (`Data de Emplacamento >= 2000`, contrato
  completo com hash) e `silver.veiculos_historico` (`< 2000`, só normalizado, sem
  hash — raramente consultado, custo de manutenção não compensa).
- **Estado atual**: só 2016, 2020, 2025 (amostra) + uma amostra de 1957 foram
  processados — não é o histórico completo ainda.

## Gold

### Por que não é mais uma tabela larga só

A primeira versão de `gold.fato_volumes` era uma única tabela desnormalizada (OBT) —
`marca`, `modelo`, `segmentacao_atualizada` etc. repetidos como texto em cada uma das
~7,7M linhas. Reformulado pra um star schema de verdade porque:
- Não tinha lugar sensato pra documentar colunas (um valor repetido milhões de vezes
  não é onde se pendura metadado de ontologia).
- Chaves precisam ser inteiras pequenas, não hash, porque Tableau/Power BI sofrem em
  performance de join com hash de 64 bits.

A ontologia vive no próprio banco: `COMMENT ON COLUMN` em cada coluna não óbvia, e
`COMMENT ON TABLE` com o **grão** de cada tabela como frase verificável ("uma linha
representa..."), aplicados em `gold/build_volumes.py::apply_comments` /
`apply_grain_comments`. Metodologia: skill `dimensional-modeler` (Kimball, ver
`~/.claude/skills/dimensional-modeler/SKILL.md`) — grão declarado, SCD por atributo,
seleção de linha vencedora sempre completa (nunca `arg_max`/`ROW_NUMBER` por coluna
isolada), determinismo testado construindo o Gold duas vezes seguidas e comparando
linha a linha (`EXCEPT` nos dois sentidos, não só contagem/soma) — as 5 tabelas do
star schema batem 0 diferenças entre builds, chaves surrogate incluídas.

### As duas dimensões de veículo (a decisão mais importante do modelo)

`vehicle_key` (do Silver) não determina sozinho `segmentacao_atualizada`,
`segmentacao_original` nem `tipo_veiculo_principal` — a DENATRAN reclassifica o mesmo
modelo ao longo do tempo (~6,5% dos `vehicle_key` têm mais de uma combinação
observada). Só existe `data_emplacamento` (data da venda), não uma data real de
vigência de classificação — então **não dá pra construir uma linha do tempo confiável
de "quando a classificação mudou"** (SCD Type 2 clássico foi cogitado e descartado por
esse motivo, depois de uma revisão externa apontar o problema).

Solução: duas dimensões, dois propósitos, nenhuma inventando uma linha do tempo:

- **`gold.dim_veiculo_observado`** — histórico fiel. Uma linha por combinação de
  atributos que *realmente coexistiu* num registro real. É essa dimensão que a view
  de compatibilidade usa pras colunas antigas (`segmentacao_atualizada`, `versao`
  etc.) — uma pergunta sobre 2018 mostra a classificação de 2018.
- **`gold.dim_veiculo_atual`** — Type 1 de propósito. Uma linha por `vehicle_key`,
  pegando o registro mais recente completo (nunca por coluna isolada, pra não montar
  uma combinação que nunca existiu). Alimenta a coluna `segmentacao_klume` — "nosso
  melhor entendimento atual", independente de quando o veículo foi vendido. Seleção
  via `QUALIFY ROW_NUMBER() OVER (PARTITION BY vehicle_key ORDER BY ...)` com
  desempate total (todas as colunas do SELECT, incluindo `combustivel_normalizado` —
  faltava antes, existiam ~5.600 grupos de empate reais nos dados; nenhum mudava o
  resultado hoje, mas o `ORDER BY` não era total).

### Demais dimensões

- **`gold.dim_geografia`** — chave natural `codigo_municipio` (código IBGE, ~5.572
  valores, bate com o número real de municípios do Brasil). Usar o nome em texto como
  chave seria errado — nomes colidem entre estados (ex: "Bom Jesus" existe em 6).
  Município e estado vêm da mesma linha vencedora (`QUALIFY ROW_NUMBER`), não de
  `arg_max` independente por coluna — nos dados atuais nunca divergia (nenhum
  `codigo_municipio` observado com mais de um nome/estado), mas `arg_max` por coluna
  isolada podia, em tese, misturar município de uma data com estado de outra. Linha
  sentinela (`-1`, `'NÃO IDENTIFICADO'`) pra nunca deixar um `JOIN` comum
  derrubar linha silenciosamente (~23% dos registros não têm código IBGE — mas TÊM o
  nome do município em texto, por isso o texto também fica direto na fato, não só
  via essa dimensão).
- **`gold.dim_data`** — calendário contínuo (todo dia entre o mínimo e o máximo
  observado, não só datas com venda), chave `YYYYMMDD` inteira (padrão Kimball).
- Atributos de cardinalidade trivial (`cor_predominante`=18, `tipo_venda`=3,
  `match_tier`=2) ficam **inline na fato** — DuckDB/Parquet já comprime string de
  baixa cardinalidade bem, uma dimensão separada só adicionaria join sem ganho real.
- **`gold.dim_empresa`** (2026-08-20) — enriquecimento de `cnpj_basico_faturado`
  (razão social, CNAE, `categoria_empresa`). Escopo deliberadamente restrito aos
  ~8.455 CNPJs que já aparecem em `silver.veiculos` — não os ~65M CNPJs da Receita
  Federal inteira. Fonte: `staging.bronze_master_cnpj` + `main.CNPJ_empresas_final`
  (mesma base "Empresas", schema idêntico, **zero sobreposição verificada** entre
  as duas — juntas cobrem 99,98% dos CNPJs relevantes, nenhuma sozinha passa de
  75%) + linha matriz de `staging.bronze_master_estabelecimentos` (CNAE, cobre
  96,6%). `categoria_empresa` classifica por CNAE: `45xx` = concessionária/comércio
  de veículos (54% do volume faturado por CNPJ), `771x` = locadora (deliberadamente
  mais estreito que `77xx` inteiro, que também pegaria aluguel de máquinas sem
  relação com veículo). Duas sentinelas em `empresa_key` (não em `cnpj_basico` —
  `'00000000'` é um CNPJ real, Banco do Brasil, então não pode virar sentinela):
  `-1` = venda não faturada por CNPJ, `-2` = CNPJ real sem correspondência em
  nenhuma fonte Empresas. **Refresh é manual, desacoplado do pipeline automático de
  upload** (`python gold/build_dim_empresa.py`) — evita escanear ~104M linhas de
  CNPJ a cada arquivo novo de volumes; `gold/build_volumes.py::main()` só constrói
  `dim_empresa` automaticamente na primeira vez (bootstrap), depois disso CNPJ novo
  fica com a sentinela `-2` até o próximo refresh manual.
- **Preço FIPE em `gold.dim_veiculo_atual`** (2026-08-24) — `codigo_fipe`,
  `preco_fipe`, `match_tier_fipe`, `data_referencia_fipe`, mesmo grão Type 1 já
  usado por `segmentacao_klume` (propriedade estável do `vehicle_key`, não da
  venda). Fonte: `silver.fipe_precos` (normalizador novo,
  `silver/normalizers/fipe.py`, populado a partir dos CSVs já extraídos em
  `s3://klume-volumes-s3-platform/Fipe_Csv/`, ~546 mil linhas, grão
  `codigo_fipe × year_code × reference_month` — histórico completo mantido,
  não colapsado, porque módulos futuros de TCO/Preço Transacionado vão
  precisar de trajetória de preço). Três tiers, ativando um conceito que já
  existia documentado desde sempre mas nunca tinha código (`match_tier`
  aparecia em `fato_volumes_base` sem nenhuma linha marcada tier 2):
  - **Tier 1** (na própria fato, não aqui): código FIPE que já vinha embutido
    na linha de origem do DENATRAN — inalterado, ver `fato_volumes_base`
    abaixo.
  - **Tier 2** (novo): hash canônico via `canonical_str_fipe_sql`
    (`silver/vehicle_key/canonical_sql.py`) — mesmo domínio de hash do
    `vehicle_key` de DENATRAN, com um alias de marca pequeno e curado à mão
    (`silver/vehicle_key/marca_alias_fipe.py`: GM/Chevrolet, VW/Volkswagen,
    M Benz/Mercedes Benz, Chery/Caoa Chery, Kia/Kia Motors — nunca fuzzy
    match, e nunca altera o `vehicle_key` real de DENATRAN). **Yield real é
    baixo** (457 de ~30 mil `vehicle_key`, ~8% do volume) porque o campo
    `versao` do DENATRAN não carrega cilindrada (principal atributo
    distintivo do lado FIPE) e as abreviações não alinham token a token
    (`"TORO FREEDOM AT9"` vs. `"Toro Freedom 2.0 16V 4x2 TB Diesel Mec."`) —
    confirmado por comparação direta, não é bug de normalização de texto.
    Decidido não construir uma tabela de tradução de abreviação por marca pra
    fechar esse gap: risco real de atribuir preço do trim errado
    silenciosamente, e o tier 3 abaixo já resolve essa classe de problema
    melhor (ver `docs/architecture-roadmap.md` item B2 pro raciocínio
    completo).
  - **Tier 3**: o crosswalk manual pré-existente (`silver.mapping_table`),
    com dois bugs corrigidos nesta rodada — descartava o código que acabara
    de casar (`SELECT * EXCLUDE(...)`, guardava só o flag) e tratava strings
    de anotação (`'NE'`, `'A'`, `'ND'`, `'ver'`) como match válido. Corrigir
    os dois removeu 54.771 falsos-positivos (2.857.766 → 2.802.995 linhas).
    Continua sendo o tier de maior cobertura real (44% do volume) — curadoria
    humana lida melhor com a divergência de vocabulário do que o hash exato.
  - Tier 2 tem precedência sobre tier 3 quando ambos casam. `NULL` = nenhum
    dos dois achou (~47% do volume hoje).
  - Construído dentro do mesmo `CREATE OR REPLACE` de `dim_veiculo_atual`
    (não é refresh desacoplado como `dim_empresa`) — `silver.fipe_precos` é
    pequeno o bastante (~546 mil linhas) pra reconstruir a cada upload
    automático, e uma segunda passada separada seria apagada no próximo
    rebuild de qualquer forma.

### `gold.fato_volumes_base` (fato física) + `gold.fato_volumes` (view)

A tabela física é estreita: chaves inteiras (`data_key`, `veiculo_key`,
`veiculo_atual_key`, `codigo_municipio`) + poucos atributos triviais inline +
`quantidade` (medida aditiva, sempre `SUM`, nunca `COUNT(*)`).

`gold.fato_volumes` continua existindo, mas como **view** que junta fato+dimensões de
volta no formato plano de sempre (+ a coluna nova `segmentacao_klume`). Motivo: o
Vanna já tem exemplos de treino calibrados contra esse formato plano — LLMs erram bem
mais gerando JOIN do que `SELECT ... GROUP BY` simples. Ferramentas de BI que
conectam direto (Tableau/Power BI) usam as tabelas físicas; o app usa a view.

## Camada de aplicação (`app/`)

- **Vanna** (`app/vanna_client.py`, `app/training_data.py`) — texto → SQL, Claude
  Haiku (barato, tarefa mecânica), ChromaDB local como memória de treino.
  `get_vanna()` treina sozinho no primeiro uso se detectar memória vazia (necessário
  porque `app/chroma_store/` é gitignored — um deploy novo no Streamlit Cloud não
  teria treino nenhum sem isso).
- **Streamlit** (`app/streamlit_app.py`) — pergunta → SQL → seletor de dimensões (sem
  precisar saber SQL, reconstrói a pergunta com a dimensão pedida) → tabela → gráfico
  automático (quando poucas dimensões) → export CSV/Excel. Limite de segurança: acima
  de 300 mil linhas a consulta é recusada (protege contra estourar o limite do Excel
  e a memória do plano gratuito do Streamlit Cloud).
- **Identidade visual**: cores extraídas direto do SVG da logo oficial (`#EB671B`,
  `#141415`), não de uma paleta genérica.
- **Login**: suporte nativo do Streamlit (`st.login`, OIDC/Google) — código pronto,
  desligado até as credenciais OAuth serem configuradas (passo manual no Google Cloud
  Console, incluindo lista de "test users").
- **Histórico de queries**: `app/query_log.py` grava toda pergunta em
  `app.query_log` no MotherDuck (usuário, pergunta, SQL, linhas, duração) — base pra
  futuramente promover perguntas frequentes a exemplos de treino do Vanna.
- **Upload de dados** (`app/pages/1_Upload_Dados.py`) — página operacional, não pra
  vendedor: XLSX novo → casa colunas com `staging.bronze_{ano}` por nome → insere no
  MotherDuck → dual-write pro S3 → **Silver+Gold reconstroem automaticamente, sem
  botão** (mudou de manual pra obrigatório em 2026-08-11: arquivo novo chega poucas
  vezes por mês, então o custo de sempre reprocessar é baixo, e um clique manual
  esquecido deixava o Gold desatualizado sem nenhum aviso). A tela mostra a pipeline
  como etapas nomeadas (`st.status`, estilo Airflow/CI — cada etapa rotulada com a
  função/script por trás), pra facilitar isolar em qual passo algo quebrou.
  Duas proteções, adicionadas depois de um upload de teste (1958)
  deixar 30 linhas órfãs no Bronze por quebrar no passo do S3 (secret AWS não
  configurado na Streamlit Cloud, mas o INSERT no MotherDuck já tinha rodado):
  - **`app.upload_log`** (ts, filename, hash SHA-256 do arquivo, ano, rows_inserted,
    s3_ok) — hash registrado logo após o INSERT no MotherDuck ter sucesso, **antes**
    de tentar o S3, pra uma falha no S3 não deixar uma reexecução vulnerável a
    duplicar linhas. Arquivo com hash já visto no log é bloqueado antes de tocar em
    qualquer tabela. Falha no S3 é capturada (não derruba a página) e fica visível
    como `s3_ok = false`, em vez de crash sem rastro do que já foi inserido.
  - **Schema validation**: rejeita o arquivo antes de qualquer insert se faltar
    alguma coluna obrigatória (`Data de Emplacamento`, `Marca`, `Modelo`,
    `Quantidade`) ou se menos de 50% das colunas do formato DENATRAN de referência
    (`staging.bronze_2024`) baterem — antes disso, coluna faltando virava `NULL`
    silencioso, sem checagem de que o arquivo era o formato certo.

## Decisão de acesso: interno vs. externo

Duas superfícies diferentes pro mesmo Gold, não um mecanismo só:
- **Interno (vendas)**: SQL livre/assistido (Vanna hoje) — baixo risco, o usuário tem
  contexto de negócio pra notar erro.
- **Externo (cliente pagante)**: MCP com **tools fixas** (`get_datamart(nome,
  filtros)`), não SQL livre — necessário pra sustentar a separação de plano pago
  (ex: preço FIPE atual vs. histórico) de forma estrutural, não como política de
  query espalhada. **Ainda não construído.**

## Pendências conhecidas

- **Backfill completo do Silver** — só 2016/2020/2025 + amostra de 1957 processados.
- **Migrar anos de Bronze pro S3** (mesmo bucket do `fipe_api`) antes de apagar do
  MotherDuck — armazenamento perto do limite do plano gratuito.
  `normalize_denatran()` já aceita `read_parquet('s3://...')` como fonte, sem mudança
  de código.
- **Join preço FIPE × volume — feito** (`gold.dim_veiculo_atual`, 2026-08-24, ver
  seção "Demais dimensões"). Pendências restantes: tier 2 tem yield baixo em
  carros por divergência de vocabulário DENATRAN/FIPE (decidido não corrigir
  automaticamente, ver seção acima); limite de retenção pra
  `silver.fipe_precos` ainda não definido (decisão de negócio, só anotada);
  sem `gold.dim_fipe` — sem consumidor de trajetória de preço até TCO/Preço
  Transacionado existirem.
- **Join CNPJ × volume — feito** (`gold.dim_empresa`, 2026-08-20, ver seção "Demais
  dimensões"). Pendências restantes desse item: as 3 tabelas brutas de CNPJ
  (`bronze_master_cnpj`, `CNPJ_empresas_final`, `bronze_master_estabelecimentos`)
  continuam residentes no MotherDuck só pra viabilizar refresh futuro de
  `dim_empresa` — candidatas a migrar pro S3 (mesmo padrão do bronze de volumes),
  ainda não decidido. Também: `staging.fipe_2024/2023/2022` (100% vazias, tentativa
  abandonada de FIPE), `ADHOC_FILES.CNPJ_Empresas` e `staging.estab_y0` (dumps
  brutos já superados pelas versões parseadas) e
  `gold.fato_volumes_snapshot_pre_star` (backup antigo, já testado exaustivamente)
  são candidatas seguras a apagar já — nenhuma ainda foi removida.
- **`gold.semantic_dictionary`** — tabela de ontologia mais rica que
  `COMMENT ON COLUMN` (definição de negócio, exemplos, owner) — ideia registrada,
  não construída.
- **Ativar login** (credenciais Google OAuth) e **migrar hospedagem** pra
  Railway + Supabase Auth (hoje: Streamlit Community Cloud, restrição por e-mail).
  Deve reconstruir `veiculo_atual_key` de qualquer forma se essa migração
  reprocessar dados.
- **MCP pra clientes externos** — não iniciado.
- **Ingestão automática via Gmail/Drive** — planejada e aprovada, mas deliberadamente
  adiada (2026-08-17): `docs/architecture-roadmap.md` item D2 já recomendava manter
  intake manual até virar gargalo de verdade. Plano completo continua salvo, pronto
  pra retomar se isso mudar.
- **4 databases MotherDuck órfãos** (`bronze`, `silver`, `gold`, `my_db`, de
  fevereiro, quase vazios, sem relação com os schemas reais dentro de
  `Klume_DB_Cloud`) — seguros de apagar, ainda não confirmado com o usuário.
