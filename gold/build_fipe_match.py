"""
Diagnóstico/verificação do match FIPE em gold.dim_veiculo_atual e
gold.fato_volumes_base — a lógica de match em si mora dentro de
gold/build_volumes.py::build_dim_veiculo_atual() (roda junto com o resto do
Gold a cada upload automático; ver comentário lá pra saber por que não é um
passo desacoplado como gold/build_dim_empresa.py).

Este script não constrói nada — só inspeciona o que já foi construído.

Uso:
    python gold/build_fipe_match.py                     # distribuição de match_tier_fipe
    python gold/build_fipe_match.py --verify-alignment   # recompara marca/modelo FIPE vs DENATRAN
    python gold/build_fipe_match.py --verify-determinism # build dim_veiculo_atual 2x, diff (mesmo padrão de build_dim_empresa.py)
Requer MOTHERDUCK_TOKEN no .env.
"""

import sys

from gold.build_volumes import build_dim_veiculo_atual
from silver.db.connection import get_connection
from silver.vehicle_key.canonical_sql import register_sql_macros


def verify_alignment(con) -> None:
    n_fipe = con.execute("SELECT COUNT(DISTINCT normalize_text_sql(brand_name)) FROM staging.raw_json_fipe").fetchone()[0]
    n_denatran = con.execute("SELECT COUNT(DISTINCT normalize_text_sql(marca)) FROM gold.dim_veiculo_atual").fetchone()[0]
    print(f"Marcas distintas normalizadas -- FIPE: {n_fipe} | DENATRAN (dim_veiculo_atual): {n_denatran}")

    n_ambos = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT normalize_text_sql(marca) AS m FROM gold.dim_veiculo_atual
        ) d
        WHERE d.m IN (SELECT DISTINCT normalize_text_sql(brand_name) FROM staging.raw_json_fipe)
    """).fetchone()[0]
    print(f"Marcas em comum (normalizadas, já considerando marca_alias_fipe_sql se algum código a montante já aplicou): {n_ambos}")

    print()
    print("Top 20 marcas DENATRAN de maior volume SEM nenhum match FIPE (tier 2 ou 3):")
    sql = """
        SELECT o.marca, SUM(f.quantidade) AS veiculos
        FROM gold.fato_volumes_base f
        JOIN gold.dim_veiculo_observado o ON f.veiculo_key = o.veiculo_key
        JOIN gold.dim_veiculo_atual a ON f.veiculo_atual_key = a.veiculo_atual_key
        WHERE a.match_tier_fipe IS NULL
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 20
    """
    for row in con.execute(sql).fetchall():
        print(" ", row)


def print_distribution(con) -> None:
    print("Distribuição de match_tier_fipe em gold.dim_veiculo_atual (por vehicle_key, não por volume):")
    for row in con.execute(
        "SELECT match_tier_fipe, COUNT(*) FROM gold.dim_veiculo_atual GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(" ", row)

    print()
    print("Distribuição de match_tier_fipe por VOLUME (SUM(quantidade) em gold.fato_volumes):")
    for row in con.execute(
        "SELECT match_tier_fipe, SUM(quantidade) FROM gold.fato_volumes GROUP BY 1 ORDER BY 1"
    ).fetchall():
        print(" ", row)

    print()
    n_tier1 = con.execute("SELECT COUNT(*) FROM gold.fato_volumes_base WHERE fipe IS NOT NULL").fetchone()[0]
    print(f"Linhas de fato_volumes_base com FIPE tier 1 (embutido na própria venda): {n_tier1:,}")


def verify_determinism(con) -> None:
    print("--verify-determinism: reconstruindo dim_veiculo_atual do zero pra comparar...")
    con.execute("CREATE OR REPLACE TEMP TABLE _dim_veiculo_atual_snapshot1 AS SELECT * FROM gold.dim_veiculo_atual")
    build_dim_veiculo_atual(con)
    diff_a = con.execute(
        "SELECT COUNT(*) FROM (SELECT * FROM _dim_veiculo_atual_snapshot1 EXCEPT SELECT * FROM gold.dim_veiculo_atual)"
    ).fetchone()[0]
    diff_b = con.execute(
        "SELECT COUNT(*) FROM (SELECT * FROM gold.dim_veiculo_atual EXCEPT SELECT * FROM _dim_veiculo_atual_snapshot1)"
    ).fetchone()[0]
    print(f"build1-only={diff_a}, build2-only={diff_b}")
    assert diff_a == 0 and diff_b == 0, "dim_veiculo_atual não é determinístico entre builds."
    print("OK: determinístico (0 diferenças entre dois builds).")


def main():
    con = get_connection("motherduck")
    register_sql_macros(con)

    if "--verify-alignment" in sys.argv:
        verify_alignment(con)
    elif "--verify-determinism" in sys.argv:
        verify_determinism(con)
    else:
        print_distribution(con)


if __name__ == "__main__":
    main()
