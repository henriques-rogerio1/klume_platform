"""
Constrói gold.fato_volumes — tabela única (não normalizada) de volumes de
emplacamento, agregada a partir de silver.veiculos.

Uma tabela larga, não um star schema separado: MVP de um dia, mais fácil
do Vanna raciocinar sem precisar acertar joins, e já cobre os 3 formatos
de pergunta reais que encontramos em Documents/data/Amostras (extract
linha a linha fica no silver.veiculos direto; pivot mês/ano sai desta
tabela via date_trunc/date_part).

Uso:
    python gold/build_volumes.py
Requer MOTHERDUCK_TOKEN no .env.
"""

from silver.db.connection import get_connection
from silver.vehicle_key.canonical_sql import register_sql_macros

DIMENSIONS = [
    "data_emplacamento",
    "marca",
    "modelo",
    "versao",
    "segmentacao_atualizada",
    "segmentacao_original",
    "combustivel",
    "cor_predominante",
    "tipo_venda",
    "estado_emplacamento",
    "tipo_veiculo_principal",
    "cnpj_basico_faturado",
    "match_tier",
]


def main():
    con = get_connection("motherduck")
    con.execute("CREATE SCHEMA IF NOT EXISTS gold")

    # combustivel é passthrough bruto do Silver — o mesmo combustível aparece
    # grafado diferente por era ('Álcool / Gasolina' em 2016 vs 'ALCOOL/GASOLINA'
    # em 2025), o que fragmentaria contagem por combustível silenciosamente.
    # map_combustivel_sql já existe e já é testado (mesma macro do canonical_str) —
    # reaproveitada aqui só pra normalizar o rótulo, não pro hash.
    register_sql_macros(con)

    dims_sql = ",\n    ".join(DIMENSIONS)
    con.execute(f"""
        CREATE OR REPLACE TABLE gold.fato_volumes AS
        SELECT
            {dims_sql},
            map_combustivel_sql(combustivel) AS combustivel_normalizado,
            SUM(quantidade) AS quantidade
        FROM silver.veiculos
        GROUP BY ALL
    """)

    n_gold = con.execute("SELECT COUNT(*) FROM gold.fato_volumes").fetchone()[0]
    n_silver = con.execute("SELECT COUNT(*) FROM silver.veiculos").fetchone()[0]
    total_qtd_gold = con.execute("SELECT SUM(quantidade) FROM gold.fato_volumes").fetchone()[0]
    total_qtd_silver = con.execute("SELECT SUM(quantidade) FROM silver.veiculos").fetchone()[0]

    print(f"silver.veiculos: {n_silver:,} linhas, SUM(quantidade)={total_qtd_silver:,}")
    print(f"gold.fato_volumes: {n_gold:,} linhas, SUM(quantidade)={total_qtd_gold:,}")

    assert total_qtd_gold == total_qtd_silver, (
        "SUM(quantidade) divergiu entre silver e gold — a agregação perdeu ou duplicou volume."
    )
    print("OK: SUM(quantidade) bate entre silver.veiculos e gold.fato_volumes.")


if __name__ == "__main__":
    main()
