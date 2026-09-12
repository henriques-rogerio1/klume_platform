# Klume Platform — Dicionário de Dados

Documento complementar a `docs/ARQUITETURA.md` (que descreve o desenho e o
fluxo) — aqui o foco é tabela por tabela, coluna por coluna: o que cada uma
significa e o que acontece com o dado entre uma fase do medalhão e a
próxima. Gerado a partir do catálogo real do banco (`duckdb_columns()`,
`duckdb_tables()`, `information_schema.tables`).

**Desde 2026-09-11, todas as tabelas de `staging`/`silver`/`app` têm
`COMMENT ON TABLE` (grão) aplicado direto no banco, e as colunas não-óbvias
têm `COMMENT ON COLUMN`** — mesmo padrão que já existia só pro Gold
(`gold/build_volumes.py::apply_comments`/`apply_grain_comments`), agora
estendido via `silver/comments.py`, `app/comments.py` e
`scripts/apply_bronze_comments.py`. O texto abaixo é o mesmo que aparece se
alguém abrir o catálogo direto no MotherDuck (Power BI, Tableau, MotherDuck
UI) — não é só um artefato deste markdown.

Escopo: os schemas que fazem parte do fluxo Bronze → Silver → Gold —
`staging`, `silver`, `gold`, `app` (tabelas de controle do produto). O
schema `main` tem uma quantidade grande de views que **não** fazem parte
desse desenho — ver a nota no final do documento antes de assumir que algo
lá é intencional.

---

## Bronze (`staging`)

### Schema compartilhado DENATRAN — `staging.bronze_YYYY`

Uma tabela por ano de emplacamento (`staging.bronze_1958`,
`staging.bronze_2000` até `staging.bronze_2025` — faltam `2003` e `2015` no
catálogo atual), todas com o mesmo layout de 46 colunas (texto bruto da
fonte, sem conversão de tipo — isso só acontece no Silver). Cobertura por
ano/mês é irregular por construção histórica, não por perda de dado — ver
`docs/POST-MORTEM.md`, "Ingestão histórica via cliente SQL manual".

| Coluna (fonte) | Tipo | Observação |
|---|---|---|
| Data de Emplacamento | VARCHAR | formato `YYYYMMDD` na maioria dos anos, `YYYY-MM-DD` em alguns — ver `TRY_STRPTIME` duplo no Silver |
| Número do Chassi / Placa do Veículo | VARCHAR | identificadores do veículo físico — não usados na chave de negócio (`vehicle_key`), só texto de referência |
| Tipo do Faturado / Identificação do Faturado | VARCHAR | `Tipo do Faturado = 'CNPJ'` dispara a extração do CNPJ raiz no Silver (ver `cnpj_basico_faturado` abaixo) |
| Tipo de Venda | VARCHAR | confiável só a partir de ~2020 — 2016 é 100% nulo nesta coluna (campo não veio na fonte daquele ano) |
| UF do Faturado / Tipo do Proprietário / UF de Jurisdição | VARCHAR | atributos cadastrais do comprador |
| Código do Município / Município do Emplacamento / Estado do Emplacamento | VARCHAR | geografia da venda — `Código do Município` é o código IBGE, vira chave natural de `gold.dim_geografia` |
| Ano de Fabricação / Ano Modelo | VARCHAR | ano do veículo, não da venda |
| Código DENATRAN / Marca / Modelo / Versão | VARCHAR | atributos de identidade do veículo — `Marca/Versão/Ano Modelo/Combustível` compõem a string canônica (`canonical_str`) que vira `vehicle_key` no Silver |
| Tipo de Veículo Principal / Tipo de Veículo DENATRAN | VARCHAR | grafia varia por safra (ex.: "Moto" vs "MOTOCICLETA") — preservado como veio, sem normalizar no Bronze |
| Segmentação Atualizada / Segmentação Original | VARCHAR | classificação de segmento como veio na fonte daquele ano — "Atualizada" já reflete revisões da própria DENATRAN, "Original" não |
| Espécie de Veículo / Cód. Carroceria / Carroceria | VARCHAR | atributos de carroceria |
| Cor Predominante / Combustível / Potência / Cilindradas | VARCHAR | atributos técnicos — `Combustível` é normalizado no Gold via `map_combustivel_sql` |
| Número de Lugares / Capacidade de Carga / Peso Bruto Total (PBT) / Capacidade Máxima de Tração (CMT) | VARCHAR | atributos técnicos de capacidade |
| Procedência / Situação do Chassi / Número de Eixos | VARCHAR | atributos cadastrais/técnicos |
| Restrição 1-4 / Data Limite da Restrição Tributária / Veículo cadastrado BIN | VARCHAR | restrições registradas no DENATRAN |
| Quantidade | VARCHAR | medida — vira `INTEGER` no Silver, é a base de `SUM(quantidade)` no Gold |
| FIPE / Preço | VARCHAR | código FIPE e preço **já vindos na própria linha do DENATRAN** — isso é o "tier 1" de match FIPE (ver `match_tier` no Silver e `fato_volumes_base.fipe/preco` no Gold), distinto do enriquecimento por catálogo (tier 2/3) |

