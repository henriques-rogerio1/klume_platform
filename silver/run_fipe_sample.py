"""
Runner manual (não é teste automatizado do pytest) que valida o pipeline
Silver FIPE contra o MotherDuck de verdade, a partir de staging.raw_json_fipe.

Escreve silver.fipe_precos no MotherDuck e imprime estatísticas pra
conferência manual.

Uso:
    python silver/run_fipe_sample.py
Requer MOTHERDUCK_TOKEN no .env.
"""

from silver.comments import COMMENTS, GRAIN, apply_comments, apply_grain_comments
from silver.db.connection import get_connection
from silver.normalizers.fipe import normalize_fipe


def main():
    con = get_connection("motherduck")

    view = normalize_fipe(con)

    con.execute("CREATE SCHEMA IF NOT EXISTS silver")
    con.execute(f"CREATE OR REPLACE TABLE silver.fipe_precos AS SELECT * FROM {view}")

    total = con.execute("SELECT COUNT(*) FROM silver.fipe_precos").fetchone()[0]
    print(f"silver.fipe_precos: {total:,} linhas")

    n_dup = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT codigo_fipe, year_code, reference_month, COUNT(*) c
            FROM silver.fipe_precos GROUP BY 1, 2, 3 HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    assert n_dup == 0, f"Grão duplicado: {n_dup} grupo(s) de (codigo_fipe, year_code, reference_month)."
    print("OK: grão único (codigo_fipe, year_code, reference_month).")

    n_null_key = con.execute("SELECT COUNT(*) FROM silver.fipe_precos WHERE vehicle_key IS NULL").fetchone()[0]
    assert n_null_key == 0, f"{n_null_key} linha(s) com vehicle_key nulo."
    print("OK: vehicle_key nunca nulo.")

    n_null_preco = con.execute("SELECT COUNT(*) FROM silver.fipe_precos WHERE preco IS NULL").fetchone()[0]
    print(f"preco nulo: {n_null_preco:,} de {total:,} ({n_null_preco/total:.1%})")

    print("\nAplicando comentários de grão (COMMENT ON TABLE)...")
    apply_grain_comments(con, {"fipe_precos": GRAIN["fipe_precos"]})
    print("Aplicando comentários (ontologia)...")
    apply_comments(con, {"fipe_precos": COMMENTS["fipe_precos"]})

    print("\npor vehicle_type:")
    for tipo, n in con.execute(
        "SELECT vehicle_type, COUNT(*) FROM silver.fipe_precos GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"  {tipo}: {n:,}")

    print("\nmeses de referência:")
    for mes, n in con.execute(
        "SELECT data_referencia, COUNT(*) FROM silver.fipe_precos GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(f"  {mes}: {n:,}")


if __name__ == "__main__":
    main()
