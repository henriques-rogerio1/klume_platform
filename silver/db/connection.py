"""
Camada de conexão DuckDB / MotherDuck.

Nenhum normalizador deve montar a DSN do MotherDuck diretamente — sempre
recebem um `con` já pronto daqui. Isso mantém os testes 100% locais (sem
depender de rede ou do MOTHERDUCK_TOKEN) e deixa o alvo real (MotherDuck)
trocável em um único lugar.
"""

import os

import duckdb
from dotenv import load_dotenv

MOTHERDUCK_DATABASE = "Klume_DB_Cloud"


def get_connection(target: str = "local", *, path: str | None = None) -> duckdb.DuckDBPyConnection:
    """
    target="local" (default): conexão local, sem qualquer dependência de rede.
        path=None -> banco em memória (":memory:"); path="arquivo.duckdb" -> arquivo local.
    target="motherduck": conecta em Klume_DB_Cloud usando MOTHERDUCK_TOKEN do .env.
        Levanta ValueError se o token não estiver definido.
    """
    if target == "local":
        return duckdb.connect(path or ":memory:")

    if target == "motherduck":
        load_dotenv(dotenv_path=".env")
        token = os.getenv("MOTHERDUCK_TOKEN")
        if not token:
            raise ValueError("MOTHERDUCK_TOKEN environment variable not set!")
        return duckdb.connect(f"md:{MOTHERDUCK_DATABASE}?motherduck_token={token}")

    raise ValueError(f"target desconhecido: {target!r} (use 'local' ou 'motherduck')")
