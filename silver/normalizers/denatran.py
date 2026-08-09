"""
Adapter de normalização para a fonte DENATRAN (emplacamentos).

Lê o Bronze — tabela do MotherDuck (ex: 'staging.bronze_2016') pra anos
>= 2000, ou um glob de Parquet local pra anos < 2000, onde o MotherDuck
não tem cobertura — e produz duas views Silver:

  *_recent     (Data de Emplacamento >= 2000)
      contrato completo: colunas tipadas + canonical_str + vehicle_key + match_tier
  *_historico  (Data de Emplacamento < 2000, ou sem data)
      só colunas tipadas/renomeadas — sem canonical_str/vehicle_key/match_tier,
      deliberadamente fora do contrato de hash (ver silver/vehicle_key/canonical.py)

Este módulo só monta views — persistir em silver.veiculos/silver.veiculos_historico
é responsabilidade de quem chama (ver silver/run_sample.py), pra poder
combinar várias fontes (vários anos) antes de escrever a tabela final.
"""

from silver.utils.columns import rename_to_snake_case
from silver.utils.sentinels import blankify_view
from silver.vehicle_key.canonical_sql import register_sql_macros

SPLIT_YEAR = 2000


def _type_cast(con, source_view: str, typed_view: str) -> str:
    con.execute(f"""
        CREATE OR REPLACE VIEW {typed_view} AS
        SELECT
            COALESCE(
                TRY_STRPTIME(data_emplacamento, '%Y%m%d'),
                TRY_STRPTIME(data_emplacamento, '%Y-%m-%d')
            )::DATE                                            AS data_emplacamento,
            numero_chassi,
            placa_veiculo,
            tipo_faturado,
            identificacao_faturado,
            tipo_venda,
            uf_faturado,
            tipo_proprietario,
            uf_jurisdicao,
            TRY_CAST(codigo_municipio AS INTEGER)              AS codigo_municipio,
            municipio_emplacamento,
            estado_emplacamento,
            TRY_CAST(ano_fabricacao AS INTEGER)                AS ano_fabricacao,
            TRY_CAST(ano_modelo AS INTEGER)                    AS ano_modelo,
            codigo_denatran,
            marca,
            modelo,
            versao,
            tipo_veiculo_principal,
            tipo_veiculo_denatran,
            segmentacao_atualizada,
            segmentacao_original,
            especie_veiculo,
            cod_carroceria,
            carroceria,
            cor_predominante,
            combustivel,
            TRY_CAST(potencia AS INTEGER)                      AS potencia,
            TRY_CAST(cilindradas AS INTEGER)                   AS cilindradas,
            TRY_CAST(numero_lugares AS INTEGER)                AS numero_lugares,
            TRY_CAST(capacidade_carga AS INTEGER)              AS capacidade_carga,
            TRY_CAST(peso_bruto_total_pbt AS INTEGER)          AS peso_bruto_total_pbt,
            TRY_CAST(capacidade_maxima_tracao_cmt AS INTEGER)  AS capacidade_maxima_tracao_cmt,
            procedencia,
            situacao_chassi,
            TRY_CAST(numero_eixos AS INTEGER)                  AS numero_eixos,
            restricao_1,
            restricao_2,
            restricao_3,
            restricao_4,
            data_limite_restricao_tributaria,
            veiculo_cadastrado_bin,
            TRY_CAST(quantidade AS INTEGER)                    AS quantidade,
            fipe,
            TRY_CAST(preco AS DECIMAL(12,2))                   AS preco,
            CASE WHEN fipe IS NOT NULL THEN 1 ELSE NULL END    AS match_tier_raw,
            CASE
                WHEN tipo_faturado = 'CNPJ' THEN
                    LEFT(
                        LPAD(
                            CASE WHEN identificacao_faturado LIKE '%.0'
                                 THEN LEFT(identificacao_faturado, LENGTH(identificacao_faturado) - 2)
                                 ELSE identificacao_faturado
                            END,
                            14, '0'
                        ),
                    8)
                ELSE NULL
            END                                                 AS cnpj_basico_faturado
        FROM {source_view}
    """)
    return typed_view


