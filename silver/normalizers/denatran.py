"""
Adapter de normalização para a fonte DENATRAN (emplacamentos Parquet).

Lê um arquivo Parquet do Bronze e produz o Silver normalizado,
incluindo canonical_str para geração de vehicle_key no DuckDB.
"""

import duckdb
from pathlib import Path
from silver.vehicle_key.canonical import canonical_str, map_combustivel


SILVER_SCHEMA = """
    data_emplacamento   DATE,
    chassi              VARCHAR,
    placa               VARCHAR,
    marca               VARCHAR,
    modelo              VARCHAR,
    versao              VARCHAR,
    ano_fabricacao      INTEGER,
    ano_modelo          INTEGER,
    combustivel         VARCHAR,
    tipo_veiculo        VARCHAR,
    segmentacao         VARCHAR,
    uf_faturado         VARCHAR,
    municipio           VARCHAR,
    estado              VARCHAR,
    tipo_venda          VARCHAR,
    procedencia         VARCHAR,
    quantidade          INTEGER,
    codeFipe            VARCHAR,
    preco_fipe          DECIMAL(12,2),
    canonical_str       VARCHAR,
    match_tier          TINYINT,
"""


def normalize_parquet(bronze_path: str | Path, con: duckdb.DuckDBPyConnection) -> str:
    """
    Lê o Parquet Bronze do DENATRAN e retorna uma view 'denatran_silver_raw'
    com todos os campos normalizados e o canonical_str calculado.

    O vehicle_key (UBIGINT) é gerado pelo DuckDB via hash(canonical_str)
    na etapa de persistência — não aqui.
    """
    bronze_path = str(bronze_path).replace("\\", "/")

    con.execute(f"""
        CREATE OR REPLACE VIEW denatran_silver_raw AS
        SELECT
            -- datas e identificadores
            strptime("Data de Emplacamento", '%Y%m%d')::DATE   AS data_emplacamento,
            "Número do Chassi"                                  AS chassi,
            "Placa do Veículo"                                  AS placa,

            -- veículo
            trim(upper("Marca"))                                AS marca,
            trim("Modelo")                                      AS modelo,
            trim("Versão")                                      AS versao,
            TRY_CAST("Ano de Fabricação" AS INTEGER)            AS ano_fabricacao,
            TRY_CAST("Ano Modelo" AS INTEGER)                   AS ano_modelo,
            trim("Combustível")                                 AS combustivel,
            trim("Tipo de Veículo Principal")                   AS tipo_veiculo,
            trim("Segmentação Atualizada")                      AS segmentacao,

            -- localização e comercial
            trim("UF do Faturado")                              AS uf_faturado,
            trim("Município do Emplacamento")                   AS municipio,
            trim("Estado do Emplacamento")                      AS estado,
            trim("Tipo de Venda")                               AS tipo_venda,
            trim("Procedência")                                 AS procedencia,
            TRY_CAST("Quantidade" AS INTEGER)                   AS quantidade,

            -- FIPE (quando já preenchido na fonte)
            CASE
                WHEN "FIPE" IN ('nan', '', 'None') OR "FIPE" IS NULL THEN NULL
                ELSE trim("FIPE")
            END AS codeFipe,
            CASE
                WHEN "Preço FIPE" IN ('nan', '', 'None') OR "Preço FIPE" IS NULL THEN NULL
                ELSE TRY_CAST("Preço FIPE" AS DECIMAL(12,2))
            END AS preco_fipe,

            -- match tier inicial
            CASE
                WHEN "FIPE" NOT IN ('nan', '', 'None') AND "FIPE" IS NOT NULL THEN 1
                ELSE NULL
            END AS match_tier_raw

        FROM read_parquet('{bronze_path}')
    """)

    return "denatran_silver_raw"


def add_canonical(view_name: str, con: duckdb.DuckDBPyConnection) -> str:
    """
    Adiciona canonical_str à view, calculado via Python UDF.
    Retorna nome da view final pronta para persistência.
    """
    con.create_function(
        "make_canonical",
        lambda marca, versao, ano, comb: canonical_str(
            marca or "", versao or "", ano or 0, comb or "", source="denatran"
        ),
        ["VARCHAR", "VARCHAR", "INTEGER", "VARCHAR"],
        "VARCHAR",
    )

    con.execute(f"""
        CREATE OR REPLACE VIEW denatran_silver AS
        SELECT
            *,
            make_canonical(marca, versao, ano_modelo, combustivel) AS canonical_str,
            COALESCE(match_tier_raw, 2) AS match_tier
        FROM {view_name}
    """)

    return "denatran_silver"
