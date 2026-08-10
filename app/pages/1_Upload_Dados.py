"""
Página operacional (não é pra vendedor usar) — upload de arquivo XLSX novo de
volumes DENATRAN: lê o arquivo, casa colunas com staging.bronze_{ano} pelo
nome (nunca hardcoded), insere no MotherDuck, sobe cópia em Parquet pro S3
(dual-write até decidirmos a estratégia final de bronze), e oferece um botão
separado pra rodar Silver + Gold — não dispara sozinho a cada upload, porque
reprocessar tudo é caro/demorado (mesma preocupação de custo do resto do app).

Achado importante: read_xlsx(..., all_varchar=true) transforma data em número
de série do Excel (ex: '21915'), não texto legível — por isso a leitura NÃO
usa all_varchar; deixa o DuckDB inferir a coluna de data como DATE de verdade
e só depois formata pra texto.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
import streamlit as st

from silver.db.connection import get_connection

st.set_page_config(page_title="Klume — Upload de Dados", page_icon="📥")

os.environ["MOTHERDUCK_TOKEN"] = st.secrets["MOTHERDUCK_TOKEN"]

st.title("Upload de Dados — Volumes DENATRAN")
st.caption(
    "Página operacional: sobe um arquivo XLSX novo pro Bronze (MotherDuck + S3). "
    "Não atualiza Silver/Gold automaticamente — isso é um passo separado, explícito."
)

DATE_COL = "Data de Emplacamento"
S3_PREFIX = "denatran-bronze"
SCHEMA_TEMPLATE_YEAR = "bronze_2024"  # ano "normal" (45 colunas), não o formato de 2025 com colunas extras


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"],
        region_name=st.secrets["AWS_REGION"],
    )


uploaded = st.file_uploader("Arquivo XLSX", type="xlsx")

if uploaded is not None:
    con = get_connection("motherduck")
    con.execute("INSTALL excel")
    con.execute("LOAD excel")

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(uploaded.getvalue())
        tmp_path = tmp.name

    try:
        # Sem all_varchar: deixa a coluna de data ser inferida como DATE de verdade
        # (com all_varchar ela vira número de série do Excel, tipo '21915').
        src_cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_xlsx('{tmp_path}')").fetchall()]

        anos = con.execute(f"""
            SELECT DISTINCT date_part('year', "{DATE_COL}") AS ano
            FROM read_xlsx('{tmp_path}')
            WHERE "{DATE_COL}" IS NOT NULL
            ORDER BY 1
        """).fetchall()
        anos = [int(a[0]) for a in anos]

        if not anos:
            st.error(f"Não encontrei nenhuma data válida na coluna '{DATE_COL}'.")
        else:
            if len(anos) > 1:
                st.warning(f"O arquivo cobre mais de um ano: {anos}. Processando cada um separadamente.")

            for ano in anos:
                st.subheader(f"Ano {ano}")
                target_table = f"staging.bronze_{ano}"

                exists = con.execute(f"""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = 'staging' AND table_name = 'bronze_{ano}'
                """).fetchone()[0] > 0

                if not exists:
                    st.info(f"{target_table} não existe ainda — criando com o schema de staging.{SCHEMA_TEMPLATE_YEAR}.")
                    con.execute(f"CREATE TABLE {target_table} AS SELECT * FROM staging.{SCHEMA_TEMPLATE_YEAR} LIMIT 0")

                tgt_cols = [r[0] for r in con.execute(f"DESCRIBE {target_table}").fetchall()]
                common = [c for c in tgt_cols if c in src_cols]
                only_src = [c for c in src_cols if c not in tgt_cols]
                only_tgt = [c for c in tgt_cols if c not in src_cols]

                if only_src:
                    st.caption(f"Colunas no arquivo mas não em {target_table} (ignoradas): {only_src}")
                if only_tgt:
                    st.caption(f"Colunas em {target_table} mas não no arquivo (ficam NULL): {only_tgt}")

                # Monta o SELECT casado por nome: data formatada como texto (padrão
                # compacto YYYYMMDD, mesmo usado nas safras recentes), resto CAST pra VARCHAR.
                select_parts = []
                for c in tgt_cols:
                    if c not in common:
                        select_parts.append(f"NULL AS \"{c}\"")
                    elif c == DATE_COL:
                        select_parts.append(f'strftime("{c}", \'%Y%m%d\') AS "{c}"')
                    else:
                        select_parts.append(f'CAST("{c}" AS VARCHAR) AS "{c}"')
                select_sql = ",\n    ".join(select_parts)

                staged_view = f"_upload_{ano}"
                con.execute(f"""
                    CREATE OR REPLACE TEMP VIEW {staged_view} AS
                    SELECT
                        {select_sql}
                    FROM read_xlsx('{tmp_path}')
                    WHERE date_part('year', "{DATE_COL}") = {ano}
                """)

                n_before = con.execute(f"SELECT COUNT(*) FROM {target_table}").fetchone()[0]
                con.execute(f"INSERT INTO {target_table} SELECT * FROM {staged_view}")
                n_after = con.execute(f"SELECT COUNT(*) FROM {target_table}").fetchone()[0]
                n_inserted = n_after - n_before
                st.success(f"{n_inserted:,} linhas inseridas em {target_table} (total agora: {n_after:,}).")

                # Dual-write pro S3 — mesmas linhas que acabaram de entrar no MotherDuck,
                # não um dump bruto do xlsx original (uma fonte de verdade só pro que "essa
                # subida" produziu).
                meses = con.execute(f"""
                    SELECT DISTINCT strftime(CAST(strptime("{DATE_COL}", '%Y%m%d') AS DATE), '%Y%m')
                    FROM {staged_view}
                """).fetchall()
                s3 = get_s3_client()
                bucket = st.secrets["S3_BUCKET"]
                for (mes,) in meses:
                    local_parquet = Path(tempfile.gettempdir()) / f"upload_{ano}_{mes}.parquet"
                    con.execute(f"""
                        COPY (
                            SELECT * FROM {staged_view}
                            WHERE strftime(CAST(strptime("{DATE_COL}", '%Y%m%d') AS DATE), '%Y%m') = '{mes}'
                        ) TO '{local_parquet.as_posix()}' (FORMAT PARQUET)
                    """)
                    key = f"{S3_PREFIX}/{ano}/{mes}/{uploaded.name}.parquet"
                    s3.upload_file(str(local_parquet), bucket, key)
                    local_parquet.unlink()
                    st.success(f"Cópia enviada pro S3: s3://{bucket}/{key}")
    finally:
        os.unlink(tmp_path)

    st.divider()
    st.subheader("Próximo passo")
    st.write(
        "O upload só afeta o Bronze. Silver e Gold ainda não foram atualizados "
        "— clique abaixo quando quiser (pode demorar, reprocessa os dados)."
    )
    if st.button("Atualizar Silver e Gold"):
        with st.spinner("Reprocessando o(s) ano(s) afetado(s) e reconstruindo o Gold..."):
            from gold.build_volumes import main as build_gold
            from silver.normalizers.denatran import normalize_denatran

            con = get_connection("motherduck")
            for ano in anos:
                # Reprocessa só o ano afetado a partir do bronze e faz MERGE em
                # silver.veiculos/historico (delete + insert) — nunca substitui a
                # tabela inteira, que já acumula outros anos (2016/2020/2025/etc).
                recent, historico = normalize_denatran(con, f"staging.bronze_{ano}", stage_prefix=f"upl{ano}")

                con.execute(f"DELETE FROM silver.veiculos WHERE date_part('year', data_emplacamento) = {ano}")
                con.execute(f"INSERT INTO silver.veiculos SELECT * FROM {recent}")

                con.execute(f"DELETE FROM silver.veiculos_historico WHERE date_part('year', data_emplacamento) = {ano}")
                con.execute(f"INSERT INTO silver.veiculos_historico SELECT * FROM {historico}")

            build_gold()
        st.success("Silver e Gold atualizados.")
