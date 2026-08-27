"""
Verifica API key (header X-API-Key) contra app.api_clients -- consulta a
cada request, sem cache: tráfego confirmado baixo/batchy (K.LUME ONE
cacheia do lado dele), não vale a complexidade de invalidação de cache só
pra poder revogar uma chave na hora.
"""

from fastapi import Depends, Header, HTTPException

from api.db import get_cursor


def _is_valid_key(cursor, api_key: str) -> bool:
    row = cursor.execute(
        "SELECT active FROM app.api_clients WHERE api_key = ?", [api_key]
    ).fetchone()
    return row is not None and bool(row[0])


def verify_api_key(x_api_key: str | None = Header(default=None), cursor=Depends(get_cursor)) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key obrigatório")
    if not _is_valid_key(cursor, x_api_key):
        raise HTTPException(status_code=401, detail="API key inválida ou inativa")
    return x_api_key
