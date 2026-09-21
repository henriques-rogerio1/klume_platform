"""
Motor de cálculo de TCO (Custo Estratégico Operacional) — ver
docs/architecture-roadmap.md item C2 e o plano "TCO — Modelo de dados e
motor de cálculo".

Não é um build de tabela Gold: calcular_tco() é uma função pura, chamada sob
demanda por cenário (meses, km/ano, UF são parâmetros escolhidos na hora,
não dá pra pré-materializar toda combinação). Ela não toca o banco — recebe
um TCOInputs já resolvido. Isso é deliberado, mesmo espírito do seam
get_connection()/_motherduck_dsn() em silver/db/connection.py: separar o
cálculo puro (testável sem banco nenhum) de onde os dados vêm.

Fórmulas verificadas linha a linha contra a amostra real (Chevrolet S10 LTZ
vs. Toyota Hilux SRV, Amostra_K.LUME_Extração_PDF.pdf +
Amostra_K.LUME_Extração_EXCEL.xlsx, 2026-08-27) — ver
gold/tco/tests/test_engine.py, que reproduz os dois totais exatos.

Dois pontos NÃO reproduzidos por falta de confiança na fórmula real (opacos
de propósito, recebidos já calculados em vez de decompostos):
  - Seguro: "Total com Seguros no Período" da amostra não bate com um
    múltiplo simples do prêmio anual informado — a metodologia real de como
    o prêmio varia com a idade do veículo ao longo do período não é
    verificável só com os números da amostra. `premio_seguro_periodo` é
    recebido pronto.
  - Lubrificantes (só no bloco de revisão em concessionária): a amostra
    mistura litros e preço por tipo de fluido (motor/transmissão/
    diferencial) numa planilha com colunas que colidem entre os dois
    veículos comparados — não dá pra decompor com segurança.
    `custo_lubrificantes_revisao` é recebido pronto.

Curva de depreciação: por decisão desta rodada de planejamento, o valor
residual deve ser derivado empiricamente da trajetória de preço em
silver.fipe_precos — mas esse ajuste de curva ainda não está implementado
aqui. `residual_selecionado` é recebido já resolvido; quando a curva for
implementada, ela entra como uma função ANTES de calcular_tco(), não dentro
dela. Sub-questão que continua em aberto (não decidir aqui): qual trajetória
usar quando só existe match FIPE proxy (tier 2/3) — ver
project_fipe_tier2_low_yield.md.

ACHADO na amostra real, não reproduzido de propósito: a coluna "Por
quilômetro" da planilha original divide o TCO total do período (3 anos) pela
quilometragem ANUAL (1 ano), não pela quilometragem total do período — R$
230.311,51 / 20.000 km = R$ 11,52, não R$ 230.311,51 / 60.000 km = R$ 3,84.
Isso é dimensionalmente inconsistente (R$ de 3 anos ÷ km de 1 ano). Este
motor implementa a versão correta (custo_total / km_total) — reportar esse
achado, pode ser um bug real no gerador de relatório do K.LUME ONE.
"""

from dataclasses import dataclass, field
from math import floor


@dataclass
class PecaCesta:
    peca: str
    quantidade: int
    custo_unitario: float

    @property
    def custo_total(self) -> float:
        return self.quantidade * self.custo_unitario


@dataclass
class PneuSpec:
    dimensao: str
    custo_unitario: float
    ciclo_troca_km: int


@dataclass
class TCOInputs:
    vehicle_key: int
    meses: int
    km_por_ano: float

    preco_lista: float
    valor_opcionais: float
    desconto: float
    residual_selecionado: float

    consumo_combinado_km_l: float
    preco_litro_combustivel: float

    premio_seguro_periodo: float

    horas_trabalho_revisao: float
    horas_trabalho_manutencao_geral: float
    valor_hora_mao_de_obra: float
    pecas_revisao: list[PecaCesta] = field(default_factory=list)
    pecas_manutencao_geral: list[PecaCesta] = field(default_factory=list)
    custo_lubrificantes_revisao: float = 0.0

    pneu_dianteiro: PneuSpec | None = None
    pneu_traseiro: PneuSpec | None = None

    aliquota_ipva: float = 0.0
    valor_licenciamento: float = 0.0
    valor_dpvat: float = 0.0


