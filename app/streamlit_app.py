"""
App interno de vendas: pergunta em texto -> SQL (Vanna, editável) ->
preview com seleção de colunas -> gráfico (quando poucas dimensões) ->
export xlsx/csv.

Local: streamlit run app/streamlit_app.py  (usa .streamlit/secrets.toml)
Streamlit Cloud: mesmo código, secrets vêm da UI do Streamlit Cloud.
"""

import io
import os
import sys

# Streamlit Cloud roda o script sem a raiz do repo no sys.path (diferente do
# nosso PYTHONPATH=. local) — sem isso, "from app.vanna_client import ..." e
# os imports de "silver.*" dentro dele quebram com ModuleNotFoundError.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import plotly.express as px
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

if "result_df" not in st.session_state:
    st.session_state.result_df = None
if "sql_editor" not in st.session_state:
    st.session_state.sql_editor = ""


def run_query(sql: str) -> None:
    vn = get_vanna(ANTHROPIC_API_KEY)
    with st.spinner("Consultando..."):
        try:
            st.session_state.result_df = vn.run_sql(sql)
        except Exception as e:
            st.error(f"A consulta falhou: {e}")
            st.session_state.result_df = None


question = st.text_input("Sua pergunta", placeholder="Ex: volume de motos por cor em 2025")

if st.button("Consultar") and question:
    vn = get_vanna(ANTHROPIC_API_KEY)
    with st.spinner("Gerando SQL..."):
        st.session_state.sql_editor = vn.generate_sql(question)
    run_query(st.session_state.sql_editor)

if st.session_state.sql_editor:
    st.text_area(
        "SQL — edite aqui se quiser adicionar/trocar colunas antes de rodar de novo",
        key="sql_editor",
        height=140,
    )
    if st.button("Executar SQL"):
        run_query(st.session_state.sql_editor)

if st.session_state.result_df is not None:
    full_df = st.session_state.result_df

    if full_df.empty:
        st.warning("A consulta rodou certo, mas não retornou nenhuma linha.")
    else:
        all_cols = list(full_df.columns)
        selected_cols = st.multiselect("Colunas exibidas/exportadas", all_cols, default=all_cols)
        df = full_df[selected_cols] if selected_cols else full_df

        st.dataframe(df, use_container_width=True)

        # Gráfico automático só quando dá pra ler visualmente: poucas
        # colunas de dimensão (categoria/data) e uma única métrica numérica.
        # Com muitas dimensões o gráfico vira ruído — melhor só a tabela.
        numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        dim_cols = [c for c in df.columns if c not in numeric_cols]

        if 1 <= len(dim_cols) <= 2 and len(numeric_cols) == 1:
            metric = numeric_cols[0]
            is_temporal = pd.api.types.is_datetime64_any_dtype(df[dim_cols[0]])

            if len(dim_cols) == 1 and is_temporal:
                fig = px.line(df.sort_values(dim_cols[0]), x=dim_cols[0], y=metric, markers=True)
            elif len(dim_cols) == 1:
                top = df.sort_values(metric, ascending=False).head(30)
                fig = px.bar(top, x=dim_cols[0], y=metric)
            else:
                top_combo = df.sort_values(metric, ascending=False).head(200)
                fig = px.bar(top_combo, x=dim_cols[0], y=metric, color=dim_cols[1], barmode="group")

            st.plotly_chart(fig, use_container_width=True)

        col1, col2 = st.columns(2)

        csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
        col1.download_button(
            "Baixar CSV",
            data=csv_bytes,
            file_name="consulta_volumes.csv",
            mime="text/csv",
        )

        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)
        col2.download_button(
            "Baixar Excel",
            data=buffer,
            file_name="consulta_volumes.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
