"""
Cliente Vanna (pergunta em texto -> SQL) contra o gold.fato_volumes no
MotherDuck. Usa Claude Haiku (gerar SQL a partir de um schema treinado é
tarefa mecânica, não precisa do modelo mais caro) e ChromaDB local como
memória de treinamento (regenerável via train_vanna.py, não versionada).
"""

import os

from vanna.legacy.anthropic import Anthropic_Chat
from vanna.legacy.chromadb import ChromaDB_VectorStore

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


def get_vanna(anthropic_api_key: str) -> KlumeVanna:
    return KlumeVanna(anthropic_api_key)
