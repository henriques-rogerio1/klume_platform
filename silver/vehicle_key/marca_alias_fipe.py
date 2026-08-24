"""
Alias de marca DENATRAN -> FIPE, só usado pra achar o match de preço FIPE
(nunca altera vehicle_key/canonical_str de DENATRAN, que continua exatamente
como sempre foi).

Por quê: comparando os catálogos reais nesta sessão (staging.raw_json_fipe vs
gold.dim_veiculo_atual), a maioria das marcas sem match é cauda longa real
(reboque, importador pequeno, sentinela "desconhecido") — mas um punhado de
marcas de altíssimo volume no DENATRAN diverge de nome da FIPE por
abreviação/naming diferente, não por falta de cobertura. Confirmado
consultando staging.raw_json_fipe.brand_name direto: 'gm'+'vw'+'m benz'+
'chery'+'kia' sozinhos são mais de 900 mil veículos em silver.veiculos sem
nenhum match de FIPE por essa divergência pura de nome.

Curado à mão a partir de dado real — não é fuzzy-match. Ambos os lados já
passam por normalize_text/normalize_text_sql (sem acento, minúsculo, sem
pontuação) antes de comparar, então as chaves e valores aqui já estão nesse
formato normalizado.
"""

MARCA_ALIAS_FIPE = {
    "gm": "chevrolet",
    "vw": "volkswagen",
    "m benz": "mercedes benz",
    "chery": "caoa chery",
    "kia": "kia motors",
}
