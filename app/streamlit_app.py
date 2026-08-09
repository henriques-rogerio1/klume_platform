"""
App interno de vendas: pergunta em texto -> SQL (Vanna) -> resultado -> export xlsx.

Local: streamlit run app/streamlit_app.py  (usa .streamlit/secrets.toml)
Streamlit Cloud: mesmo código, secrets vêm da UI do Streamlit Cloud.
"""

import io
import os

import pandas as pd
import streamlit as st

from app.vanna_client import get_vanna

st.set_page_config(page_title="Klume — Consulta de Volumes", page_icon="🚗")

# Streamlit Cloud/local: st.secrets é a única fonte de verdade pra chave.
# Espelha MOTHERDUCK_TOKEN pro ambiente porque silver/db/connection.py lê via
# os.getenv — reaproveita o helper existente sem duplicar lógica de conexão.
os.environ["MOTHERDUCK_TOKEN"] = st.secrets["MOTHERDUCK_TOKEN"]
ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]

st.title("Consulta de Volumes")
st.caption(
    "Pergunte em português sobre volumes de emplacamento (2016, 2020 e 2025 — "
    "cobertura parcial, mais anos chegam depois)."
)

question = st.text_input("Sua pergunta", placeholder="Ex: volume de motos por cor em 2025")

if st.button("Consultar") and question:
    vn = get_vanna(ANTHROPIC_API_KEY)

    with st.spinner("Gerando SQL..."):
        sql = vn.generate_sql(question)

    st.code(sql, language="sql")

    with st.spinner("Consultando..."):
        try:
            df = vn.run_sql(sql)
        except Exception as e:
            st.error(f"A consulta falhou: {e}")
            df = None

    if df is not None:
        st.dataframe(df)

        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)

        st.download_button(
            "Baixar Excel",
            data=buffer,
            file_name="consulta_volumes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
