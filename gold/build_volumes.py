"""
Constrói o star schema de volumes no Gold: 4 dimensões + fato estreita
(chaves inteiras sequenciais, pensadas pra Tableau/Power BI) + a view
gold.fato_volumes, que reconstrói o formato plano de hoje (mais a coluna
nova segmentacao_klume) — o Vanna e o app continuam consultando essa view
sem nenhuma mudança de código.

Duas dimensões de veículo, com propósitos diferentes e deliberados:
  - dim_veiculo_observado: fiel ao histórico — uma linha por combinação de
    atributos que realmente coexistiu num registro real, sem inventar
    data de vigência (só temos data_emplacamento, que é a data da venda,
    não a data em que a DENATRAN mudou alguma classificação).
  - dim_veiculo_atual: Type 1 de propósito — "nosso melhor entendimento
    atual" pra cada vehicle_key, usado só pra alimentar segmentacao_klume.

Preço FIPE (ver gold/build_fipe_match.py pro diagnóstico, plano em
"shimmering-toasting-cookie"): dim_veiculo_atual ganha codigo_fipe,
preco_fipe, match_tier_fipe, data_referencia_fipe (tier 2 = hash canônico
contra silver.fipe_precos, tier 3 = crosswalk manual corrigido, tier 2 tem
precedência sobre tier 3). fato_volumes_base ganha fipe/preco (tier 1, já
vem embutido na linha de origem DENATRAN, confirmado sem fragmentação).
A junção mora dentro de build_dim_veiculo_atual() (não é um passo
desacoplado como build_dim_empresa.py) porque silver.fipe_precos é pequeno
(~546K linhas) e dim_veiculo_atual já é CREATE OR REPLACE do zero a cada
rodada de qualquer forma.

Uso:
    python gold/build_volumes.py
Requer MOTHERDUCK_TOKEN no .env.
"""

from silver.db.connection import get_connection
from silver.vehicle_key.canonical_sql import register_sql_macros

COMMENTS = {
    "dim_veiculo_observado": {
        "veiculo_key": "Chave surrogate inteira. Uma linha por combinação de atributos "
        "que realmente coexistiu num registro do Silver — histórico fiel, sem inferir "
        "quando a classificação mudou.",
        "vehicle_key": "Chave de negócio (hash) que agrupa as diferentes versões "
        "históricas do mesmo veículo — ver silver.vehicle_key.canonical_sql.",
        "segmentacao_atualizada": "Classificação de segmento como estava registrada "
        "naquela venda específica — não é a classificação atual, ver dim_veiculo_atual.",
        "segmentacao_original": "Classificação original da DENATRAN, como registrada "
        "naquela venda.",
        "tipo_veiculo_principal": "Tipo de veículo como registrado naquela venda — "
        "grafia pode variar por safra (ex: 'Moto' vs 'MOTOCICLETA').",
    },
    "dim_veiculo_atual": {
        "veiculo_atual_key": "Chave surrogate inteira do 'melhor entendimento atual' "
        "pra esse veículo — Type 1 por escolha, não representa nenhum momento histórico.",
        "segmentacao_klume": "Classificação de segmento mais recente conhecida pra esse "
        "vehicle_key, independente de quando o veículo foi vendido.",
        "codigo_fipe": "Código FIPE do match mais recente pra esse vehicle_key — tier 2 "
        "(hash canônico contra silver.fipe_precos) tem prioridade sobre tier 3 "
        "(crosswalk manual, silver.mapping_table). NULL se nenhum dos dois achou.",
        "preco_fipe": "Preço do match de tier 2 (silver.fipe_precos.preco) — só "
        "preenchido quando match_tier_fipe = 2. Tier 3 não traz preço, só o código.",
        "match_tier_fipe": "2 = hash canônico bateu contra o catálogo FIPE "
        "(silver.vehicle_key.canonical_sql::canonical_str_fipe_sql, com alias de marca "
        "quando aplicável — ver marca_alias_fipe.py). 3 = achou só via crosswalk manual. "
        "NULL = nenhum dos dois.",
        "data_referencia_fipe": "Mês de referência do preço em preco_fipe (o mais "
        "recente disponível pra esse vehicle_key na última vez que o Gold rebuildou) — "
        "sempre conferir antes de assumir que é o preço do mês corrente: se o veículo "
        "saiu do catálogo FIPE, isso fica parado no último mês em que ele existia.",
    },
    "dim_geografia": {
        "codigo_municipio": "Código IBGE do município — chave natural, não surrogate. "
        "-1 = registro sem código IBGE informado na fonte (~23% dos casos).",
    },
    "dim_data": {
        "data_key": "Chave surrogate inteira YYYYMMDD (padrão Kimball). Calendário "
        "contínuo do menor ao maior data_emplacamento observado, não só datas com venda.",
    },
    "fato_volumes_base": {
        "quantidade": "Medida aditiva — soma de veículos emplacados. Sempre agregar "
        "com SUM, nunca COUNT(*).",
        "match_tier": "Tier de match FIPE da própria linha de origem (tier 1 — código "
        "FIPE veio direto na linha do DENATRAN). NULL = essa linha não trouxe FIPE "
        "embutido; ver dim_veiculo_atual.match_tier_fipe pro match por catálogo "
        "(tier 2/3), que é propriedade do veículo, não da venda.",
        "fipe": "Código FIPE que já veio na própria linha do DENATRAN (tier 1) — "
        "atributo da venda específica, verificado 2026-08-24 que não varia dentro da "
        "combinação de colunas já agregada aqui (não fragmenta SUM(quantidade)).",
        "preco": "Preço que já veio na própria linha do DENATRAN (tier 1), mesmo "
        "caso de fipe acima.",
        "cnpj_basico_faturado": "8 primeiros dígitos do CNPJ de quem faturou (pessoa "
        "jurídica) — só preenchido quando tipo_faturado = 'CNPJ'.",
        "empresa_key": "FK pra gold.dim_empresa. -1 = venda não faturada por CNPJ "
        "(cnpj_basico_faturado NULL), -2 = CNPJ real sem correspondência em "
        "nenhuma fonte Empresas na última vez que dim_empresa foi atualizada "
        "(refresh manual, desacoplado deste build — ver gold/build_dim_empresa.py).",
    },
}


