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
from silver.vehicle_key.marca_alias_fipe import MARCA_ALIAS_FIPE


def _sql_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def register_sql_macros(con) -> None:
    combustivel_case = "\n".join(
        f"                WHEN {_sql_quote(key)} THEN {_sql_quote(code)}"
        for key, code in COMBUSTIVEL_MAP.items()
    )
    marca_alias_case = "\n".join(
        f"                WHEN {_sql_quote(key)} THEN {_sql_quote(value)}"
        for key, value in MARCA_ALIAS_FIPE.items()
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

    # FIPE já vem com o campo "model" limpo, sem prefixo de marca -- não passa
    # por extract_modelo_denatran_sql (que é específico do formato
    # "MARCA/MODELO" que só o DENATRAN usa). Espelha exatamente
    # canonical_str(..., source="fipe") do lado Python, já testado em
    # test_canonical.py::test_denatran_fipe_same_key.
    con.execute("""
        CREATE OR REPLACE MACRO canonical_str_fipe_sql(marca, modelo, ano, comb) AS
            normalize_text_sql(marca) || '|' ||
            normalize_text_sql(modelo) || '|' ||
            COALESCE(trim(CAST(ano AS VARCHAR)), '0') || '|' ||
            map_combustivel_sql(comb)
    """)

    # Alias de marca só pra achar match de preço FIPE -- nunca usado no
    # vehicle_key/canonical_str_denatran_sql em si, que continua igual.
    # Ver silver/vehicle_key/marca_alias_fipe.py pro porquê de cada entrada.
    con.execute(f"""
        CREATE OR REPLACE MACRO marca_alias_fipe_sql(marca_normalizada) AS (
            CASE marca_normalizada
{marca_alias_case}
                ELSE marca_normalizada
            END
        )
    """)

    # Hash do lado DENATRAN pra comparar contra canonical_str_fipe_sql (tier 2)
    # -- usa a extração de modelo do DENATRAN (versão ainda vem como
    # "MARCA/MODELO"), mas com a marca já passada pelo alias FIPE quando
    # aplicável. Isso é só pra achar o match; vehicle_key em si nunca muda.
    con.execute("""
        CREATE OR REPLACE MACRO canonical_str_denatran_for_fipe_match_sql(marca, versao, ano, comb) AS
            marca_alias_fipe_sql(normalize_text_sql(marca)) || '|' ||
            normalize_text_sql(extract_modelo_denatran_sql(versao)) || '|' ||
            COALESCE(trim(CAST(ano AS VARCHAR)), '0') || '|' ||
            map_combustivel_sql(comb)
    """)
