"""
Histórico de perguntas/SQL por usuário — grava no MotherDuck (schema `app`,
separado de bronze/silver/gold pra não misturar dado operacional com dado
de negócio). Base pra depois identificar perguntas frequentes e usá-las
como exemplo de treino do Vanna (feito manual por enquanto — aqui só
guarda o histórico).
"""

from datetime import datetime, timezone

from silver.db.connection import get_connection


def _ensure_table(con) -> None:
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


def log_query(
    user_email: str,
    question: str,
    sql: str,
    *,
    row_count: int | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Registra uma pergunta/consulta. Nunca levanta exceção — logging não
    pode derrubar a consulta do usuário se o registro falhar por algum motivo."""
    try:
        con = get_connection("motherduck")
        _ensure_table(con)
        con.execute(
            "INSERT INTO app.query_log VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                datetime.now(timezone.utc),
                user_email,
                question,
                sql,
                row_count,
                duration_ms,
                error,
            ],
        )
    except Exception:
        pass
