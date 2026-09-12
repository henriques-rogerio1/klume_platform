# Contratos da API — resposta às 3 perguntas do parceiro

Documento de referência técnica pro time do K.LUME ONE escrever endpoints/
integração sem ambiguidade. Resolve os 3 pontos levantados sobre o
documento "Klume Data Platform — Visão Técnica".

---

## 1. Contrato de erro/nulos da API

Dois problemas diferentes, duas respostas diferentes — não confundir:

### 1a. Erro de requisição (já implementado, `api/main.py`)

| Situação | HTTP | Corpo |
|---|---|---|
| `X-API-Key` ausente/inválida | 401 | `{"detail": "..."}` |
| `group_by` fora do allowlist, vazio, ou `data_a < data_de` | 400 | `{"detail": "group_by inválido: [...] -- permitido: [...]"}` |
| Rate limit excedido | 429 | `{"detail": "Rate limit excedido -- tente de novo em instantes"}` |
| Falha ao conectar no MotherDuck (`/v1/health`) | 503 | — |

Contrato padrão FastAPI/`HTTPException`, sem envelope customizado.

### 1b. Dado parcial dentro de um registro válido (a pergunta real)

**Regra**: nunca omitir o registro por causa de um campo ausente. Omissão
parece "esse veículo não existe" — estritamente pior do que "existe, mas
este campo específico é desconhecido". Sempre HTTP 200, sempre o registro
presente, com o campo faltante em `null` **mais um campo-irmão de status**
explicando o porquê — mesmo padrão já usado em `gold.dim_veiculo_atual`
(`match_tier_fipe`: `2` = match exato, `3` = crosswalk manual, `NULL` =
nenhum dos dois) e em `gold.fato_volumes_base.empresa_key` (`-1`/`-2` como
sentinelas, nunca `NULL` silencioso).

Pro exemplo do parceiro (TCO sem FIPE — endpoint ainda não construído, mas o
contrato vale desde já pra esse e qualquer campo tiered futuro):

```json
{
  "vehicle_key": 123456789,
  "preco_tabela": 100000,
  "fipe": null,
  "fipe_status": "UNMATCHED"
}
```

`fipe_status` é uma tradução amigável, feita na camada da API
(`api/schemas.py`), do `match_tier_fipe` interno do Gold — não expor o
código `2`/`3`/`NULL` cru pro consumidor sem dicionário:

| `match_tier_fipe` (Gold) | `fipe_status` (API) | Significado |
|---|---|---|
| `2` | `"MATCHED_EXACT"` | Casamento automático por hash canônico contra o catálogo FIPE |
| `3` | `"MATCHED_MANUAL"` | Achado só via crosswalk curado por pessoa |
| `NULL` | `"UNMATCHED"` | Nenhum dos dois — sem preço FIPE disponível pra esse veículo hoje |

**Resultado vazio não é erro.** Uma consulta válida (filtros corretos) que
não bate com nenhum dado retorna `200` com `"data": []`, `"meta": {"rows":
0, ...}` — nunca `404`. `404` fica reservado pra quando o identificador em
si não existe (ex: pedir um `vehicle_key` que não está em nenhuma dimensão
Gold) — caso diferente de "existe, mas um campo está vazio".

---

## 2. Dicionário de dados — schema Gold (consultado ao vivo no MotherDuck, não de memória)

Ler diretamente de `gold.fato_volumes` (view de compatibilidade) cobre a
maioria dos casos de uso — é o que `api/repository.py::query_volumes` já
consulta hoje, junta as 4 dimensões + a fato numa única linha plana.
Recorrer às tabelas de base só quando `fato_volumes` não tiver a coluna
necessária.

### `gold.fato_volumes` (VIEW — recomendada como leitura padrão da API)

| Coluna | Tipo | Nota |
|---|---|---|
| `data_emplacamento` | DATE | |
| `marca`, `modelo`, `versao` | VARCHAR | |
| `segmentacao_atualizada`, `segmentacao_original` | VARCHAR | Como estava na venda — não é a classificação atual |
| `combustivel_normalizado` | VARCHAR | |
| `cor_predominante` | VARCHAR | |
| `tipo_venda` | VARCHAR | `'Varejo'`/`'Direta'`/`'ND'`/`NULL` — só confiável a partir de 2020 (2016 é 100% `NULL`) |
| `municipio_emplacamento`, `estado_emplacamento` | VARCHAR | |
| `tipo_veiculo_principal` | VARCHAR | |
| `cnpj_basico_faturado` | VARCHAR | Só preenchido quando a venda foi faturada por CNPJ |
| `match_tier` | INTEGER | Tier do FIPE embutido na própria linha DENATRAN (tier 1) — não confundir com `match_tier_fipe` abaixo |
| `segmentacao_klume` | VARCHAR | Classificação **atual**, Type 1, independente de quando o veículo foi vendido |
| `razao_social`, `categoria_empresa` | VARCHAR | De `gold.dim_empresa` |
| `fipe`, `preco` | VARCHAR / DECIMAL(12,2) | Tier 1 — código/preço FIPE já vinham na linha de origem |
| `codigo_fipe`, `preco_fipe`, `match_tier_fipe`, `data_referencia_fipe` | VARCHAR / DECIMAL(12,2) / INTEGER / DATE | Tier 2/3 — ver seção 1b acima pro contrato de status |
| `quantidade` | HUGEINT | **Medida aditiva** — sempre `SUM()`, nunca `COUNT(*)` |
| `quantidade_tipo_venda_conhecido` | HUGEINT | `= quantidade` quando `tipo_venda IN ('Varejo','Direta')`, senão `NULL` — usar pra % varejo/direta sem excluir `ND`/`NULL` manualmente a cada consulta |

