"""
Ontologia do Bronze: COMMENT ON TABLE / COMMENT ON COLUMN, aplicados direto
no banco — mesmo padrão do Gold/Silver/app (gold/build_volumes.py,
silver/comments.py, app/comments.py).

Bronze não tem "build script" próprio (staging.bronze_{ano} é populado por
app/pages/1_Upload_Dados.py e por cargas históricas manuais) — roda como
migração pontual:
    python scripts/apply_bronze_comments.py

Reaplicar quando um ano novo (staging.bronze_{ano}) for criado pela primeira
vez, já que o script cobre só os anos existentes no catálogo no momento em
que roda.
"""

from silver.db.connection import get_connection

BRONZE_GRAIN = (
    "Uma linha representa um emplacamento bruto (texto, sem conversão de "
    "tipo) reportado pela DENATRAN para este ano — schema compartilhado "
    "entre todos os anos de staging.bronze_*, tipagem real só acontece no "
    "Silver (ver silver/normalizers/denatran.py)."
)

BRONZE_COLUMN_COMMENTS = {
    "Quantidade": "Medida — vira INTEGER no Silver, é a base de "
    "SUM(quantidade) no Gold.",
    "FIPE": "Código FIPE já vindo na própria linha da fonte — é o match "
    "'tier 1' de preço, distinto do enriquecimento por catálogo (tier 2/3) "
    "feito no Gold.",
    "Preço": "Preço já vindo na própria linha da fonte — mesmo caso de "
    "FIPE acima (tier 1).",
    "Tipo do Faturado": "Quando = 'CNPJ', dispara a extração do CNPJ raiz "
    "no Silver (cnpj_basico_faturado). Quando = 'CPF', a "
    "Identificação do Faturado correspondente é mascarada no Silver (dado "
    "pessoal sob LGPD).",
    "Código do Município": "Código IBGE — vira chave natural de "
    "gold.dim_geografia no Gold.",
    "Marca": "Compõe, junto com Versão/Ano Modelo/Combustível, a string "
    "canônica (canonical_str) que vira vehicle_key no Silver.",
}

OTHER_TABLE_COMMENTS = {
    "raw_json_fipe": (
        "Uma linha representa um preço FIPE reportado pela API pública "
        "para uma combinação codigo_fipe x ano-modelo x mês de referência "
        "— schema bruto (JSON achatado), tipagem real só acontece no "
        "Silver (ver silver/normalizers/fipe.py).",
        {},
    ),
    "ingest_control": (
        "TABELA ÓRFÃ (0 linhas) — schema de controle de ingestão "
        "preparado (file_name, sheet, rows, ts_ingest, parquet_path) mas "
        "não referenciado em nenhum normalizador ou página do app hoje. O "
        "controle de upload real vive em app.upload_log. Candidata a "
        "remoção, não confirmada ainda.",
        {},
    ),
    "veiculo_raw": (
        "TABELA ÓRFÃ (0 linhas) — replica o schema de staging.bronze_{ano} "
        "mas não é referenciada em nenhum normalizador ou página do app "
        "hoje. Candidata a remoção, não confirmada ainda.",
        {},
    ),
}


def main():
    con = get_connection("motherduck")

    bronze_years = [
        r[0]
        for r in con.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'staging' AND table_name LIKE 'bronze_%'
            ORDER BY 1
            """
        ).fetchall()
    ]
    print(f"Anos de Bronze encontrados: {len(bronze_years)}")

    grain_escaped = BRONZE_GRAIN.replace("'", "''")
    for table in bronze_years:
        con.execute(f"COMMENT ON TABLE staging.{table} IS '{grain_escaped}'")
        for col, text in BRONZE_COLUMN_COMMENTS.items():
            text_escaped = text.replace("'", "''")
            con.execute(f'COMMENT ON COLUMN staging.{table}."{col}" IS \'{text_escaped}\'')
    print(f"OK: grão + {len(BRONZE_COLUMN_COMMENTS)} colunas comentadas em {len(bronze_years)} tabelas bronze_*.")

    for table, (grain, cols) in OTHER_TABLE_COMMENTS.items():
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            f"WHERE table_schema = 'staging' AND table_name = '{table}'"
        ).fetchone()[0]
        if not exists:
            print(f"  aviso: staging.{table} não existe, pulando.")
            continue
        grain_escaped = grain.replace("'", "''")
        con.execute(f"COMMENT ON TABLE staging.{table} IS '{grain_escaped}'")
        for col, text in cols.items():
            text_escaped = text.replace("'", "''")
            con.execute(f"COMMENT ON COLUMN staging.{table}.{col} IS '{text_escaped}'")
        print(f"  OK: staging.{table}")


if __name__ == "__main__":
    main()
