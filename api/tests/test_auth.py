import duckdb
import pytest

from api.auth import _is_valid_key


@pytest.fixture
def cursor():
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA app")
    con.execute("""
        CREATE TABLE app.api_clients (
            api_key VARCHAR, client_name VARCHAR, active BOOLEAN, created_at TIMESTAMP
        )
    """)
    con.execute("INSERT INTO app.api_clients VALUES ('valid-key', 'klume_one', true, now())")
    con.execute("INSERT INTO app.api_clients VALUES ('revoked-key', 'old_client', false, now())")
    return con.cursor()


def test_valid_active_key(cursor):
    assert _is_valid_key(cursor, "valid-key") is True


def test_revoked_key_rejected(cursor):
    assert _is_valid_key(cursor, "revoked-key") is False


def test_unknown_key_rejected(cursor):
    assert _is_valid_key(cursor, "does-not-exist") is False
