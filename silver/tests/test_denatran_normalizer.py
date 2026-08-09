from datetime import date
from pathlib import Path

import pytest

from silver.db.connection import get_connection
from silver.normalizers.denatran import normalize_denatran

FIXTURES = Path(__file__).parent / "fixtures"


def _parquet(name: str) -> str:
    return f"read_parquet('{(FIXTURES / name).as_posix()}')"


@pytest.fixture
def con():
    c = get_connection("local")
    c.execute("CREATE SCHEMA IF NOT EXISTS silver")
    c.execute(f"""
        CREATE TABLE silver.mapping_table AS
        SELECT * FROM {_parquet('mapping_table_sample.parquet')}
    """)
    return c


def test_pipeline_runs_without_binder_error_2016(con):
    recent, historico = normalize_denatran(con, _parquet("bronze_2016_sample.parquet"))
    # não deve levantar exceção — regressão direta do bug "Preço FIPE" inexistente
    con.execute(f"SELECT * FROM {recent}").fetchall()
    con.execute(f"SELECT * FROM {historico}").fetchall()


def test_pipeline_runs_without_binder_error_2020_2025(con):
    for label, name in [("d2020e", "bronze_2020_sample.parquet"), ("d2025e", "bronze_2025_sample.parquet")]:
        recent, _ = normalize_denatran(con, _parquet(name), stage_prefix=label)
        con.execute(f"SELECT * FROM {recent}").fetchall()


def test_date_parses_dashed_iso_format_2016(con):
    recent, historico = normalize_denatran(con, _parquet("bronze_2016_sample.parquet"))
    rows = con.execute(f"SELECT data_emplacamento FROM {recent} UNION ALL SELECT data_emplacamento FROM {historico}").fetchall()
    dates = [r[0] for r in rows if r[0] is not None]
    assert dates, "esperava pelo menos uma data parseada em 2016"
    assert all(isinstance(d, date) for d in dates)
    assert any(d.year == 2016 for d in dates)


def test_date_parses_compact_format_2025(con):
    recent, _ = normalize_denatran(con, _parquet("bronze_2025_sample.parquet"), stage_prefix="d2025")
    rows = con.execute(f"SELECT data_emplacamento FROM {recent}").fetchall()
    dates = [r[0] for r in rows if r[0] is not None]
    assert dates
    assert all(d.year == 2025 for d in dates)


def test_blank_sentinels_become_null(con):
    recent, historico = normalize_denatran(con, _parquet("bronze_2016_sample.parquet"))
    literal_nan = con.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT numero_chassi FROM {recent} UNION ALL SELECT numero_chassi FROM {historico}
        ) WHERE numero_chassi = 'nan'
    """).fetchone()[0]
    assert literal_nan == 0


def test_2025_fipe_dash_sentinel_does_not_become_tier_1(con):
    recent, _ = normalize_denatran(con, _parquet("bronze_2025_sample.parquet"), stage_prefix="d2025b")
    bad = con.execute(f"SELECT COUNT(*) FROM {recent} WHERE fipe = '-'").fetchone()[0]
    assert bad == 0, "'-' deveria virar NULL, não permanecer como código FIPE"


def test_2016_combustivel_accented_padded_produces_canonical_G(con):
    recent, historico = normalize_denatran(con, _parquet("bronze_2016_sample.parquet"))
    rows = con.execute(f"""
        SELECT canonical_str FROM {recent}
        WHERE combustivel ILIKE '%lcool%/%asolina%'
    """).fetchall()
    assert rows, "esperava ao menos uma linha flex (álcool/gasolina) em 2016"
    assert all(r[0].endswith("|G") for r in rows)


def test_year_split_1957_only_in_historico(con):
    recent, historico = normalize_denatran(con, _parquet("bronze_1957_sample.parquet"), stage_prefix="d1957")
    assert con.execute(f"SELECT COUNT(*) FROM {recent}").fetchone()[0] == 0
    assert con.execute(f"SELECT COUNT(*) FROM {historico}").fetchone()[0] > 0


def test_historico_schema_excludes_hash_columns(con):
    _, historico = normalize_denatran(con, _parquet("bronze_1957_sample.parquet"), stage_prefix="d1957b")
    cols = {r[0] for r in con.execute(f"DESCRIBE {historico}").fetchall()}
    assert "canonical_str" not in cols
    assert "vehicle_key" not in cols
    assert "match_tier" not in cols


def test_recent_has_vehicle_key_and_canonical_str(con):
    recent, _ = normalize_denatran(con, _parquet("bronze_2025_sample.parquet"), stage_prefix="d2025c")
    row = con.execute(f"SELECT canonical_str, vehicle_key FROM {recent} LIMIT 1").fetchone()
    assert row[0] is not None
    assert row[1] is not None


def test_match_tier_only_1_3_or_null(con):
    recent, _ = normalize_denatran(
        con, _parquet("bronze_2025_sample.parquet"), mapping_table="silver.mapping_table", stage_prefix="d2025d"
    )
    tiers = {r[0] for r in con.execute(f"SELECT DISTINCT match_tier FROM {recent}").fetchall()}
    assert tiers <= {1, 3, None}


def test_cnpj_basico_faturado_extracted_from_float_string(con):
    recent, _ = normalize_denatran(con, _parquet("bronze_2020_sample.parquet"), stage_prefix="d2020")
    rows = con.execute(f"""
        SELECT identificacao_faturado, cnpj_basico_faturado
        FROM {recent}
        WHERE tipo_faturado = 'CNPJ' AND identificacao_faturado IS NOT NULL
        LIMIT 5
    """).fetchall()
    assert rows
    for raw, basico in rows:
        assert basico is not None
        assert len(basico) == 8
        assert basico.isdigit()
