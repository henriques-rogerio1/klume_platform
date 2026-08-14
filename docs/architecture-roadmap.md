# Architecture Roadmap — Findings & Agreed Next Steps

Captures the outcome of an architecture stress-test session (2026-08-14) covering
the current medallion pipeline (Bronze → Silver → Gold) and how it needs to evolve
to support the K.LUME ONE product vision (`docs/` partner deck: 6 modules —
Custo Estratégico Operacional, Identificação do Mercado de Locadoras, Incentivos
Comerciais, Emplacamentos Varejo e Vendas Diretas, Preço Transacionado, Itens de
Especificações).

Each item below is meant to become one or more tickets. Where a decision still has
an open unknown, that's called out explicitly rather than assumed.

Overall architecture rating from this review: **7/10** — the built pipeline
(Emplacamentos) has real production instincts (dedup-by-hash logged before the
risky step, non-fatal S3 handling, grain documented in the database itself, a
deliberate SCD-2 rejection rather than a cargo-culted one). What holds it back:
zero tests outside Silver until this review, no CI, two of the six roadmap
modules needing architecture that doesn't exist yet, and a single-developer bus
factor.

---

## A. Data-layer hardening (foundational, do first)

### A1. Replace the hardcoded Gold assertion with a real test suite

**Problem**: `gold/build_volumes.py` has one correctness check today —
`assert total == 10_658_607` — a hardcoded grand total that is guaranteed to
fail the next time *any* new file is uploaded, since the total legitimately
changes. It's wired to break on success, not on failure.

**Decision**: add a pytest suite for Gold mirroring the pattern already used in
`silver/tests/`, with these five tests:

1. **Volume conservation** — `SUM(quantidade)` in `gold.fato_volumes` equals
   `SUM(quantidade)` in `silver.veiculos`. Replaces the hardcoded number with a
   relative invariant that survives new data.
2. **No row loss/duplication in the fact join** — formalizes the existing
   `n_pre == n_base` assert as a real test.
3. **Build determinism** — run `build_volumes.py` twice, diff every dimension
   table with `EXCEPT`, assert the diff is empty. This is the methodology
   `docs/ARQUITETURA.md` already prescribes; it's just never been applied
   outside Silver.
4. **Surrogate key uniqueness** on each dimension table's key column.
5. **Referential completeness** — every `veiculo_key` / `veiculo_atual_key` /
   `data_key` in `fato_volumes_base` resolves in its dimension. This catches a
   class of bug the row-count-only check can mask: a join could drop N rows
   here and gain N elsewhere and the count assert wouldn't notice.

**Reasoning**: Gold is what actually reaches users (the app, Vanna, BI tools) —
today it's the *least* tested layer even though it's the most user-visible one.
Cheap to add now; expensive to retrofit once more product domains multiply the
number of fact tables to trust.

### A2. Lock down Vanna's database access

**Problem**: Vanna (via Claude) generates SQL and executes it directly against
MotherDuck with no query validation, allowlist, or role separation today.

**Decision**: two MotherDuck tokens/roles —
- a **write** role used only by the upload pipeline (`app/pages/1_Upload_Dados.py`,
  `gold/build_volumes.py`),
- a **read-only** role used only by the Vanna connection, with no DDL/DELETE
  privileges at the database level.

**Reasoning**: even with a trusted internal audience (not customer-facing),
DB-level enforcement removes an entire class of risk regardless of what the LLM
ever outputs — cheaper and more robust than trying to parse/validate generated
SQL at the app level.

### A3. Wire the test suite into CI

**Problem**: no CI exists at all — not even running the current `silver/tests/`
suite on push.

**Decision**: add CI (GitHub Actions or equivalent) that runs `pytest` across
`silver/` and the new `gold/` suite (A1) on every push.

**Reasoning**: a test suite nobody runs automatically only catches bugs the
one developer remembers to run it against.

---

## B. Near-term product modules (cheapest, closest to shippable)

### B1. Locadoras module — CNPJ join + CNAE classification

**Problem/Opportunity**: `fato_volumes_base.cnpj_basico_faturado` already
exists, and Receita Federal CNPJ reference data is already sitting in Bronze
(`staging.bronze_master_cnpj`, 40.4M rows; `staging.bronze_master_estabelecimentos`,
63.8M rows, with CNAE) — ingested but never joined into Silver/Gold
(`docs/ARQUITETURA.md` lines 26-29). This is not a new data source; it's a join
against data already on hand.

**Decision**: build a `dim_empresa`-style enrichment (or a dedicated view) that
joins `cnpj_basico_faturado` against the Bronze CNPJ tables, and classify which
CNPJs count as locadoras via CNAE code.

**Reasoning**: near-zero new ingestion cost, already produces useful analytics
per this session's discussion, and validates "CNPJ as an identity key" before
it's needed elsewhere (e.g. TCO's B2B/B2C segmentation).

**Open item**: confirm which CNAE code(s) define "locadora" for classification
purposes — a business definition, not a technical one.

### B2. FIPE integration

