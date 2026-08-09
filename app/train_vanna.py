"""
Treina o Vanna local (ChromaDB) contra o schema real de gold.fato_volumes
e perguntas de exemplo baseadas nos padrões reais de cliente encontrados
em Documents/data/Amostras (ver memória do projeto).

Roda uma vez (ou de novo quando o schema/exemplos mudarem):
    python app/train_vanna.py
Requer ANTHROPIC_API_KEY e MOTHERDUCK_TOKEN no .env.
"""

import os

from dotenv import load_dotenv

from app.vanna_client import get_vanna
from silver.db.connection import get_connection

DOCUMENTATION = [
    "quantidade é a métrica de volume (soma de veículos emplacados) — sempre use "
    "SUM(quantidade), nunca COUNT(*): uma linha de gold.fato_volumes já pode representar "
    "mais de um veículo agregado.",
    "match_tier: 1 significa que o código FIPE veio direto da fonte DENATRAN na própria "
    "linha. NULL significa que não foi possível identificar o FIPE. Não existe join com "
    "preço FIPE disponível ainda nesta versão — não tente calcular valor monetário.",
    "segmentacao_atualizada é a reclassificação mais recente do tipo de veículo; "
    "segmentacao_original é como o DENATRAN classificou originalmente. Prefira "
    "segmentacao_atualizada, a menos que a pergunta peça explicitamente a original.",
    "cnpj_basico_faturado são os 8 primeiros dígitos do CNPJ de quem faturou o veículo "
    "(pessoa jurídica) — só preenchido quando tipo_faturado = 'CNPJ'. Pode ser cruzado com "
    "staging.bronze_master_estabelecimentos.cnpj_basico para descobrir segmento de negócio "
    "(cnae_fiscal_principal) ou nome_fantasia.",
    "Cobertura de dados atual: gold.fato_volumes só tem os anos 2016, 2020 e 2025 "
    "completos (mais uma amostra pequena pré-2000). Não é o histórico completo do "
    "DENATRAN ainda — avise se uma pergunta pedir um ano fora dessa lista.",
    "combustivel é o valor bruto da fonte e varia de grafia por ano (ex: 'Álcool / "
    "Gasolina' em 2016 vs 'ALCOOL/GASOLINA' em 2025 — mesmo combustível, string "
    "diferente). Para QUALQUER pergunta que filtre ou agrupe por tipo de combustível, "
    "use sempre combustivel_normalizado, nunca combustivel bruto — combustivel_normalizado "
    "colapsa essas variações em um código único de uma letra, sempre em maiúsculas, "
    "SEM abreviações por extenso: combustivel_normalizado = 'G' (gasolina E também "
    "'flex'/'bicombustível' — NÃO existe valor 'Flex', o código pra flex É 'G'), "
    "combustivel_normalizado = 'A' (álcool/etanol puro), 'D' (diesel), 'E' (elétrico), "
    "'GNV' (gás natural veicular), 'H' (híbrido), 'N' (sem combustível, ex: reboque), "
    "'X' (raro/não classificado). Nunca use o nome do combustível por extenso nem em "
    "português como valor de filtro nessa coluna — só esses códigos.",
    "Glossário direto: 'flex' = combustivel_normalizado = 'G'. Não existe e nunca "
    "existirá o valor 'Flex' (com F maiúsculo ou não) na coluna combustivel_normalizado.",
    "tipo_veiculo_principal NÃO é normalizado (ainda não existe crosswalk pra essa "
    "coluna, diferente de combustivel) — o mesmo tipo de veículo aparece com "
    "capitalização e palavra diferente por era, ex: motocicleta aparece como 'Moto' OU "
    "'MOTOCICLETA'; carro de passeio aparece como 'Auto' OU 'CARRO DE PASSEIO'; caminhão "
    "aparece como 'Caminhão' OU 'COMERCIAL PESADO'. NUNCA filtre tipo_veiculo_principal "
    "com '=' — sempre use ILIKE '%palavra-chave%' (ILIKE já ignora maiúsc/minúsc, então "
    "'%moto%' sozinho já cobre 'Moto' e 'MOTOCICLETA'). Se as variações usarem palavras "
    "totalmente diferentes (ex: 'Auto' vs 'CARRO DE PASSEIO'), combine com OR.",
]