def _split_by_year(con, typed_view: str, stage_prefix: str) -> tuple[str, str]:
    recent_view = f"{stage_prefix}_split_recent"
    historico_view = f"{stage_prefix}_split_historico"
    con.execute(f"""
        CREATE OR REPLACE VIEW {recent_view} AS
        SELECT * FROM {typed_view}
        WHERE data_emplacamento IS NOT NULL AND date_part('year', data_emplacamento) >= {SPLIT_YEAR}
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW {historico_view} AS
        SELECT * EXCLUDE (match_tier_raw, cnpj_basico_faturado), cnpj_basico_faturado
        FROM {typed_view}
        WHERE data_emplacamento IS NULL OR date_part('year', data_emplacamento) < {SPLIT_YEAR}
    """)
    return recent_view, historico_view


def _add_canonical_and_match_tier(
    con,
    source_view: str,
    out_view: str,
    mapping_table: str | None,
) -> str:
    # Macro SQL, não função Python: roda no mesmo motor que grava no
    # MotherDuck, sem depender de uma ponte local↔remoto (ver canonical_sql.py).
    register_sql_macros(con)

    con.execute(f"""
        CREATE OR REPLACE VIEW {out_view}_base AS
        SELECT
            *,
            canonical_str_denatran_sql(marca, versao, ano_modelo, combustivel) AS canonical_str,
            hash(canonical_str_denatran_sql(marca, versao, ano_modelo, combustivel)) AS vehicle_key
        FROM {source_view}
    """)

    if mapping_table is None:
        con.execute(f"""
            CREATE OR REPLACE VIEW {out_view} AS
            SELECT * EXCLUDE (match_tier_raw), match_tier_raw AS match_tier
            FROM {out_view}_base
        """)
        return out_view

    # Tier 3: crosswalk manual (silver.mapping_table) — best-effort, dados com
    # sujeira conhecida na coluna "Existente" (ver plano). Não sobrescreve
    # tier 1, só preenche quando a própria linha não trouxe FIPE.
    con.execute(f"""
        CREATE OR REPLACE VIEW {out_view}_mapped AS
        SELECT b.*, m."FIPE Carros Com Leves" AS fipe_tabela_polo
        FROM {out_view}_base b
        LEFT JOIN {mapping_table} m
          ON strip_accents(lower(trim(b.versao))) = strip_accents(lower(trim(m."MARCA/MODELO (original sem espaços)")))
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW {out_view} AS
        SELECT
            * EXCLUDE (match_tier_raw, fipe_tabela_polo),
            CASE
                WHEN match_tier_raw = 1 THEN 1
                WHEN fipe_tabela_polo IS NOT NULL AND fipe_tabela_polo NOT IN ('0', '-', '') THEN 3
                ELSE NULL
            END AS match_tier
        FROM {out_view}_mapped
    """)
    return out_view


def normalize_denatran(
    con,
    source_relation: str,
    *,
    mapping_table: str | None = None,
    stage_prefix: str = "denatran",
) -> tuple[str, str]:
    """
    Roda o pipeline Bronze -> Silver completo pra uma única fonte DENATRAN
    (nome de tabela, ex: 'staging.bronze_2016', ou um FROM válido de Parquet
    local, ex: "read_parquet('C:/.../1957/*.parquet')").

    Retorna (view_recente, view_historico) — ainda não persiste em silver.*.
    """
    renamed_view = f"{stage_prefix}_renamed"
    rename_to_snake_case(con, source_relation, renamed_view)

    blank_view = f"{stage_prefix}_blank"
    blankify_view(con, renamed_view, blank_view)

    typed_view = _type_cast(con, blank_view, f"{stage_prefix}_typed")

    recent_typed, historico_view = _split_by_year(con, typed_view, stage_prefix)

    recent_view = _add_canonical_and_match_tier(
        con, recent_typed, f"{stage_prefix}_recent_final", mapping_table
    )

    return recent_view, historico_view