**Problem/Opportunity**: two roadmap modules (Custo Estratégico Operacional's
depreciation calc, Preço Transacionado's reference pricing) need FIPE data.
FIPE ingestion exists as a separate, already-working pipeline
(`fipe_api` repo, orchestrated by Mage AI — handles calling and testing the FIPE
API) but has never populated MotherDuck (`docs/ARQUITETURA.md` lines 30-33,
"deliberately out of scope until now").

**Decision**:
- Do **not** rebuild the FIPE-calling logic — Mage AI already solves the hard
  part (API calls, testing). Bridge its output into `staging.bronze_fipe` in
  MotherDuck instead of reimplementing ingestion.
- Join FIPE data onto the vehicle dimension via a **compound/tiered match**,
  not a strict equality join: marca+modelo is a reliable match key, versão is
  best-effort (FIPE doesn't cover every DENATRAN trim variant).
- Extend the existing `match_tier` column (already present in
  `fato_volumes_base`, already documented as anticipating exactly this) to:
  - `1` = FIPE code came directly from the DENATRAN source row (existing
    semantics)
  - `2` = matched via marca+modelo+versão
  - `3` = matched via marca+modelo only, versão unresolved
  - `NULL` = no match found
- Keep FIPE price/code nullable downstream everywhere rather than dropping
  unmatched rows — "no match" is expected (e.g. brand-new models), not an
  error state.

**Reasoning**: `match_tier`'s existing comment — *"Não existe preço FIPE
disponível ainda nesta versão"* — shows this was already a deliberately left
seam in the schema, not new scope. Reusing Mage AI's output avoids duplicating
already-solved API integration work.

**Open item — verify before trusting the join**: "marca+modelo is a unique
nationwide key" is true *within FIPE's own catalog*, but unverified as a
cross-source match against DENATRAN's independently-sourced text. The exact
same class of problem already hit DENATRAN-internally (combustível/tipo_veiculo
spelling drifting by safra — "Moto" vs "MOTOCICLETA"). Before committing to a
simple join:
- Pull FIPE's distinct marca/modelo values and diff against DENATRAN's.
- If they don't align cleanly, budget for a normalization/mapping layer in the
  same spirit as `silver/vehicle_key/canonical.py`, rather than assuming a
  clean join.

---

## C. Structural changes needed before the product surface grows

### C1. Split `build_volumes.py` into one build per fact table

**Problem**: today's Gold build is one script that rebuilds *everything* on
every upload. That's fine with one fact table. Once Preço Transacionado,
Especificações, etc. exist as separate fact tables, an unrelated product's
monthly file would trigger a full rebuild of tables it has nothing to do with.

**Decision**: refactor into one build function per fact table, sharing
conformed dimensions (`dim_veiculo_observado`, `dim_veiculo_atual`, `dim_geografia`,
`dim_data`) via `vehicle_key` — a Kimball bus architecture. Do this **before**
the second product domain lands, not after.

**Reasoning**: cheap to do now with one fact table; retrofitting after a second
and third domain exist is real rework. Keep full-rebuild-per-domain as the
strategy as long as it stays fast (add a runtime log line); only add
incremental/partitioned builds if a specific domain's rebuild time actually
becomes a problem.

### C2. Architecture shapes for the remaining roadmap modules

Not being built yet — recorded here so the shape is agreed before implementation
starts, rather than discovered mid-build.

- **Preço Transacionado**: new fact table, transaction grain. Third-party
  licensed data (Nota Fiscal values) — will need its own vehicle-key mapping
  since it won't arrive DENATRAN-shaped (same class of problem as FIPE
  matching in B2).
- **Itens de Especificações**: new dimension, vehicle-version grain — but the
  first data source with a **genuine effective-dated history**
  ("identificando mudanças entre versões, facelifts e novas gerações"). Unlike
  `dim_veiculo_atual` (deliberately Type 1, no true effective date available),
  this is a real SCD Type 2 candidate — don't reuse the Type 1 pattern here by
  default.
- **Custo Estratégico Operacional (TCO)**: not a file-ingest domain at all — a
  **calculation engine** over rate-table inputs (fuel price, insurance
  premium, maintenance cost, tax tables) by segment/region/period. Needs its
  own architecture, not the existing upload-and-normalize pattern.
- **Incentivos Comerciais**: campaign grain (fabricante × vigência ×
  abrangência), not vehicle-instance grain. Sourced from unstructured campaign
  documents via LLM extraction plus a human audit step. Needs a
  document-ingestion-and-review pipeline — the most architecturally novel of
  the six modules, nothing like the existing Excel-upload pattern.

---

## D. Deferred, but tracked with a revisit trigger

### D1. Auth / leaving Streamlit Community Cloud free tier

**Decision**: stay on the free tier without auth for now — genuinely
single/few-user prototype stage, and customer data intake is human-mediated
(email → manual upload), so nobody external touches the app regardless of auth
state.

**Revisit trigger**: before anyone outside the team needs to log in directly —
don't let hosting migration block product work until that's imminent.

### D2. Automating customer data intake

**Decision**: keep the current pattern (customer emails a file → a human saves
and uploads it via the existing Upload Dados-style page, one normalizer per
domain) rather than building automated inbox parsing now.

**Revisit trigger**: when manual intake volume/frequency itself becomes the
bottleneck — not before.
