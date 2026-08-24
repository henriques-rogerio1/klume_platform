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

### B1. Locadoras module — CNPJ join + CNAE classification — **Done (2026-08-20)**

**Problem/Opportunity**: `fato_volumes_base.cnpj_basico_faturado` already
exists, and Receita Federal CNPJ reference data is already sitting in Bronze
(`staging.bronze_master_cnpj`, 40.4M rows; `staging.bronze_master_estabelecimentos`,
63.8M rows, with CNAE) — ingested but never joined into Silver/Gold
(`docs/ARQUITETURA.md` lines 26-29). This is not a new data source; it's a join
against data already on hand.

**Shipped**: `gold.dim_empresa` (`gold/build_dim_empresa.py`) — scoped to the
~8,455 CNPJs actually observed in `silver.veiculos`, sourced from
`staging.bronze_master_cnpj` **and** a second, previously-undocumented reference
table `main.CNPJ_empresas_final` found during this work (zero row overlap between
the two, confirmed by direct query — together they cover 99.98% of relevant CNPJs
vs. ~75% from either alone). CNAE from `staging.bronze_master_estabelecimentos`
(matriz row, 96.6% coverage). Wired into `gold.fato_volumes_base`/`gold.fato_volumes`
additively (`empresa_key`, `razao_social`, `categoria_empresa`). Full design in
`docs/ARQUITETURA.md`'s "Demais dimensões" section.

**CNAE boundary — resolved**: `categoria_empresa` = `'Concessionária/Comércio de
Veículos'` for CNAE `45xx` (54% of CNPJ-invoiced volume — dealers invoicing
retail sales dominate, not fleet/rental companies), `'Locadora'` for CNAE `771x`
(aluguel de meios de transporte — deliberately narrower than `77xx`, which also
sweeps in unrelated equipment-rental CNAE groups), else `'Outro'`. Confirmed
2026-08-20; **not yet propagated** to the existing `CNAE LIKE '7711%'` assumption
already hardcoded in `app/training_data.py`'s Vanna example — that's a deliberate,
separate follow-up, gated on seeing this classification hold up in production use.