# Grão de cada tabela como frase verificável (metodologia dimensional-modeler:
# "uma linha representa [evento/estado] de [entidade] para [dimensões] em [momento],
# com [medidas]") — documentado no próprio banco via COMMENT ON TABLE, não só em
# docstring, pra quem abrir o catálogo direto (MotherDuck UI, Power BI, Tableau)
# ver o grão sem precisar ler o código Python.
GRAIN = {
    "fato_volumes_base": "Uma linha representa a soma de veículos emplacados "
    "(SUM(quantidade)) para uma combinação única de data_key, veiculo_key "
    "(atributos observados na venda), veiculo_atual_key (melhor entendimento atual), "
    "codigo_municipio, cor_predominante, tipo_venda, match_tier e "
    "cnpj_basico_faturado — não existe grão de venda individual, só a soma por essa "
    "combinação de atributos (mesmo grão de _fato_pre, que agrega silver.veiculos "
    "por GROUP BY ALL). empresa_key não adiciona granularidade — é totalmente "
    "determinado por cnpj_basico_faturado (ver gold.dim_empresa). fipe/preco (tier 1) "
    "também não adicionam granularidade — verificado 2026-08-24 que são "
    "funcionalmente dependentes da combinação já agregada (0 grupos com mais de um "
    "valor distinto).",
    "dim_veiculo_observado": "Uma linha representa uma combinação de atributos de "
    "veículo (vehicle_key, marca, modelo, versao, ano_modelo, combustivel_normalizado, "
    "segmentacao_atualizada, segmentacao_original, tipo_veiculo_principal) que "
    "realmente coexistiu em pelo menos um registro do Silver — histórico fiel, sem "
    "inferir data de vigência.",
    "dim_veiculo_atual": "Uma linha representa o melhor entendimento atual (Type 1) "
    "de um vehicle_key — os atributos observados na venda mais recente desse "
    "veículo, selecionados como linha completa (nunca arg_max por coluna isolada). "
    "codigo_fipe/preco_fipe/match_tier_fipe/data_referencia_fipe (adicionado "
    "2026-08-24) seguem o mesmo grão — match por catálogo FIPE mais recente "
    "disponível pra esse vehicle_key, não muda a granularidade da linha.",
    "dim_geografia": "Uma linha representa um codigo_municipio (código IBGE) com o "
    "nome de município e estado mais recentemente observados (linha completa, não "
    "arg_max por coluna); -1 é a linha sentinela para 'sem código IBGE informado'.",
    "dim_data": "Uma linha representa um dia do calendário contínuo entre a menor e "
    "a maior data_emplacamento observada em silver.veiculos — inclui dias sem "
    "nenhuma venda.",
}


