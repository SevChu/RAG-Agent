from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.indexing.runtime import DocumentIndexingPipeline

COURSE_ID = UUID("1feb9db2-a5ee-4c75-aeee-82370726a700")
QUESTIONS = (
    "图的邻接矩阵和邻接表各有什么优缺点？",
    "Dijkstra 算法如何求单源最短路径，时间复杂度是多少？",
    "二分查找的适用条件和时间复杂度是什么？",
    "哈希表发生冲突时有哪些处理方法？",
    "栈和队列在操作规则上有什么区别？",
)
BOUNDARY_QUESTIONS = (
    "队列是一种先进后出的线性表，对吗？请按照课程资料回答。",
    "Dijkstra 算法在 1000 个顶点时会精确执行多少次比较？",
    "TCP 为什么需要三次握手？",
)


def _sqlite_path(database_url: str) -> Path:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("The reranker audit expects the local SQLite database.")
    return Path(database_url.removeprefix(prefix)).resolve()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--boundary", action="store_true")
    arguments = parser.parse_args()
    questions = BOUNDARY_QUESTIONS if arguments.boundary else QUESTIONS
    with sqlite3.connect(_sqlite_path(settings.database_url)) as connection:
        rows = connection.execute(
            "SELECT id FROM documents WHERE course_id = ? AND status = 'completed'",
            (COURSE_ID.hex,),
        ).fetchall()
    document_ids = [str(UUID(str(row[0]))) for row in rows]
    if not document_ids:
        raise RuntimeError("No completed Data Structures documents were found.")

    pipeline = DocumentIndexingPipeline(settings)
    try:
        for question in questions:
            dense = pipeline.search(
                course_id=COURSE_ID,
                query=question,
                top_k=settings.rag_answer_candidate_k,
                document_ids=document_ids,
            )
            reranked = pipeline.reranker.rerank(
                dense,
                top_k=settings.rag_answer_top_k,
            )
            dense_ranks = {
                hit.point_id: rank for rank, hit in enumerate(dense.hits, start=1)
            }
            print(
                json.dumps(
                    {
                        "question": question,
                        "dense_candidates": len(dense.hits),
                        "rejected_evidence": reranked.rejected_evidence_count,
                        "embedding_device": reranked.embedding_device,
                        "reranker_device": reranked.reranker_device,
                        "results": [
                            {
                                "rerank": rank,
                                "dense_rank": dense_ranks[hit.point_id],
                                "reranker_score": round(hit.score, 6),
                                "dense_score": round(
                                    float(hit.payload["dense_score"]), 6
                                ),
                                "role": hit.payload["content_role"],
                                "file": hit.payload.get("file_name"),
                                "pages": hit.payload.get("page_numbers", []),
                                "slides": hit.payload.get("slide_numbers", []),
                                "text": hit.text[:180].replace("\n", " "),
                            }
                            for rank, hit in enumerate(reranked.hits, start=1)
                        ],
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        pipeline.close()


if __name__ == "__main__":
    main()
