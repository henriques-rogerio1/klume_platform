"""
App interno de vendas: pergunta em texto -> SQL (Vanna) -> seletor de
dimensões (sem precisar saber SQL) -> preview -> gráfico (quando poucas
dimensões) -> export xlsx/csv. Edição de SQL direta fica só como opção
avançada, pra quem já sabe SQL.

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

# Mesma lista de dimensões de gold/build_volumes.py — mantém os dois em
# sincronia manualmente por enquanto (repo pequeno, sem import cruzado
# gold->app pra não acoplar as duas camadas por causa de uma constante).
DIMENSION_COLUMNS = [
    "data_emplacamento",
    "marca",
    "modelo",
    "versao",
    "segmentacao_atualizada",
    "segmentacao_original",
    "combustivel_normalizado",
    "cor_predominante",
    "tipo_venda",
    "municipio_emplacamento",
    "estado_emplacamento",
    "tipo_veiculo_principal",
    "match_tier",
]

st.title("Consulta de Volumes")
st.caption(
    "Pergunte em português sobre volumes de emplacamento (2016, 2020 e 2025 — "
    "cobertura parcial, mais anos chegam depois)."
)

for key, default in [
    ("result_df", None),
    ("sql_editor", ""),
    ("base_question", None),
    ("last_dims", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


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
    st.session_state.base_question = question
    vn = get_vanna(ANTHROPIC_API_KEY)
    with st.spinner("Gerando SQL..."):
        sql = vn.generate_sql(question)
    st.session_state.sql_editor = sql
    run_query(sql)
    if st.session_state.result_df is not None:
        st.session_state.last_dims = [
            c for c in DIMENSION_COLUMNS if c in st.session_state.result_df.columns
        ]

if st.session_state.base_question:
    chosen_dims = st.multiselect(
        "Dimensões (marque o que quer ver — o resultado é reagrupado automaticamente)",
        DIMENSION_COLUMNS,
        default=st.session_state.last_dims or [],
    )

    if chosen_dims and chosen_dims != st.session_state.last_dims:
        st.session_state.last_dims = chosen_dims
        vn = get_vanna(ANTHROPIC_API_KEY)
        augmented_question = (
            f"{st.session_state.base_question}\n\n"
            f"Retorne o resultado agrupado exatamente por estas colunas de "
            f"gold.fato_volumes: {', '.join(chosen_dims)}. Some quantidade normalmente."
        )
        with st.spinner("Ajustando colunas..."):
            sql = vn.generate_sql(augmented_question)
        st.session_state.sql_editor = sql
        run_query(sql)

    with st.expander("Avançado: editar SQL diretamente"):
        st.text_area("SQL", key="sql_editor", height=140)
        if st.button("Executar SQL"):
            run_query(st.session_state.sql_editor)

if st.session_state.result_df is not None:
    df = st.session_state.result_df

    if df.empty:
        st.warning("A consulta rodou certo, mas não retornou nenhuma linha.")
    else:
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
