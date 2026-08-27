"""
Único lugar que sabe o nome de tabela/colunas de gold.fato_volumes -- rotas
(main.py) e auth nunca montam SQL direto.
"""

from api.schemas import ALLOWED_GROUP_BY, VolumesFilters


def query_volumes(cursor, filters: VolumesFilters) -> tuple[list[dict], bool]:
    """
    Retorna (linhas, truncated). Pede filters.limit + 1 linhas e corta em
    filters.limit pra saber se truncou sem precisar de uma segunda query
    de COUNT(*).
    """
    invalid = set(filters.group_by) - set(ALLOWED_GROUP_BY)
    if invalid:
        # Não deveria acontecer -- main.py já valida antes de construir
        # VolumesFilters. Checagem redundante de propósito (defesa em
        # profundidade contra um futuro caller que pule essa validação).
        raise ValueError(f"group_by fora do allowlist: {sorted(invalid)}")

    group_cols = ", ".join(filters.group_by)
    where_clauses = ["data_emplacamento BETWEEN ? AND ?"]
    params: list = [filters.data_de, filters.data_a]
    if filters.marca is not None:
        where_clauses.append("marca = ?")
        params.append(filters.marca)
    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT {group_cols},
               SUM(quantidade) AS quantidade,
               SUM(quantidade_tipo_venda_conhecido) AS quantidade_tipo_venda_conhecido
        FROM gold.fato_volumes
        WHERE {where_sql}
        GROUP BY {group_cols}
        ORDER BY {group_cols}
        LIMIT ?
    """
    params.append(filters.limit + 1)

    cursor.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    truncated = len(rows) > filters.limit
    if truncated:
        rows = rows[: filters.limit]
    return rows, truncated
