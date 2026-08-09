"""
Prova de que canonical_str_denatran_sql() (macro SQL, roda no MotherDuck)
produz exatamente o mesmo resultado que canonical_str() (Python, já testado
em test_canonical.py). Sem essa paridade, trocar Python por SQL poderia
corromper vehicle_key silenciosamente — exatamente o tipo de bug que motivou
essa reescrita inteira.
"""

from pathlib import Path

import pytest

from silver.db.connection import get_connection
from silver.vehicle_key.canonical import canonical_str
from silver.vehicle_key.canonical_sql import register_sql_macros

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def con():
    c = get_connection("local")
    register_sql_macros(c)
    return c


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bronze_1957_sample.parquet",
        "bronze_2016_sample.parquet",
        "bronze_2020_sample.parquet",
        "bronze_2025_sample.parquet",
    ],
)
def test_sql_macro_matches_python_canonical_str(con, fixture_name):
    path = (FIXTURES / fixture_name).as_posix()
    rows = con.execute(f"""
        SELECT
            "Marca" AS marca,
            "Versão" AS versao,
            "Ano Modelo" AS ano_modelo,
            "Combustível" AS combustivel,
            canonical_str_denatran_sql("Marca", "Versão", "Ano Modelo", "Combustível") AS sql_result
        FROM read_parquet('{path}')
        WHERE "Marca" NOT IN ('nan', '')
          AND "Versão" NOT IN ('nan', '')
          AND "Ano Modelo" NOT IN ('nan', '')
        LIMIT 300
    """).fetchall()
    if not rows:
        # 1957 é dado agregado antigo — Ano Modelo é 'nan' em toda a amostra,
        # não sobra nenhuma linha completa pra comparar. Não é defeito da
        # macro, é a esparsidade real do histórico.
        pytest.skip(f"sem linhas com todos os campos preenchidos em {fixture_name}")

    mismatches = []
    for marca, versao, ano_modelo, combustivel, sql_result in rows:
        py_result = canonical_str(
            marca or "", versao or "", ano_modelo or 0, combustivel or "", source="denatran"
        )
        if py_result != sql_result:
            mismatches.append((marca, versao, ano_modelo, combustivel, py_result, sql_result))

    assert not mismatches, f"{len(mismatches)} divergências Python vs SQL, ex: {mismatches[:5]}"


def test_sql_macro_matches_python_for_known_tricky_cases(con):
    cases = [
        ("HONDA", "HONDA/CG 160 FAN", "2016", "Álcool / Gasolina                                 "),
        ("FIAT", "FIAT/SIENA TETRAFUEL 1.4", "2016", "Álcool / Gasolina / Gás Natural Veicular          "),
        ("MINI", "I/MINI COOPER S CABRIO", "2026", "GASOLINA"),
        ("FIAT", "FIAT/ARGO 1.0", "2024", "ALCOOL/GASOLINA"),
    ]
    for marca, versao, ano, comb in cases:
        py_result = canonical_str(marca, versao, ano, comb, source="denatran")
        sql_result = con.execute(
            "SELECT canonical_str_denatran_sql(?, ?, ?, ?)", [marca, versao, ano, comb]
        ).fetchone()[0]
        assert py_result == sql_result, f"{marca}/{versao}: python={py_result!r} sql={sql_result!r}"
