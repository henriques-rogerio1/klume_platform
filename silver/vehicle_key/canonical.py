"""
Canonical vehicle key — contrato de normalização da plataforma Klume.

Qualquer fonte que produza dados de veículos deve usar este módulo
para gerar o canonical_str antes de inserir no Silver.
O DuckDB gera o vehicle_key (UBIGINT) a partir do canonical_str no momento
da ingestão — nunca fora do DuckDB, para garantir determinismo.

Join key no Silver/Gold:
    hash(canonical_str)  →  UBIGINT  (via DuckDB SQL)

Tier de match:
    1 = codeFipe direto         (mais confiável)
    2 = canonical hash          (normalização)
    3 = tabela polo manual      (mapeamento explícito)
    NULL = sem correspondência  (veículo sem FIPE ou muito antigo)
"""

import re
import unicodedata


COMBUSTIVEL_MAP = {
    "gasolina":               "G",
    "alcool/gasolina":        "G",   # flex — FIPE registra como gasolina
    "gasolina/alcool":        "G",
    "alcool":                 "A",
    "etanol":                 "A",
    "diesel":                 "D",
    "diesel/gnv":             "D",
    "eletrico":               "E",
    "eletrico/gasolina":      "E",
    "gas natural veicular":   "GNV",
    "gnv":                    "GNV",
    "hibrido":                "H",
}


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_modelo_denatran(versao: str) -> str:
    """
    DENATRAN Versão: "HONDA/CG 160 FAN" → "CG 160 FAN"
                     "I/MINI COOPER S"   → "MINI COOPER S"
    """
    if "/" in versao:
        return versao.split("/", 1)[1]
    return versao


def map_combustivel(raw: str) -> str:
    key = raw.lower().strip()
    return COMBUSTIVEL_MAP.get(key, "X")


def canonical_str(
    marca: str,
    modelo_raw: str,
    ano_modelo: str | int,
    combustivel: str,
    *,
    source: str = "denatran",
) -> str:
    """
    Gera a string canônica que serve como entrada do hash no DuckDB.

    Args:
        marca:        nome da marca (qualquer casing)
        modelo_raw:   campo de modelo/versão da fonte (aplica extração por source)
        ano_modelo:   ano modelo (int ou str)
        combustivel:  combustível no formato da fonte
        source:       "denatran" | "fipe" | "generic"
                      controla como extrair o modelo do campo cru

    Returns:
        "marca_norm|modelo_norm|ano|comb_code"
        Ex: "honda|cg 160 fan|2026|G"
    """
    marca_n = normalize_text(marca)

    if source == "denatran":
        modelo_n = normalize_text(extract_modelo_denatran(modelo_raw))
    else:
        modelo_n = normalize_text(modelo_raw)

    ano = str(ano_modelo).strip()
    comb = map_combustivel(combustivel)

    return f"{marca_n}|{modelo_n}|{ano}|{comb}"


# DuckDB SQL que gera vehicle_key a partir do canonical_str já persistido:
#
# ALTER TABLE silver.emplacamentos ADD COLUMN vehicle_key UBIGINT
#     GENERATED ALWAYS AS (hash(canonical_str));
#
# Ou na query de ingestão:
#   SELECT *, hash(canonical_str) AS vehicle_key FROM staging_normalized