**Transformação Bronze → Silver** (`silver/normalizers/denatran.py`): rename
para snake_case → `blank_to_null` (strings vazias/sentinela viram `NULL`) →
cast de tipo (`TRY_CAST`/`TRY_STRPTIME`, nunca `CAST` puro — linha com valor
fora do formato esperado vira `NULL` na coluna, não derruba a carga) →
split por `data_emplacamento >= 2000` (`*_recent` seguem para
`canonical_str`/`vehicle_key`/`match_tier`; `*_historico` não).

### `staging.raw_json_fipe`

Bronze da fonte FIPE — um registro por combinação `codigo_fipe × ano-modelo
× mês de referência`, como a API pública devolve.

| Coluna | Tipo |
|---|---|
| brand_name, model_name, codeFipe, year_code, fuel, fuelAcronym, reference_month | VARCHAR |
| vehicle_type, model_year | INTEGER |
| price | VARCHAR (ex.: `"R$ 10.892,00"`, convertido para `DECIMAL` só no Silver) |

**Transformação Bronze → Silver** (`silver/normalizers/fipe.py`): rename +
`codeFipe→codigo_fipe`/`fuelAcronym→fuel_acronym` → parsing de `price`
(`"R$ 10.892,00"` → `10892.00`) e de `reference_month` ("agosto de 2026" →
`DATE '2026-08-01'`, convenção: primeiro dia do mês) → `vehicle_key =
hash(canonical_str_fipe_sql(brand_name, model_name, model_year, fuel))`, no
mesmo domínio de hash do lado DENATRAN — é isso que permite o join tier 2
sem comparação de texto.

### `staging.ingest_control` e `staging.veiculo_raw`

Ambas com **0 linhas** no catálogo atual. `ingest_control` tem schema de
controle de ingestão (`file_name`, `sheet`, `rows`, `ts_ingest`,
`parquet_path`); `veiculo_raw` replica exatamente o schema de
`staging.bronze_YYYY`. Nenhuma das duas aparece referenciada em
`silver/normalizers/*.py` nem em `app/pages/1_Upload_Dados.py` — parecem
tabelas preparadas para um padrão de controle que não chegou a entrar em
uso (o controle de upload real hoje vive em `app.upload_log`, ver abaixo).
Não removidas aqui porque "tabela vazia sem uso aparente" não é a mesma
confirmação de segurança que as remoções já documentadas em
`docs/POST-MORTEM.md` (verificação explícita de conteúdo antes de apagar).
Desde 2026-09-11, as duas têm `COMMENT ON TABLE` marcando explicitamente
"TABELA ÓRFÃ" no próprio catálogo — quem abrir o banco direto (sem ler este
markdown) já vê o aviso.

---

## Silver

### `silver.veiculos`

Tabela principal do Silver — emplacamentos de `data_emplacamento >= 2000`,
uma linha por linha original do Bronze (nenhuma agregação ainda acontece
aqui). É a fonte de todo o Gold de volumes.

