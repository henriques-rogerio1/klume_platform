"""
Constrói gold.dim_empresa — enriquecimento de CNPJ faturado (razão social, CNAE,
classificação) pra silver.veiculos.cnpj_basico_faturado.

Escopo: só os cnpj_basico que já aparecem em silver.veiculos — não os ~65M CNPJs
inteiros da Receita Federal, pra manter isso pequeno e barato de consultar.

Fontes:
  - staging.bronze_master_cnpj (40,4M linhas) + main.CNPJ_empresas_final (24,8M
    linhas): mesma fonte "Empresas" da Receita Federal, zero sobreposição
    verificada entre as duas — juntas cobrem 99,98% dos CNPJs relevantes (uma
    sozinha não passa de 74,4%).
  - staging.bronze_master_estabelecimentos (63,8M linhas): CNAE + nome fantasia,
    uma linha por estabelecimento (matriz + filiais) — pega a linha matriz.

Refresh é manual, desacoplado do pipeline automático de upload — rodar direto
quando decidido (não é chamado por gold/build_volumes.py::main(), exceto no
bootstrap da primeira vez que a tabela ainda não existe). Evita escanear
~104M linhas de CNPJ a cada arquivo novo de volumes, que chega bem mais
frequente do que este refresh precisa rodar. CNPJ que aparecer entre um
refresh e outro fica com a sentinela "Não identificado" (-2) até o próximo
refresh — sem urgência, nada no produto depende disso no mesmo dia.

Uso:
    python gold/build_dim_empresa.py                      # build normal
    python gold/build_dim_empresa.py --verify-determinism  # build 2x, diff (caro)
Requer MOTHERDUCK_TOKEN no .env.
"""

import sys

from gold.build_volumes import apply_comments, apply_grain_comments
from silver.db.connection import get_connection

GRAIN = {
    "dim_empresa": "Uma linha representa um cnpj_basico observado em "
    "silver.veiculos.cnpj_basico_faturado, com os atributos cadastrais da união "
    "de staging.bronze_master_cnpj/main.CNPJ_empresas_final e, quando existente, "
    "a linha matriz de staging.bronze_master_estabelecimentos — mais duas linhas "
    "sentinela (-1 = não aplicável, -2 = não identificado) para FK que não se "
    "aplica ou não foi encontrada.",
}

COMMENTS = {
    "dim_empresa": {
        "empresa_key": "Chave surrogate inteira. -1 = não aplicável (venda não "
        "faturada por CNPJ), -2 = CNPJ real que não bateu em nenhuma fonte "
        "Empresas.",
        "cnpj_basico": "8 primeiros dígitos do CNPJ (raiz) — chave de negócio. "
        "NULL só nas duas linhas sentinela.",
        "fonte_empresas": "De qual das duas fontes Empresas (sem sobreposição "
        "entre elas) veio razao_social/natureza_juridica/porte — NULL nas linhas "
        "sentinela ou quando nenhuma fonte tem esse CNPJ.",
        "tem_estabelecimento": "FALSE quando o CNPJ existe numa fonte Empresas mas "
        "não foi encontrado em bronze_master_estabelecimentos (~3,4% dos casos) — "
        "nome_fantasia/cnae_fiscal_principal/categoria_empresa ficam NULL nesse "
        "caso, sem virar uma sentinela à parte (o CNPJ existe de verdade, só falta "
        "esse detalhe). NULL nas duas linhas sentinela (não se aplica).",
        "categoria_empresa": "Classificação por CNAE principal: CNAE 45xx = "
        "'Concessionária/Comércio de Veículos', CNAE 771x = 'Locadora' (aluguel de "
        "meios de transporte — deliberadamente mais estreito que 77xx inteiro, que "
        "também inclui aluguel de máquinas/equipamentos sem relação com veículos), "
        "senão 'Outro'. Decisão confirmada em 2026-08-20 — ver "
        "docs/architecture-roadmap.md item B1.",
    },
}


