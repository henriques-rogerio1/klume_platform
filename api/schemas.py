"""
Contratos de dado da API (Pydantic v2) -- separado de repository.py (SQL) e
de main.py (rotas/validação de query params).
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

# Único allowlist de dimensões que /v1/volumes aceita em group_by -- nunca
# interpolar coluna vinda do usuário sem passar por aqui primeiro (injeção
# de SQL via identificador). Ampliar isso é decisão deliberada, não
# consequência de aceitar qualquer string.
ALLOWED_GROUP_BY = ("marca", "tipo_venda")

DEFAULT_LIMIT = 5000
MAX_LIMIT = 20000


class VolumesFilters(BaseModel):
    data_de: date
    data_a: date
    group_by: list[str]
    marca: str | None = None
    limit: int = DEFAULT_LIMIT


class VolumesMeta(BaseModel):
    rows: int
    truncated: bool
    generated_at: datetime


class VolumesResponse(BaseModel):
    data: list[dict[str, Any]]
    meta: VolumesMeta
