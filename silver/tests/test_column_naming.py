import pytest

from silver.utils.columns import clean_columns, to_snake_case

# Nomes reais de coluna do Bronze DENATRAN (staging.bronze_YYYY / veiculos_raw).
REAL_DENATRAN_HEADERS = [
    "Data de Emplacamento",
    "Número do Chassi",
    "Placa do Veículo",
    "Tipo do Faturado",
    "Identificação do Faturado",
    "Tipo de Venda",
    "UF do Faturado",
    "Tipo do Proprietário",
    "UF de Jurisdição",
    "Código do Município",
    "Município do Emplacamento",
    "Estado do Emplacamento",
    "Ano de Fabricação",
    "Ano Modelo",
    "Código DENATRAN",
    "Marca",
    "Modelo",
    "Versão",
    "Tipo de Veículo Principal",
    "Tipo de Veículo DENATRAN",
    "Segmentação Atualizada",
    "Segmentação Original",
    "Espécie de Veículo",
    "Cód. Carroceria",
    "Carroceria",
    "Cor Predominante",
    "Combustível",
    "Potência",
    "Cilindradas",
    "Número de Lugares",
    "Capacidade de Carga",
    "Peso Bruto Total (PBT)",
    "Capacidade Máxima de Tração (CMT)",
    "Procedência",
    "Situação do Chassi",
    "Número de Eixos",
    "Restrição 1",
    "Restrição 2",
    "Restrição 3",
    "Restrição 4",
    "Data Limite da Restrição Tributária",
    "Veículo cadastrado BIN",
    "Quantidade",
    "FIPE",
    "Preço",
]

EXPECTED = {
    "Data de Emplacamento": "data_emplacamento",
    "Número do Chassi": "numero_chassi",
    "Placa do Veículo": "placa_veiculo",
    "Identificação do Faturado": "identificacao_faturado",
    "UF de Jurisdição": "uf_jurisdicao",
    "UF do Faturado": "uf_faturado",
    "Ano de Fabricação": "ano_fabricacao",
    "Tipo de Veículo Principal": "tipo_veiculo_principal",
    "Tipo de Veículo DENATRAN": "tipo_veiculo_denatran",
    "Segmentação Atualizada": "segmentacao_atualizada",
    "Segmentação Original": "segmentacao_original",
    "Cód. Carroceria": "cod_carroceria",
    "Peso Bruto Total (PBT)": "peso_bruto_total_pbt",
    "Capacidade Máxima de Tração (CMT)": "capacidade_maxima_tracao_cmt",
    "Veículo cadastrado BIN": "veiculo_cadastrado_bin",
    "FIPE": "fipe",
    "Preço": "preco",
}


@pytest.mark.parametrize("raw,expected", EXPECTED.items())
def test_to_snake_case_real_headers(raw, expected):
    assert to_snake_case(raw) == expected


def test_all_real_headers_produce_unique_names():
    mapping = clean_columns(REAL_DENATRAN_HEADERS)
    assert len(set(mapping.values())) == len(REAL_DENATRAN_HEADERS)


def test_collision_raises():
    with pytest.raises(ValueError):
        clean_columns(["Preço", "Preço  "])  # both normalize to "preco"


def test_override_resolves_collision():
    mapping = clean_columns(["Preço", "Preço  "], overrides={"Preço  ": "preco_2"})
    assert mapping == {"Preço": "preco", "Preço  ": "preco_2"}
