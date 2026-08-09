"""
Reimplementação em SQL puro (macros DuckDB) da lógica de canonical.py.

Por quê: canonical_str/vehicle_key eram calculados por uma função Python
registrada na conexão (create_function). Funções Python só existem
localmente — quando a query final tenta escrever direto numa tabela remota
do MotherDuck, o motor de execução híbrido perde a referência a essa
função e a query falha. Macros SQL são só texto expandido pelo parser,
então rodam no mesmo motor que grava no MotherDuck, sem essa ponte.

O mapa de combustível é gerado a partir de COMBUSTIVEL_MAP (canonical.py)
em vez de duplicado à mão em SQL — as duas versões nunca podem dessincronizar.
Todo o resto (normalize_text, extract_modelo_denatran, etc.) é uma tradução
1:1 das funções Python equivalentes; ver test_canonical_sql_parity.py pra
prova de que produzem o mesmo resultado.
"""

from silver.vehicle_key.canonical import COMBUSTIVEL_MAP


def _sql_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def register_sql_macros(con) -> None:
    combustivel_case = "\n".join(
        f"                WHEN {_sql_quote(key)} THEN {_sql_quote(code)}"
        for key, code in COMBUSTIVEL_MAP.items()
    )

    con.execute(r"""
        CREATE OR REPLACE MACRO normalize_text_sql(s) AS
            CASE WHEN s IS NULL OR trim(s) = '' THEN ''
            ELSE trim(regexp_replace(
                     regexp_replace(lower(strip_accents(trim(s))), '[^a-z0-9 ]', ' ', 'g'),
                     '\s+', ' ', 'g'
                 ))
            END
    """)

    con.execute("""
        CREATE OR REPLACE MACRO extract_modelo_denatran_sql(versao) AS
            CASE WHEN versao IS NOT NULL AND position('/' IN versao) > 0
                 THEN substr(versao, position('/' IN versao) + 1)
                 ELSE versao
            END
    """)

    con.execute(r"""
        CREATE OR REPLACE MACRO normalize_combustivel_key_sql(raw) AS
            CASE WHEN raw IS NULL OR trim(raw) = '' THEN ''
            ELSE trim(regexp_replace(
                     regexp_replace(lower(strip_accents(trim(raw))), '\s*/\s*', '/', 'g'),
                     '\s+', ' ', 'g'
                 ))
            END
    """)

    con.execute(f"""
        CREATE OR REPLACE MACRO map_combustivel_sql(raw) AS (
            CASE normalize_combustivel_key_sql(raw)
{combustivel_case}
                ELSE 'X'
            END
        )
    """)

    con.execute("""
        CREATE OR REPLACE MACRO canonical_str_denatran_sql(marca, versao, ano, comb) AS
            normalize_text_sql(marca) || '|' ||
            normalize_text_sql(extract_modelo_denatran_sql(versao)) || '|' ||
            COALESCE(trim(CAST(ano AS VARCHAR)), '0') || '|' ||
            map_combustivel_sql(comb)
    """)
