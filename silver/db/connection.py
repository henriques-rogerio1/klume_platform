"""
Camada de conexão DuckDB / MotherDuck.

Nenhum normalizador deve montar a DSN do MotherDuck diretamente — sempre
recebem um `con` já pronto daqui. Isso mantém os testes 100% locais (sem
depender de rede ou do MOTHERDUCK_TOKEN) e deixa o alvo real (MotherDuck)
trocável em um único lugar.

get_connection() é o node mais conectado de toda a plataforma (confirmado via
graphify: 29 edges, todo domínio -- API, DENATRAN, FIPE, CNPJ, Vanna, testes --
passa por aqui). A lógica de resolver a DSN/token fica isolada em
_motherduck_dsn() especificamente pra ser testável sem precisar de rede nem de
mockar duckdb.connect() -- ver silver/tests/test_connection.py.
"""

import os

import duckdb
from dotenv import load_dotenv

MOTHERDUCK_DATABASE = "Klume_DB_Cloud"


def _motherduck_dsn(token_env: str = "MOTHERDUCK_TOKEN") -> str:
    load_dotenv(dotenv_path=".env")
    token = os.getenv(token_env)
    if not token:
        raise ValueError(f"{token_env} environment variable not set!")
    return f"md:{MOTHERDUCK_DATABASE}?motherduck_token={token}"


def get_connection(
    target: str = "local", *, path: str | None = None, token_env: str = "MOTHERDUCK_TOKEN"
) -> duckdb.DuckDBPyConnection:
    """
    target="local" (default): conexão local, sem qualquer dependência de rede.
        path=None -> banco em memória (":memory:"); path="arquivo.duckdb" -> arquivo local.
    target="motherduck": conecta em Klume_DB_Cloud usando o token da env var `token_env`
        (default MOTHERDUCK_TOKEN) do .env. Levanta ValueError se o token não estiver
        definido. `token_env` existe pra permitir um token diferente (ex: read-only)
        sem duplicar a lógica de DSN em nenhum lugar novo — ver api/db.py.
    """
    if target == "local":
        return duckdb.connect(path or ":memory:")

    if target == "motherduck":
        return duckdb.connect(_motherduck_dsn(token_env))

    raise ValueError(f"target desconhecido: {target!r} (use 'local' ou 'motherduck')")
