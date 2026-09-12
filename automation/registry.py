"""
Registro de domínios que usam a sincronização genérica do Drive
(automation/drive_sync.py). Cada entrada mapeia uma pasta Inbox pra um
handler de processamento — hoje só DENATRAN; adicionar um domínio novo
(ex.: TCO, quando existir) é só mais uma entrada aqui, sem tocar em
drive_sync.py.

IDs de pasta e caminho da chave de service account vêm de variável de
ambiente — nada hardcoded, mesmo padrão do resto do projeto (.env local,
Secret Manager em produção).
"""

import os
from dataclasses import dataclass
from typing import Callable

from automation.drive_sync import SyncOutcome


@dataclass
class DominioIngestao:
    nome: str
    inbox_folder_id: str
    processados_folder_id: str
    erro_folder_id: str
    handler: Callable[[bytes, str], SyncOutcome]
    mime_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _handler_denatran(file_bytes: bytes, filename: str) -> SyncOutcome:
    from app.upload_pipeline import (
        ConfigurationError, DataIntegrityError, PipelineError,
        get_s3_client, process_upload,
    )
    from silver.db.connection import get_connection

    con = get_connection("motherduck")
    # build_gold_fn=no-op: um lote de N arquivos do Drive não deve rodar o
    # rebuild completo do Gold N vezes -- automation/gdrive_ingest.py::run()
    # roda uma vez só, no final, se algum arquivo do lote trouxe ano novo
    # (ver SyncOutcome.dados_novos).
    try:
        resultado = process_upload(
            con, file_bytes, filename, s3_client=get_s3_client(),
            # False = "não reconstruí" -- mantém gold_reconstruido/mensagem
            # honestos (o Gold roda uma vez no fim do lote, não por arquivo).
            build_gold_fn=lambda: False,
        )
    except ConfigurationError:
        # Config quebrada afeta o LOTE INTEIRO, não este arquivo -- propaga
        # pra abortar a execução em vez de carimbar arquivo bom como "erro"
        # e movê-lo pra pasta Erro por um problema que não é dele.
        raise
    except DataIntegrityError as e:
        return SyncOutcome(status="erro", mensagem=str(e), dados_novos=False)
    except PipelineError as e:
        # Rollback já executado -- o banco não mudou, então retentar é seguro.
        return SyncOutcome(status="retry", mensagem=str(e), dados_novos=False)

    dados_novos = bool(resultado.anos_processados)

    if resultado.status in ("rejeitado_schema", "sem_data_valida"):
        # Erro permanente -- não adianta reprocessar o mesmo arquivo sozinho.
        return SyncOutcome(status="erro", mensagem=resultado.mensagem, dados_novos=dados_novos)

    if resultado.houve_falha_s3:
        # Falha transitória (S3 fora do ar etc.) -- deixa em Inbox, tenta de
        # novo no próximo ciclo. Anos que já tiveram sucesso não são
        # reprocessados (dedup por hash+ano em process_upload).
        return SyncOutcome(status="retry", mensagem=resultado.mensagem, dados_novos=dados_novos)

    return SyncOutcome(status="sucesso", mensagem=resultado.mensagem, dados_novos=dados_novos)


def get_dominios() -> list:
    return [
        DominioIngestao(
            nome="denatran",
            inbox_folder_id=os.getenv("DENATRAN_INBOX_FOLDER_ID"),
            processados_folder_id=os.getenv("DENATRAN_PROCESSADOS_FOLDER_ID"),
            erro_folder_id=os.getenv("DENATRAN_ERRO_FOLDER_ID"),
            handler=_handler_denatran,
        ),
    ]
