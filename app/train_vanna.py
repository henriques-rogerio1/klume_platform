"""
Script manual pra (re)treinar o Vanna local — útil depois de editar
app/training_data.py, pra testar o resultado sem esperar o auto-treino
lazy do primeiro uso (ver ensure_trained() em vanna_client.py).

Pra forçar um retreino do zero (ex: depois de mudar o DDL/exemplos), apague
app/chroma_store/ antes de rodar — train()/vn.train() só adiciona, não
substitui.

Uso:
    python app/train_vanna.py
Requer ANTHROPIC_API_KEY e MOTHERDUCK_TOKEN no .env.
"""

import os

from dotenv import load_dotenv

from app.training_data import DOCUMENTATION, EXAMPLES
from app.vanna_client import KlumeVanna
from silver.db.connection import get_connection


def main():
    load_dotenv(dotenv_path=".env")
    vn = KlumeVanna(os.environ["ANTHROPIC_API_KEY"])

    con = get_connection("motherduck")
    ddl_rows = con.execute("DESCRIBE gold.fato_volumes").fetchall()
    ddl_cols = ",\n    ".join(f"{name} {dtype}" for name, dtype, *_ in ddl_rows)
    vn.train(ddl=f"CREATE TABLE gold.fato_volumes (\n    {ddl_cols}\n)")
    print("DDL treinado.")

    for doc in DOCUMENTATION:
        vn.train(documentation=doc)
    print(f"{len(DOCUMENTATION)} documentos treinados.")

    for question, sql in EXAMPLES:
        vn.train(question=question, sql=sql)
    print(f"{len(EXAMPLES)} exemplos de pergunta/SQL treinados.")


if __name__ == "__main__":
    main()