EXAMPLES = [
    (
        "Volume de motos por cor em 2025",
        """
        SELECT cor_predominante, SUM(quantidade) AS quantidade
        FROM gold.fato_volumes
        WHERE tipo_veiculo_principal ILIKE '%moto%'
          AND date_part('year', data_emplacamento) = 2025
        GROUP BY cor_predominante
        ORDER BY quantidade DESC
        """,
    ),
    (
        "Quantos veículos flex foram emplacados em Minas Gerais em 2025?",
        """
        SELECT SUM(quantidade) AS quantidade
        FROM gold.fato_volumes
        WHERE combustivel_normalizado = 'G'
          AND estado_emplacamento = 'MG'
          AND date_part('year', data_emplacamento) = 2025
        """,
    ),
    (
        "Quantos veículos foram emplacados por marca em 2024?",
        """
        SELECT marca, SUM(quantidade) AS quantidade
        FROM gold.fato_volumes
        WHERE date_part('year', data_emplacamento) = 2024
        GROUP BY marca
        ORDER BY quantidade DESC
        """,
    ),
    (
        "Volume mensal por cor e segmentação atualizada desde 2020",
        """
        SELECT date_trunc('month', data_emplacamento) AS mes,
               cor_predominante, segmentacao_atualizada,
               SUM(quantidade) AS quantidade
        FROM gold.fato_volumes
        WHERE data_emplacamento >= '2020-01-01'
        GROUP BY 1, 2, 3
        ORDER BY 1
        """,
    ),
    (
        "Volume por marca, modelo e estado, por ano",
        """
        SELECT date_part('year', data_emplacamento) AS ano,
               marca, modelo, estado_emplacamento,
               SUM(quantidade) AS quantidade
        FROM gold.fato_volumes
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 5 DESC
        """,
    ),
    (
        "Quais os principais combustíveis emplacados em SP em 2025?",
        """
        SELECT combustivel_normalizado, SUM(quantidade) AS quantidade
        FROM gold.fato_volumes
        WHERE estado_emplacamento = 'SP' AND date_part('year', data_emplacamento) = 2025
        GROUP BY combustivel_normalizado
        ORDER BY quantidade DESC
        """,
    ),
    (
        "Volume de veículos vendidos para locadoras",
        """
        SELECT g.marca, g.modelo, SUM(g.quantidade) AS quantidade
        FROM gold.fato_volumes g
        JOIN staging.bronze_master_estabelecimentos e
          ON g.cnpj_basico_faturado = e.cnpj_basico
        WHERE e.cnae_fiscal_principal LIKE '7711%'
        GROUP BY g.marca, g.modelo
        ORDER BY quantidade DESC
        """,
    ),
]


def main():
    load_dotenv(dotenv_path=".env")
    vn = get_vanna(os.environ["ANTHROPIC_API_KEY"])

    con = get_connection("motherduck")
    ddl_rows = con.execute("DESCRIBE gold.fato_volumes").fetchall()
    ddl_cols = ",\n    ".join(f"{name} {dtype}" for name, dtype, *_ in ddl_rows)
    ddl = f"CREATE TABLE gold.fato_volumes (\n    {ddl_cols}\n)"
    vn.train(ddl=ddl)
    print("DDL treinado.")

    for doc in DOCUMENTATION:
        vn.train(documentation=doc)
    print(f"{len(DOCUMENTATION)} documentos treinados.")

    for question, sql in EXAMPLES:
        vn.train(question=question, sql=sql)
    print(f"{len(EXAMPLES)} exemplos de pergunta/SQL treinados.")


if __name__ == "__main__":
    main()
