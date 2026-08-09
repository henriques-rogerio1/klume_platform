"""
Normalização de valores-sentinela de ausência ("nan", "-", "", "None") para NULL real.

Bronze usa mais de um sentinela pra "ausente" dependendo da era do dado
(ex: FIPE = 'nan' em 2016, '-' em 2025). Tratar isso coluna a coluna é frágil
(foi exatamente o bug encontrado) — aqui é uma regra única aplicada a todas
as colunas de uma vez, antes de qualquer cast tipado.
"""

DEFAULT_SENTINELS = ("nan", "NaN", "-", "", "None", "null", "NULL")


def register_blank_to_null_macro(con, sentinels: tuple[str, ...] = DEFAULT_SENTINELS) -> None:
    sentinel_list = ", ".join("'" + s.replace("'", "''") + "'" for s in sentinels)
    con.execute(
        f"CREATE OR REPLACE MACRO blank_to_null(x) AS "
        f"CASE WHEN x IS NULL OR trim(x) IN ({sentinel_list}) THEN NULL ELSE x END"
    )


def blankify_view(
    con,
    source_relation: str,
    view_name: str,
    columns: list[str] | None = None,
) -> str:
    """Cria uma view onde toda coluna VARCHAR passa por blank_to_null()."""
    register_blank_to_null_macro(con)
    if columns is None:
        columns = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {source_relation}").fetchall()]
    select_list = ", ".join(f'blank_to_null("{c}") AS "{c}"' for c in columns)
    con.execute(f"CREATE OR REPLACE VIEW {view_name} AS SELECT {select_list} FROM {source_relation}")
    return view_name
