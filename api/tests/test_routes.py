"""
Testes end-to-end das rotas via TestClient -- sem tocar MotherDuck:
get_cursor é sobrescrito (dependency_overrides) pra devolver uma conexão
local em memória com tabelas sintéticas. TestClient é usado SEM `with` de
propósito -- isso evita disparar o lifespan real (que tentaria conectar no
MotherDuck de verdade via MOTHERDUCK_API_TOKEN).
"""

import duckdb
import pytest
from fastapi.testclient import TestClient

from api.db import get_cursor
from api.main import app, get_rate_limiter
from api.rate_limit import RateLimiter


@pytest.fixture
def client():
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA gold")
    con.execute("""
        CREATE TABLE gold.fato_volumes AS SELECT * FROM (VALUES
            (DATE '2020-01-15', 'FIAT', 'Varejo', 10, 10),
            (DATE '2020-01-20', 'FIAT', 'Direta', 5, 5)
        ) AS t(data_emplacamento, marca, tipo_venda, quantidade, quantidade_tipo_venda_conhecido)
    """)
    con.execute("CREATE SCHEMA app")
    con.execute("""
        CREATE TABLE app.api_clients (
            api_key VARCHAR, client_name VARCHAR, active BOOLEAN, created_at TIMESTAMP
        )
    """)
    con.execute("INSERT INTO app.api_clients VALUES ('test-key', 'test', true, now())")

    app.dependency_overrides[get_cursor] = lambda: con.cursor()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_ok(client):
    r = client.get("/v1/health")
    assert r.status_code == 200


def test_volumes_requires_api_key(client):
    r = client.get("/v1/volumes?data_de=2020-01-01&data_a=2020-12-31&group_by=marca")
    assert r.status_code == 401


def test_volumes_rejects_unknown_api_key(client):
    r = client.get(
        "/v1/volumes?data_de=2020-01-01&data_a=2020-12-31&group_by=marca",
        headers={"X-API-Key": "not-a-real-key"},
    )
    assert r.status_code == 401


def test_volumes_rejects_group_by_outside_allowlist(client):
    r = client.get(
        "/v1/volumes?data_de=2020-01-01&data_a=2020-12-31&group_by=preco",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 400


def test_volumes_rejects_inverted_date_range(client):
    r = client.get(
        "/v1/volumes?data_de=2020-12-31&data_a=2020-01-01&group_by=marca",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 400


def test_volumes_rate_limited_returns_429(client):
    # Prova que enforce_rate_limit está de fato ligado na rota, não só que a
    # classe RateLimiter funciona isolada (isso já é coberto em
    # test_rate_limit.py). Override baixo só nesse teste -- get_rate_limiter
    # já é limpo pelo teardown do fixture `client` (app.dependency_overrides.clear()).
    # Instância única, reaproveitada a cada request -- se o override fosse
    # `lambda: RateLimiter(...)`, cada request ganharia um limiter novo (zerado),
    # e o limite nunca acumularia.
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    url = "/v1/volumes?data_de=2020-01-01&data_a=2020-12-31&group_by=marca"
    headers = {"X-API-Key": "test-key"}
    assert client.get(url, headers=headers).status_code == 200
    assert client.get(url, headers=headers).status_code == 200
    r = client.get(url, headers=headers)
    assert r.status_code == 429


def test_volumes_happy_path(client):
    r = client.get(
        "/v1/volumes?data_de=2020-01-01&data_a=2020-12-31&group_by=marca,tipo_venda",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["rows"] == 2
    assert body["meta"]["truncated"] is False
    totals = {(row["marca"], row["tipo_venda"]): row["quantidade"] for row in body["data"]}
    assert totals[("FIAT", "Varejo")] == 10
    assert totals[("FIAT", "Direta")] == 5
