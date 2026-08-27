"""
get_connection() é o node mais conectado de toda a plataforma (29 edges no
grafo de conhecimento -- API, DENATRAN, FIPE, CNPJ, Vanna e todos os testes
passam por aqui) e, até esses testes, não tinha nenhuma cobertura direta.
Sem tocar rede/MotherDuck: target="local" é testado de verdade; a resolução
de DSN/token (_motherduck_dsn) é testada isoladamente via monkeypatch de
variável de ambiente, não de duckdb.connect() -- testa a lógica, não a
infraestrutura.
"""

import os

import pytest

from silver.db.connection import MOTHERDUCK_DATABASE, _motherduck_dsn, get_connection


def test_local_in_memory_connection_works():
    con = get_connection("local")
    assert con.execute("SELECT 1").fetchone() == (1,)


def test_local_file_connection_works(tmp_path):
    db_path = str(tmp_path / "test.duckdb")
    con = get_connection("local", path=db_path)
    con.execute("CREATE TABLE t AS SELECT 1 AS x")
    con.close()
    assert os.path.exists(db_path)


def test_unknown_target_raises():
    with pytest.raises(ValueError, match="desconhecido"):
        get_connection("bigquery")


def test_motherduck_dsn_raises_when_token_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    # dotenv não deve achar um .env de verdade no diretório de teste.
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="MOTHERDUCK_TOKEN"):
        _motherduck_dsn()


def test_motherduck_dsn_reads_custom_token_env(monkeypatch):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    monkeypatch.setenv("MOTHERDUCK_API_TOKEN", "api-token-xyz")
    dsn = _motherduck_dsn(token_env="MOTHERDUCK_API_TOKEN")
    assert dsn == f"md:{MOTHERDUCK_DATABASE}?motherduck_token=api-token-xyz"


def test_motherduck_dsn_exact_format(monkeypatch):
    # Prova a sintaxe exata da DSN -- um erro de digitação aqui (ex:
    # "motherduckToken=" em vez de "motherduck_token=") só falharia em
    # runtime contra o MotherDuck real sem este teste.
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "faketoken123")
    assert _motherduck_dsn() == "md:Klume_DB_Cloud?motherduck_token=faketoken123"


def test_get_connection_motherduck_uses_default_token_env(monkeypatch, tmp_path):
    monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
    # chdir obrigatório: o .env real do projeto tem um MOTHERDUCK_TOKEN válido --
    # sem isso, load_dotenv() recarregaria o token real e o teste passaria por
    # acidente (ou pior, tentaria conectar de verdade no MotherDuck).
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="MOTHERDUCK_TOKEN"):
        get_connection("motherduck")


def test_get_connection_motherduck_uses_custom_token_env(monkeypatch, tmp_path):
    # Confirma que get_connection repassa token_env corretamente -- é
    # exatamente o comportamento que a separação de token da API (read-write
    # hoje, mas trocável via env var) depende de estar certo.
    monkeypatch.delenv("MOTHERDUCK_API_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)  # mesmo motivo -- .env real também tem MOTHERDUCK_API_TOKEN
    with pytest.raises(ValueError, match="MOTHERDUCK_API_TOKEN"):
        get_connection("motherduck", token_env="MOTHERDUCK_API_TOKEN")