| Coluna | Tipo | Origem/transformação |
|---|---|---|
| data_emplacamento | DATE | `TRY_STRPTIME` duplo (`%Y%m%d` ou `%Y-%m-%d`) sobre o texto do Bronze |
| numero_chassi, placa_veiculo | VARCHAR | rename direto |
| tipo_faturado, tipo_venda, uf_faturado, tipo_proprietario, uf_jurisdicao | VARCHAR | rename direto |
| **identificacao_faturado** | VARCHAR | **mascarada (2026-09-09)**: só passa o valor bruto quando `tipo_faturado = 'CNPJ'` — `CPF`/`Desconhecido`/`Outros` viram `NULL`. Achado ao revisar este dicionário: CPF de pessoa física é dado pessoal sob LGPD, estava sendo persistido em texto puro sem nenhum uso downstream (nada em Gold/app lê esta coluna — só `cnpj_basico_faturado` abaixo, que já é derivada só do ramo CNPJ). Ver `docs/POST-MORTEM.md`. |
| codigo_municipio | INTEGER | `TRY_CAST` do texto do Bronze |
| municipio_emplacamento, estado_emplacamento | VARCHAR | rename direto |
| ano_fabricacao, ano_modelo | INTEGER | `TRY_CAST` |
| codigo_denatran, marca, modelo, versao, tipo_veiculo_principal, tipo_veiculo_denatran, segmentacao_atualizada, segmentacao_original, especie_veiculo, cod_carroceria, carroceria, cor_predominante, combustivel | VARCHAR | rename direto, sem normalizar ainda (normalização de combustível é só no Gold) |
| potencia, cilindradas, numero_lugares, capacidade_carga, peso_bruto_total_pbt, capacidade_maxima_tracao_cmt, numero_eixos, quantidade | INTEGER | `TRY_CAST` |
| procedencia, situacao_chassi, restricao_1-4, data_limite_restricao_tributaria, veiculo_cadastrado_bin | VARCHAR | rename direto |
| fipe | VARCHAR | código FIPE tier 1 (já veio na linha de origem) |
| preco | DECIMAL(12,2) | preço tier 1, `TRY_CAST` |
| **cnpj_basico_faturado** | VARCHAR | **derivada**: só quando `tipo_faturado = 'CNPJ'` — normaliza `identificacao_faturado` (remove sufixo `.0` de float mal formatado, preenche com zero à esquerda até 14 dígitos) e pega os 8 primeiros dígitos (raiz do CNPJ). É a chave de junção com `gold.dim_empresa` |
| **canonical_str** | VARCHAR | **derivada**: string canônica de `marca + versao + ano_modelo + combustivel` (função SQL `canonical_str_denatran_sql`, registrada como macro DuckDB — roda no mesmo motor que grava no banco) |
| **vehicle_key** | UBIGINT | **derivada**: `hash(canonical_str)` — chave de negócio que identifica "o mesmo veículo" entre vendas diferentes e entre fontes (DENATRAN e FIPE compartilham o mesmo domínio de hash) |
| **codigo_fipe_crosswalk** | VARCHAR | **derivada**: match tier 3 — join de `versao` (normalizado: sem acento, minúsculo, trim) contra `silver.mapping_table`, só aceita valor no formato real de código FIPE (`######-#`); corrigido 2026-08-24 (antes descartava o código e aceitava lixo de anotação) |
| **match_tier** | INTEGER | **derivada**: `1` = código FIPE já veio na própria linha do DENATRAN; `3` = achou só via crosswalk manual; `NULL` = nenhum dos dois. (Tier 2 — hash contra o catálogo FIPE — não é calculado aqui, é calculado no Gold sobre `dim_veiculo_atual`, porque é propriedade do veículo, não da venda individual) |

### `silver.veiculos_historico`

Mesmo layout de `silver.veiculos` **menos** `canonical_str`, `vehicle_key`,
`match_tier`, `cnpj_basico_faturado` — deliberadamente fora do contrato de
hash. Cobre `data_emplacamento < 2000` ou datas ausentes/não parseáveis. Não
alimenta o star schema do Gold hoje (`gold/build_volumes.py` lê só
`silver.veiculos`).

### `silver.fipe_precos`

