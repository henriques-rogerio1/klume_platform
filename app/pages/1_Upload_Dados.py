"""
Página operacional (não é pra vendedor usar) — upload de arquivo XLSX novo de
volumes DENATRAN. A lógica de pipeline (Bronze landing-first -> Silver ->
Gold) mora em app/upload_pipeline.py::process_upload() — esta página é só a
casca de UI em cima dela, pra poder ser reaproveitada pela automação de
Google Drive (ver automation/gdrive_ingest.py) sem duplicar a lógica.

A tela mostra a pipeline em etapas nomeadas (estilo Airflow/CI) — mesmo
comportamento visível de sempre, só que renderizado a partir do resultado
estruturado que process_upload() devolve, não mais com st.status() espalhado
dentro da lógica em si.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

from app.upload_pipeline import ensure_upload_log, file_hash, get_s3_client, process_upload
from silver.db.connection import get_connection

st.set_page_config(page_title="Klume — Upload de Dados", page_icon="📥")

os.environ["MOTHERDUCK_TOKEN"] = st.secrets["MOTHERDUCK_TOKEN"]
os.environ["AWS_ACCESS_KEY_ID"] = st.secrets["AWS_ACCESS_KEY_ID"]
os.environ["AWS_SECRET_ACCESS_KEY"] = st.secrets["AWS_SECRET_ACCESS_KEY"]
os.environ["AWS_REGION"] = st.secrets["AWS_REGION"]
os.environ["S3_BUCKET"] = st.secrets["S3_BUCKET"]

st.title("Upload de Dados — Volumes DENATRAN")
st.caption(
    "Página operacional: sobe um arquivo XLSX novo pro Bronze (S3 primeiro, depois "
    "MotherDuck) e reconstrói Silver + Gold automaticamente, em pipeline."
)

uploaded = st.file_uploader("Arquivo XLSX", type="xlsx")

if uploaded is not None:
    con = get_connection("motherduck")
    ensure_upload_log(con)

    file_bytes = uploaded.getvalue()
    hash_ = file_hash(file_bytes)

    st.subheader("Pipeline")

    with st.spinner("Rodando pipeline — Bronze, Silver e Gold..."):
        resultado = process_upload(con, file_bytes, uploaded.name, s3_client=get_s3_client())

    if resultado.status == "rejeitado_schema":
        st.error(f"Arquivo rejeitado: {resultado.mensagem}")
        st.stop()

    if resultado.status == "sem_data_valida":
        st.error(resultado.mensagem)
        st.stop()

    for ano_res in resultado.anos:
        st.markdown(f"#### Ano {ano_res.ano}")
        if ano_res.status == "ja_processado":
            st.info(f"Já processado antes — {ano_res.mensagem}")
        elif ano_res.status == "s3_falhou":
            st.error(ano_res.mensagem)
        elif ano_res.status == "ok":
            st.success(f"Bronze + Silver — OK. {ano_res.mensagem}")

    if resultado.gold_reconstruido:
        st.success(f"8. Reconstruir Gold — OK. {resultado.mensagem}")
    elif resultado.houve_falha_s3:
        st.warning(resultado.mensagem)
    else:
        st.info(resultado.mensagem)
