"""
Histórico de perguntas/SQL por usuário — grava no MotherDuck (schema `app`,
separado de bronze/silver/gold pra não misturar dado operacional com dado
de negócio). Base pra depois identificar perguntas frequentes e usá-las
como exemplo de treino do Vanna (feito manual por enquanto — aqui só
guarda o histórico).

Duas decisões de desenho, as duas por causa do mesmo problema (log não pode
pesar no caminho síncrono que o usuário vê):
- `_ensure_table_once()` roda o DDL uma vez por processo (`st.cache_resource`),
  não a cada `log_query()` -- rodar `CREATE ... IF NOT EXISTS` redundante a
  partir de múltiplas escritas não tem motivo pra acontecer toda vez.
- O `INSERT` roda numa thread separada, com sua PRÓPRIA conexão isolada --
  não bloqueia a renderização do resultado da consulta, e não reusa a
  conexão de nenhuma outra thread (DuckDBPyConnection não é seguro pra
  execução concorrente do mesmo objeto entre threads).
"""

import threading
from datetime import datetime, timezone

import streamlit as st

from silver.db.connection import get_connection


def _create_table_ddl(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS app")
    con.execute("""
        CREATE TABLE IF NOT EXISTS app.query_log (
            ts TIMESTAMP,
            user_email VARCHAR,
            question VARCHAR,
            sql VARCHAR,
            row_count INTEGER,
            duration_ms INTEGER,
            error VARCHAR
        )
    """)


@st.cache_resource
def _ensure_table_once() -> bool:
    con = get_connection("motherduck")
    _create_table_ddl(con)
    return True


def _insert_worker(row: list) -> None:
    try:
        con = get_connection("motherduck")
        con.execute("INSERT INTO app.query_log VALUES (?, ?, ?, ?, ?, ?, ?)", row)
    except Exception:
        pass


def log_query(
    user_email: str,
    question: str,
    sql: str,
    *,
    row_count: int | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Registra uma pergunta/consulta. Nunca levanta exceção nem bloqueia --
    logging não pode derrubar nem atrasar a consulta do usuário se o
    registro falhar ou demorar por algum motivo."""
    try:
        _ensure_table_once()
        row = [
            datetime.now(timezone.utc),
            user_email,
            question,
            sql,
            row_count,
            duration_ms,
            error,
        ]
        threading.Thread(target=_insert_worker, args=(row,), daemon=True).start()
    except Exception:
        pass
