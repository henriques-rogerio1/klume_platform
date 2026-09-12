# Klume Volumes API — Guia de Integração

Guia pro time do K.LUME ONE consumir a API. Referência endpoint-a-endpoint
(parâmetros, tipos) também fica disponível automaticamente em `/docs`
(Swagger UI) assim que a API estiver no ar — este documento cobre o que o
Swagger não explica sozinho: como autenticar, exemplos reais, códigos de
erro, e os avisos de qualidade de dado que valem saber antes de integrar.

## Status atual

**Hospedagem: a definir.** A API roda hoje (`uvicorn api.main:app`), mas
ainda não está publicada num endereço acessível pelo parceiro — pendente de
aprovação/provisionamento do EC2. Este guia já reflete o contrato final;
só a `Base URL` abaixo muda quando isso acontecer.

**Endpoints disponíveis hoje**: `GET /v1/health`, `GET /v1/volumes`. Outros
endpoints do roadmap (ex: `/v1/tco`) ainda não existem — ver
`docs/api-contratos.md` pro contrato já definido pra quando existirem.

## Base URL

```
https://<a definir>/v1
```

## Autenticação

Toda rota (exceto `/v1/health`) exige uma API key própria, enviada no
header `X-API-Key`:

```
X-API-Key: <sua-chave>
```

A chave é provisionada por nós (`python -m api.provision_client`) — o
K.LUME ONE não se autoprovisiona. Chave ausente ou inválida → `401`.

## Limite de requisições

60 requisições por minuto por chave (janela deslizante). Acima disso →
`429`. Pensado como cinto de segurança contra bug/loop do lado do
consumidor, não como mecanismo de cobrança — o uso esperado é o backend do
K.LUME ONE agregando/cacheando do lado dele e chamando em ciclo, não a cada
interação de usuário final.

## Versionamento

Contrato vive sob `/v1/`. Mudança que quebra o formato de resposta vem como
`/v2/` novo, não como alteração silenciosa de `/v1/`.

---

## `GET /v1/health`

Confirma que a API está no ar e conectada ao banco. Sem autenticação.

**Resposta — `200`:**
```json
{"status": "ok"}
```

Se a conexão com o banco falhar, a rota retorna erro (não um `{"status": "ok"}` falso).

---

## `GET /v1/volumes`

Emplacamentos agregados — marca × tipo de venda × período. Cobre o Radar
Nacional de Emplacamentos.

### Parâmetros (query string)

| Parâmetro | Obrigatório | Tipo | Nota |
|---|---|---|---|
| `data_de` | sim | `YYYY-MM-DD` | Início do período (inclusive) |
| `data_a` | sim | `YYYY-MM-DD` | Fim do período (inclusive) — não pode ser anterior a `data_de` |
| `group_by` | sim | string, separado por vírgula | Só aceita `marca`, `tipo_venda`, ou os dois — qualquer outro valor retorna `400` |
| `marca` | não | string | Filtro exato (case-sensitive, mesmo valor de `gold.fato_volumes.marca`) |
| `limit` | não | inteiro | Default `5000`, teto `20000` |

### Exemplo de requisição

```bash
curl "https://<base-url>/v1/volumes?data_de=2025-01-01&data_a=2025-12-31&group_by=marca,tipo_venda" \
  -H "X-API-Key: <sua-chave>"
```

### Resposta — `200`

```json
{
  "data": [
    {"marca": "CHEVROLET", "tipo_venda": "Varejo", "quantidade": 284218, "quantidade_tipo_venda_conhecido": 284218},
    {"marca": "CHEVROLET", "tipo_venda": "Direta", "quantidade": 484767, "quantidade_tipo_venda_conhecido": 484767},
    {"marca": "CHEVROLET", "tipo_venda": null, "quantidade": 336123, "quantidade_tipo_venda_conhecido": null}
  ],
  "meta": {"rows": 3, "truncated": false, "generated_at": "2026-08-30T12:00:00Z"}
}
```

**As duas medidas nunca vêm separadas — sempre as duas juntas:**
- `quantidade`: total real, sempre soma pro denominador de "participação de mercado total".
- `quantidade_tipo_venda_conhecido`: `= quantidade` quando `tipo_venda` é `'Varejo'` ou `'Direta'`; `null` quando é desconhecido/não informado. Use esta pra calcular % Varejo-vs-Direta sem precisar excluir `null`/`'ND'` manualmente a cada consulta — dividir por essa soma, não pela `quantidade` total.

**Resultado vazio não é erro**: filtro válido sem nenhum dado retorna `200` com `"data": []`, `"meta": {"rows": 0, ...}`.

### Avisos de qualidade de dado — ler antes de montar telas com isso

- **`tipo_venda` só é confiável a partir de 2020.** Em 2016 o campo vem 100% `null` na fonte — não é buraco nosso, o campo simplesmente não existia naquele formato de arquivo.
- **Cobertura de período hoje é 2016, 2020 e 2025 — não uma série contínua.** Essas três safras foram escolhidas de propósito por representarem formatos diferentes que a DENATRAN já usou (validação de robustez do pipeline), não uma amostra aleatória nem os únicos anos que algum dia existirão. Um `data_de`/`data_a` que caia fora desse conjunto retorna `data: []`, não erro. Ano de 2016 especificamente também não tem município nem canal de venda preenchido (0% nos dois campos).

### Erros

| Situação | HTTP | Corpo |
|---|---|---|
| `X-API-Key` ausente/inválida | 401 | `{"detail": "..."}` |
| `group_by` vazio ou com valor fora de `marca`/`tipo_venda` | 400 | `{"detail": "group_by inválido: [...] -- permitido: [...]"}` |
| `data_a` anterior a `data_de` | 400 | `{"detail": "data_a não pode ser anterior a data_de"}` |
| Rate limit excedido | 429 | `{"detail": "Rate limit excedido -- tente de novo em instantes"}` |

---

## Próximos endpoints (roadmap, ainda não construídos)

`/v1/tco` e outros do roadmap do produto — contrato de erro/nulos e schema
de dado já definidos em `docs/api-contratos.md`, implementação pendente.
Este README é atualizado quando cada um for ao ar.
