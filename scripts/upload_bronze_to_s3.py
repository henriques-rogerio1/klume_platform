"""
Sobe os arquivos Parquet locais de Bronze DENATRAN (data/bronze/veiculos_raw)
pro mesmo bucket S3 que o fipe_api já usa, sob o prefixo denatran-bronze/,
mantendo a estrutura de pastas {ano}/{YYYYMM-ou-ano}/ que já existe local.

Passo 1 de "migrar bronze pro S3" — só sobe os arquivos originais; trocar
staging.bronze_YYYY (MotherDuck) por leitura direta do S3 e depois apagar
essas tabelas do MotherDuck fica pra uma etapa separada.

Uso:
    python scripts/upload_bronze_to_s3.py
Requer AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET no .env.
"""

import os
from pathlib import Path

import boto3
from dotenv import load_dotenv

LOCAL_ROOT = Path(r"C:\Users\Rogerio Henriques\Documents\data\bronze\veiculos_raw")
S3_PREFIX = "denatran-bronze"


def main():
    load_dotenv(dotenv_path=".env")
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ["AWS_REGION"],
    )
    bucket = os.environ["S3_BUCKET"]

    files = sorted(LOCAL_ROOT.rglob("*.parquet"))
    total = len(files)
    total_bytes = sum(f.stat().st_size for f in files)
    print(f"{total} arquivos, {total_bytes / 1024 / 1024:.0f} MB, destino: s3://{bucket}/{S3_PREFIX}/")

    uploaded_bytes = 0
    for i, f in enumerate(files, 1):
        rel = f.relative_to(LOCAL_ROOT).as_posix()
        key = f"{S3_PREFIX}/{rel}"
        s3.upload_file(str(f), bucket, key)
        uploaded_bytes += f.stat().st_size
        if i % 25 == 0 or i == total:
            pct = uploaded_bytes / total_bytes * 100
            print(f"  [{i}/{total}] {pct:.0f}% ({uploaded_bytes / 1024 / 1024:.0f} MB)")

    print("\nUpload concluído. Verificando...")
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=f"{S3_PREFIX}/")
    n_s3 = resp.get("KeyCount", 0)
    continuation = resp.get("NextContinuationToken")
    while continuation:
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=f"{S3_PREFIX}/", ContinuationToken=continuation)
        n_s3 += resp.get("KeyCount", 0)
        continuation = resp.get("NextContinuationToken")

    print(f"Arquivos locais: {total} | Arquivos em s3://{bucket}/{S3_PREFIX}/: {n_s3}")
    assert n_s3 == total, "Contagem de arquivos no S3 não bate com o local — upload incompleto."
    print("OK: contagem bate.")


if __name__ == "__main__":
    main()
