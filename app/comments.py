"""
Ontologia das tabelas de controle do app: COMMENT ON TABLE (grão) / COMMENT
ON COLUMN, aplicados direto no banco — mesmo padrão do Gold/Silver
(gold/build_volumes.py, silver/comments.py).

Diferente de Gold/Silver, estas 3 tabelas não são reconstruídas por nenhum
script (api_clients é gerenciada manualmente; query_log/upload_log usam
CREATE TABLE IF NOT EXISTS, criadas uma única vez) — não há um "build" pra
acoplar isso. Rodar como migração pontual:
    python -m app.comments
"""

GRAIN = {
    "api_clients": "Uma linha representa um cliente autorizado a consumir "
    "a API de parceiro (docs/api-contratos.md) — gerenciada manualmente, "
    "não por pipeline.",
    "query_log": "Uma linha representa uma pergunta feita ao Vanna (texto + "
    "SQL gerado + resultado), gravada de forma assíncrona e best-effort — "
    "ausência de linha não significa erro na pergunta em si, pode ser falha "
    "silenciosa do log.",
    "upload_log": "Uma linha representa um upload de arquivo de "
    "emplacamentos processado com sucesso — só existe depois que S3 e "
    "MotherDuck já tiveram sucesso (ver app/pages/1_Upload_Dados.py).",
}

COMMENTS = {
    "api_clients": {
        "api_key": "Chave de autenticação enviada pelo cliente (header) — "
        "ver docs/api-contratos.md.",
        "active": "FALSE revoga acesso sem apagar o registro (histórico de "
        "quem já teve acesso se mantém).",
    },
    "query_log": {
        "row_count": "Linhas retornadas pela query gerada — NULL se a "
        "query falhou (ver coluna error).",
        "error": "Mensagem de erro se a query gerada falhou — NULL em "
        "queries bem-sucedidas.",
    },
    "upload_log": {
        "file_hash": "SHA-256 do arquivo — mecanismo de deduplicação, "
        "upload do mesmo arquivo é bloqueado antes de tocar qualquer "
        "tabela.",
        "s3_ok": "Sempre TRUE quando a linha existe (ver grão da tabela) — "
        "mantida por compatibilidade de leitura do log, não porque possa "
        "ser FALSE hoje.",
    },
}


def apply_grain_comments(con, grain: dict = GRAIN) -> None:
    for table, text in grain.items():
        text_escaped = text.replace("'", "''")
        con.execute(f"COMMENT ON TABLE app.{table} IS '{text_escaped}'")


def apply_comments(con, comments: dict = COMMENTS) -> None:
    for table, cols in comments.items():
        for col, text in cols.items():
            text_escaped = text.replace("'", "''")
            con.execute(f"COMMENT ON COLUMN app.{table}.{col} IS '{text_escaped}'")


if __name__ == "__main__":
    from silver.db.connection import get_connection

    con = get_connection("motherduck")
    print("Aplicando comentários de grão (COMMENT ON TABLE)...")
    apply_grain_comments(con)
    print("Aplicando comentários (ontologia)...")
    apply_comments(con)
    print("OK.")
