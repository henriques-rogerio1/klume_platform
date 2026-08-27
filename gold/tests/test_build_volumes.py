"""
Fecha o gap identificado no grafo de conhecimento: docs/architecture-roadmap.md
item A1 ("Replace hardcoded Gold assertion with a real test suite") ficou 12
dias sem execução -- o Gold era a camada menos testada apesar de ser a mais
visível pro usuário (Vanna, BI direto).

Não duplica lógica: roda o main() de verdade (mesmo `gold/build_volumes.py`
usado em produção) contra um fixture local em memória -- os mesmos 4 asserts
que já existiam (conservação de volume, sem perda de linha no join da fato,
integridade referencial de empresa_key, e agora também unicidade de chave
surrogate) são os únicos exercitados, não uma cópia paralela deles. Sem custo
de MotherDuck, sem rede.

gold.dim_empresa é pré-semeada no fixture (não deixada pro bootstrap
automático) pra não arrastar a complexidade de CNPJ (~104M linhas em
produção) pra dentro de um teste que é sobre o build de volumes -- isso é
coberto separadamente em gold/build_dim_empresa.py.
"""

import duckdb
import pytest

from gold.build_volumes import main
from silver.vehicle_key.canonical_sql import register_sql_macros


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    register_sql_macros(c)

    c.execute("CREATE SCHEMA silver")
    c.execute("""
        CREATE TABLE silver.veiculos AS SELECT * FROM (VALUES
            (DATE '2025-01-15', 1001, 'FIAT', 'UNO', 'FIAT/UNO 1.0', 2024, 'Flex',
             'Popular', 'Popular', 'Automóvel', 3550308, 'São Paulo', 'SP',
             'Branco', 'Varejo', NULL, '12345678', NULL, NULL, 5, CAST(NULL AS VARCHAR)),
            (DATE '2025-01-20', 1001, 'FIAT', 'UNO', 'FIAT/UNO 1.0', 2024, 'Flex',
             'Popular', 'Popular', 'Automóvel', 3550308, 'São Paulo', 'SP',
             'Prata', 'Varejo', NULL, NULL, NULL, NULL, 3, CAST(NULL AS VARCHAR)),
            (DATE '2025-02-01', 1002, 'CHEVROLET', 'ONIX', 'CHEVROLET/ONIX LT', 2024, 'Flex',
             'Popular', 'Popular', 'Automóvel', 3550308, 'São Paulo', 'SP',
             'Preto', 'Direta', 1, '87654321', '023456-7', 45000.00, 2, CAST(NULL AS VARCHAR)),
            (DATE '2025-02-10', 1003, 'FIAT', 'UNO', 'FIAT/UNO 1.0', 2023, 'Flex',
             'Popular', 'Popular', 'Automóvel', NULL, 'Rio de Janeiro', 'RJ',
             'Vermelho', NULL, NULL, '12345678', NULL, NULL, 1, CAST(NULL AS VARCHAR)),
            (DATE '2025-03-05', 1002, 'CHEVROLET', 'ONIX', 'CHEVROLET/ONIX LT', 2024, 'Flex',
             'Popular', 'Popular', 'Automóvel', 3550308, 'São Paulo', 'SP',
             'Branco', 'Direta', 1, '87654321', '023456-7', 46000.00, 4, CAST(NULL AS VARCHAR))
        ) AS t(
            data_emplacamento, vehicle_key, marca, modelo, versao, ano_modelo, combustivel,
            segmentacao_atualizada, segmentacao_original, tipo_veiculo_principal,
            codigo_municipio, municipio_emplacamento, estado_emplacamento,
            cor_predominante, tipo_venda, match_tier, cnpj_basico_faturado,
            fipe, preco, quantidade, codigo_fipe_crosswalk
        )
    """)
    # Vazia de propósito -- sem match de FIPE tier 2 nesse teste, não é o que
    # está sendo verificado aqui (ver silver/tests/ e gold/build_fipe_match.py).
    c.execute("""
        CREATE TABLE silver.fipe_precos (
            vehicle_key BIGINT, codigo_fipe VARCHAR, preco DECIMAL(12,2),
            data_referencia DATE, reference_month VARCHAR, year_code VARCHAR
        )
    """)

    # gold.dim_empresa pré-semeada (não deixa o bootstrap automático rodar) --
    # '12345678' resolve normal, '87654321' fica sem match de propósito (testa
    # o caminho do sentinel -2), cnpj_basico_faturado NULL testa o -1.
    c.execute("CREATE SCHEMA gold")
    c.execute("""
        CREATE TABLE gold.dim_empresa (
            empresa_key INTEGER, cnpj_basico VARCHAR, razao_social VARCHAR,
            natureza_juridica VARCHAR, qualificacao_responsavel VARCHAR,
            capital_social VARCHAR, porte VARCHAR, fonte_empresas VARCHAR,
            tem_estabelecimento BOOLEAN, nome_fantasia VARCHAR,
            situacao_cadastral VARCHAR, cnae_fiscal_principal VARCHAR,
            municipio_estabelecimento VARCHAR, uf_estabelecimento VARCHAR,
            categoria_empresa VARCHAR
        )
    """)
    c.execute("""
        INSERT INTO gold.dim_empresa VALUES
            (-1, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
            (-2, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
            (100, '12345678', 'Empresa Teste LTDA', NULL, NULL, NULL, NULL, 'teste', true, NULL, NULL, NULL, NULL, NULL, 'Outro')
    """)
    return c


def test_main_runs_end_to_end_without_raising(con):
    # Se main() não levantar exceção, os 4 asserts inline (conservação de
    # volume, sem perda de linha, integridade referencial de empresa_key,
    # unicidade de chave surrogate) já passaram -- não precisa reimplementar
    # essas checagens aqui.
    main(con=con)


def test_volume_conservation(con):
    main(con=con)
    total_silver = con.execute("SELECT SUM(quantidade) FROM silver.veiculos").fetchone()[0]
    total_gold = con.execute("SELECT SUM(quantidade) FROM gold.fato_volumes").fetchone()[0]
    assert total_gold == total_silver == 15


def test_empresa_key_resolves_all_three_sentinel_paths(con):
    main(con=con)
    rows = con.execute("""
        SELECT DISTINCT empresa_key FROM gold.fato_volumes_base ORDER BY empresa_key
    """).fetchall()
    keys = {r[0] for r in rows}
    assert keys == {-2, -1, 100}, f"esperava -1 (sem CNPJ), -2 (CNPJ sem match), 100 (match real); achou {keys}"


def test_dim_veiculo_observado_has_expected_grain(con):
    main(con=con)
    # 3 vehicle_key distintos (1001, 1002, 1003) -- linhas 1 e 2 compartilham
    # vehicle_key e todos os atributos do grão de dim_veiculo_observado
    # (só cor/tipo_venda/etc divergem, que não fazem parte desse grão).
    n = con.execute("SELECT COUNT(*) FROM gold.dim_veiculo_observado").fetchone()[0]
    assert n == 3
