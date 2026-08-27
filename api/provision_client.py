"""
Provisiona uma linha em app.api_clients -- não é fluxo de self-service, uso
manual único por cliente confiável (hoje só o K.LUME ONE, talvez uma segunda
chave prod/staging).

Uso (via -m, não como script direto -- senão "silver" não é importável):
    python -m api.provision_client <api_key> <client_name>
Requer MOTHERDUCK_TOKEN no .env (token de escrita normal -- só este script
grava; a API em si só lê, via MOTHERDUCK_API_TOKEN).
"""

import sys
from datetime import datetime, timezone

from silver.db.connection import get_connection


def provision(api_key: str, client_name: str) -> None:
    con = get_connection("motherduck")
    con.execute("CREATE SCHEMA IF NOT EXISTS app")
    con.execute("""
        CREATE TABLE IF NOT EXISTS app.api_clients (
            api_key VARCHAR,
            client_name VARCHAR,
            active BOOLEAN,
            created_at TIMESTAMP
        )
    """)
    existing = con.execute(
        "SELECT COUNT(*) FROM app.api_clients WHERE api_key = ?", [api_key]
    ).fetchone()[0]
    if existing:
        print(f"api_key já existe pra {client_name!r} -- nada feito.")
        return
    con.execute(
        "INSERT INTO app.api_clients VALUES (?, ?, ?, ?)",
        [api_key, client_name, True, datetime.now(timezone.utc)],
    )
    print(f"Provisionado: {client_name!r}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python api/provision_client.py <api_key> <client_name>")
        sys.exit(1)
    provision(sys.argv[1], sys.argv[2])
