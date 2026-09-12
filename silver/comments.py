"""
Ontologia do Silver: COMMENT ON TABLE (grão) / COMMENT ON COLUMN (colunas não
óbvias), aplicados direto no banco — mesmo padrão já usado no Gold
(gold/build_volumes.py::apply_grain_comments/apply_comments). Chamado a partir
de silver/run_sample.py depois das tabelas existirem.

Só colunas derivadas/não-óbvias ganham comentário — colunas de passagem
(rename 1:1 do Bronze, sem transformação) não precisam, o nome já basta.
"""

GRAIN = {
    "veiculos": "Uma linha representa um emplacamento (linha original do "
    "Bronze DENATRAN) com data_emplacamento >= 2000 — sem agregação, grão "
    "igual ao da fonte.",
    "veiculos_historico": "Uma linha representa um emplacamento (linha "
    "original do Bronze DENATRAN) com data_emplacamento < 2000 ou sem data "
    "parseável — mesmo grão de silver.veiculos, mas deliberadamente fora do "
    "contrato de chave de negócio (sem canonical_str/vehicle_key/match_tier/"
    "cnpj_basico_faturado).",
    "fipe_precos": "Uma linha representa um preço de catálogo FIPE para uma "
    "combinação codigo_fipe x year_code x reference_month — histórico "
    "completo mantido, não colapsado para 'preço mais recente' (essa "
    "decisão é de quem consome no Gold).",
    "mapping_table": "Crosswalk manual marca/versão -> código FIPE — "
    "planilha carregada como está, não gerada por pipeline. Usada como "
    "fallback de match (tier 3) quando o match por hash (tier 1/2) não "
    "encontra correspondência.",
    "fipe": "TABELA ÓRFÃ — não escrita por nenhum normalizador ou runner "
    "atual (silver/normalizers/*.py, silver/run_sample.py). Schema em "
    "formato DENATRAN, não FIPE, apesar do nome — resultado provável de uma "
    "versão anterior do pipeline, de antes da separação veiculos/"
    "veiculos_historico. Candidata a remoção, não confirmada ainda.",
}

COMMENTS = {
    "veiculos": {
        "cnpj_basico_faturado": "Derivada: só preenchida quando "
        "tipo_faturado = 'CNPJ' — 8 primeiros dígitos (raiz) da "
        "identificacao_faturado normalizada (remove sufixo '.0' de float "
        "mal formatado, preenche zero à esquerda até 14 dígitos). Chave de "
        "junção com gold.dim_empresa.",
        "identificacao_faturado": "Mascarada (2026-09-09) para qualquer "
        "tipo_faturado diferente de 'CNPJ' — CPF de pessoa física é dado "
        "pessoal sob LGPD, sem uso downstream (só cnpj_basico_faturado, "
        "que já é derivada só do ramo CNPJ). Ver silver/normalizers/"
        "denatran.py.",
        "canonical_str": "Derivada: string canônica de marca + versao + "
        "ano_modelo + combustivel (macro SQL canonical_str_denatran_sql), "
        "usada só para gerar vehicle_key — não pretende ser legível.",
        "vehicle_key": "Derivada: hash(canonical_str) — chave de negócio "
        "que identifica 'o mesmo veículo' entre vendas diferentes e entre "
        "fontes (DENATRAN e FIPE compartilham o mesmo domínio de hash). Não "
        "é surrogate key de dimensão — isso só existe no Gold.",
        "codigo_fipe_crosswalk": "Derivada: match tier 3 — join de versao "
        "(normalizado: sem acento, minúsculo, trim) contra "
        "silver.mapping_table, só aceita valor no formato real de código "
        "FIPE (######-#). Corrigido 2026-08-24 (antes descartava o código "
        "e aceitava lixo de anotação da planilha).",
        "match_tier": "Derivada: 1 = código FIPE já veio na própria linha "
        "do DENATRAN; 3 = achou só via crosswalk manual "
        "(codigo_fipe_crosswalk); NULL = nenhum dos dois. Nunca contém 2 — "
        "tier 2 (hash contra o catálogo FIPE) só existe em "
        "gold.dim_veiculo_atual.match_tier_fipe, propriedade do veículo, "
        "não da venda individual.",
    },
    "veiculos_historico": {
        "cnpj_basico_faturado": "Presente no schema mas nunca populada com "
        "chave de negócio (mesma mitigação de identificacao_faturado — ver "
        "silver.veiculos) — esta era é anterior ao próprio conceito de "
        "match_tier/vehicle_key, tratada como puramente descritiva.",
    },
    "fipe_precos": {
        "vehicle_key": "hash(canonical_str_fipe_sql(brand_name, "
        "model_name, model_year, fuel)) — mesmo domínio de hash do lado "
        "DENATRAN (silver.veiculos.vehicle_key), permite join tier 2 por "
        "igualdade em vez de comparação de texto.",
        "data_referencia": "Parseada de reference_month (\"agosto de "
        "2026\" -> DATE '2026-08-01') — convenção: sempre primeiro dia do "
        "mês, não é uma data real de referência de preço.",
        "reference_month": "Texto original da fonte, formato 'mês por "
        "extenso de YYYY' (ex.: 'agosto de 2026') — ver data_referencia "
        "para a versão parseada como DATE.",
    },
}


def apply_grain_comments(con, grain: dict = GRAIN) -> None:
    for table, text in grain.items():
        text_escaped = text.replace("'", "''")
        con.execute(f"COMMENT ON TABLE silver.{table} IS '{text_escaped}'")


def apply_comments(con, comments: dict = COMMENTS) -> None:
    for table, cols in comments.items():
        for col, text in cols.items():
            text_escaped = text.replace("'", "''")
            con.execute(f"COMMENT ON COLUMN silver.{table}.{col} IS '{text_escaped}'")
