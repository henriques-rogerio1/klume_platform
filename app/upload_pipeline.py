"""
Pipeline de upload DENATRAN (Bronze -> Silver -> Gold), extraído de
app/pages/1_Upload_Dados.py pra virar uma função pura, sem Streamlit —
chamável tanto pela página quanto por automação (ver automation/gdrive_ingest.py).

Mesma lógica de sempre: ordem landing-first (S3 antes do MotherDuck, por
ano/mês, fail-closed — ver docs/POST-MORTEM.md pro incidente que motivou),
mesma carga substitutiva escopada (DELETE dos meses do upload + INSERT, não
o ano inteiro). Só a interface mudou: em vez de st.status()/st.write(),
retorna um UploadResultado estruturado.

**Correção de dedup em relação à versão anterior (achado ao desenhar a
automação, não específico dela — o bug já existia no fluxo manual)**: o
dedup era por hash do arquivo inteiro, bloqueando o upload inteiro se
qualquer ano dele já tivesse sido visto. Um XLSX pode conter mais de um
ano; se o ano A tinha sucesso e o ano B falhava no S3 (falha transitória),
reenviar o mesmo arquivo pra tentar de novo o ano B era bloqueado como
"duplicata" pelo hash do arquivo inteiro — o ano B nunca conseguia ser
reprocessado. Dedup agora é por (hash, ano): só pula o que já teve sucesso
pra aquele ano especificamente, deixando o que falhou tentar de novo.

get_s3_client() lê de variável de ambiente (os.getenv), não st.secrets --
funciona tanto rodando dentro do Streamlit (que expõe secrets como env var)
quanto numa Cloud Function (que não tem contexto Streamlit nenhum).
"""

import os
import re
import shutil
import tempfile
import uuid
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import boto3

DATE_COL = "Data de Emplacamento"
# Coluna interna adicionada à materialização temporária -- prefixo duplo pra
# não colidir com nenhuma coluna real do arquivo de origem.
PARSED_DATE_COL = "__parsed_date"
S3_PREFIX = "denatran-bronze"
SCHEMA_TEMPLATE_YEAR = "bronze_2024"  # ano "normal" (45 colunas), não o formato de 2025 com colunas extras


class PipelineError(Exception):
    """Base das falhas do pipeline de upload."""


class ConfigurationError(PipelineError):
    """Configuração ausente/errada (env var, bucket inacessível). NUNCA é
    transitória -- retentar sem corrigir a config só repete o erro pra
    sempre. Quem orquestra deve abortar, não reagendar."""


class TransientS3Error(PipelineError):
    """Falha de rede/indisponibilidade no S3. Retentar faz sentido."""


class DataIntegrityError(PipelineError):
    """Dado do arquivo é inválido/inconsistente. Reprocessar o mesmo arquivo
    não resolve -- precisa de arquivo novo/corrigido."""

# Colunas sem as quais o arquivo não serve pra nada no pipeline (data pra
# particionar por ano/mês, marca/modelo pro vehicle_key, quantidade pra
# medida da fato) — ausência de qualquer uma bloqueia o upload.
REQUIRED_COLUMNS = [DATE_COL, "Marca", "Modelo", "Quantidade"]
# Abaixo disso, o arquivo provavelmente não é um export de volumes DENATRAN
# (formato errado), não só uma safra com colunas a mais/a menos.
MIN_MATCH_RATE = 0.5


@dataclass
class AnoResultado:
    ano: int
    status: str  # "ok" | "s3_falhou" | "ja_processado"
    meses: list
    linhas_inseridas: int | None
    mensagem: str


