"""
Tabelas de referência/taxa pro motor de TCO (ver gold/tco/engine.py e o plano
"TCO — Modelo de dados e motor de cálculo").

Diferente do resto do Silver (normalizado a partir de upload de arquivo,
CREATE OR REPLACE a cada rodada), estas 4 tabelas são mantidas à mão —
não têm pipeline de ingestão automática ainda, por isso CREATE TABLE IF NOT
EXISTS (não apagar dado inserido manualmente ao rodar de novo), mesmo padrão
de app/query_log.py::_ensure_table.

Nenhuma tem fonte real conectada nesta primeira versão (decisão explícita,
2026-08-27) — são esqueleto de estrutura pra receber dado real depois. O
comentário de tabela de cada uma documenta que tipo de fonte resolveria isso.

silver.tco_especificacoes_veiculo é Type 1 por escolha, deliberadamente
reduzido — NÃO é o item futuro "Itens de Especificações" do roadmap
(docs/architecture-roadmap.md linha 232-237, dimensão SCD Type 2 real por
versão/geração). Quando esse item for construído de verdade, esta tabela
provavelmente precisa migrar/unificar com ele — não tratar como definitivo.

Uso:
    python -m silver.tco.tables
Requer MOTHERDUCK_TOKEN no .env (ou passe con=... pra rodar contra fixture
local, ver gold/tco/tests/test_engine.py).
"""

from silver.db.connection import get_connection

GRAIN = {
    "tco_especificacoes_veiculo": "Uma linha representa a especificação "
    "técnica atual (Type 1, sem histórico) de um vehicle_key relevante pro "
    "cálculo de TCO — preço de lista, consumo INMETRO, specs de pneu "
    "dianteiro/traseiro, plano de revisão padrão e valor da hora de mão de "
    "obra. Versão reduzida do futuro 'Itens de Especificações' "
    "(docs/architecture-roadmap.md), não substitui essa dimensão quando ela "
    "existir.",
    "tco_cesta_pecas": "Uma linha representa uma peça necessária num tipo de "
    "revisão (concessionaria ou manutencao_geral) de um vehicle_key, com "
    "quantidade e custo unitário — bridge legítima (um vehicle_key×tipo_"
    "revisao associa-se a várias peças), mas não é bridge de peso de "
    "alocação: custo_total da peça = quantidade × custo_unitario, sem "
    "restrição de soma de pesos = 1.",
    "tco_combustivel_preco": "Uma linha representa o preço médio do litro de "
    "um tipo de combustível numa UF, num mês de referência. Sem fonte real "
    "conectada ainda — candidato natural: ANP (Agência Nacional do "
    "Petróleo).",
    "tco_impostos": "Uma linha representa a alíquota de IPVA e os valores de "
    "licenciamento/DPVAT pra uma categoria de veículo numa UF, num ano. Sem "
    "fonte real conectada ainda — candidato natural: tabela de IPVA "
    "publicada por SEFAZ/Detran de cada estado.",
    "tco_seguro_cotacao": "Uma linha representa o prêmio médio de seguro "
    "estimado pra um vehicle_key (ou segmento), num mês de referência, junto "
    "com o tamanho da amostra de seguradoras usada. Sem fonte real conectada "
    "ainda — candidato natural: agregador/cotador de seguradoras.",
}