def apply_grain_comments(con, grain: dict = GRAIN) -> None:
    for table, text in grain.items():
        text_escaped = text.replace("'", "''")
        con.execute(f"COMMENT ON TABLE gold.{table} IS '{text_escaped}'")


def apply_comments(con, comments: dict = COMMENTS) -> None:
    for table, cols in comments.items():
        for col, text in cols.items():
            text_escaped = text.replace("'", "''")
            con.execute(f"COMMENT ON COLUMN gold.{table}.{col} IS '{text_escaped}'")


def build_dim_veiculo_observado(con) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_veiculo_observado AS
        SELECT
            row_number() OVER (
                ORDER BY vehicle_key, marca, modelo, versao, ano_modelo,
                         combustivel_normalizado, segmentacao_atualizada,
                         segmentacao_original, tipo_veiculo_principal
            ) AS veiculo_key,
            vehicle_key, marca, modelo, versao, ano_modelo,
            combustivel_normalizado, segmentacao_atualizada, segmentacao_original,
            tipo_veiculo_principal
        FROM (
            SELECT DISTINCT
                vehicle_key, marca, modelo, versao, ano_modelo,
                map_combustivel_sql(combustivel) AS combustivel_normalizado,
                segmentacao_atualizada, segmentacao_original, tipo_veiculo_principal
            FROM silver.veiculos
        )
    """)


def build_dim_veiculo_atual(con) -> None:
    # Preço FIPE (tier 2/3) é propriedade estável do vehicle_key, mesmo grão
    # Type 1 já usado por segmentacao_klume — entra na MESMA construção, não
    # numa segunda passada: dim_veiculo_atual é CREATE OR REPLACE a cada
    # upload automático, uma UPDATE/ALTER separada seria apagada no próximo
    # rebuild. Diferente do CNPJ (gold.dim_empresa, refresh desacoplado —
    # tabelas de origem grandes demais pra reescanear toda hora), o dado FIPE
    # é pequeno (silver.fipe_precos ~546 mil linhas), reconstruir junto é
    # barato.
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _fipe_tier2 AS
        SELECT vehicle_key, codigo_fipe, preco, data_referencia
        FROM silver.fipe_precos
        QUALIFY row_number() OVER (
            PARTITION BY vehicle_key
            ORDER BY reference_month DESC, codigo_fipe, year_code
        ) = 1
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _fipe_tier3 AS
        SELECT vehicle_key, codigo_fipe_crosswalk
        FROM silver.veiculos
        WHERE codigo_fipe_crosswalk IS NOT NULL
        QUALIFY row_number() OVER (
            PARTITION BY vehicle_key
            ORDER BY data_emplacamento DESC, codigo_fipe_crosswalk
        ) = 1
    """)

    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_veiculo_atual AS
        SELECT
            row_number() OVER (ORDER BY a.vehicle_key) AS veiculo_atual_key,
            a.vehicle_key, a.marca, a.modelo, a.versao, a.ano_modelo, a.combustivel_normalizado,
            a.segmentacao_atualizada AS segmentacao_klume,
            a.segmentacao_original AS segmentacao_original_klume,
            a.tipo_veiculo_principal AS tipo_veiculo_klume,
            COALESCE(t2.codigo_fipe, t3.codigo_fipe_crosswalk) AS codigo_fipe,
            t2.preco AS preco_fipe,
            CASE
                WHEN t2.codigo_fipe IS NOT NULL THEN 2
                WHEN t3.codigo_fipe_crosswalk IS NOT NULL THEN 3
                ELSE NULL
            END AS match_tier_fipe,
            t2.data_referencia AS data_referencia_fipe
        FROM (
            SELECT vehicle_key, marca, modelo, versao, ano_modelo, combustivel,
                   map_combustivel_sql(combustivel) AS combustivel_normalizado,
                   segmentacao_atualizada, segmentacao_original, tipo_veiculo_principal
            FROM silver.veiculos
            QUALIFY row_number() OVER (
                PARTITION BY vehicle_key
                ORDER BY data_emplacamento DESC, marca, modelo, versao, ano_modelo,
                         combustivel_normalizado, segmentacao_atualizada,
                         segmentacao_original, tipo_veiculo_principal
            ) = 1
        ) a
        LEFT JOIN _fipe_tier2 t2
          ON hash(canonical_str_denatran_for_fipe_match_sql(a.marca, a.versao, a.ano_modelo, a.combustivel))
             = t2.vehicle_key
        LEFT JOIN _fipe_tier3 t3 ON a.vehicle_key = t3.vehicle_key
    """)


def build_dim_geografia(con) -> None:
    # Linha vencedora completa por codigo_municipio (não arg_max independente por
    # coluna) — município e estado sempre vêm da MESMA linha de origem, nunca de
    # datas diferentes. Hoje isso nunca diverge (nenhum codigo_municipio observado
    # com mais de um nome/estado ao longo do tempo), mas o padrão independente é
    # frágil pra dados futuros (ex: variação de grafia entre safras).
    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_geografia AS
        SELECT codigo_municipio, municipio_emplacamento AS municipio,
               estado_emplacamento AS estado
        FROM silver.veiculos
        WHERE codigo_municipio IS NOT NULL
        QUALIFY row_number() OVER (
            PARTITION BY codigo_municipio
            ORDER BY data_emplacamento DESC, municipio_emplacamento, estado_emplacamento
        ) = 1

        UNION ALL

        SELECT -1, 'NÃO IDENTIFICADO', 'NÃO IDENTIFICADO'
    """)