@dataclass
class UploadResultado:
    # "ok" | "rejeitado_schema" | "sem_data_valida"
    # "ok" cobre tanto "processou algo novo" quanto "todo ano já estava processado" --
    # ver anos_processados/anos_pulados pra distinguir.
    status: str
    mensagem: str
    anos: list = field(default_factory=list)  # list[AnoResultado]
    gold_reconstruido: bool = False
    total_lidas: int = 0        # linhas no arquivo de origem
    total_quarentena: int = 0   # linhas rejeitadas (ver staging.bronze_quarantine)

    @property
    def anos_processados(self) -> list:
        return [a.ano for a in self.anos if a.status == "ok"]

    @property
    def houve_falha_s3(self) -> bool:
        return any(a.status == "s3_falhou" for a in self.anos)

    @property
    def total_inseridas(self) -> int:
        return sum(a.linhas_inseridas or 0 for a in self.anos if a.status == "ok")


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION"),
    )


def _sanitize_s3_component(name: str) -> str:
    """Neutraliza o nome do arquivo antes de virar parte da chave S3 --
    barra viraria prefixo novo, e espaço/acento complicam ferramentas de
    linha de comando. Só o nome do objeto é afetado; o conteúdo não muda."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def preflight(s3_client, s3_bucket: str, *, check_env: bool = True) -> None:
    """Fail-fast de configuração ANTES de baixar/ler qualquer arquivo.
    Sem isso, S3_BUCKET ausente só estourava lá na frente, dentro do
    try/except do upload, e era classificado como falha transitória de S3 --
    virando retry infinito pra um erro de config que nunca se resolve
    sozinho.

    check_env=False quando quem chama injetou o próprio cliente S3: nesse
    caso as credenciais vieram de outro lugar que não as env vars, então
    checá-las seria falso negativo. O alcance ao bucket continua sendo
    verificado pelo próprio cliente injetado."""
    if check_env:
        faltando = [
            k for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION")
            if not os.getenv(k)
        ]
        if faltando:
            raise ConfigurationError(f"Variáveis de ambiente ausentes: {faltando}")
    if not s3_bucket:
        raise ConfigurationError("S3_BUCKET não configurado.")
    try:
        s3_client.head_bucket(Bucket=s3_bucket)
    except Exception as e:
        raise ConfigurationError(f"Bucket '{s3_bucket}' inacessível: {e}") from e


def ensure_upload_log(con) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS app")
    con.execute("""
        CREATE TABLE IF NOT EXISTS app.upload_log (
            ts TIMESTAMP,
            filename VARCHAR,
            file_hash VARCHAR,
            ano INTEGER,
            rows_inserted INTEGER,
            s3_ok BOOLEAN
        )
    """)


def ensure_quarantine(con) -> None:
    """Tabela de quarentena (dead-letter) das linhas rejeitadas na ingestão.
    raw_row como JSON de propósito: o schema do Bronze varia por safra (45
    vs 48 colunas), então uma tabela com colunas fixas ou quebraria ou
    precisaria migrar a cada formato novo."""
    con.execute("CREATE SCHEMA IF NOT EXISTS staging")
    con.execute("""
        CREATE TABLE IF NOT EXISTS staging.bronze_quarantine (
            ts TIMESTAMP,
            filename VARCHAR,
            file_hash VARCHAR,
            reject_reason VARCHAR,
            raw_row JSON
        )
    """)


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_previous_upload(con, hash_: str, ano: int):
    """Retorna a linha de log mais recente pra (hash, ano) se esse ano já foi
    processado com sucesso -- None se ainda não. Grão (hash, ano), não só
    hash: um mesmo arquivo pode ter anos ainda pendentes mesmo que outro
    ano dele já tenha sido processado."""
    return con.execute(
        "SELECT ts, filename, rows_inserted FROM app.upload_log "
        "WHERE file_hash = ? AND ano = ? ORDER BY ts DESC LIMIT 1",
        [hash_, ano],
    ).fetchone()


def log_insert(con, *, filename: str, hash_: str, ano: int, rows_inserted: int, s3_ok: bool) -> None:
    # s3_ok sempre True na prática agora -- landing-first garante que o S3 já
    # teve sucesso antes desta linha ser gravada.
    con.execute(
        "INSERT INTO app.upload_log VALUES (?, ?, ?, ?, ?, ?)",
        [datetime.now(timezone.utc), filename, hash_, ano, rows_inserted, s3_ok],
    )


def process_upload(
    con,
    file_bytes: bytes,
    filename: str,
    *,
    s3_client=None,
    s3_bucket: str = None,
    build_gold_fn=None,
) -> UploadResultado:
    """Roda a pipeline completa (Bronze landing-first -> Silver -> Gold) pra
    um arquivo XLSX de volumes DENATRAN já lido em memória. Sem efeitos
    colaterais de UI -- quem chama decide como reportar o resultado.

    build_gold_fn injetável (default: gold.build_volumes.main, que conecta
    na MotherDuck real quando chamado sem argumento) -- existe pra permitir
    testes locais substituírem por um no-op, sem depender de/afetar a
    MotherDuck de produção. Achado ao escrever o teste desta função
    (2026-09-11): sem essa injeção, rodar os testes localmente disparava um
    rebuild real do Gold de produção a cada execução (~3 min, consumindo
    compute real da conta) -- efeito colateral que um teste nunca deveria
    ter."""
    from silver.normalizers.denatran import normalize_denatran

    if build_gold_fn is None:
        from gold.build_volumes import main as build_gold_fn

    client_injetado = s3_client is not None
    s3_client = s3_client or get_s3_client()
    s3_bucket = s3_bucket or os.getenv("S3_BUCKET")

    preflight(s3_client, s3_bucket, check_env=not client_injetado)

    ensure_upload_log(con)
    hash_ = file_hash(file_bytes)

    con.execute("INSTALL excel")
    con.execute("LOAD excel")

    # Diretório efêmero próprio por execução -- antes o parquet temporário
    # tinha nome fixo por (ano, mês) no tempdir compartilhado, então duas
    # execuções simultâneas (página Streamlit + Cloud Function agendada, ou
    # ciclos sobrepostos) escreviam e apagavam o mesmo caminho.
    run_tmp = Path(tempfile.mkdtemp(prefix=f"denatran_{uuid.uuid4().hex[:8]}_"))
    tmp_path = (run_tmp / "origem.xlsx").as_posix()
    Path(tmp_path).write_bytes(file_bytes)

    # all_varchar=true -- achado real (2026-09-11, backlog outubro/2025 a
    # julho/2026): sem isso, read_xlsx() tenta inferir um tipo único por
    # coluna e QUEBRA com exceção fatal (não recuperável em SQL depois)
    # assim que encontra uma célula fora do tipo inferido -- ex.:
    # "Identificação do Faturado" é majoritariamente CNPJ/CPF numérico, mas
    # tem "Desconhecido" (texto) quando Tipo do Faturado = 'Outros'. Como
    # todo o Bronze acaba em VARCHAR de qualquer forma (ver
    # staging.bronze_{ano}), ler tudo como texto desde o início não perde
    # nada e evita esse crash em qualquer coluna, não só nas que já vimos
    # com esse problema.
    xlsx_src = f"read_xlsx('{tmp_path}', all_varchar=true)"

    # Trade-off conhecido de all_varchar=true (por isso não era usado antes
    # deste achado): a coluna de data deixa de vir como DATE nativo. Precisa
    # ser reconstruída em texto -- dois formatos observados na prática
    # (YYYYMMDD puro, com ou sem formatação de data real no Excel por trás)
    # mais um terceiro como rede de segurança (serial de data do Excel,
    # época 1899-12-30, caso all_varchar=true devolva o serial cru pra
    # alguma célula com formatação de data genuína).
    # Faixa do fallback restrita a serial plausível de data (~1982-2050) --
    # achado ao testar contra o backlog real: um valor "0" solto (claramente
    # sentinela/erro de digitação, não data) virava 1899-12-30 sem essa
    # restrição. Fora da faixa = NULL (data inválida), não um serial aceito
    # às cegas.
    DATE_EXPR = (
        f'COALESCE('
        f'TRY_STRPTIME("{DATE_COL}", \'%Y%m%d\'), '
        f'TRY_STRPTIME("{DATE_COL}", \'%Y-%m-%d\'), '
        f'CASE WHEN regexp_matches("{DATE_COL}", \'^[0-9]+$\') '
        f'AND TRY_CAST("{DATE_COL}" AS DOUBLE) BETWEEN 30000 AND 55000 '
        f'THEN DATE \'1899-12-30\' + CAST(TRY_CAST("{DATE_COL}" AS DOUBLE) AS INTEGER) '
        f'ELSE NULL END)'
    )

    try:
        src_cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {xlsx_src}").fetchall()]

        reference_cols = [r[0] for r in con.execute(f"DESCRIBE staging.{SCHEMA_TEMPLATE_YEAR}").fetchall()]
        missing_required = [c for c in REQUIRED_COLUMNS if c not in src_cols]
        match_rate = sum(1 for c in reference_cols if c in src_cols) / len(reference_cols)

        if missing_required:
            return UploadResultado(
                status="rejeitado_schema",
                mensagem=f"Faltam colunas obrigatórias {missing_required}. Não parece ser um export de volumes DENATRAN.",
            )
        if match_rate < MIN_MATCH_RATE:
            return UploadResultado(
                status="rejeitado_schema",
                mensagem=f"Bate com apenas {match_rate:.0%} das colunas do formato DENATRAN esperado (mínimo {MIN_MATCH_RATE:.0%}).",
            )

        # ---- ÚNICA leitura completa do XLSX ----------------------------
        # Antes o arquivo era relido 2+N vezes (anos, datas, e um COPY por
        # mês), cada passada custando ~12s num arquivo de ~500k linhas --
        # medido: ~38s dos ~49s totais eram re-leitura. Materializar uma vez
        # numa TEMP TABLE e servir todo o resto da memória troca isso por um
        # scan só. Guarda as colunas CRUAS + a data já parseada; a projeção
        # contra tgt_cols continua por ano (cada ano tem seu schema: 2025
        # tem 48 colunas, 2024/2026 têm 45).
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE _raw_staged AS
            SELECT *, {DATE_EXPR} AS {PARSED_DATE_COL}
            FROM {xlsx_src}
        """)
        total_lidas = con.execute("SELECT COUNT(*) FROM _raw_staged").fetchone()[0]

        # ---- Quarentena (DLQ) ------------------------------------------
        # Linhas sem data parseável nunca entram em ano nenhum e sumiam
        # silenciosamente -- confirmado real: 3 linhas assim já residem em
        # staging.bronze_2023 (data = '0') sem nenhum registro de descarte.
        # Guarda a linha inteira como JSON pra não acoplar o schema da
        # quarentena ao formato variável de cada safra.
        ensure_quarantine(con)
        con.execute(
            "DELETE FROM staging.bronze_quarantine WHERE file_hash = ?", [hash_]
        )
        con.execute(
            f"""
            INSERT INTO staging.bronze_quarantine
            SELECT now(), ?, ?, 'DATA_INVALIDA', to_json(q)
            FROM (
                SELECT * EXCLUDE ({PARSED_DATE_COL}) FROM _raw_staged
                WHERE {PARSED_DATE_COL} IS NULL
            ) q
            """,
            [filename, hash_],
        )
        n_quarentena = con.execute(
            "SELECT COUNT(*) FROM staging.bronze_quarantine WHERE file_hash = ?", [hash_]
        ).fetchone()[0]

        anos = [
            int(a[0])
            for a in con.execute(f"""
                SELECT DISTINCT date_part('year', {PARSED_DATE_COL}) AS ano
                FROM _raw_staged
                WHERE {PARSED_DATE_COL} IS NOT NULL
                ORDER BY 1
            """).fetchall()
        ]

        if not anos:
            return UploadResultado(
                status="sem_data_valida",
                mensagem=(
                    f"Não encontrei nenhuma data válida na coluna '{DATE_COL}' "
                    f"({total_lidas:,} linhas lidas, todas para a quarentena)."
                ),
                total_lidas=total_lidas,
                total_quarentena=n_quarentena,
            )

        resultado = UploadResultado(
            status="ok", mensagem="",
            total_lidas=total_lidas, total_quarentena=n_quarentena,
        )

        for ano in anos:
            # Dedup por (hash, ano) -- ver docstring do módulo. Pula só o
            # que já teve sucesso pra este ano específico, não o arquivo
            # inteiro.
            ja_processado = find_previous_upload(con, hash_, ano)
            if ja_processado:
                ts, _, rows = ja_processado
                resultado.anos.append(AnoResultado(
                    ano=ano, status="ja_processado", meses=[], linhas_inseridas=rows,
                    mensagem=f"Já processado em {ts:%Y-%m-%d %H:%M} UTC ({rows:,} linhas) — pulado.",
                ))
                continue

            target_table = f"staging.bronze_{ano}"

            exists = con.execute(f"""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'staging' AND table_name = 'bronze_{ano}'
            """).fetchone()[0] > 0
            if not exists:
                con.execute(f"CREATE TABLE {target_table} AS SELECT * FROM staging.{SCHEMA_TEMPLATE_YEAR} LIMIT 0")

            tgt_cols = [r[0] for r in con.execute(f"DESCRIBE {target_table}").fetchall()]
            common = [c for c in tgt_cols if c in src_cols]

            # A projeção continua por ano (schemas diferem entre safras), mas
            # agora lê da TEMP TABLE materializada, não do XLSX -- e usa a
            # data já parseada, sem reavaliar DATE_EXPR linha a linha.
            select_parts = []
            for c in tgt_cols:
                if c not in common:
                    select_parts.append(f"NULL AS \"{c}\"")
                elif c == DATE_COL:
                    select_parts.append(f"strftime({PARSED_DATE_COL}, '%Y%m%d') AS \"{c}\"")
                else:
                    select_parts.append(f'CAST("{c}" AS VARCHAR) AS "{c}"')
            select_sql = ",\n    ".join(select_parts)

            staged_view = f"_upload_{ano}"
            con.execute(f"""
                CREATE OR REPLACE TEMP VIEW {staged_view} AS
                SELECT
                    {select_sql}
                FROM _raw_staged
                WHERE date_part('year', {PARSED_DATE_COL}) = {ano}
            """)

            # Datas exatas presentes no arquivo -- é ISSO que define o escopo
            # do DELETE no Bronze, não o mês. Achado ao revisar o cenário de
            # arquivo diário (2026-09-12): com escopo mensal, subir o dia 2
            # apagava o mês inteiro (incluindo o dia 1 já carregado) e
            # inseria só o dia 2 -- perda silenciosa, sem erro e com
            # n_inserted "correto". Escopar pelas datas do arquivo se ajusta
            # sozinho aos dois formatos: mensal lista ~30 datas, diário lista
            # 1. O mês continua sendo derivado daqui só pra chave do S3.
            datas = [
                d
                for (d,) in con.execute(
                    f'SELECT DISTINCT "{DATE_COL}" FROM {staged_view} ORDER BY 1'
                ).fetchall()
            ]
            meses = sorted({d[:6] for d in datas})

            # Etapa S3 (landing-first): sobe todos os meses antes de tocar o
            # MotherDuck. Falha em qualquer mês pula o ano inteiro -- fail
            # closed, sem estado parcial. Os parquets locais são MANTIDOS
            # (não apagados aqui) -- achado real (2026-09-12): staged_view é
            # uma view preguiçosa, então INSERT INTO ... SELECT FROM
            # {staged_view} reexecutava a leitura inteira do XLSX de novo
            # (já lento/frágil o bastante pra já ter causado os bugs de
            # tipo misto corrigidos antes). Os parquets que acabamos de
            # escrever pro S3 já SÃO a versão materializada e limpa dessa
            # mesma transformação -- reusar como fonte do Bronze evita reler
            # o XLSX de novo.
            # COPY local e upload S3 em try/except SEPARADOS: antes estavam
            # no mesmo bloco, então um erro de disco/DuckDB no COPY era
            # reportado como "Falha no S3" e classificado como transitório --
            # o arquivo ficava preso na Inbox, retentado a cada ciclo pra
            # sempre, por um problema que retry nenhum resolve.
            s3_ok_for_year = True
            s3_erro = None
            local_parquets = []
            safe_name = _sanitize_s3_component(filename)
            for mes in meses:
                local_parquet = run_tmp / f"upload_{ano}_{mes}.parquet"
                try:
                    con.execute(f"""
                        COPY (
                            SELECT * FROM {staged_view}
                            WHERE substr("{DATE_COL}", 1, 6) = '{mes}'
                        ) TO '{local_parquet.as_posix()}' (FORMAT PARQUET)
                    """)
                except Exception as e:
                    for p in local_parquets:
                        p.unlink(missing_ok=True)
                    raise DataIntegrityError(
                        f"Falha ao materializar o parquet de {ano}/{mes} ({filename}): {e}"
                    ) from e

                try:
                    key = f"{S3_PREFIX}/{ano}/{mes}/{safe_name}.parquet"
                    s3_client.upload_file(str(local_parquet), s3_bucket, key)
                    local_parquets.append(local_parquet)
                except Exception as e:
                    s3_ok_for_year = False
                    s3_erro = str(e)
                    break

            if not s3_ok_for_year:
                for p in local_parquets:
                    p.unlink(missing_ok=True)
                resultado.anos.append(AnoResultado(
                    ano=ano, status="s3_falhou", meses=meses, linhas_inseridas=None,
                    mensagem=f"Falha no S3: {s3_erro}. Nada inserido no MotherDuck pra esse ano -- reenviar depois tenta só este ano de novo.",
                ))
                continue

            # Bronze + Silver + log numa transação só. Antes: log_insert
            # rodava ANTES do Silver, então uma falha no Silver deixava o ano
            # marcado como processado (dedup pulava na reexecução) com o
            # Silver vazio -- e, na automação, o arquivo ia pra pasta Erro e
            # ninguém reprocessava. Além disso o DELETE+INSERT do Bronze era
            # avulso: uma falha no meio deixava o mês vazio até a próxima
            # execução. Transação única resolve os dois: ou tudo commita, ou
            # nada muda. Verificado (2026-09-12) que o MotherDuck honra
            # BEGIN/COMMIT/ROLLBACK, inclusive DDL de view no bloco.
            parquet_paths_sql = "[" + ", ".join(f"'{p.as_posix()}'" for p in local_parquets) + "]"
            # DELETE escopado às datas do arquivo (ver comentário em `datas`).
            # Parse dos dois formatos que o Bronze histórico tem (com e sem
            # traço) -- TRY_STRPTIME, não strptime, pra não estourar em linha
            # antiga com formato inesperado.
            data_expr_alvo = (
                f'COALESCE(TRY_STRPTIME("{DATE_COL}", \'%Y%m%d\'), '
                f'TRY_STRPTIME("{DATE_COL}", \'%Y-%m-%d\'))::DATE'
            )
            datas_list_sql = ", ".join(
                f"DATE '{d[:4]}-{d[4:6]}-{d[6:8]}'" for d in datas
            )

            con.execute("BEGIN TRANSACTION")
            try:
                con.execute(f"""
                    DELETE FROM {target_table}
                    WHERE {data_expr_alvo} IN ({datas_list_sql})
                """)
                con.execute(f"INSERT INTO {target_table} SELECT * FROM read_parquet({parquet_paths_sql})")
                n_inserted = con.execute(
                    f"SELECT COUNT(*) FROM read_parquet({parquet_paths_sql})"
                ).fetchone()[0]

                # Silver -- mapping_table explícito (achado 2026-09-11: o
                # código original da página nunca passava, então todo upload
                # pulava o match de tier 3 silenciosamente).
                #
                # DELETE do ano INTEIRO, não das datas: normalize_denatran
                # normaliza a tabela staging.bronze_{ano} completa, então o
                # INSERT abaixo traz o ano todo. Escopar este DELETE por data
                # duplicaria as datas que não estão neste arquivo.
                recent, historico = normalize_denatran(
                    con, target_table, mapping_table="silver.mapping_table", stage_prefix=f"upl{ano}"
                )
                con.execute(f"DELETE FROM silver.veiculos WHERE date_part('year', data_emplacamento) = {ano}")
                con.execute(f"INSERT INTO silver.veiculos SELECT * FROM {recent}")
                con.execute(f"DELETE FROM silver.veiculos_historico WHERE date_part('year', data_emplacamento) = {ano}")
                con.execute(f"INSERT INTO silver.veiculos_historico SELECT * FROM {historico}")

                log_insert(con, filename=filename, hash_=hash_, ano=ano, rows_inserted=n_inserted, s3_ok=True)
                con.execute("COMMIT")
            except Exception as err:
                con.execute("ROLLBACK")
                raise PipelineError(
                    f"Falha na ingestão do ano {ano} ({filename}) — rollback executado, "
                    f"nada foi alterado no banco: {err}"
                ) from err
            finally:
                for p in local_parquets:
                    p.unlink(missing_ok=True)

            resultado.anos.append(AnoResultado(
                ano=ano, status="ok", meses=meses, linhas_inseridas=n_inserted,
                mensagem=f"{n_inserted:,} linhas carregadas ({len(datas)} data(s), meses {meses}).",
            ))

        # ---- Reconciliação -------------------------------------------------
        # Só faz sentido quando TODO ano do arquivo foi processado agora: se
        # algum foi pulado por dedup ou falhou no S3, as linhas dele
        # legitimamente não entram na conta.
        todos_ok = bool(resultado.anos) and all(a.status == "ok" for a in resultado.anos)
        if todos_ok:
            esperado = resultado.total_inseridas + resultado.total_quarentena
            if esperado != total_lidas:
                raise DataIntegrityError(
                    f"Reconciliação falhou em {filename}: {total_lidas:,} linhas lidas, "
                    f"mas {resultado.total_inseridas:,} inseridas + "
                    f"{resultado.total_quarentena:,} em quarentena = {esperado:,}. "
                    f"Diferença de {total_lidas - esperado:,} linha(s) não explicada."
                )

        if resultado.anos_processados:
            # gold_reconstruido só vira True se build_gold_fn REALMENTE
            # reconstruiu. No lote do Drive ele é um no-op (o Gold roda uma
            # vez no fim, em gdrive_ingest.run()) -- antes a mensagem
            # afirmava "Gold atualizado" uma vez por arquivo, o que era
            # falso e poluiu o log do backlog inteiro.
            rebuild_real = build_gold_fn() is not False
            resultado.gold_reconstruido = bool(rebuild_real)
            alvo = "Bronze, Silver e Gold" if resultado.gold_reconstruido else "Bronze e Silver"
            quarentena_txt = (
                f" ({resultado.total_quarentena} linha(s) em quarentena)"
                if resultado.total_quarentena else ""
            )
            resultado.mensagem = (
                f"Pipeline concluída — {alvo} atualizados pra "
                f"{resultado.anos_processados}{quarentena_txt}."
            )
        elif resultado.houve_falha_s3:
            resultado.mensagem = "Nenhum ano novo foi processado (falha no S3) — Gold não foi reconstruído."
        else:
            resultado.mensagem = "Todos os anos deste arquivo já haviam sido processados antes — nada novo a fazer."

        return resultado
    finally:
        shutil.rmtree(run_tmp, ignore_errors=True)