COMMENTS = {
    "tco_especificacoes_veiculo": {
        "vehicle_key": "Chave de negócio (hash) — mesmo domínio de "
        "silver.veiculos.vehicle_key. Uma linha por vehicle_key (Type 1).",
        "valor_hora_mao_de_obra": "Valor da hora de mão de obra do "
        "fabricante/rede autorizada — usado tanto em revisões de "
        "concessionária quanto em manutenção geral (mesmo valor observado "
        "nos dois blocos na amostra real).",
    },
    "tco_cesta_pecas": {
        "tipo_revisao": "'concessionaria' (revisão programada em rede "
        "autorizada) ou 'manutencao_geral' (desgaste/reposição fora do "
        "plano de revisão) — os dois blocos de custo do TCO que consomem "
        "peças.",
    },
    "tco_combustivel_preco": {
        "fonte": "Nome da fonte real que preencheria esta linha quando "
        "conectada (ex: 'ANP') — NULL enquanto não houver fonte real, não é "
        "um dado do cálculo em si.",
    },
    "tco_impostos": {
        "aliquota_ipva": "Fração (não percentual) aplicada sobre o preço "
        "final do veículo — ex: 0.04 = 4%.",
        "fonte": "Nome da fonte real que preencheria esta linha quando "
        "conectada (ex: 'SEFAZ-SP') — NULL enquanto não houver fonte real.",
    },
    "tco_seguro_cotacao": {
        "premio_medio": "Prêmio já resolvido pro período de referência — "
        "este motor não decompõe seguro anual × fator de idade do veículo "
        "(metodologia real não verificada com confiança suficiente pra "
        "reproduzir aqui, ver gold/tco/engine.py).",
        "fonte": "Nome da fonte real que preencheria esta linha quando "
        "conectada (ex: agregador de seguradoras) — NULL enquanto não "
        "houver fonte real.",
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


def create_tco_especificacoes_veiculo(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver.tco_especificacoes_veiculo (
            vehicle_key BIGINT,
            preco_lista DECIMAL(12,2),
            valor_opcionais DECIMAL(12,2),
            tipo_combustivel_calculo VARCHAR,
            consumo_combinado_inmetro DECIMAL(6,2),
            pneu_dianteiro_dimensao VARCHAR,
            pneu_dianteiro_custo_unitario DECIMAL(10,2),
            pneu_dianteiro_ciclo_troca_km INTEGER,
            pneu_traseiro_dimensao VARCHAR,
            pneu_traseiro_custo_unitario DECIMAL(10,2),
            pneu_traseiro_ciclo_troca_km INTEGER,
            revisoes_no_periodo_padrao INTEGER,
            horas_trabalho_por_revisao DECIMAL(6,2),
            horas_trabalho_manutencao_geral DECIMAL(6,2),
            valor_hora_mao_de_obra DECIMAL(8,2),
            atualizado_em TIMESTAMP
        )
    """)


def create_tco_cesta_pecas(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver.tco_cesta_pecas (
            vehicle_key BIGINT,
            tipo_revisao VARCHAR,
            peca VARCHAR,
            quantidade INTEGER,
            custo_unitario DECIMAL(10,2)
        )
    """)


def create_tco_combustivel_preco(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver.tco_combustivel_preco (
            uf VARCHAR,
            tipo_combustivel VARCHAR,
            mes_referencia DATE,
            preco_litro DECIMAL(6,2),
            fonte VARCHAR
        )
    """)


def create_tco_impostos(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver.tco_impostos (
            uf VARCHAR,
            categoria_veiculo VARCHAR,
            ano INTEGER,
            aliquota_ipva DECIMAL(6,4),
            valor_licenciamento DECIMAL(8,2),
            valor_dpvat DECIMAL(8,2),
            fonte VARCHAR
        )
    """)


def create_tco_seguro_cotacao(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver.tco_seguro_cotacao (
            vehicle_key BIGINT,
            mes_referencia DATE,
            premio_medio DECIMAL(10,2),
            numero_seguradoras_amostra INTEGER,
            fonte VARCHAR
        )
    """)


def main(con=None):
    con = con or get_connection("motherduck")
    con.execute("CREATE SCHEMA IF NOT EXISTS silver")

    print("Criando silver.tco_especificacoes_veiculo...")
    create_tco_especificacoes_veiculo(con)
    print("Criando silver.tco_cesta_pecas...")
    create_tco_cesta_pecas(con)
    print("Criando silver.tco_combustivel_preco...")
    create_tco_combustivel_preco(con)
    print("Criando silver.tco_impostos...")
    create_tco_impostos(con)
    print("Criando silver.tco_seguro_cotacao...")
    create_tco_seguro_cotacao(con)

    print("Aplicando comentários de grão (COMMENT ON TABLE)...")
    apply_grain_comments(con)
    print("Aplicando comentários (ontologia)...")
    apply_comments(con)


if __name__ == "__main__":
    main()