def build_dim_data(con) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_data AS
        WITH bounds AS (
            SELECT MIN(data_emplacamento) AS d_min, MAX(data_emplacamento) AS d_max
            FROM silver.veiculos WHERE data_emplacamento IS NOT NULL
        )
        SELECT
            CAST(strftime(d, '%Y%m%d') AS INTEGER) AS data_key,
            CAST(d AS DATE) AS data,
            date_part('year', d) AS ano,
            date_part('month', d) AS mes,
            date_part('quarter', d) AS trimestre,
            date_part('dow', d) AS dia_semana,
            date_part('dow', d) IN (0, 6) AS fim_de_semana,
            ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho',
              'Agosto','Setembro','Outubro','Novembro','Dezembro'][date_part('month', d)] AS nome_mes
        FROM bounds, generate_series(d_min, d_max, INTERVAL 1 DAY) AS t(d)
    """)


def build_fato_volumes_base(con) -> None:
    # fipe/preco (tier 1 -- código FIPE que já vinha na própria linha do
    # DENATRAN) entram direto aqui, não em dim_veiculo_atual: são atributo
    # da venda específica, não propriedade estável do veículo. Verificado
    # antes de adicionar (2026-08-24): não fragmentam a agregação -- 0
    # grupos de _fato_pre têm mais de um preco/fipe distinto.
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _fato_pre AS
        SELECT
            data_emplacamento, vehicle_key, marca, modelo, versao, ano_modelo,
            map_combustivel_sql(combustivel) AS combustivel_normalizado,
            segmentacao_atualizada, segmentacao_original, tipo_veiculo_principal,
            COALESCE(codigo_municipio, -1) AS codigo_municipio,
            municipio_emplacamento, estado_emplacamento,
            cor_predominante, tipo_venda, match_tier, cnpj_basico_faturado,
            fipe, preco,
            SUM(quantidade) AS quantidade
        FROM silver.veiculos
        GROUP BY ALL
    """)

    con.execute("""
        CREATE OR REPLACE TABLE gold.fato_volumes_base AS
        SELECT
            d.data_key,
            o.veiculo_key,
            a.veiculo_atual_key,
            p.codigo_municipio, p.municipio_emplacamento, p.estado_emplacamento,
            p.cor_predominante, p.tipo_venda, p.match_tier, p.cnpj_basico_faturado,
            p.fipe, p.preco,
            CASE
                WHEN p.cnpj_basico_faturado IS NULL THEN -1
                WHEN e.empresa_key IS NULL THEN -2
                ELSE e.empresa_key
            END AS empresa_key,
            p.quantidade
        FROM _fato_pre p
        JOIN gold.dim_veiculo_observado o
          ON p.vehicle_key = o.vehicle_key
         AND p.marca IS NOT DISTINCT FROM o.marca
         AND p.modelo IS NOT DISTINCT FROM o.modelo
         AND p.versao IS NOT DISTINCT FROM o.versao
         AND p.ano_modelo IS NOT DISTINCT FROM o.ano_modelo
         AND p.combustivel_normalizado IS NOT DISTINCT FROM o.combustivel_normalizado
         AND p.segmentacao_atualizada IS NOT DISTINCT FROM o.segmentacao_atualizada
         AND p.segmentacao_original IS NOT DISTINCT FROM o.segmentacao_original
         AND p.tipo_veiculo_principal IS NOT DISTINCT FROM o.tipo_veiculo_principal
        JOIN gold.dim_veiculo_atual a ON p.vehicle_key = a.vehicle_key
        JOIN gold.dim_data d ON p.data_emplacamento = d.data
        LEFT JOIN gold.dim_empresa e ON p.cnpj_basico_faturado = e.cnpj_basico
    """)