Catálogo de preços FIPE normalizado — grão `codigo_fipe × year_code ×
reference_month` (histórico completo, sem colapsar para "preço mais
recente" — essa decisão é de quem consome no Gold).

| Coluna | Tipo | Observação |
|---|---|---|
| brand_name, model_name, year_code, combustivel, fuel_acronym, reference_month | VARCHAR | |
| vehicle_type, model_year | INTEGER | |
| codigo_fipe | VARCHAR | |
| preco | DECIMAL(12,2) | parseado de `"R$ X.XXX,XX"` |
| data_referencia | DATE | parseado de `"mês de YYYY"`, primeiro dia do mês |
| vehicle_key | UBIGINT | `hash(canonical_str_fipe_sql(...))` — mesmo domínio do lado DENATRAN |

**TODO registrado no código, não decisão de negócio ainda tomada**: histórico
completo não tem limite de retenção — cresce indefinidamente conforme mais
meses são coletados (ver `[[project_fipe_retention_todo]]` na memória deste
projeto).

### `silver.mapping_table`

Crosswalk manual marca/versão → código FIPE, usado como tier 3 de match
(fallback quando nem o tier 1 nem o tier 2 acham correspondência). Não é
gerado por pipeline — é uma planilha carregada como está, com colunas em
formato de nome de planilha (`COD.`, `MARCA/MODELO (original sem
espaços)`, etc.), incluindo uma coluna `Comentários` de anotação manual.
**Correção (segunda rodada — a primeira correção aqui também estava
errada)**: existem duas métricas de "yield do tier 3" legítimas e
diferentes, dependendo de qual consumidor você olha, e não dá pra citar só
uma sem dizer qual é:
- **No Gold** (`gold.dim_veiculo_atual.match_tier_fipe`, ponderado por
  volume de venda via `fato_volumes_base`): tier 3 resolve **44,4% do
  volume** (4.730.431 de 10.658.607 unidades vendidas, conferido em
  2026-09-11) — este é o número que já estava certo em
  `docs/ARQUITETURA.md` o tempo todo; tier 2 nessa mesma base é 8,4%
  (bate com `[[project_fipe_tier2_low_yield]]`), `NULL` é 47,2%.
- **No Silver** (`silver.veiculos.match_tier`, grão por linha de venda —
  um conceito **diferente**, tier 1 tem precedência e tier 2 nem existe
  nessa coluna): match_tier = 3 em 28,7% de todas as linhas (2.802.995 de
  9.779.251) — métrica correta, só que não é a mesma coisa que a de cima,
  e não deveria ter sido usada pra "corrigir" o 44% do Gold (erro meu, na
  primeira versão desta nota).

Não é prioridade expandir esta tabela — o rendimento real já é mais alto do
que os "~8%" que apareciam aqui antes de qualquer correção.

### `silver.fipe` — tabela órfã, não escrita pelo pipeline atual

**Achado ao levantar este dicionário, não investigado antes**: existe uma
tabela `silver.fipe` com 48 colunas em formato DENATRAN (chassi, placa,
marca, modelo — não formato FIPE, apesar do nome), incluindo colunas que
não existem em nenhum outro lugar do Silver hoje (`pais_de_origem`,
`tipo_de_montagem`, `preco_fipe`, `ano_arquivo`). Não aparece referenciada
em `silver/run_sample.py` (o runner atual, que só escreve
`silver.veiculos`/`silver.veiculos_historico`) nem em nenhum script de
Gold. Tudo indica ser resultado de uma versão anterior do pipeline, de
antes da separação `veiculos`/`veiculos_historico` — sobra, não schema
ativo. Não removida aqui (mesma cautela do achado de `main.*` abaixo:
levantamento, não limpeza autorizada). Desde 2026-09-11 tem `COMMENT ON
TABLE` marcando "TABELA ÓRFÃ" direto no catálogo, mesmo padrão de
`staging.ingest_control`/`veiculo_raw` acima.

---

## Gold

Star schema Kimball — 4 dimensões + fato estreita (`fato_volumes_base`) +
uma view de compatibilidade (`gold.fato_volumes`, formato plano que o app e
o Vanna consultam) + duas views de período corrente. Todas as tabelas já
têm `COMMENT ON TABLE`/`COMMENT ON COLUMN` aplicados diretamente no banco
(`gold/build_volumes.py::apply_grain_comments`/`apply_comments`,
`gold/build_dim_empresa.py` mesmo padrão) — o texto abaixo é o mesmo que
aparece se alguém abrir o catálogo direto no MotherDuck.

### `gold.dim_veiculo_observado`

**Grão**: uma linha por combinação de atributos de veículo que realmente
coexistiu em pelo menos um registro do Silver — histórico fiel, sem inferir
data de vigência.

| Coluna | Tipo | Descrição |
|---|---|---|
| veiculo_key | BIGINT | chave surrogate — `hash` das 9 colunas do grão (não `ROW_NUMBER()`, ver nota de migração abaixo), mascarado para caber em `BIGINT` assinado |
| vehicle_key | UBIGINT | chave de negócio que agrupa as versões históricas do mesmo veículo |
| marca, modelo, versao, combustivel_normalizado, segmentacao_atualizada, segmentacao_original, tipo_veiculo_principal | VARCHAR | atributos como registrados naquela venda específica — não são a classificação atual (ver `dim_veiculo_atual`) |
| ano_modelo | INTEGER | idem |

### `gold.dim_veiculo_atual`

**Grão**: uma linha por `vehicle_key` — "melhor entendimento atual" (Type
1), atributos da venda mais recente, selecionados como linha completa
(nunca `arg_max` por coluna isolada).

| Coluna | Tipo | Descrição |
|---|---|---|
| veiculo_atual_key | BIGINT | = `vehicle_key` mascarado (não um novo hash — o grão já é 1 linha por `vehicle_key`) |
| vehicle_key | UBIGINT | |
| marca, modelo, versao, combustivel_normalizado | VARCHAR | |
| ano_modelo | INTEGER | |
| segmentacao_klume, segmentacao_original_klume, tipo_veiculo_klume | VARCHAR | classificação mais recente conhecida, independente de quando o veículo foi vendido |
| codigo_fipe | VARCHAR | match mais recente — tier 2 (hash contra `silver.fipe_precos`) tem prioridade sobre tier 3 (crosswalk); `NULL` se nenhum achou |
| preco_fipe | DECIMAL(12,2) | só preenchido quando `match_tier_fipe = 2` — tier 3 não traz preço |
| match_tier_fipe | INTEGER | `2` = hash canônico bateu no catálogo FIPE; `3` = só crosswalk manual; `NULL` = nenhum |
| data_referencia_fipe | DATE | mês de referência do preço — pode ficar parado no último mês em que o veículo existiu no catálogo FIPE, conferir antes de assumir "preço do mês corrente" |

### `gold.dim_empresa`

**Grão**: uma linha por `cnpj_basico` observado em
`silver.veiculos.cnpj_basico_faturado`, mais duas linhas sentinela.

| Coluna | Tipo | Descrição |
|---|---|---|
| empresa_key | BIGINT | `-1` = venda não faturada por CNPJ; `-2` = CNPJ real sem correspondência em nenhuma fonte |
| cnpj_basico | VARCHAR | chave de negócio; `NULL` só nas sentinelas |
| razao_social, natureza_juridica, qualificacao_responsavel, porte | VARCHAR | união de duas fontes cadastrais sem sobreposição verificada entre elas (juntas cobrem 99,98% dos CNPJs relevantes) |
| capital_social | VARCHAR | idem — mantido como texto da fonte, não convertido pra numérico |
| fonte_empresas | VARCHAR | de qual das duas fontes veio o dado cadastral |
| tem_estabelecimento | BOOLEAN | `FALSE` quando o CNPJ existe na fonte cadastral mas não em estabelecimentos (~3,4% dos casos) — nome_fantasia/cnae/categoria ficam `NULL` nesse caso |
| nome_fantasia, situacao_cadastral, cnae_fiscal_principal, municipio_estabelecimento, uf_estabelecimento | VARCHAR | vêm da linha matriz (não filial) |
| categoria_empresa | VARCHAR | CNAE `45xx` → "Concessionária/Comércio de Veículos"; `771x` → "Locadora" (deliberadamente mais estreito que `77xx` inteiro); senão "Outro" |

Refresh **desacoplado** do build automático de volumes (escaneia ~104M
linhas de CNPJ, caro demais para rodar a cada upload) — roda manualmente via
`python gold/build_dim_empresa.py`. Fontes vêm de Parquet arquivado no S3
desde 2026-09-09 (as 3 tabelas brutas de CNPJ foram removidas do MotherDuck
principal — ver `docs/POST-MORTEM.md`).

### `gold.dim_geografia`

**Grão**: uma linha por `codigo_municipio` (código IBGE) — nome mais
recentemente observado (linha completa, não `arg_max` por coluna
isolada); `-1` = sem código IBGE informado na fonte (~23% dos casos).

| Coluna | Tipo | Descrição |
|---|---|---|
| codigo_municipio | INTEGER | código IBGE — chave natural, não surrogate |
| municipio | VARCHAR | |
| estado | VARCHAR | |

### `gold.dim_data`

**Grão**: uma linha por dia do calendário contínuo entre a menor e a maior
`data_emplacamento` observada — inclui dias sem venda. Chave `data_key`
formato `YYYYMMDD` (padrão Kimball).

| Coluna | Tipo | Descrição |
|---|---|---|
| data_key | INTEGER | `YYYYMMDD` |
| data | DATE | |
| ano, mes, trimestre, dia_semana | BIGINT | |
| fim_de_semana | BOOLEAN | `dia_semana IN (0, 6)` |
| nome_mes | VARCHAR | nome por extenso, em português |

### `gold.fato_volumes_base`

**Grão**: soma de `quantidade` para uma combinação única de `data_key,
veiculo_key, veiculo_atual_key, codigo_municipio, cor_predominante,
tipo_venda, match_tier, cnpj_basico_faturado` — não existe grão de venda
individual.

| Coluna | Tipo | Descrição |
|---|---|---|
| data_key | INTEGER | FK pra `dim_data` |
| veiculo_key, veiculo_atual_key, empresa_key | BIGINT | FKs pra `dim_veiculo_observado`/`dim_veiculo_atual`/`dim_empresa` |
| codigo_municipio | INTEGER | FK natural pra `dim_geografia` |
| municipio_emplacamento, estado_emplacamento, cor_predominante, tipo_venda | VARCHAR | atributos degenerados na fato |
| match_tier | INTEGER | **correção**: assume `1` (FIPE embutido na própria linha DENATRAN), `3` (achou via crosswalk manual — `silver.mapping_table`, mesmo mecanismo usado no Silver) ou `NULL` — **nunca `2`** (tier 2, hash contra o catálogo FIPE, só existe em `dim_veiculo_atual.match_tier_fipe`, calculado à parte no Gold, propriedade do veículo, não da venda). Os dois nomes parecidos (`match_tier` aqui vs. `match_tier_fipe` na dimensão) cobrem domínios de valor parecidos mas não idênticos — não presuma que são a mesma coisa. |
| cnpj_basico_faturado | VARCHAR | só preenchido quando faturado por CNPJ |
| fipe | VARCHAR | código FIPE tier 1 — verificado que não fragmenta a agregação (0 grupos com mais de um valor distinto) |
| preco | DECIMAL(12,2) | preço tier 1, mesma verificação |
| quantidade | BIGINT | medida aditiva — sempre `SUM`, nunca `COUNT(*)`. Era `HUGEINT` (promoção automática do DuckDB pra `SUM()` sem cast) até 2026-09-09 — trocado por `CAST(...AS BIGINT)` explícito em `gold/build_volumes.py`: volume real (~10,6M) cabe folgado em `BIGINT`, sem motivo pra pagar o dobro do espaço por linha. Efetivo a partir do próximo rebuild do Gold. |
| quantidade_tipo_venda_conhecido | BIGINT | mesma correção de tipo que `quantidade` acima (era `HUGEINT`). `= quantidade` quando `tipo_venda IN ('Varejo','Direta')`, `NULL` quando `NULL`/`'ND'` — existe para calcular % varejo-vs-direta sem repetir a exclusão em cada consumidor; participação de mercado total continua usando `quantidade` puro |

### `gold.fato_volumes` (view) e período corrente

`gold.fato_volumes` reconstrói o formato plano (join das 4 dimensões +
fato) que o app/Vanna já consultavam antes do star schema existir — mesmas
colunas de sempre, mais `segmentacao_klume`, `razao_social`,
`categoria_empresa`. `gold.fato_volumes_ano_atual` e
`gold.fato_volumes_mes_atual` são views sobre a mesma view, filtradas por
`CURRENT_DATE` — não duplicam dado, não precisam de rebuild na virada do
ano/mês.

### Migração de chave surrogate (2026-09-09)

`veiculo_key`, `veiculo_atual_key` e `empresa_key` eram `ROW_NUMBER() OVER
(ORDER BY <chave de negócio>)` até esta data — trocados por hash
determinístico porque uma entidade nova que ordena antes de uma existente
deslocava toda chave depois dela a cada rebuild, corrompendo a FK física já
persistida em `fato_volumes_base`. Detalhe completo em
`docs/POST-MORTEM.md`, seção "Migração: surrogate key sequencial → hash
determinístico".

---

## `app` — tabelas de controle do produto

Grão + colunas comentados direto no banco via `app/comments.py` — como não
são reconstruídas por nenhum script de build (`api_clients` é gerenciada
manualmente, `query_log`/`upload_log` usam `CREATE TABLE IF NOT EXISTS`,
criadas uma única vez), rodar `python -m app.comments` de novo só se essas
tabelas forem recriadas do zero.

### `app.api_clients`

| Coluna | Tipo |
|---|---|
| api_key | VARCHAR |
| client_name | VARCHAR |
| active | BOOLEAN |
| created_at | TIMESTAMP |

Autenticação da API de parceiro (`docs/api-contratos.md`) — uma linha por
cliente autorizado, `active = FALSE` revoga acesso sem apagar o registro.

### `app.query_log`

| Coluna | Tipo |
|---|---|
| ts | TIMESTAMP |
| user_email | VARCHAR |
| question | VARCHAR |
| sql | VARCHAR |
| row_count | INTEGER |
| duration_ms | INTEGER |
| error | VARCHAR |

Log de cada pergunta feita ao Vanna (pergunta em linguagem natural + SQL
gerado + resultado). Escrita é best-effort e assíncrona (thread separada,
conexão própria, `try/except` silencioso) — não bloqueia a resposta na tela
nem derruba a sessão se o insert falhar (ver ponto C do plano de correções
arquiteturais, `docs/POST-MORTEM.md`).

### `app.upload_log`

| Coluna | Tipo |
|---|---|
| ts | TIMESTAMP |
| filename | VARCHAR |
| file_hash | VARCHAR |
| ano | INTEGER |
| rows_inserted | INTEGER |
| s3_ok | BOOLEAN |

Registro de cada upload processado — `file_hash` é o mecanismo de
deduplicação (upload do mesmo arquivo é bloqueado antes de tocar qualquer
tabela). Desde a correção de ordem de escrita (S3 antes do MotherDuck — ver
`docs/POST-MORTEM.md`), uma linha só existe aqui depois que **as duas**
etapas (S3 e MotherDuck) já tiveram sucesso — `s3_ok` sempre `TRUE` quando a
linha existe.

---

## Nota: schema `main` tem artefatos que não são schema intencional

Ao levantar este dicionário, o catálogo mostrou ~55 views em `main` com
nomes como `run_1957_blank`, `run_2016_typed`, `run_2020_split_historico`,
`s3test_recent_final`, `upl1958_split_recent`, além de `main.fipe_blank` /
`fipe_renamed` / `fipe_typed`. Não são schema ativo — são views
intermediárias que `silver/normalizers/denatran.py::normalize_denatran()` e
`silver/normalizers/fipe.py::normalize_fipe()` criam durante a execução
(uma por estágio do pipeline: renomeada → sentinelas nulas → tipada →
separada por ano → com hash), nomeadas pelo `stage_prefix` que quem chama
passa. `silver/run_sample.py` usa `stage_prefix=f"run_{label}"` para os
labels `1957`/`2016`/`2020`/`2025` — o que corresponde exatamente aos
prefixos `run_*` encontrados. Os prefixos `s3test_*` e `upl1958_*` vêm de
execuções manuais equivalentes feitas fora deste script (prováveis testes
do upload de 1958 documentado em `docs/POST-MORTEM.md`).

O código cria essas views como `CREATE OR REPLACE VIEW` comum, não `TEMP
VIEW` — por isso persistem entre sessões em vez de somem ao fechar a
conexão. Não é dado (são só definições de view, custo de armazenamento
desprezível), mas é ruído de catálogo: alguém explorando o banco direto via
MotherDuck UI vê ~55 objetos que não servem a nenhum consumidor real hoje.

**Não removido aqui** — é um achado de levantamento, não uma limpeza
autorizada (mesmo padrão de cautela do resto do projeto: nunca apagar sem
confirmação explícita, ver `docs/POST-MORTEM.md`). Fica registrado como
candidato de limpeza; a correção de raiz, se decidido fazer, é trocar
`CREATE OR REPLACE VIEW` por `CREATE OR REPLACE TEMP VIEW` nos dois
normalizers, para que execuções futuras parem de deixar sobra.

`ADHOC_FILES.{base, cnpj_restantes, cnpj_resto}` também ficam fora do
escopo deste documento pelo mesmo motivo — não investigados ainda, citados
aqui só para não serem confundidos com schema intencional caso apareçam
numa exploração futura do catálogo.
