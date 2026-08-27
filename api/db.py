"""
Conexão MotherDuck compartilhada da API -- uma só, criada no lifespan do
FastAPI (main.py), nunca por request. Cada request pega um cursor próprio
via .cursor() (thread-local, seguro sob o threadpool do FastAPI -- rotas que
tocam o DuckDB precisam ser `def` normal, não `async def`, senão o FastAPI
não despacha pra uma thread do pool e o event loop trava na query).

Sem pool de conexão externo -- a doc do MotherDuck desaconselha
explicitamente (atrapalha o cache de instância deles):
https://motherduck.com/docs/key-tasks/authenticating-and-connecting-to-motherduck/multithreading-and-parallelism/multithreading-and-parallelism-python/
"""

import duckdb
from fastapi import Request

from silver.db.connection import get_connection


def create_shared_connection() -> duckdb.DuckDBPyConnection:
    # Token read-only (Read Scaling Token do MotherDuck) -- nunca o token de
    # escrita do pipeline. Ver api/provision_client.py pro único fluxo que
    # precisa escrever (provisionar app.api_clients), que usa o token normal.
    return get_connection("motherduck", token_env="MOTHERDUCK_API_TOKEN")


def get_cursor(request: Request) -> duckdb.DuckDBPyConnection:
    return request.app.state.db_con.cursor()
