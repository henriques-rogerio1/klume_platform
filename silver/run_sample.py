"""
Runner manual (não é teste automatizado do pytest) que valida o pipeline
Silver DENATRAN contra o MotherDuck de verdade, combinando as fontes de
amostra definidas no plano: staging.bronze_2016, staging.bronze_2020,
staging.bronze_2025 (MotherDuck) e o Parquet local de 1957 (histórico).

Escreve silver.veiculos / silver.veiculos_historico no MotherDuck e
imprime estatísticas pra conferência manual.

Uso:
    python silver/run_sample.py
Requer MOTHERDUCK_TOKEN no .env.
"""

from silver.db.connection import get_connection
from silver.normalizers.denatran import normalize_denatran

LOCAL_1957 = (
    "C:/Users/Rogerio Henriques/Documents/data/bronze/veiculos_raw"
    "/1957/1957/Dados_ingest_20251001T225605Z.parquet"
)

SOURCES = [
    ("2016", "staging.bronze_2016"),
    ("2020", "staging.bronze_2020"),
    ("2025", "staging.bronze_2025"),
    ("1957", f"read_parquet('{LOCAL_1957}')"),
]


def main():
    con = get_connection("motherduck")

    recent_views = []
    historico_views = []
    for label, source in SOURCES:
        recent, historico = normalize_denatran(
            con, source, mapping_table="silver.mapping_table", stage_prefix=f"run_{label}"
        )
        recent_views.append(recent)
        historico_views.append(historico)
        n_recent = con.execute(f"SELECT COUNT(*) FROM {recent}").fetchone()[0]
        n_hist = con.execute(f"SELECT COUNT(*) FROM {historico}").fetchone()[0]
        print(f"[{label}] recente={n_recent} historico={n_hist}")

    recent_union = " UNION ALL BY NAME ".join(f"SELECT * FROM {v}" for v in recent_views)
    historico_union = " UNION ALL BY NAME ".join(f"SELECT * FROM {v}" for v in historico_views)

    con.execute("CREATE SCHEMA IF NOT EXISTS silver")
    con.execute(f"CREATE OR REPLACE TABLE silver.veiculos AS {recent_union}")
    con.execute(f"CREATE OR REPLACE TABLE silver.veiculos_historico AS {historico_union}")

    total_recent = con.execute("SELECT COUNT(*) FROM silver.veiculos").fetchone()[0]
    total_hist = con.execute("SELECT COUNT(*) FROM silver.veiculos_historico").fetchone()[0]
    print(f"\nsilver.veiculos: {total_recent} linhas")
    print(f"silver.veiculos_historico: {total_hist} linhas")

    print("\nmatch_tier (silver.veiculos):")
    for tier, n in con.execute(
        "SELECT match_tier, COUNT(*) FROM silver.veiculos GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"  {tier}: {n}")

    cnpj_rows = con.execute(
        "SELECT COUNT(*) FROM silver.veiculos WHERE tipo_faturado = 'CNPJ'"
    ).fetchone()[0]
    cnpj_extracted = con.execute(
        "SELECT COUNT(*) FROM silver.veiculos "
        "WHERE tipo_faturado = 'CNPJ' AND cnpj_basico_faturado IS NOT NULL"
    ).fetchone()[0]
    print(f"\nCNPJ: {cnpj_extracted}/{cnpj_rows} linhas com cnpj_basico_faturado extraído")

    hist_cols = {r[0] for r in con.execute("DESCRIBE silver.veiculos_historico").fetchall()}
    assert "vehicle_key" not in hist_cols, "silver.veiculos_historico não deveria ter vehicle_key"
    assert "canonical_str" not in hist_cols, "silver.veiculos_historico não deveria ter canonical_str"
    print("\nOK: silver.veiculos_historico não tem colunas de hash.")


if __name__ == "__main__":
    main()