Grão: uma linha por combinação única de `data_key × veiculo_key ×
veiculo_atual_key × codigo_municipio × cor_predominante × tipo_venda ×
match_tier × cnpj_basico_faturado`, já agregada — **não existe grão de
venda individual**.

Views auxiliares, mesmo schema, sem duplicar dado: `gold.fato_volumes_ano_atual`
(filtra `CURRENT_DATE`), `gold.fato_volumes_mes_atual`.

### `gold.dim_veiculo_atual` (Type 1 — "melhor entendimento atual" por veículo)

| Coluna | Tipo | Nota |
|---|---|---|
| `veiculo_atual_key` | BIGINT | PK surrogate |
| `vehicle_key` | UBIGINT | Chave de negócio (hash) |
| `marca`, `modelo`, `versao`, `ano_modelo`, `combustivel_normalizado` | — | |
| `segmentacao_klume`, `segmentacao_original_klume`, `tipo_veiculo_klume` | VARCHAR | |
| `codigo_fipe` | VARCHAR | `NULL` se nenhum tier achou |
| `preco_fipe` | DECIMAL(12,2) | Só preenchido quando `match_tier_fipe = 2` |
| `match_tier_fipe` | INTEGER | `2`/`3`/`NULL` — ver contrato seção 1b |
| `data_referencia_fipe` | DATE | Mês do preço — conferir antes de assumir "preço atual" |

### `gold.dim_empresa` (CNPJ faturado)

`empresa_key` (PK, `-1` = venda não faturada por CNPJ, `-2` = CNPJ sem
match em nenhuma fonte), `cnpj_basico`, `razao_social`, `nome_fantasia`,
`categoria_empresa` (`'Concessionária/Comércio de Veículos'` /
`'Locadora'` / `'Outro'`), `tem_estabelecimento` (BOOLEAN).

### `gold.dim_geografia` / `gold.dim_data`

`dim_geografia`: `codigo_municipio` (PK, código IBGE, `-1` = sem código
informado ~23% dos casos), `municipio`, `estado`.
`dim_data`: `data_key` (PK, `YYYYMMDD` inteiro), `data`, `ano`, `mes`,
`trimestre`, `dia_semana`, `fim_de_semana`, `nome_mes`.

---

## 3. Estratégia de cache (cold start do MotherDuck)

**Confirmado, não hipotético**: o Duckling do MotherDuck sobe sob demanda e
suspende quando ocioso — a primeira query depois de um período parado tem
latência de wake real. **Não medido ainda** pra esta conta/tier
especificamente — antes de construir a camada de cache, vale medir o tempo
de wake de verdade (`/v1/health` cronometrado depois de ociosidade
conhecida) pra saber se o problema justifica cache, ou se um simples
keep-alive (`/v1/health` a cada N minutos) já resolve sozinho.

**Recomendação: cache em memória no processo do FastAPI, não Redis.**
Mesmo padrão já decidido pro rate limiter (`api/rate_limit.py`: dict +
`threading.Lock`, "suficiente pra 1 processo/1 box") e pela mesma razão
estrutural: hoje é uma instância EC2 única sob `systemd`, sem necessidade
de escalar horizontalmente, e o próprio backend do K.LUME ONE já
agrega/cacheia do lado dele antes de chamar essa API (tráfego real é
baixo e batchy, não por interação de usuário final). Redis adiciona um
serviço a mais pra um operador solo manter sem resolver nenhum problema
que a instância única já não resolva.

Desenho concreto: dict `{(endpoint, filtros_normalizados): (resultado,
computado_em)}` com TTL curto (10-15 min é um ponto de partida razoável,
ajustar depois de medir), escopado só aos agregados do ecrã inicial do
K.LUME ONE (não virar um cache genérico de qualquer consulta). Invalidação
por tempo, não por evento — hoje não existe um sinal de "Gold acabou de
rebuildar" pra invalidar sob demanda (mesma lacuna já registrada pro
`/v1/health` no plano da API), então TTL curto é a opção honesta até esse
sinal existir.

**Gatilho de revisão pra Redis**: se o K.LUME ONE algum dia precisar de
múltiplas instâncias da API atrás de um load balancer, cache em memória
por processo deixa de ser coerente entre instâncias — nesse momento, sim,
Redis (ou equivalente) é a escolha certa. Não antes disso.
