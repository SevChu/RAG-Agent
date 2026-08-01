from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from app.ingestion.chunking import (
    ChunkingConfig,
    ChunkingContext,
    StructuredDocumentChunker,
)
from app.ingestion.models import BlockKind
from app.ingestion.registry import build_default_registry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect the structured output of a local document parser."
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--file-type",
        help="Override the type inferred from the file extension.",
    )
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=20,
        help="Maximum number of parsed blocks to print.",
    )
    parser.add_argument(
        "--kind",
        choices=[kind.value for kind in BlockKind],
        help="Only print blocks of this kind.",
    )
    parser.add_argument(
        "--slide-number",
        type=int,
        help="Only print blocks from this one-based slide number.",
    )
    parser.add_argument(
        "--chunks",
        action="store_true",
        help="Also run structured chunking and print chunk statistics.",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=10,
        help="Maximum number of chunks to print when --chunks is used.",
    )
    parser.add_argument(
        "--chunk-index",
        type=int,
        help="Only print one zero-based chunk index when --chunks is used.",
    )
    parser.add_argument(
        "--target-tokens",
        type=int,
        default=600,
        help="Estimated target tokens per chunk.",
    )
    parser.add_argument(
        "--overlap-tokens",
        type=int,
        default=80,
        help="Estimated overlap tokens between chunks in one section.",
    )
    parser.add_argument("--course-id", help="Optional course ID for chunk metadata.")
    parser.add_argument("--document-id", help="Optional document ID for chunk metadata.")
    args = parser.parse_args()
    if args.max_blocks < 1:
        parser.error("--max-blocks must be at least 1")
    if args.slide_number is not None and args.slide_number < 1:
        parser.error("--slide-number must be at least 1")
    if args.max_chunks < 1:
        parser.error("--max-chunks must be at least 1")
    if args.chunk_index is not None and args.chunk_index < 0:
        parser.error("--chunk-index cannot be negative")
    try:
        chunking_config = ChunkingConfig(
            target_tokens=args.target_tokens,
            overlap_tokens=args.overlap_tokens,
        )
    except ValueError as error:
        parser.error(str(error))

    result = build_default_registry().parse(
        args.path,
        file_type=args.file_type,
    )
    block_kind_counts = Counter(block.kind.value for block in result.blocks)
    page_numbers = [
        block.source.page_number
        for block in result.blocks
        if block.source.page_number is not None
    ]
    slide_numbers = [
        block.source.slide_number
        for block in result.blocks
        if block.source.slide_number is not None
    ]
    matching_blocks = [
        block
        for block in result.blocks
        if (args.kind is None or block.kind.value == args.kind)
        and (
            args.slide_number is None
            or block.source.slide_number == args.slide_number
        )
    ]
    payload = {
        "summary": {
            "file_name": result.file_name,
            "file_type": result.file_type,
            "parser_name": result.parser_name,
            "block_count": len(result.blocks),
            "character_count": result.character_count,
            "warning_count": len(result.warnings),
            "matched_block_count": len(matching_blocks),
            "shown_blocks": min(len(matching_blocks), args.max_blocks),
            "block_kind_counts": dict(sorted(block_kind_counts.items())),
            "max_page_number": max(page_numbers, default=None),
            "max_slide_number": max(slide_numbers, default=None),
        },
        "warnings": [asdict(warning) for warning in result.warnings],
        "blocks": [asdict(block) for block in matching_blocks[: args.max_blocks]],
    }
    if args.chunks:
        chunking = StructuredDocumentChunker().chunk(
            result,
            config=chunking_config,
            context=ChunkingContext(
                course_id=args.course_id,
                document_id=args.document_id,
            ),
        )
        matching_chunks = [
            chunk
            for chunk in chunking.chunks
            if args.chunk_index is None or chunk.chunk_index == args.chunk_index
        ]
        payload["chunking"] = {
            "token_measure": "deterministic estimate; replace with model tokenizer later",
            "config": asdict(chunking.config),
            "stats": asdict(chunking.stats),
            "warning_count": len(chunking.warnings),
            "warnings": [asdict(warning) for warning in chunking.warnings],
            "matched_chunk_count": len(matching_chunks),
            "shown_chunks": min(len(matching_chunks), args.max_chunks),
            "chunks": [
                asdict(chunk) for chunk in matching_chunks[: args.max_chunks]
            ],
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
