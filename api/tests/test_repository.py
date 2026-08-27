from datetime import date

import duckdb
import pytest

from api.repository import query_volumes
from api.schemas import VolumesFilters


@pytest.fixture
def cursor():
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA gold")
    con.execute("""
        CREATE TABLE gold.fato_volumes AS SELECT * FROM (VALUES
            (DATE '2020-01-15', 'FIAT', 'Varejo', 10, 10),
            (DATE '2020-01-20', 'FIAT', 'Direta', 5, 5),
            (DATE '2020-02-01', 'FIAT', 'Varejo', 7, 7),
            (DATE '2020-01-10', 'CHEVROLET', NULL, 3, NULL),
            (DATE '2019-12-31', 'FIAT', 'Varejo', 999, 999)
        ) AS t(data_emplacamento, marca, tipo_venda, quantidade, quantidade_tipo_venda_conhecido)
    """)
    return con.cursor()


def test_group_by_marca_tipo_venda(cursor):
    filters = VolumesFilters(
        data_de=date(2020, 1, 1), data_a=date(2020, 12, 31),
        group_by=["marca", "tipo_venda"], limit=100,
    )
    rows, truncated = query_volumes(cursor, filters)
    assert not truncated
    by_key = {(r["marca"], r["tipo_venda"]): r for r in rows}
    assert by_key[("FIAT", "Varejo")]["quantidade"] == 17
    assert by_key[("FIAT", "Direta")]["quantidade"] == 5
    assert by_key[("CHEVROLET", None)]["quantidade"] == 3
    assert by_key[("CHEVROLET", None)]["quantidade_tipo_venda_conhecido"] is None


def test_date_range_excludes_outside_window(cursor):
    filters = VolumesFilters(
        data_de=date(2020, 1, 1), data_a=date(2020, 12, 31),
        group_by=["marca"], limit=100,
    )
    rows, _ = query_volumes(cursor, filters)
    fiat = next(r for r in rows if r["marca"] == "FIAT")
    # 10 + 5 + 7 = 22 -- a linha de 2019-12-31 (999) fica de fora do filtro.
    assert fiat["quantidade"] == 22


def test_marca_filter(cursor):
    filters = VolumesFilters(
        data_de=date(2020, 1, 1), data_a=date(2020, 12, 31),
        group_by=["marca"], marca="CHEVROLET", limit=100,
    )
    rows, _ = query_volumes(cursor, filters)
    assert len(rows) == 1
    assert rows[0]["marca"] == "CHEVROLET"


def test_marca_filter_is_parameterized_not_interpolated(cursor):
    # marca vem de query param do usuário -- prova que é tratado como valor
    # literal (bound parameter), não concatenado na string SQL. Um marca
    # malicioso não deve derrubar a tabela nem alterar o resultado da query.
    malicious = "FIAT'; DROP TABLE gold.fato_volumes; --"
    filters = VolumesFilters(
        data_de=date(2020, 1, 1), data_a=date(2020, 12, 31),
        group_by=["marca"], marca=malicious, limit=100,
    )
    rows, _ = query_volumes(cursor, filters)
    assert rows == []  # nenhuma marca é literalmente esse texto -- 0 resultados, sem erro

    # A tabela sobrevive -- se o DROP tivesse executado, isso levantaria exceção.
    survives = cursor.execute("SELECT COUNT(*) FROM gold.fato_volumes").fetchone()[0]
    assert survives > 0


def test_limit_truncates_and_flags(cursor):
    filters = VolumesFilters(
        data_de=date(2020, 1, 1), data_a=date(2020, 12, 31),
        group_by=["marca", "tipo_venda"], limit=1,
    )
    rows, truncated = query_volumes(cursor, filters)
    assert len(rows) == 1
    assert truncated is True


def test_rejects_group_by_outside_allowlist(cursor):
    filters = VolumesFilters(
        data_de=date(2020, 1, 1), data_a=date(2020, 12, 31),
        group_by=["marca", "quantidade"], limit=100,
    )
    with pytest.raises(ValueError, match="allowlist"):
        query_volumes(cursor, filters)
