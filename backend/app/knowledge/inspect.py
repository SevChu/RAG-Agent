from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ingestion.chunking import ChunkingContext, StructuredDocumentChunker
from app.ingestion.registry import build_default_registry
from app.knowledge import BgeM3Embedder, EmbeddingDevice, KnowledgeIndexer, QdrantChunkStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed one local document, write its chunks to Qdrant and run a scoped query."
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("../data/models/embedding/bge-m3"),
    )
    parser.add_argument(
        "--qdrant-path",
        type=Path,
        default=Path("../data/qdrant"),
    )
    parser.add_argument("--collection", default="knowledge_chunks_v1")
    parser.add_argument(
        "--device",
        choices=[device.value for device in EmbeddingDevice],
        default=EmbeddingDevice.AUTO,
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    if args.batch_size < 1 or args.limit < 1:
        parser.error("--batch-size and --limit must be positive")

    document = build_default_registry().parse(args.path)
    chunking = StructuredDocumentChunker().chunk(
        document,
        context=ChunkingContext(
            course_id=args.course_id,
            document_id=args.document_id,
        ),
    )
    embedder = BgeM3Embedder(
        args.model_path,
        device=args.device,
        batch_size=args.batch_size,
    )
    store = QdrantChunkStore(
        args.qdrant_path,
        collection_name=args.collection,
    )
    try:
        indexer = KnowledgeIndexer(embedder, store)
        indexing = indexer.index(
            chunking,
            course_id=args.course_id,
            document_id=args.document_id,
        )
        results = indexer.search(
            args.query,
            course_id=args.course_id,
            limit=args.limit,
        )
        payload = {
            "indexing": {
                "course_id": indexing.course_id,
                "document_id": indexing.document_id,
                "chunk_count": indexing.chunk_count,
                "vector_dimension": indexing.vector_dimension,
                "device": indexing.device,
                "fallback_reason": indexing.fallback_reason,
                "collection": args.collection,
                "qdrant_path": str(args.qdrant_path.resolve()),
            },
            "query": args.query,
            "results": [
                {
                    "score": result.score,
                    "course_id": result.course_id,
                    "document_id": result.document_id,
                    "chunk_index": result.chunk_index,
                    "text": result.text,
                }
                for result in results
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
