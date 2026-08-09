"""
Testes de contrato para canonical.py.

Estes testes são o contrato da plataforma — se quebrarem,
a normalização divergiu e joins históricos podem ser afetados.
"""

from silver.vehicle_key.canonical import (
    canonical_str,
    normalize_text,
    map_combustivel,
    normalize_combustivel_key,
)


def test_denatran_remove_brand_prefix():
    result = canonical_str("HONDA", "HONDA/CG 160 FAN", 2026, "ALCOOL/GASOLINA")
    assert result == "honda|cg 160 fan|2026|G"


def test_denatran_importado_prefix():
    result = canonical_str("MINI", "I/MINI COOPER S CABRIO", 2026, "GASOLINA")
    assert result == "mini|mini cooper s cabrio|2026|G"


def test_fipe_source_no_prefix_strip():
    result = canonical_str("honda", "CG 160 Fan", 2026, "gasolina", source="fipe")
    assert result == "honda|cg 160 fan|2026|G"


def test_denatran_fipe_same_key():
    denatran = canonical_str("HONDA", "HONDA/CG 160 FAN", 2026, "ALCOOL/GASOLINA", source="denatran")
    fipe     = canonical_str("honda", "CG 160 Fan",      2026, "gasolina",         source="fipe")
    assert denatran == fipe, f"Mismatch:\n  DENATRAN: {denatran}\n  FIPE:     {fipe}"


def test_normalize_removes_accents():
    assert normalize_text("Elétrico") == "eletrico"
    assert normalize_text("Câmbio") == "cambio"


def test_normalize_collapses_spaces():
    assert normalize_text("CG  160  FAN") == "cg 160 fan"


def test_combustivel_flex_maps_to_G():
    assert map_combustivel("ALCOOL/GASOLINA") == "G"
    assert map_combustivel("gasolina/alcool") == "G"
    assert map_combustivel("GASOLINA") == "G"


def test_combustivel_eletrico():
    assert map_combustivel("ELETRICO") == "E"


def test_combustivel_unknown_maps_to_X():
    assert map_combustivel("HIDROGÊNIO") == "X"


def test_ano_modelo_as_int_or_str():
    r1 = canonical_str("FIAT", "FIAT/ARGO 1.0", 2024, "FLEX")
    r2 = canonical_str("FIAT", "FIAT/ARGO 1.0", "2024", "FLEX")
    assert r1 == r2


def test_combustivel_2016_accented_padded_maps_to_G():
    # valor real do Bronze 2016 — acentuado e com padding de largura fixa
    raw = "Álcool / Gasolina                                 "
    assert map_combustivel(raw) == "G"


def test_normalize_combustivel_key_preserves_slash_separator():
    # normalize_text() trocaria "/" por espaço, o que quebraria as chaves
    # de COMBUSTIVEL_MAP — normalize_combustivel_key() não pode fazer isso
    assert normalize_combustivel_key("Álcool / Gasolina") == "alcool/gasolina"
    assert "/" in normalize_combustivel_key("Diesel/GNV")


def test_combustivel_hibrido_plugin_maps_to_H():
    assert map_combustivel("Hibrido Plug-in") == "H"


def test_combustivel_sem_combustivel_maps_to_N():
    assert map_combustivel("Sem Combustivel") == "N"


def test_combustivel_gasogenio_stays_unknown():
    # combustível histórico raro, deliberadamente fora do mapa
    assert map_combustivel("Gasogênio") == "X"
