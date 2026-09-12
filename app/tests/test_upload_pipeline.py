"""
Testa process_upload() isolado -- sem Streamlit, sem rede real (S3 fake, banco
local). Confirma que o refactor de app/pages/1_Upload_Dados.py::process_upload
não perdeu comportamento, e que o fix de dedup por (hash, ano) funciona:
reenviar o mesmo arquivo pula o que já foi processado, sem duplicar linhas.
"""

from pathlib import Path

import duckdb
import pytest

from app.upload_pipeline import process_upload
from silver.db.connection import get_connection
from silver.normalizers.denatran import normalize_denatran

FIXTURES = Path(__file__).parent.parent.parent / "silver" / "tests" / "fixtures"


class _FakeS3Client:
    """S3 client fake -- grava em memória, nunca toca rede."""

    def __init__(self):
        self.uploads = []

    def head_bucket(self, Bucket):  # noqa: N803 (assinatura do boto3)
        return {}

    def upload_file(self, local_path, bucket, key):
        self.uploads.append((local_path, bucket, key))


def _make_xlsx_from_parquet(parquet_path: Path, tmp_path: Path) -> Path:
    # A fonte real de "Data de Emplacamento" chega como DATE de verdade no
    # XLSX (ver docstring de app/upload_pipeline.py) -- o fixture parquet
    # guarda como VARCHAR (mesmo formato bruto do Bronze), então convertemos
    # pra DATE antes de escrever o XLSX, senão date_part()/strftime() em
    # process_upload quebrariam contra uma coluna texto.
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT * REPLACE (
            COALESCE(
                TRY_STRPTIME("Data de Emplacamento", '%Y%m%d'),
                TRY_STRPTIME("Data de Emplacamento", '%Y-%m-%d')
            )::DATE AS "Data de Emplacamento"
        )
        FROM read_parquet('{parquet_path.as_posix()}')
    """).df()
    xlsx_path = tmp_path / "sample.xlsx"
    df.to_excel(xlsx_path, index=False, engine="openpyxl")
    return xlsx_path


@pytest.fixture
def con():
    c = get_connection("local")
    c.execute("CREATE SCHEMA IF NOT EXISTS staging")
    c.execute("CREATE SCHEMA IF NOT EXISTS silver")
    c.execute("CREATE SCHEMA IF NOT EXISTS app")

    bronze_2020 = FIXTURES / "bronze_2020_sample.parquet"

    c.execute(f"""
        CREATE TABLE staging.bronze_2024 AS
        SELECT * FROM read_parquet('{bronze_2020.as_posix()}') LIMIT 0
    """)
    c.execute(f"""
        CREATE TABLE silver.mapping_table AS
        SELECT * FROM read_parquet('{(FIXTURES / "mapping_table_sample.parquet").as_posix()}')
    """)

    # silver.veiculos/veiculos_historico com o schema real de
    # normalize_denatran, derivado rodando a função uma vez contra o fixture.
    recent, historico = normalize_denatran(
        c, f"read_parquet('{bronze_2020.as_posix()}')",
        mapping_table="silver.mapping_table", stage_prefix="setup",
    )
    c.execute(f"CREATE TABLE silver.veiculos AS SELECT * FROM {recent} LIMIT 0")
    c.execute(f"CREATE TABLE silver.veiculos_historico AS SELECT * FROM {historico} LIMIT 0")
    return c


def test_process_upload_new_file(con, tmp_path):
    xlsx_path = _make_xlsx_from_parquet(FIXTURES / "bronze_2020_sample.parquet", tmp_path)
    file_bytes = xlsx_path.read_bytes()

    s3 = _FakeS3Client()
    resultado = process_upload(con, file_bytes, "teste_2020.xlsx", s3_client=s3, s3_bucket="fake-bucket", build_gold_fn=lambda: None)

    assert resultado.status == "ok"
    assert 2020 in resultado.anos_processados
    assert s3.uploads, "deveria ter subido pelo menos um arquivo pro S3 (fake)"

    n2020 = con.execute("SELECT COUNT(*) FROM staging.bronze_2020").fetchone()[0]
    assert n2020 > 0
    n_silver = con.execute(
        "SELECT COUNT(*) FROM silver.veiculos WHERE date_part('year', data_emplacamento) = 2020"
    ).fetchone()[0]
    assert n_silver > 0


def test_process_upload_dedup_by_hash_and_year(con, tmp_path):
    xlsx_path = _make_xlsx_from_parquet(FIXTURES / "bronze_2020_sample.parquet", tmp_path)
    file_bytes = xlsx_path.read_bytes()
    s3 = _FakeS3Client()

    r1 = process_upload(con, file_bytes, "teste_2020.xlsx", s3_client=s3, s3_bucket="fake-bucket", build_gold_fn=lambda: None)
    assert r1.anos_processados == [2020]

    n_before = con.execute("SELECT COUNT(*) FROM staging.bronze_2020").fetchone()[0]
    r2 = process_upload(con, file_bytes, "teste_2020.xlsx", s3_client=s3, s3_bucket="fake-bucket", build_gold_fn=lambda: None)
    n_after = con.execute("SELECT COUNT(*) FROM staging.bronze_2020").fetchone()[0]

    assert r2.anos_processados == [], "reenvio do mesmo arquivo não deveria reprocessar o ano já feito"
    assert any(a.status == "ja_processado" for a in r2.anos)
    assert n_before == n_after, "reenvio não deveria duplicar linhas"
    assert not r2.gold_reconstruido, "sem ano novo processado, não deveria tentar reconstruir Gold"


def test_linhas_com_data_invalida_vao_para_quarentena(con, tmp_path):
    """Regressão do achado real: linha com data inválida ('0') sumia
    silenciosamente -- 3 linhas assim já residiam em staging.bronze_2023 sem
    nenhum registro. Agora tem que ir pra quarentena e fechar a conta."""
    import pandas as pd

    src = duckdb.connect().execute(f"""
        SELECT * REPLACE (
            COALESCE(
                TRY_STRPTIME("Data de Emplacamento", '%Y%m%d'),
                TRY_STRPTIME("Data de Emplacamento", '%Y-%m-%d')
            )::DATE AS "Data de Emplacamento"
        )
        FROM read_parquet('{(FIXTURES / "bronze_2020_sample.parquet").as_posix()}')
        LIMIT 50
    """).df()
    # Injeta o lixo real observado em produção: data = '0'
    src["Data de Emplacamento"] = src["Data de Emplacamento"].astype(str)
    src.loc[0, "Data de Emplacamento"] = "0"
    src.loc[1, "Data de Emplacamento"] = "0"
    xlsx_path = tmp_path / "com_lixo.xlsx"
    src.to_excel(xlsx_path, index=False, engine="openpyxl")

    s3 = _FakeS3Client()
    resultado = process_upload(
        con, xlsx_path.read_bytes(), "com_lixo.xlsx",
        s3_client=s3, s3_bucket="fake-bucket", build_gold_fn=lambda: None,
    )

    assert resultado.total_lidas == 50
    assert resultado.total_quarentena == 2, "as 2 linhas com data '0' deveriam estar em quarentena"
    assert resultado.total_inseridas == 48
    # Reconciliação: nada some sem explicação
    assert resultado.total_inseridas + resultado.total_quarentena == resultado.total_lidas

    q = con.execute(
        "SELECT reject_reason, raw_row FROM staging.bronze_quarantine"
    ).fetchall()
    assert len(q) == 2
    assert all(r[0] == "DATA_INVALIDA" for r in q)
    assert all('"0"' in str(r[1]) for r in q), "raw_row deve preservar a linha original"


def test_process_upload_rejects_bad_schema(con, tmp_path):
    import pandas as pd

    df = pd.DataFrame({"Coluna Qualquer": [1, 2, 3]})
    xlsx_path = tmp_path / "invalido.xlsx"
    df.to_excel(xlsx_path, index=False, engine="openpyxl")

    s3 = _FakeS3Client()
    resultado = process_upload(con, xlsx_path.read_bytes(), "invalido.xlsx", s3_client=s3, s3_bucket="fake-bucket")

    assert resultado.status == "rejeitado_schema"
    assert not s3.uploads, "arquivo rejeitado não deveria nem tentar subir pro S3"
