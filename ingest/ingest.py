#!/usr/bin/env python3
"""Ingestion pipeline: GCS bucket -> parse -> split -> embed -> upsert to Qdrant.

Idempotent: point IDs are uuid5(NAMESPACE_URL, "<gcs_uri>#<chunk_index>"), so
re-running the job over the same documents is a no-op.

Configuration is via environment variables (see CONFIG below). --dry-run lists
files and chunk counts without embedding or upserting.
"""

import argparse
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

CONFIG = {
    "bucket": os.environ.get("GCS_BUCKET", ""),
    "prefix": os.environ.get("GCS_PREFIX", ""),
    "qdrant_url": os.environ.get("QDRANT_URL", "http://localhost:6333"),
    "qdrant_api_key": os.environ.get("QDRANT_API_KEY"),
    "embed_url": os.environ.get("EMBED_URL", "http://localhost:8080"),
    "embed_api_key": os.environ.get("EMBED_API_KEY"),
    "collection": os.environ.get("QDRANT_COLLECTION", "docs-v1"),
    "chunk_size": int(os.environ.get("CHUNK_SIZE", "1200")),
    "chunk_overlap": int(os.environ.get("CHUNK_OVERLAP", "200")),
    "batch_size": int(os.environ.get("EMBED_BATCH_SIZE", "32")),
}

DIRECT_FORMATS = {".md", ".markdown", ".html"}
DOCLING_FORMATS = {".pdf", ".docx", ".pptx"}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("ingest")


def list_documents(client, bucket, prefix):
    blobs = client.list_blobs(bucket, prefix=prefix)
    return [b for b in blobs if os.path.splitext(b.name)[1].lower() in DIRECT_FORMATS | DOCLING_FORMATS]


def parse_document(blob, converter_cache):
    ext = os.path.splitext(blob.name)[1].lower()
    if ext in DIRECT_FORMATS:
        return blob.download_as_text()
    if ext in DOCLING_FORMATS:
        from docling.document_converter import DocumentConverter

        if "converter" not in converter_cache:
            converter_cache["converter"] = DocumentConverter()
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            blob.download_to_filename(tmp.name)
            result = converter_cache["converter"].convert(tmp.name)
        os.unlink(tmp.name)
        return result.document.export_to_markdown()
    raise ValueError(f"unsupported format: {blob.name}")


def split_markdown(text, chunk_size, chunk_overlap):
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    headers = [("#", "h1"), ("##", "h2"), ("###", "h3")]
    header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers)
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    chunks = []
    for section in header_splitter.split_text(text):
        heading_path = " > ".join(
            section.metadata[h] for h in ("h1", "h2", "h3") if h in section.metadata
        )
        for piece in size_splitter.split_text(section.page_content):
            chunks.append((heading_path, piece))
    return chunks


def embed_batch(texts):
    import requests

    headers = {"Content-Type": "application/json"}
    if CONFIG["embed_api_key"]:
        headers["Authorization"] = f"Bearer {CONFIG['embed_api_key']}"
    resp = requests.post(
        f"{CONFIG['embed_url']}/v1/embeddings",
        json={"model": "qwen3-embedding", "input": texts},
        headers=headers,
        timeout=120,
    )
    resp.raise_for_status()
    return [item["embedding"] for item in resp.json()["data"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not CONFIG["bucket"]:
        log.error("GCS_BUCKET is not set")
        sys.exit(1)

    from google.cloud import storage

    client = storage.Client()
    blobs = list_documents(client, CONFIG["bucket"], CONFIG["prefix"])
    log.info("found %d documents under gs://%s/%s", len(blobs), CONFIG["bucket"], CONFIG["prefix"])

    qdrant = None
    if not args.dry_run:
        from qdrant_client import QdrantClient
        from qdrant_client.models import PointStruct

        qdrant = QdrantClient(url=CONFIG["qdrant_url"], api_key=CONFIG["qdrant_api_key"])

    converter_cache = {}
    total_chunks = 0
    total_upserts = 0
    errors = 0

    for blob in blobs:
        gcs_uri = f"gs://{CONFIG['bucket']}/{blob.name}"
        try:
            markdown = parse_document(blob, converter_cache)
            chunks = split_markdown(markdown, CONFIG["chunk_size"], CONFIG["chunk_overlap"])
        except Exception:
            log.exception("failed to parse %s", gcs_uri)
            errors += 1
            continue
        total_chunks += len(chunks)
        log.info("%s -> %d chunks", gcs_uri, len(chunks))
        if args.dry_run or not chunks:
            continue

        prefixed = [
            f"{gcs_uri} > {heading}\n\n{text}" if heading else f"{gcs_uri}\n\n{text}"
            for heading, text in chunks
        ]
        ingested_at = datetime.now(timezone.utc).isoformat()
        for start in range(0, len(prefixed), CONFIG["batch_size"]):
            batch = prefixed[start : start + CONFIG["batch_size"]]
            vectors = embed_batch(batch)
            points = [
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{gcs_uri}#{start + i}")),
                    vector=vector,
                    payload={
                        "source": gcs_uri,
                        "heading_path": chunks[start + i][0],
                        "chunk_index": start + i,
                        "text": prefixed[start + i],
                        "ingested_at": ingested_at,
                    },
                )
                for i, vector in enumerate(vectors)
            ]
            qdrant.upsert(collection_name=CONFIG["collection"], points=points)
            total_upserts += len(points)

    log.info(
        "done: %d files, %d chunks, %d upserts, %d errors",
        len(blobs), total_chunks, total_upserts, errors,
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
