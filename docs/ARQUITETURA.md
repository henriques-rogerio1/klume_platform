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
- **FIPE**: ainda não ingerido no MotherDuck. Dado real e atual existe localmente
  (`Documents/fipe_api/jsons/{Cars,Bikes,Trucks}/*_sample_*.json`) — pipeline própria
  (repo separado `fipe_api`, orquestrada por Mage AI) nunca populou
  `staging.raw_json_fipe` nesta instância. **Deliberadamente fora de escopo** até agora.

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
  melhor entendimento atual", independente de quando o veículo foi vendido.

### Demais dimensões

- **`gold.dim_geografia`** — chave natural `codigo_municipio` (código IBGE, ~5.572
  valores, bate com o número real de municípios do Brasil). Usar o nome em texto como
  chave seria errado — nomes colidem entre estados (ex: "Bom Jesus" existe em 6).
  Linha sentinela (`-1`, `'NÃO IDENTIFICADO'`) pra nunca deixar um `JOIN` comum
  derrubar linha silenciosamente (~23% dos registros não têm código IBGE — mas TÊM o
  nome do município em texto, por isso o texto também fica direto na fato, não só
  via essa dimensão).
- **`gold.dim_data`** — calendário contínuo (todo dia entre o mínimo e o máximo
  observado, não só datas com venda), chave `YYYYMMDD` inteira (padrão Kimball).
- Atributos de cardinalidade trivial (`cor_predominante`=18, `tipo_venda`=3,
  `match_tier`=2) ficam **inline na fato** — DuckDB/Parquet já comprime string de
  baixa cardinalidade bem, uma dimensão separada só adicionaria join sem ganho real.

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
- **`silver.fipe_precos`** — normalizador FIPE ainda não existe (fonte local em JSON
  já mapeada, ver `Bronze` acima).
- **Join preço × volume no Gold** — depende do item acima.
- **`gold.semantic_dictionary`** — tabela de ontologia mais rica que
  `COMMENT ON COLUMN` (definição de negócio, exemplos, owner) — ideia registrada,
  não construída.
- **Ativar login** (credenciais Google OAuth) e **migrar hospedagem** pra
  Railway + Supabase Auth (hoje: Streamlit Community Cloud, restrição por e-mail).
  Deve reconstruir `veiculo_atual_key` de qualquer forma se essa migração
  reprocessar dados.
- **MCP pra clientes externos** — não iniciado.
- **4 databases MotherDuck órfãos** (`bronze`, `silver`, `gold`, `my_db`, de
  fevereiro, quase vazios, sem relação com os schemas reais dentro de
  `Klume_DB_Cloud`) — seguros de apagar, ainda não confirmado com o usuário.
