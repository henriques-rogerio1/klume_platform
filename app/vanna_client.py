"""
Cliente Vanna (pergunta em texto -> SQL) contra o gold.fato_volumes no
MotherDuck. Usa Claude Haiku (gerar SQL a partir de um schema treinado é
tarefa mecânica, não precisa do modelo mais caro) e ChromaDB local como
memória de treinamento.

app/chroma_store/ é gitignored (regenerável, não versionado) — então num
deploy novo (ex: Streamlit Cloud, clonado do zero) ele não existe ainda.
get_vanna() detecta isso e treina automaticamente na primeira chamada, pra
não depender de alguém rodar train_vanna.py manualmente num ambiente onde
isso não é nem possível (Streamlit Cloud não dá shell).
"""

import os

from vanna.legacy.anthropic import Anthropic_Chat
from vanna.legacy.chromadb import ChromaDB_VectorStore

from app.training_data import DOCUMENTATION, EXAMPLES
from silver.db.connection import get_connection

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_store")
MODEL = "claude-haiku-4-5-20251001"


class KlumeVanna(ChromaDB_VectorStore, Anthropic_Chat):
    def __init__(self, anthropic_api_key: str):
        ChromaDB_VectorStore.__init__(self, config={"path": CHROMA_PATH})
        Anthropic_Chat.__init__(self, config={"api_key": anthropic_api_key, "model": MODEL})
        self.run_sql_is_set = True
        self._con = None

    def run_sql(self, sql: str):
        if self._con is None:
            self._con = get_connection("motherduck")
        return self._con.execute(sql).df()


def ensure_trained(vn: KlumeVanna) -> None:
    """Treina vn se a base de treino local estiver vazia (primeiro uso/deploy novo)."""
    existing = vn.get_training_data()
    if existing is not None and len(existing) > 0:
        return

    if vn._con is None:
        vn._con = get_connection("motherduck")

    ddl_rows = vn._con.execute("DESCRIBE gold.fato_volumes").fetchall()
    ddl_cols = ",\n    ".join(f"{name} {dtype}" for name, dtype, *_ in ddl_rows)
    vn.train(ddl=f"CREATE TABLE gold.fato_volumes (\n    {ddl_cols}\n)")

    for doc in DOCUMENTATION:
        vn.train(documentation=doc)

    for question, sql in EXAMPLES:
        vn.train(question=question, sql=sql)


def get_vanna(anthropic_api_key: str) -> KlumeVanna:
    vn = KlumeVanna(anthropic_api_key)
    ensure_trained(vn)
    return vn