def build_dim_empresa(con) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_empresa AS
        WITH relevantes AS (
            SELECT DISTINCT cnpj_basico_faturado AS cnpj_basico
            FROM silver.veiculos
            WHERE cnpj_basico_faturado IS NOT NULL
        ),
        empresas AS (
            SELECT cnpj_basico, razao_social, natureza_juridica, qualificacao,
                   capital_social, porte, fonte_empresas
            FROM (
                SELECT cnpj_basico, razao_social, natureza_juridica, qualificacao,
                       capital_social, porte, 'bronze_master_cnpj' AS fonte_empresas
                FROM staging.bronze_master_cnpj

                UNION ALL

                SELECT cnpj_basico, razao_social, natureza_juridica, qualificacao,
                       capital_social, porte, 'CNPJ_empresas_final' AS fonte_empresas
                FROM main.CNPJ_empresas_final
            )
            -- Defensivo: hoje as duas fontes têm zero sobreposição (verificado),
            -- mas não presume isso pra sempre — desempate total se algum dia
            -- passar a existir CNPJ duplicado entre as duas.
            QUALIFY row_number() OVER (
                PARTITION BY cnpj_basico
                ORDER BY fonte_empresas, razao_social, capital_social DESC NULLS LAST
            ) = 1
        ),
        estab_matriz AS (
            -- Linha vencedora completa (matriz preferida sobre filial via
            -- identificador_matriz_filial), nunca arg_max por coluna isolada.
            -- cnpj_ordem desempata matriz/filial reais; md5 da linha é o último
            -- recurso pra garantir ordem total mesmo se nada mais desempatar.
            SELECT cnpj_basico, nome_fantasia, situacao_cadastral,
                   cnae_fiscal_principal, municipio, uf
            FROM staging.bronze_master_estabelecimentos
            QUALIFY row_number() OVER (
                PARTITION BY cnpj_basico
                ORDER BY (identificador_matriz_filial = '1') DESC, cnpj_ordem,
                         situacao_cadastral, nome_fantasia,
                         md5(cnpj_basico || cnpj_ordem || cnpj_dv)
            ) = 1
        )
        SELECT
            row_number() OVER (ORDER BY r.cnpj_basico) AS empresa_key,
            r.cnpj_basico,
            e.razao_social,
            e.natureza_juridica,
            e.qualificacao AS qualificacao_responsavel,
            e.capital_social,
            e.porte,
            e.fonte_empresas,
            (est.cnpj_basico IS NOT NULL) AS tem_estabelecimento,
            est.nome_fantasia,
            est.situacao_cadastral,
            est.cnae_fiscal_principal,
            est.municipio AS municipio_estabelecimento,
            est.uf AS uf_estabelecimento,
            CASE
                WHEN est.cnae_fiscal_principal LIKE '45%' THEN 'Concessionária/Comércio de Veículos'
                WHEN est.cnae_fiscal_principal LIKE '771%' THEN 'Locadora'
                WHEN est.cnae_fiscal_principal IS NOT NULL THEN 'Outro'
                ELSE NULL
            END AS categoria_empresa
        FROM relevantes r
        LEFT JOIN empresas e ON r.cnpj_basico = e.cnpj_basico
        LEFT JOIN estab_matriz est ON r.cnpj_basico = est.cnpj_basico

        UNION ALL

        SELECT -1, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
               CAST(NULL AS BOOLEAN), NULL, NULL, NULL, NULL, NULL, NULL

        UNION ALL

        SELECT -2, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
               CAST(NULL AS BOOLEAN), NULL, NULL, NULL, NULL, NULL, NULL
    """)


def main():
    verify_determinism = "--verify-determinism" in sys.argv

    con = get_connection("motherduck")
    con.execute("CREATE SCHEMA IF NOT EXISTS gold")

    print("Construindo dim_empresa...")
    build_dim_empresa(con)
    print("Aplicando comentários de grão (COMMENT ON TABLE)...")
    apply_grain_comments(con, GRAIN)
    print("Aplicando comentários (ontologia)...")
    apply_comments(con, COMMENTS)

    # 1) Unicidade de empresa_key e cnpj_basico (fora das sentinelas).
    dup_key = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT empresa_key FROM gold.dim_empresa GROUP BY 1 HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    assert dup_key == 0, f"empresa_key duplicada: {dup_key} caso(s)."
    dup_cnpj = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT cnpj_basico FROM gold.dim_empresa
            WHERE cnpj_basico IS NOT NULL
            GROUP BY 1 HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    assert dup_cnpj == 0, f"cnpj_basico duplicado: {dup_cnpj} caso(s)."
    print("OK: empresa_key e cnpj_basico únicos.")

    # 2) Cobertura: nenhum cnpj_basico_faturado de silver.veiculos ficou de fora.
    n_relevantes = con.execute("""
        SELECT COUNT(DISTINCT cnpj_basico_faturado) FROM silver.veiculos
        WHERE cnpj_basico_faturado IS NOT NULL
    """).fetchone()[0]
    n_dim = con.execute("SELECT COUNT(*) FROM gold.dim_empresa WHERE empresa_key > 0").fetchone()[0]
    print(f"CNPJs relevantes em silver.veiculos: {n_relevantes:,} | linhas reais em dim_empresa: {n_dim:,}")
    assert n_dim == n_relevantes, "dim_empresa perdeu ou duplicou CNPJ relevante."
    print("OK: cobertura completa, sem perda silenciosa.")

    # 3) Exatamente as 2 sentinelas esperadas.
    sentinelas = con.execute("""
        SELECT empresa_key FROM gold.dim_empresa WHERE empresa_key < 0 ORDER BY 1
    """).fetchall()
    assert [s[0] for s in sentinelas] == [-2, -1], f"Sentinelas inesperadas: {sentinelas}"
    print("OK: exatamente as 2 linhas sentinela (-1, -2).")

    n_nao_identificado = con.execute("""
        SELECT COUNT(*) FROM silver.veiculos v
        WHERE v.cnpj_basico_faturado IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM gold.dim_empresa d
              WHERE d.cnpj_basico = v.cnpj_basico_faturado
          )
    """).fetchone()[0]
    print(f"CNPJs de silver.veiculos sem nenhuma linha em dim_empresa (deve ser 0): {n_nao_identificado}")
    assert n_nao_identificado == 0

    if verify_determinism:
        print("\n--verify-determinism: reconstruindo do zero pra comparar (caro, escaneia ~104M linhas de novo)...")
        con.execute("CREATE OR REPLACE TEMP TABLE _dim_empresa_snapshot1 AS SELECT * FROM gold.dim_empresa")
        build_dim_empresa(con)
        diff_a = con.execute(
            "SELECT COUNT(*) FROM (SELECT * FROM _dim_empresa_snapshot1 EXCEPT SELECT * FROM gold.dim_empresa)"
        ).fetchone()[0]
        diff_b = con.execute(
            "SELECT COUNT(*) FROM (SELECT * FROM gold.dim_empresa EXCEPT SELECT * FROM _dim_empresa_snapshot1)"
        ).fetchone()[0]
        print(f"build1-only={diff_a}, build2-only={diff_b}")
        assert diff_a == 0 and diff_b == 0, "dim_empresa não é determinística entre builds."
        print("OK: determinístico (0 diferenças entre dois builds).")


if __name__ == "__main__":
    main()
