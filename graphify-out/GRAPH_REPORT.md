# Graph Report - klume_platform  (2026-08-26)

## Corpus Check
- 146 files · ~61,219 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 593 nodes · 910 edges · 44 communities (39 shown, 5 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 79 edges (avg confidence: 0.75)
- Token cost: 0 input · 497,435 output

## Community Hubs (Navigation)
- Pipeline Entry Points & App
- Volumes API Service
- Ticket & Triage Skills
- Grilling & Prototyping Skills
- TDD & Agent Brief Concepts
- Canonical Key Logic & Tests
- DENATRAN Normalizer & Tests
- FIPE Normalizer & Utils
- Writing & Wizard Skills
- Wizard Template Commands
- FIPE Integration Docs
- Project Dependencies
- Bug Diagnosis & Domain Modeling
- Teach Skill Formats
- CNPJ Enrichment Docs
- Issue Tracker Setup
- Gold Star Schema Docs
- Fragment & Shape Writing Skills
- Medallion Architecture Overview
- App Layer Docs
- Upload Pipeline Docs
- Gold Layer Design Docs
- Silver Layer Docs
- Shoehorn Migration Skill
- Pre-commit Setup Skill
- HITL Loop Script
- Git Guardrails Skill
- Implement Skill
- Research & Merge Conflicts Skills
- Wait-What Skill
- Klume Brand Assets
- Bronze-to-S3 Upload Script
- Git Guardrails Script
- Grill-Me Config
- Query Log Docs
- Codebase Design Interface

## God Nodes (most connected - your core abstractions)
1. `get_connection()` - 29 edges
2. `normalize_denatran()` - 23 edges
3. `Root Requirements (dev/full)` - 16 edges
4. `canonical_str()` - 15 edges
5. `VolumesFilters` - 14 edges
6. `main()` - 14 edges
7. `_parquet()` - 14 edges
8. `RateLimiter` - 13 edges
9. `gold/build_volumes.py` - 13 edges
10. `query_volumes()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `create_shared_connection()` --calls--> `get_connection()`  [EXTRACTED]
  api/db.py → silver/db/connection.py
- `provision()` --calls--> `get_connection()`  [EXTRACTED]
  api/provision_client.py → silver/db/connection.py
- `Scaffold Exercises Skill` --semantically_similar_to--> `Setup TS Deep Modules Skill`  [INFERRED] [semantically similar]
  .agents/skills/scaffold-exercises/SKILL.md → .agents/skills/setup-ts-deep-modules/SKILL.md
- `Phase 3 - Hypothesise` --semantically_similar_to--> `Domain Modeling Skill`  [INFERRED] [semantically similar]
  .agents/skills/diagnosing-bugs/SKILL.md → .agents/skills/domain-modeling/SKILL.md
- `Grill Me Skill` --semantically_similar_to--> `Domain Modeling Skill`  [INFERRED] [semantically similar]
  .agents/skills/grill-me/SKILL.md → .agents/skills/domain-modeling/SKILL.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Grilling Interview Discipline Reused Across Skills** — agents_skills_grilling_skill, agents_skills_grill_with_docs_skill, agents_skills_loop_me_skill, agents_skills_improve_codebase_architecture_skill [EXTRACTED 1.00]
- **Prototype Capture-to-Throwaway-Branch Workflow** — agents_skills_prototype_skill, agents_skills_prototype_logic, agents_skills_prototype_ui [EXTRACTED 1.00]
- **openai.yaml Agent Interface Config Pattern** — agents_skills_grill_me_agents_openai, agents_skills_grill_with_docs_agents_openai, agents_skills_grilling_agents_openai, agents_skills_handoff_agents_openai, agents_skills_implement_agents_openai, agents_skills_improve_codebase_architecture_agents_openai, agents_skills_loop_me_agents_openai, agents_skills_migrate_to_shoehorn_agents_openai, agents_skills_prototype_agents_openai [INFERRED 0.85]
- **Issue Tracker Backend Implementations (GitHub/GitLab/Local)** — agents_skills_setup_matt_pocock_skills_issue_tracker_github, agents_skills_setup_matt_pocock_skills_issue_tracker_gitlab, agents_skills_setup_matt_pocock_skills_issue_tracker_local [INFERRED 0.85]
- **Skills Consuming Codebase-Design Vocabulary** — agents_skills_setup_ts_deep_modules_skill, agents_skills_tdd_skill, concept_codebase_design_skill [INFERRED 0.80]
- **Setup Matt Pocock Skills Generated Config Files** — agents_skills_setup_matt_pocock_skills_skill, agents_skills_setup_matt_pocock_skills_domain, agents_skills_setup_matt_pocock_skills_issue_tracker_github, agents_skills_setup_matt_pocock_skills_triage_labels [EXTRACTED 1.00]
- **Ready-for-Agent Triage Label Convention** — agents_skills_triage_skill_ready_for_agent_state, agents_skills_triage_skill, agents_skills_to_spec_skill, agents_skills_to_tickets_skill [EXTRACTED 1.00]
- **Grill-to-Extract-Missing-Context Pattern** — grilling_skill, domain_modeling_skill, agents_skills_triage_skill, agents_skills_wayfinder_skill [EXTRACTED 1.00]
- **Teaching Workspace State Files** — agents_skills_teach_skill, agents_skills_teach_mission_format_mission_md, agents_skills_teach_learning_record_format_learning_record, agents_skills_teach_resources_format_resources_md, agents_skills_teach_glossary_format_glossary_md [EXTRACTED 1.00]
- **Domain Modeling Skill Artifact Set** — agents_skills_domain_modeling_skill_domain_modeling, agents_skills_domain_modeling_context_format_template, agents_skills_domain_modeling_adr_format_template [EXTRACTED 1.00]
- **Diagnosing Bugs Six-Phase Discipline** — agents_skills_diagnosing_bugs_skill_diagnosing_bugs, agents_skills_diagnosing_bugs_skill_redact_phase, agents_skills_diagnosing_bugs_skill_phase1_build_feedback_loop, agents_skills_diagnosing_bugs_skill_phase2_reproduce_minimise, agents_skills_diagnosing_bugs_skill_phase3_hypothesise, agents_skills_diagnosing_bugs_skill_phase4_instrument, agents_skills_diagnosing_bugs_skill_phase5_fix_regression_test, agents_skills_diagnosing_bugs_skill_phase6_cleanup_postmortem [EXTRACTED 1.00]
- **Git Guardrails Hook Installation** — agents_skills_git_guardrails_claude_code_skill_git_guardrails_claude_code, agents_skills_git_guardrails_claude_code_scripts_block_dangerous_git_script, agents_skills_git_guardrails_claude_code_skill_settings_json [EXTRACTED 1.00]
- **Shared Skill Interface Config Pattern (openai.yaml)** — agents_skills_wayfinder_agents_openai_config, agents_skills_wizard_agents_openai_config, agents_skills_writing_beats_agents_openai_config, agents_skills_writing_for_agents_agents_openai_config [INFERRED 0.80]
- **Writing-for-Agents Skill Documentation System** — agents_skills_writing_for_agents_skill_doc, agents_skills_writing_for_agents_skill_mechanics_doc, agents_skills_writing_for_agents_skill_mechanics_router_skill, agents_skills_writing_for_agents_skill_mechanics_invocation [EXTRACTED 1.00]
- **Wizard Generation System** — agents_skills_wizard_skill_doc, agents_skills_wizard_template_sh, agents_skills_wizard_agents_openai_config [INFERRED 0.80]
- **FIPE Match Tier System (Tiers 1-3)** — docs_arquitetura_match_tier, docs_arquitetura_canonical_str_fipe_sql, docs_arquitetura_mapping_table, docs_arquitetura_marca_alias_fipe_py [EXTRACTED 1.00]
- **Dual Vehicle Dimension Design (Type 1 vs Historical)** — docs_arquitetura_dim_veiculo_observado, docs_arquitetura_dim_veiculo_atual, docs_arquitetura_scd_type2_rejected, docs_arquitetura_vehicle_key [EXTRACTED 1.00]
- **dim_empresa CNPJ Source Reconciliation** — docs_arquitetura_staging_bronze_master_cnpj, docs_arquitetura_main_cnpj_empresas_final, docs_arquitetura_staging_bronze_master_estabelecimentos, docs_arquitetura_dim_empresa [EXTRACTED 1.00]

## Communities (44 total, 5 thin omitted)

### Community 0 - "Pipeline Entry Points & App"
Cohesion: 0.05
Nodes (49): Anthropic_Chat, provision(), Provisiona uma linha em app.api_clients -- não é fluxo de self-service, uso…, Página operacional (não é pra vendedor usar) — upload de arquivo XLSX novo de…, _ensure_table(), log_query(), Histórico de perguntas/SQL por usuário — grava no MotherDuck (schema `app`,…, Registra uma pergunta/consulta. Nunca levanta exceção — logging não pode… (+41 more)

### Community 1 - "Volumes API Service"
Cohesion: 0.06
Nodes (49): _is_valid_key(), Verifica API key (header X-API-Key) contra app.api_clients -- consulta a cada…, verify_api_key(), create_shared_connection(), get_cursor(), DuckDBPyConnection, Conexão MotherDuck compartilhada da API -- uma só, criada no lifespan do…, enforce_rate_limit() (+41 more)

### Community 2 - "Ticket & Triage Skills"
Cohesion: 0.05
Nodes (50): To Questionnaire — OpenAI Agent Config, To Questionnaire Skill, Grill the Send, Not the Subject, Discovery Questionnaire Document, To Spec — OpenAI Agent Config, To Spec Skill, Testing Seams, Spec Template (+42 more)

### Community 3 - "Grilling & Prototyping Skills"
Cohesion: 0.08
Nodes (34): Grill with Docs OpenAI Agent Config, Grill with Docs Skill, Domain Modeling Skill, Glossary Docs, Grilling OpenAI Agent Config, Grilling Skill, Design Tree, Frontier (+26 more)

### Community 4 - "TDD & Agent Brief Concepts"
Cohesion: 0.06
Nodes (33): Scaffold Exercises OpenAI Interface Config, Scaffold Exercises Skill, Domain Docs Convention, Setup TS Deep Modules OpenAI Interface Config, Setup TS Deep Modules Skill, TDD OpenAI Interface Config, TDD Mocking Guidelines, TDD Skill (+25 more)

### Community 5 - "Canonical Key Logic & Tests"
Cohesion: 0.11
Nodes (30): Testes de contrato para canonical.py. Estes testes são o contrato da plataforma…, parametrize, Prova de que canonical_str_denatran_sql() (macro SQL, roda no MotherDuck)…, test_fipe_sql_macro_matches_python(), test_sql_macro_matches_python_canonical_str(), test_sql_macro_matches_python_for_known_tricky_cases(), test_ano_modelo_as_int_or_str(), test_combustivel_2016_accented_padded_maps_to_G() (+22 more)

### Community 6 - "DENATRAN Normalizer & Tests"
Cohesion: 0.17
Nodes (23): _add_canonical_and_match_tier(), normalize_denatran(), Adapter de normalização para a fonte DENATRAN (emplacamentos). Lê o Bronze —…, Roda o pipeline Bronze -> Silver completo pra uma única fonte DENATRAN (nome de…, _split_by_year(), _type_cast(), main(), Runner manual (não é teste automatizado do pytest) que valida o pipeline Silver… (+15 more)

### Community 7 - "FIPE Normalizer & Utils"
Cohesion: 0.13
Nodes (21): normalize_fipe(), Adapter de normalização pra fonte FIPE (staging.raw_json_fipe). Lê o Bronze…, Roda o pipeline Bronze -> Silver completo pra FIPE. Retorna o nome da view…, _register_fipe_parsing_macros(), main(), Runner manual (não é teste automatizado do pytest) que valida o pipeline Silver…, parametrize, test_all_real_headers_produce_unique_names() (+13 more)

### Community 8 - "Writing & Wizard Skills"
Cohesion: 0.15
Nodes (21): Wayfinder OpenAI Agent Interface Config, Wizard OpenAI Agent Interface Config, Wizard Skill, Wizard template.sh Library, Writing Beats OpenAI Agent Interface Config, Beat (Writing Unit), Writing Beats Skill, Grounding (Prerequisite vs Introduced Concepts) (+13 more)

### Community 9 - "Wizard Template Commands"
Cohesion: 0.22
Nodes (16): ask(), ask_secret(), banner(), _clear(), finish(), note(), open_url(), pause() (+8 more)

### Community 10 - "FIPE Integration Docs"
Cohesion: 0.18
Nodes (19): B2: FIPE integration — Done 2026-08-24, C2: Architecture shapes for remaining roadmap modules, K.LUME ONE product vision (6 modules), Emplacamentos Varejo e Vendas Diretas module, Itens de Especificações module, Incentivos Comerciais module, Identificação do Mercado de Locadoras module, Preço Transacionado module (+11 more)

### Community 11 - "Project Dependencies"
Cohesion: 0.15
Nodes (17): API Requirements (production, minimal), authlib, boto3, duckdb, fastapi, httpx, numpy, openpyxl (+9 more)

### Community 12 - "Bug Diagnosis & Domain Modeling"
Cohesion: 0.14
Nodes (16): Diagnosing Bugs Skill Interface, Diagnosing Bugs Skill, /improve-codebase-architecture Skill, Phase 1 - Build a Feedback Loop, Phase 2 - Reproduce + Minimise, Phase 3 - Hypothesise, Phase 4 - Instrument, Phase 5 - Fix + Regression Test (+8 more)

### Community 13 - "Teach Skill Formats"
Cohesion: 0.17
Nodes (16): Teach — OpenAI Agent Config, GLOSSARY.md Format, GLOSSARY.md, Learning Record Format, Learning Record, MISSION.md Format, MISSION.md, RESOURCES.md Format (+8 more)

### Community 14 - "CNPJ Enrichment Docs"
Cohesion: 0.19
Nodes (14): B1: Locadoras module (CNPJ join + CNAE) — Done 2026-08-20, Bronze Layer, gold/build_dim_empresa.py, categoria_empresa (CNAE classification), cnpj_basico_faturado, gold.dim_empresa, empresa_key (sentinel keys -1/-2), fipe_api (separate repo, Mage AI orchestrated) (+6 more)

### Community 15 - "Issue Tracker Setup"
Cohesion: 0.26
Nodes (12): Setup Matt Pocock Skills OpenAI Interface Config, Issue Tracker: GitHub Template, Issue Tracker: GitLab Template, Issue Tracker: Local Markdown Template, Setup Matt Pocock Skills Skill, Triage Labels Mapping Template, gh CLI, glab CLI (+4 more)

### Community 16 - "Gold Star Schema Docs"
Cohesion: 0.23
Nodes (10): A1: Replace hardcoded Gold assertion with a real test suite, A3: Wire the test suite into CI, C1: Split build_volumes.py into one build per fact table, Kimball Bus Architecture (conformed dimensions), gold/build_volumes.py, codigo_municipio (IBGE code), gold.dim_data, gold.dim_geografia (+2 more)

### Community 17 - "Fragment & Shape Writing Skills"
Cohesion: 0.22
Nodes (11): Writing Fragments OpenAI Interface Config, Writing Fragments Skill, Explore Phase (writing), Fragment (writing unit), Leading Word, Writing Shape OpenAI Interface Config, Writing Shape Skill, Exploit Phase (writing) (+3 more)

### Community 18 - "Medallion Architecture Overview"
Cohesion: 0.22
Nodes (9): Overall architecture rating: 7/10, Architecture stress-test session (2026-08-14), silver/vehicle_key/canonical.py, silver/vehicle_key/canonical_sql.py, COMBUSTIVEL_MAP, Medallion Architecture (Bronze/Silver/Gold), MotherDuck (Klume_DB_Cloud), SQL macro over Python UDF for MotherDuck writes (+1 more)

### Community 19 - "App Layer Docs"
Cohesion: 0.28
Nodes (9): D1: Auth / leaving Streamlit free tier — deferred, Application Layer (app/), ChromaDB (local training memory), gold.fato_volumes (view), Streamlit native login (st.login, OIDC/Google), app/streamlit_app.py, app/training_data.py, Vanna (text-to-SQL) (+1 more)

### Community 20 - "Upload Pipeline Docs"
Cohesion: 0.25
Nodes (8): A2: Lock down Vanna's database access, D2: Automating customer data intake — deferred, app.upload_log, data/bronze/veiculos_raw (local Parquet source), Automated Gmail/Drive ingestion (deferred), Upload schema validation, staging.bronze_2000...bronze_2025 (DENATRAN), app/pages/1_Upload_Dados.py

### Community 21 - "Gold Layer Design Docs"
Cohesion: 0.29
Nodes (8): dimensional-modeler Kimball methodology, Original gold.fato_volumes (wide OBT, deprecated), Gold Layer, MCP for external clients (planned), 4 orphan MotherDuck databases (bronze/silver/gold/my_db), gold.semantic_dictionary (planned), Gold Star Schema, Tableau/Power BI (direct Gold access)

### Community 22 - "Silver Layer Docs"
Cohesion: 0.33
Nodes (7): canonical_str (normalized key string), silver/utils/columns.py, silver/normalizers/denatran.py, silver/utils/sentinels.py, silver.veiculos, silver.veiculos_historico, vehicle_key (hash UBIGINT)

### Community 23 - "Shoehorn Migration Skill"
Cohesion: 0.33
Nodes (3): Migrate to Shoehorn OpenAI Agent Config, Migrate to Shoehorn Skill, @total-typescript/shoehorn Library

### Community 24 - "Pre-commit Setup Skill"
Cohesion: 0.40
Nodes (5): Setup Pre-Commit OpenAI Interface Config, Setup Pre-Commit Skill, Husky, lint-staged, Prettier

### Community 25 - "HITL Loop Script"
Cohesion: 0.83
Nodes (3): capture(), hitl-loop.template.sh script, step()

### Community 26 - "Git Guardrails Skill"
Cohesion: 0.50
Nodes (4): Git Guardrails Skill Interface, block-dangerous-git.sh Script, Git Guardrails for Claude Code Skill, .claude/settings.json Hook Config

### Community 27 - "Implement Skill"
Cohesion: 0.50
Nodes (4): Implement OpenAI Agent Config, Implement Skill, Code Review Skill, TDD Skill

### Community 28 - "Research & Merge Conflicts Skills"
Cohesion: 0.50
Nodes (4): Research Skill OpenAI Interface Config, Research Skill, Resolving Merge Conflicts OpenAI Interface Config, Resolving Merge Conflicts Skill

### Community 29 - "Wait-What Skill"
Cohesion: 0.50
Nodes (4): Wait What — OpenAI Agent Config, Wait What Skill, ASD-STE100 Simplified Technical English, CONTEXT.md Ubiquitous Language

### Community 30 - "Klume Brand Assets"
Cohesion: 0.50
Nodes (4): Klume Logo (SVG), Klume Brand Mark (orange K glyph), Klume Wordmark Text (dark, two-line), Klume Platform Project

## Knowledge Gaps
- **118 isolated node(s):** `block-dangerous-git.sh script`, `Grill Me OpenAI Agent Config`, `Grill Me (Interview Skill)`, `Grill with Docs OpenAI Agent Config`, `Grilling OpenAI Agent Config` (+113 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `get_connection()` connect `Pipeline Entry Points & App` to `Volumes API Service`, `Canonical Key Logic & Tests`, `DENATRAN Normalizer & Tests`, `FIPE Normalizer & Utils`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `VolumesFilters` (e.g. with `parse_volumes_filters()` and `volumes()`) actually correct?**
  _`VolumesFilters` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `block-dangerous-git.sh script`, `Grill Me OpenAI Agent Config`, `Grill Me (Interview Skill)` to the rest of the system?**
  _118 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Pipeline Entry Points & App` be split into smaller, more focused modules?**
  _Cohesion score 0.053830227743271224 - nodes in this community are weakly interconnected._
- **Should `Volumes API Service` be split into smaller, more focused modules?**
  _Cohesion score 0.05924920850293985 - nodes in this community are weakly interconnected._
- **Should `Ticket & Triage Skills` be split into smaller, more focused modules?**
  _Cohesion score 0.05061224489795919 - nodes in this community are weakly interconnected._
- **Should `Grilling & Prototyping Skills` be split into smaller, more focused modules?**
  _Cohesion score 0.0784313725490196 - nodes in this community are weakly interconnected._