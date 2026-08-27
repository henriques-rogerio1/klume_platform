"""
API REST que serve gold.fato_volumes pro backend do K.LUME ONE -- escopo v1
é só o que o Radar Nacional de Emplacamentos precisa (marca x tipo_venda x
período), ver plano "API externa pra Klume One" pro histórico completo de
decisões.

Uso:
    uvicorn api.main:app --reload
Requer MOTHERDUCK_API_TOKEN no .env -- hoje é um token read-write normal
(Read Scaling Token exige plano Business do MotherDuck, que não temos ainda;
ver plano "API externa pra Klume One"), mas separado do MOTHERDUCK_TOKEN do
pipeline mesmo assim -- trocar de token no futuro é só mudar a env var.
"""

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query

from api.auth import verify_api_key
from api.db import create_shared_connection, get_cursor
from api.rate_limit import RateLimiter
from api.repository import query_volumes
from api.schemas import ALLOWED_GROUP_BY, DEFAULT_LIMIT, MAX_LIMIT, VolumesFilters, VolumesMeta, VolumesResponse

# Instanciado no import, não no lifespan -- RateLimiter não tem setup/
# teardown assíncrono nenhum (sem rede, sem I/O), diferente da conexão
# MotherDuck. Mantém o dependency chain de auth/rate-limit testável sem
# precisar de um Request de verdade.
_rate_limiter = RateLimiter()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_con = create_shared_connection()
    yield
    app.state.db_con.close()


app = FastAPI(title="Klume Volumes API", lifespan=lifespan)


def parse_volumes_filters(
    data_de: date = Query(...),
    data_a: date = Query(...),
    group_by: str = Query(...),
    marca: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, gt=0, le=MAX_LIMIT),
) -> VolumesFilters:
    fields = [f.strip() for f in group_by.split(",") if f.strip()]
    if not fields:
        raise HTTPException(status_code=400, detail="group_by não pode ser vazio")
    invalid = sorted(set(fields) - set(ALLOWED_GROUP_BY))
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"group_by inválido: {invalid} -- permitido: {list(ALLOWED_GROUP_BY)}",
        )
    if data_a < data_de:
        raise HTTPException(status_code=400, detail="data_a não pode ser anterior a data_de")
    return VolumesFilters(data_de=data_de, data_a=data_a, group_by=fields, marca=marca, limit=limit)


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


def enforce_rate_limit(
    api_key: str = Depends(verify_api_key), limiter: RateLimiter = Depends(get_rate_limiter)
) -> str:
    if not limiter.allow(api_key):
        raise HTTPException(status_code=429, detail="Rate limit excedido -- tente de novo em instantes")
    return api_key


@app.get("/v1/health")
def health(cursor=Depends(get_cursor)):
    cursor.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/v1/volumes", response_model=VolumesResponse)
def volumes(
    filters: VolumesFilters = Depends(parse_volumes_filters),
    api_key: str = Depends(enforce_rate_limit),
    cursor=Depends(get_cursor),
):
    rows, truncated = query_volumes(cursor, filters)
    return VolumesResponse(
        data=rows,
        meta=VolumesMeta(rows=len(rows), truncated=truncated, generated_at=datetime.now(timezone.utc)),
    )