def build_compatibility_view(con) -> None:
    # gold.fato_volumes pode existir como TABLE (o flat antigo, já com snapshot
    # salvo em gold.fato_volumes_snapshot_pre_star) OU já como VIEW (rerun deste
    # script) — DuckDB não deixa CREATE OR REPLACE mudar o tipo do objeto, então
    # tenta dropar dos dois jeitos, ignorando o que não se aplicar.
    try:
        con.execute("DROP TABLE IF EXISTS gold.fato_volumes")
    except Exception:
        pass
    try:
        con.execute("DROP VIEW IF EXISTS gold.fato_volumes")
    except Exception:
        pass
    con.execute("""
        CREATE OR REPLACE VIEW gold.fato_volumes AS
        SELECT
            d.data AS data_emplacamento, o.marca, o.modelo, o.versao,
            o.segmentacao_atualizada, o.segmentacao_original, o.combustivel_normalizado,
            f.cor_predominante, f.tipo_venda, f.municipio_emplacamento, f.estado_emplacamento,
            o.tipo_veiculo_principal, f.cnpj_basico_faturado, f.match_tier,
            a.segmentacao_klume,
            e.razao_social, e.categoria_empresa,
            f.fipe, f.preco,
            a.codigo_fipe, a.preco_fipe, a.match_tier_fipe, a.data_referencia_fipe,
            f.quantidade
        FROM gold.fato_volumes_base f
        JOIN gold.dim_veiculo_observado o ON f.veiculo_key = o.veiculo_key
        JOIN gold.dim_veiculo_atual a ON f.veiculo_atual_key = a.veiculo_atual_key
        JOIN gold.dim_data d ON f.data_key = d.data_key
        JOIN gold.dim_empresa e ON f.empresa_key = e.empresa_key
    """)


def build_current_period_views(con) -> None:
    """
    Datamarts de ano/mês corrente como views — sem duplicar dado (mesma fato+dimensões
    de gold.fato_volumes), e sem precisar de rebuild na virada do ano/mês porque usam
    CURRENT_DATE na própria definição.
    """
    con.execute("""
        CREATE OR REPLACE VIEW gold.fato_volumes_ano_atual AS
        SELECT * FROM gold.fato_volumes
        WHERE date_part('year', data_emplacamento) = date_part('year', CURRENT_DATE)
    """)
    con.execute("""
        CREATE OR REPLACE VIEW gold.fato_volumes_mes_atual AS
        SELECT * FROM gold.fato_volumes
        WHERE date_trunc('month', data_emplacamento) = date_trunc('month', CURRENT_DATE)
    """)


