"""
Utilitário genérico de renomeação de colunas Bronze -> Silver.

Nomes de coluna crus (com espaço, acento, parênteses) nunca devem ser
digitados à mão dentro de SQL de normalização — foi exatamente isso que
causou o bug do "Preço FIPE" (coluna que não existe) em denatran.py.
Este módulo introspecciona os nomes reais via DESCRIBE e gera os nomes
limpos programaticamente.
"""

import re
import unicodedata

STOPWORDS = {"de", "do", "da", "dos", "das"}


def to_snake_case(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = s.encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    tokens = [t for t in s.split() if t not in STOPWORDS]
    return "_".join(tokens)


def clean_columns(raw_names: list[str], overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Retorna {nome_original: nome_limpo}. Levanta ValueError em colisão."""
    overrides = overrides or {}
    mapping: dict[str, str] = {}
    seen: dict[str, str] = {}
    for raw in raw_names:
        clean = overrides.get(raw, to_snake_case(raw))
        if clean in seen and seen[clean] != raw:
            raise ValueError(
                f"Colisão de nome de coluna: '{raw}' e '{seen[clean]}' "
                f"geram o mesmo nome limpo '{clean}'. Use 'overrides' para resolver."
            )
        seen[clean] = raw
        mapping[raw] = clean
    return mapping


def rename_to_snake_case(
    con,
    source_relation: str,
    view_name: str,
    overrides: dict[str, str] | None = None,
) -> str:
    """
    Cria (ou substitui) uma view `view_name` com todas as colunas de
    `source_relation` renomeadas para snake_case sem acento, introspectando
    os nomes reais via DESCRIBE em vez de exigir que sejam digitados à mão.
    """
    raw_names = [row[0] for row in con.execute(f"DESCRIBE SELECT * FROM {source_relation}").fetchall()]
    mapping = clean_columns(raw_names, overrides)

    select_list = ", ".join(f'"{raw}" AS "{clean}"' for raw, clean in mapping.items())
    con.execute(f"CREATE OR REPLACE VIEW {view_name} AS SELECT {select_list} FROM {source_relation}")
    return view_name