**Deferred, tracked separately**: refresh of `dim_empresa` is manual/decoupled
from the automatic upload pipeline (scanning ~104M raw CNPJ rows on every small
upload wasn't worth it); the 3 raw CNPJ reference tables stay resident in
MotherDuck to support that refresh — archiving them to S3 (same pattern as
DENATRAN bronze) is a real, still-open storage question, not resolved here.

### B2. FIPE integration — **Done (2026-08-24)**

**Problem/Opportunity**: two roadmap modules (Custo Estratégico Operacional's
depreciation calc, Preço Transacionado's reference pricing) need FIPE data.
`match_tier` already existed in `fato_volumes_base`, anticipating this, but was
never completed — `staging.raw_json_fipe` didn't exist, and nothing in Silver
reached Gold.

**Shipped**: `staging.raw_json_fipe` populated from the already-extracted S3
CSVs (`s3://klume-volumes-s3-platform/Fipe_Csv/`, ~546K rows across ~11 months
of history) — not from the `fipe_api` repo's row-at-a-time MotherDuck script,
which would have taken hours; a bulk loader was written instead.
`silver/normalizers/fipe.py` → `silver.fipe_precos` (grain = `codigo_fipe ×
year_code × reference_month`, full history kept, not collapsed to latest —
future TCO/Preço Transacionado modules need trajectories, not a snapshot; see
retention TODO below). `vehicle_key` computed via a new
`canonical_str_fipe_sql` macro (`silver/vehicle_key/canonical_sql.py`) — same
hash domain as DENATRAN's `canonical_str_denatran_sql`, proven identical for
matching vehicles by `test_canonical_sql_parity.py`.

**Match tiers — activated, not redefined** (the original plan above proposed
redefining tier 2/3 as marca+modelo+versão / marca+modelo; rejected, since that
would have changed the meaning of the 2.86M rows already marked tier 3):
- `1` = FIPE code came directly from the DENATRAN source row — unchanged,
  lives in `fato_volumes_base.fipe`/`.preco` (confirmed non-fragmenting:
  0 groups with >1 distinct value).
- `2` (new) = hash-canonical match against `silver.fipe_precos` via
  `canonical_str_fipe_sql`, with a small hand-curated marca alias
  (`silver/vehicle_key/marca_alias_fipe.py` — GM/Chevrolet, VW/Volkswagen,
  M Benz/Mercedes Benz, Chery/Caoa Chery, Kia/Kia Motors; not fuzzy matching).
  Never touches the real DENATRAN `vehicle_key`.
- `3` = the pre-existing manual crosswalk (`silver.mapping_table`), with two
  real bugs fixed: it was discarding the matched FIPE code (`SELECT *
  EXCLUDE(...)`, kept only the boolean flag) and treating annotation strings
  (`'NE'`, `'A'`, `'ND'`, `'ver'`) as valid matches. Fixing both dropped
  54,771 false-positive tier-3 rows (2,857,766 → 2,802,995), verified via a
  before/after row-count reconciliation.
- Tier 2/3 are vehicle-grain properties → live in `gold.dim_veiculo_atual`
  (`codigo_fipe`, `preco_fipe`, `match_tier_fipe`, `data_referencia_fipe`),
  built in the same `CREATE OR REPLACE` as the rest of the table (not a
  decoupled refresh like `dim_empresa` — `silver.fipe_precos` is small enough
  to rescan every automatic Gold rebuild, and a separate pass would get wiped
  by the next one anyway). Tier 2 always takes precedence over tier 3 when
  both match.

**Marca alignment — verified, not assumed**: FIPE's ~218 distinct brand names
vs. DENATRAN's ~1,354 (duplicate spellings + a long tail of trailers/
motorcycles/heavy equipment) do NOT align cleanly on raw text — confirmed by
anti-join in both directions before building the join, which is what produced
the marca alias table above. 146 marcas now align.

**Known limitation — tier 2's real yield is low, and it's not a text-
normalization problem**: after shipping, checking the actual
`match_tier_fipe` distribution showed tier 2 only covers 457 of ~30,272
`vehicle_key`s (892K of 10.66M volume, ~8%) — and major brands (Honda, VW,
Fiat, Ford, Toyota, Hyundai, Volvo, Nissan) show **zero** tier 2 *or* tier 3
match despite FIPE covering them well. Root cause, confirmed by direct
comparison (e.g. FIAT TORO 2017): DENATRAN's `versao` field for cars doesn't
carry engine displacement at all (FIPE's primary distinguishing spec), and
abbreviations don't align token-for-token — DENATRAN's `"TORO FREEDOM AT9"`
vs. FIPE's `"Toro Freedom 2.0 16V 4x2 TB Diesel Mec."`. Closing this gap would
need a hand-curated abbreviation-translation table per brand (`AT`→`Aut.`,
`D`→`Diesel`, `T270`→turbo code, etc.) with real risk of silently assigning
the wrong trim's price — **decided not to build this**: tier 3's human-curated
crosswalk already solves exactly this class of problem better (44% of volume
vs. tier 2's 8%), so a fragile automated trim-matcher would be competing with,
not complementing, a better-performing existing solution. Tier 2 stays as
implemented — an exact hash match that fires reliably for simpler cases
(e.g. motorcycles, where naming conventions align better) and costs nothing
when it doesn't fire (`NULL`, not a wrong answer). ~53% of volume has some
FIPE price (tier 1+2+3 combined) as of 2026-08-24; the remaining ~47% is
expected to shrink over time as tier 3's manual crosswalk grows, not via
further tier 2 automation.

**Deferred, tracked separately**: `silver.fipe_precos` keeps unbounded full
price history — a retention limit (e.g. only last N years) will eventually be
needed as more months accumulate from S3, but the limit itself is a business
decision not yet made; not implemented per explicit instruction. No
`gold.dim_fipe` yet — no consumer for price trajectory in Gold until TCO/Preço
Transacionado are built.

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