def main():
    con = get_connection("motherduck")
    con.execute("CREATE SCHEMA IF NOT EXISTS gold")
    register_sql_macros(con)

    # gold.dim_empresa tem refresh manual, desacoplado deste build (escaneia
    # ~104M linhas de CNPJ, caro demais pra rodar a cada upload) — só constrói
    # na primeira vez, se ainda não existir. Depois disso, quem quiser dado de
    # CNPJ atualizado roda `python gold/build_dim_empresa.py` manualmente.
    dim_empresa_exists = con.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'gold' AND table_name = 'dim_empresa'
    """).fetchone()[0] > 0
    if not dim_empresa_exists:
        print("gold.dim_empresa não existe ainda — construindo pela primeira vez (bootstrap)...")
        from gold.build_dim_empresa import build_dim_empresa
        from gold.build_dim_empresa import COMMENTS as DIM_EMPRESA_COMMENTS
        from gold.build_dim_empresa import GRAIN as DIM_EMPRESA_GRAIN
        build_dim_empresa(con)
        apply_grain_comments(con, DIM_EMPRESA_GRAIN)
        apply_comments(con, DIM_EMPRESA_COMMENTS)

    print("Construindo dim_veiculo_observado...")
    build_dim_veiculo_observado(con)
    print("Construindo dim_veiculo_atual...")
    build_dim_veiculo_atual(con)
    print("Construindo dim_geografia...")
    build_dim_geografia(con)
    print("Construindo dim_data...")
    build_dim_data(con)
    print("Construindo fato_volumes_base...")
    build_fato_volumes_base(con)
    print("Construindo view de compatibilidade gold.fato_volumes...")
    build_compatibility_view(con)
    print("Construindo views de ano/mês corrente...")
    build_current_period_views(con)
    print("Aplicando comentários de grão (COMMENT ON TABLE)...")
    apply_grain_comments(con)
    print("Aplicando comentários (ontologia)...")
    apply_comments(con)

    n_pre = con.execute("SELECT COUNT(*) FROM _fato_pre").fetchone()[0]
    n_base = con.execute("SELECT COUNT(*) FROM gold.fato_volumes_base").fetchone()[0]
    print(f"\n_fato_pre: {n_pre:,} linhas | fato_volumes_base: {n_base:,} linhas")
    assert n_pre == n_base, "Join da fato perdeu ou duplicou linhas — dimensão incompleta."
    print("OK: nenhuma linha perdida/duplicada no join da fato.")

    total_gold = con.execute("SELECT SUM(quantidade) FROM gold.fato_volumes").fetchone()[0]
    total_silver = con.execute("SELECT SUM(quantidade) FROM silver.veiculos").fetchone()[0]
    print(f"SUM(quantidade) — silver.veiculos: {total_silver:,} | gold.fato_volumes: {total_gold:,}")
    # Invariante relativa (conservação de volume), não um total fixo — um total fixo
    # quebra garantido a cada upload novo, já que a soma muda por design.
    assert total_gold == total_silver, (
        f"SUM(quantidade) do Gold ({total_gold:,}) diferente do Silver ({total_silver:,}) "
        "— o build perdeu ou inflou volume."
    )
    print("OK: SUM(quantidade) do Gold bate com o Silver (nenhum volume perdido/inflado).")

    n_orfaos_empresa = con.execute("""
        SELECT COUNT(*) FROM gold.fato_volumes_base f
        LEFT JOIN gold.dim_empresa d ON f.empresa_key = d.empresa_key
        WHERE d.empresa_key IS NULL
    """).fetchone()[0]
    assert n_orfaos_empresa == 0, f"{n_orfaos_empresa} linha(s) com empresa_key sem dimensão correspondente."
    print("OK: toda empresa_key em fato_volumes_base resolve em gold.dim_empresa.")

    for tbl, key in [
        ("dim_veiculo_observado", "veiculo_key"),
        ("dim_veiculo_atual", "veiculo_atual_key"),
        ("dim_data", "data_key"),
    ]:
        mx = con.execute(f"SELECT MAX({key}) FROM gold.{tbl}").fetchone()[0]
        print(f"MAX({tbl}.{key}) = {mx:,}")


if __name__ == "__main__":
    main()
