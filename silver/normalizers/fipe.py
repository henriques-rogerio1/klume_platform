"""
Adapter de normalização pra fonte FIPE (staging.raw_json_fipe).

Lê o Bronze FIPE (tabela do MotherDuck, populada a partir dos CSVs já
processados em s3://.../Fipe_Csv/) e produz uma view Silver tipada, com
`vehicle_key` no mesmo domínio de hash usado por DENATRAN (ver
silver/vehicle_key/canonical_sql.py::canonical_str_fipe_sql) — permite juntar
os dois lados por igualdade de hash, sem join de texto.

Mantém histórico completo (grão = codigo_fipe × year_code × reference_month),
não colapsa pra "preço mais recente" aqui — isso é decisão de quem consome no
Gold, não do Silver. Este módulo só monta a view; persistir em
silver.fipe_precos é responsabilidade de quem chama (mesmo padrão de
silver/normalizers/denatran.py).

TODO (não implementado, só registrado — 2026-08-24): guardar histórico
completo pra sempre não escala indefinidamente conforme mais meses forem
acumulados no S3 (Fipe_Csv/). Em algum momento vale definir um limite de
retenção (ex: só manter os últimos N anos em silver.fipe_precos, arquivar o
resto) — decisão de negócio ainda não tomada, não fazer isso sem confirmar.
"""

from silver.utils.columns import rename_to_snake_case
from silver.utils.sentinels import register_blank_to_null_macro
from silver.vehicle_key.canonical_sql import register_sql_macros

# Colunas que realmente podem trazer sentinela de ausência ("nan", "-", etc.)
# -- vehicle_type/model_year já chegam como INTEGER real do loader, não passam
# por blank_to_null (que espera VARCHAR).
_BLANKABLE_COLUMNS = [
    "brand_name", "model_name", "codigo_fipe", "year_code",
    "price", "fuel", "fuel_acronym", "reference_month",
]


def _register_fipe_parsing_macros(con) -> None:
    # "R$ 10.892,00" -> 10892.00
    con.execute(r"""
        CREATE OR REPLACE MACRO parse_preco_fipe_sql(price) AS
            TRY_CAST(
                replace(replace(trim(replace(price, 'R$', '')), '.', ''), ',', '.')
            AS DECIMAL(12,2))
    """)
    # "agosto de 2026" -> DATE '2026-08-01' (convenção: primeiro dia do mês)
    con.execute(r"""
        CREATE OR REPLACE MACRO parse_data_referencia_fipe_sql(reference_month) AS
            CASE strip_accents(lower(trim(split_part(reference_month, ' de ', 1))))
                WHEN 'janeiro'   THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 1, 1)
                WHEN 'fevereiro' THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 2, 1)
                WHEN 'marco'     THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 3, 1)
                WHEN 'abril'     THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 4, 1)
                WHEN 'maio'      THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 5, 1)
                WHEN 'junho'     THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 6, 1)
                WHEN 'julho'     THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 7, 1)
                WHEN 'agosto'    THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 8, 1)
                WHEN 'setembro'  THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 9, 1)
                WHEN 'outubro'   THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 10, 1)
                WHEN 'novembro'  THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 11, 1)
                WHEN 'dezembro'  THEN make_date(TRY_CAST(split_part(reference_month, ' de ', 2) AS INTEGER), 12, 1)
                ELSE NULL
            END
    """)


def normalize_fipe(con, source_relation: str = "staging.raw_json_fipe", *, stage_prefix: str = "fipe") -> str:
    """
    Roda o pipeline Bronze -> Silver completo pra FIPE.

    Retorna o nome da view final (grão: codigo_fipe x year_code x
    reference_month) -- ainda não persiste em silver.fipe_precos.
    """
    renamed_view = f"{stage_prefix}_renamed"
    rename_to_snake_case(
        con, source_relation, renamed_view,
        overrides={"codeFipe": "codigo_fipe", "fuelAcronym": "fuel_acronym"},
    )

    # register_blank_to_null_macro precisa rodar ANTES do CREATE VIEW que usa
    # blank_to_null() -- mesma ordem de blankify_view(), só que aqui a view
    # mistura colunas VARCHAR (passam por blank_to_null) com vehicle_type/
    # model_year, que já chegam como INTEGER real do loader (trim() quebraria
    # neles, por isso não usam blankify_view() puro).
    register_blank_to_null_macro(con)

    blank_view = f"{stage_prefix}_blank"
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW {blank_view} AS
        SELECT
            {", ".join(f'blank_to_null("{c}") AS "{c}"' for c in _BLANKABLE_COLUMNS)},
            vehicle_type, model_year
        FROM {renamed_view}
    """)

    register_sql_macros(con)
    _register_fipe_parsing_macros(con)

    typed_view = f"{stage_prefix}_typed"
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW {typed_view} AS
        SELECT
            brand_name,
            vehicle_type,
            model_name,
            codigo_fipe,
            year_code,
            model_year,
            parse_preco_fipe_sql(price) AS preco,
            fuel AS combustivel,
            fuel_acronym,
            reference_month,
            parse_data_referencia_fipe_sql(reference_month) AS data_referencia,
            hash(canonical_str_fipe_sql(brand_name, model_name, model_year, fuel)) AS vehicle_key
        FROM {blank_view}
    """)
    return typed_view
