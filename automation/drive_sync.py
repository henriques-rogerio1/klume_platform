"""
Sincronização genérica Google Drive Inbox -> Processados/Erro — independente
de domínio (DENATRAN hoje, TCO ou outros no futuro). Quem chama passa uma
função `handler(file_bytes, filename) -> SyncOutcome`; este módulo só cuida
de listar/baixar/mover arquivo, nunca sabe o que tem dentro deles.

Padrão de 3 pastas (Inbox / Processados / Erro), não só 2:
- Sucesso total -> move pra Processados.
- Falha transitória (ex.: S3 fora do ar) -> deixa em Inbox, tenta de novo no
  próximo ciclo (o dedup por (hash, ano) do lado de quem processa garante
  que o que já teve sucesso não é reprocessado à toa).
- Falha permanente (ex.: schema inválido, não é um arquivo do formato
  esperado) -> move pra Erro, pra não ficar tentando pra sempre um arquivo
  que nunca vai dar certo sozinho.

Autenticação via Service Account (não OAuth de usuário) — pensado pra rodar
sem supervisão, disparado por Google Cloud Scheduler -> Cloud Function, mas
igualmente executável local (python -m automation.gdrive_ingest).
"""

import io
from dataclasses import dataclass
from typing import Callable

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]


@dataclass
class SyncOutcome:
    # "sucesso" -> move pra Processados
    # "retry"   -> deixa em Inbox, tenta de novo no próximo ciclo
    # "erro"    -> move pra Erro, não tenta mais sozinho
    status: str
    mensagem: str
    # True se este arquivo processou pelo menos um ano/período novo (Bronze/
    # Silver mudaram) -- usado por quem chama sync_inbox pra decidir se vale
    # reconstruir o Gold uma vez só, depois do lote inteiro, em vez de a
    # cada arquivo (rebuild completo custa ~1-2 min; repetir por arquivo
    # com um lote de N arquivos custa N vezes à toa).
    dados_novos: bool = False


def get_drive_service(service_account_json_path: str):
    creds = service_account.Credentials.from_service_account_file(
        service_account_json_path, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_inbox_files(service, inbox_folder_id: str, mime_type: str | None = None) -> list:
    query = f"'{inbox_folder_id}' in parents and trashed = false"
    if mime_type:
        query += f" and mimeType = '{mime_type}'"
    files = []
    page_token = None
    while True:
        response = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, modifiedTime, md5Checksum)",
            pageToken=page_token,
        ).execute()
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def download_file(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def move_file(service, file_id: str, from_folder_id: str, to_folder_id: str) -> None:
    service.files().update(
        fileId=file_id,
        addParents=to_folder_id,
        removeParents=from_folder_id,
        fields="id, parents",
    ).execute()


def sync_inbox(
    service,
    *,
    inbox_folder_id: str,
    processados_folder_id: str,
    erro_folder_id: str,
    handler: Callable[[bytes, str], SyncOutcome],
    mime_type: str | None = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
) -> list:
    """Pra cada arquivo na pasta Inbox: baixa, chama handler(bytes, nome),
    move conforme o SyncOutcome retornado. Falha de um arquivo (exceção não
    tratada no download/handler) não trava os demais -- vira "erro" pra
    aquele arquivo específico, move pra Erro, segue pro próximo."""
    arquivos = list_inbox_files(service, inbox_folder_id, mime_type=mime_type)
    resultados = []
    for i, f in enumerate(arquivos, 1):
        # Print por arquivo, não só no final do lote -- achado real
        # (2026-09-11): sem isso, um lote de N arquivos fica em silêncio até
        # TODOS terminarem (cada um pode levar ~1-2 min), o que já foi
        # confundido com travamento numa execução real e levou a matar o
        # processo antes da hora.
        print(f"  [{i}/{len(arquivos)}] processando {f['name']}...", flush=True)
        try:
            data = download_file(service, f["id"])
            outcome = handler(data, f["name"])
        except Exception as e:
            outcome = SyncOutcome(status="erro", mensagem=f"Exceção não tratada: {e}")

        if outcome.status == "sucesso":
            move_file(service, f["id"], inbox_folder_id, processados_folder_id)
        elif outcome.status == "erro":
            move_file(service, f["id"], inbox_folder_id, erro_folder_id)
        # "retry": não move -- fica em Inbox pro próximo ciclo.

        print(f"  [{i}/{len(arquivos)}] {f['name']} -> {outcome.status}: {outcome.mensagem}", flush=True)
        resultados.append((f["name"], outcome))
    return resultados
