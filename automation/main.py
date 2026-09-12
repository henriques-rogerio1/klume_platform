"""
Entry point HTTP pra Google Cloud Function (2ª geração) -- disparado pelo
Google Cloud Scheduler. Toda a lógica de verdade mora em gdrive_ingest.py/
drive_sync.py/registry.py; este arquivo só existe porque o Cloud Functions
(gatilho HTTP) espera uma função com assinatura `(request) -> response`.

Deploy (referência, não testado ainda -- depender da conta GCP existir):
    gcloud functions deploy klume-gdrive-ingest \\
        --gen2 --runtime=python312 --region=<regiao> \\
        --source=. --entry-point=gdrive_ingest_http \\
        --trigger-http --no-allow-unauthenticated \\
        --timeout=1800 --memory=512MB \\
        --set-env-vars=DENATRAN_INBOX_FOLDER_ID=...,DENATRAN_PROCESSADOS_FOLDER_ID=...,DENATRAN_ERRO_FOLDER_ID=... \\
        --set-secrets=MOTHERDUCK_TOKEN=...,AWS_ACCESS_KEY_ID=...,AWS_SECRET_ACCESS_KEY=...,GDRIVE_SERVICE_ACCOUNT_JSON=...
"""

from automation.gdrive_ingest import run


def gdrive_ingest_http(request):
    resumo = run()
    total_arquivos = sum(len(r) for r in resumo.values())
    return {
        "dominios_processados": list(resumo.keys()),
        "total_arquivos": total_arquivos,
    }, 200
