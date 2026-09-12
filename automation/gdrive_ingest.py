"""
Entry point da automação de ingestão via Google Drive.

Roda tanto local quanto como Google Cloud Function -- mesma função `run()`,
dois jeitos de disparar:
    python -m automation.gdrive_ingest                    # local, manual
    (Cloud Function importa `run` como entry point HTTP)

O primeiro teste real deste código já processa o backlog acumulado (a pasta
Inbox de verdade, com os arquivos parados esperando) -- não existe um "modo
backlog" separado, é a mesma execução de sempre.

Variáveis de ambiente esperadas (.env local / Secret Manager em produção):
    GDRIVE_SERVICE_ACCOUNT_JSON   -- caminho do arquivo de chave da service account
    DENATRAN_INBOX_FOLDER_ID
    DENATRAN_PROCESSADOS_FOLDER_ID
    DENATRAN_ERRO_FOLDER_ID
    MOTHERDUCK_TOKEN, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET
    (mesmas usadas pelo resto do projeto -- não são credenciais novas)
"""

import os

from dotenv import load_dotenv

from automation.drive_sync import get_drive_service, sync_inbox
from automation.registry import get_dominios


def run() -> dict:
    load_dotenv()

    service_account_json = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "service_account.json")
    service = get_drive_service(service_account_json)

    resumo = {}
    algum_dado_novo = False
    for dominio in get_dominios():
        if not dominio.inbox_folder_id:
            print(f"[{dominio.nome}] pasta Inbox não configurada (env var vazia) -- pulando.")
            continue

        print(f"[{dominio.nome}] sincronizando pasta Inbox {dominio.inbox_folder_id}...")
        resultados = sync_inbox(
            service,
            inbox_folder_id=dominio.inbox_folder_id,
            processados_folder_id=dominio.processados_folder_id,
            erro_folder_id=dominio.erro_folder_id,
            handler=dominio.handler,
            mime_type=dominio.mime_type,
        )
        for nome_arquivo, outcome in resultados:
            print(f"  [{outcome.status}] {nome_arquivo} — {outcome.mensagem}")
            if outcome.dados_novos:
                algum_dado_novo = True
        resumo[dominio.nome] = resultados

    # Gold reconstruído uma vez só, depois do lote inteiro -- não por arquivo
    # (ver comentário em automation/registry.py::_handler_denatran).
    if algum_dado_novo:
        print("Reconstruindo Gold (uma vez, para todo o lote)...")
        from gold.build_volumes import main as build_gold
        build_gold()
    else:
        print("Nenhum ano/período novo processado no lote -- Gold não foi reconstruído.")

    return resumo


if __name__ == "__main__":
    run()
