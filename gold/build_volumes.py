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
        "match_tier": "1 = código FIPE veio direto da fonte DENATRAN na própria linha. "
        "NULL = não identificado. Não existe preço FIPE disponível ainda nesta versão.",
        "cnpj_basico_faturado": "8 primeiros dígitos do CNPJ de quem faturou (pessoa "
        "jurídica) — só preenchido quando tipo_faturado = 'CNPJ'.",
    },
}


def apply_comments(con) -> None:
    for table, cols in COMMENTS.items():
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
    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_veiculo_atual AS
        SELECT
            row_number() OVER (ORDER BY vehicle_key) AS veiculo_atual_key,
            vehicle_key, marca, modelo, versao, ano_modelo, combustivel_normalizado,
            segmentacao_atualizada AS segmentacao_klume,
            segmentacao_original AS segmentacao_original_klume,
            tipo_veiculo_principal AS tipo_veiculo_klume
        FROM (
            SELECT vehicle_key, marca, modelo, versao, ano_modelo,
                   map_combustivel_sql(combustivel) AS combustivel_normalizado,
                   segmentacao_atualizada, segmentacao_original, tipo_veiculo_principal
            FROM silver.veiculos
            QUALIFY row_number() OVER (
                PARTITION BY vehicle_key
                ORDER BY data_emplacamento DESC, marca, modelo, versao, ano_modelo,
                         segmentacao_atualizada, segmentacao_original, tipo_veiculo_principal
            ) = 1
        )
    """)


def build_dim_geografia(con) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_geografia AS
        SELECT codigo_municipio,
               arg_max(municipio_emplacamento, data_emplacamento) AS municipio,
               arg_max(estado_emplacamento, data_emplacamento) AS estado
        FROM silver.veiculos
        WHERE codigo_municipio IS NOT NULL
        GROUP BY codigo_municipio

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
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _fato_pre AS
        SELECT
            data_emplacamento, vehicle_key, marca, modelo, versao, ano_modelo,
            map_combustivel_sql(combustivel) AS combustivel_normalizado,
            segmentacao_atualizada, segmentacao_original, tipo_veiculo_principal,
            COALESCE(codigo_municipio, -1) AS codigo_municipio,
            municipio_emplacamento, estado_emplacamento,
            cor_predominante, tipo_venda, match_tier, cnpj_basico_faturado,
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
            f.quantidade
        FROM gold.fato_volumes_base f
        JOIN gold.dim_veiculo_observado o ON f.veiculo_key = o.veiculo_key
        JOIN gold.dim_veiculo_atual a ON f.veiculo_atual_key = a.veiculo_atual_key
        JOIN gold.dim_data d ON f.data_key = d.data_key
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
    print("Aplicando comentários (ontologia)...")
    apply_comments(con)

    n_pre = con.execute("SELECT COUNT(*) FROM _fato_pre").fetchone()[0]
    n_base = con.execute("SELECT COUNT(*) FROM gold.fato_volumes_base").fetchone()[0]
    print(f"\n_fato_pre: {n_pre:,} linhas | fato_volumes_base: {n_base:,} linhas")
    assert n_pre == n_base, "Join da fato perdeu ou duplicou linhas — dimensão incompleta."
    print("OK: nenhuma linha perdida/duplicada no join da fato.")

    total = con.execute("SELECT SUM(quantidade) FROM gold.fato_volumes").fetchone()[0]
    print(f"SUM(quantidade) na view: {total:,}")
    assert total == 10_658_607, f"SUM(quantidade) diferente do esperado: {total}"
    print("OK: SUM(quantidade) bate com o valor conhecido.")

    for tbl, key in [
        ("dim_veiculo_observado", "veiculo_key"),
        ("dim_veiculo_atual", "veiculo_atual_key"),
        ("dim_data", "data_key"),
    ]:
        mx = con.execute(f"SELECT MAX({key}) FROM gold.{tbl}").fetchone()[0]
        print(f"MAX({tbl}.{key}) = {mx:,}")


if __name__ == "__main__":
    main()
