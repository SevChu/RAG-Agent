from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

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
    args = parser.parse_args()
    if args.max_blocks < 1:
        parser.error("--max-blocks must be at least 1")

    result = build_default_registry().parse(
        args.path,
        file_type=args.file_type,
    )
    payload = {
        "summary": {
            "file_name": result.file_name,
            "file_type": result.file_type,
            "parser_name": result.parser_name,
            "block_count": len(result.blocks),
            "character_count": result.character_count,
            "warning_count": len(result.warnings),
            "shown_blocks": min(len(result.blocks), args.max_blocks),
        },
        "warnings": [asdict(warning) for warning in result.warnings],
        "blocks": [asdict(block) for block in result.blocks[: args.max_blocks]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