@dataclass
class TCOBreakdown:
    vehicle_key: int
    depreciacao: float
    combustivel: float
    seguro: float
    revisoes_concessionaria: float
    manutencao_geral: float
    pneus: float
    impostos: float
    custo_total: float
    meses_total: int
    km_total: float

    @property
    def custo_por_mes(self) -> float:
        # Medida não-aditiva calculada em tempo de leitura, nunca
        # persistida — mesmo padrão de quantidade_tipo_venda_conhecido em
        # gold/build_volumes.py: guardar numerador/denominador aditivos
        # (custo_total, meses_total), não a razão pronta.
        return self.custo_total / self.meses_total

    @property
    def custo_por_km(self) -> float:
        return self.custo_total / self.km_total


def _custo_pneu(spec: PneuSpec | None, km_total: float) -> float:
    if spec is None:
        return 0.0
    # floor, não ceil: só conta trocas completas dentro do período já
    # decorrido -- confirmado contra a amostra (60.000km/40.000km de ciclo
    # = 1.5, a amostra mostra 1 jogo trocado, não 2).
    jogos_necessarios = floor(km_total / spec.ciclo_troca_km)
    # "jogo" = par de pneus do mesmo eixo (2 unidades) -- confirmado contra
    # a amostra (2 jogos dianteiros x 2 unidades x R$959,90 = R$3.839,60).
    return jogos_necessarios * 2 * spec.custo_unitario


def calcular_tco(inputs: TCOInputs) -> TCOBreakdown:
    km_total = inputs.km_por_ano * (inputs.meses / 12)

    preco_final = inputs.preco_lista + inputs.valor_opcionais - inputs.desconto
    depreciacao = preco_final - inputs.residual_selecionado

    litros_necessarios = km_total / inputs.consumo_combinado_km_l
    combustivel = litros_necessarios * inputs.preco_litro_combustivel

    seguro = inputs.premio_seguro_periodo

    custo_mao_de_obra_revisao = inputs.horas_trabalho_revisao * inputs.valor_hora_mao_de_obra
    custo_pecas_revisao = sum(p.custo_total for p in inputs.pecas_revisao)
    revisoes_concessionaria = (
        custo_mao_de_obra_revisao + custo_pecas_revisao + inputs.custo_lubrificantes_revisao
    )

    custo_mao_de_obra_manutencao = (
        inputs.horas_trabalho_manutencao_geral * inputs.valor_hora_mao_de_obra
    )
    custo_pecas_manutencao = sum(p.custo_total for p in inputs.pecas_manutencao_geral)
    manutencao_geral = custo_mao_de_obra_manutencao + custo_pecas_manutencao

    pneus = _custo_pneu(inputs.pneu_dianteiro, km_total) + _custo_pneu(inputs.pneu_traseiro, km_total)

    impostos = (preco_final * inputs.aliquota_ipva) + inputs.valor_licenciamento + inputs.valor_dpvat

    custo_total = (
        depreciacao + combustivel + seguro + revisoes_concessionaria
        + manutencao_geral + pneus + impostos
    )

    return TCOBreakdown(
        vehicle_key=inputs.vehicle_key,
        depreciacao=depreciacao,
        combustivel=combustivel,
        seguro=seguro,
        revisoes_concessionaria=revisoes_concessionaria,
        manutencao_geral=manutencao_geral,
        pneus=pneus,
        impostos=impostos,
        custo_total=custo_total,
        meses_total=inputs.meses,
        km_total=km_total,
    )
