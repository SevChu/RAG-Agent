from __future__ import annotations

import heapq
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.evaluation.benchmark import CorpusDocument, RelevanceJudgment

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[._'-][a-z0-9]+)*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    document_id: str
    score: float


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    query_count: int
    values: dict[str, float]


def tokenize_for_bm25(text: str) -> tuple[str, ...]:
    """Use one deterministic, dependency-free tokenizer for the English FiQA baseline."""

    return tuple(match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text))


def document_text(document: CorpusDocument) -> str:
    return "\n".join(part for part in (document.title.strip(), document.text.strip()) if part)


class Bm25Index:
    """An in-memory Okapi BM25 inverted index with deterministic ranking."""

    def __init__(
        self,
        documents: Iterable[CorpusDocument],
        *,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        if k1 <= 0:
            raise ValueError("BM25 k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("BM25 b must be between zero and one")
        self.k1 = k1
        self.b = b
        self.document_ids: list[str] = []
        self.document_lengths: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for document in documents:
            document_index = len(self.document_ids)
            terms = tokenize_for_bm25(document_text(document))
            self.document_ids.append(document.id)
            self.document_lengths.append(len(terms))
            for term, frequency in Counter(terms).items():
                self.postings[term].append((document_index, frequency))
        if not self.document_ids:
            raise ValueError("BM25 corpus cannot be empty")
        self.average_document_length = sum(self.document_lengths) / len(self.document_lengths)

    def search(self, query: str, *, top_k: int) -> tuple[RetrievalHit, ...]:
        if top_k < 1:
            raise ValueError("BM25 top_k must be positive")
        scores: dict[int, float] = defaultdict(float)
        document_count = len(self.document_ids)
        average_length = self.average_document_length or 1.0
        for term in dict.fromkeys(tokenize_for_bm25(query)):
            postings = self.postings.get(term)
            if not postings:
                continue
            document_frequency = len(postings)
            inverse_document_frequency = math.log(
                1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            for document_index, term_frequency in postings:
                length_ratio = self.document_lengths[document_index] / average_length
                denominator = term_frequency + self.k1 * (1.0 - self.b + self.b * length_ratio)
                scores[document_index] += inverse_document_frequency * (
                    term_frequency * (self.k1 + 1.0) / denominator
                )
        ranked = heapq.nlargest(
            min(top_k, len(scores)),
            scores.items(),
            key=lambda item: (item[1], self.document_ids[item[0]]),
        )
        return tuple(
            RetrievalHit(document_id=self.document_ids[index], score=float(score))
            for index, score in ranked
        )


def reciprocal_rank_fusion(
    runs: Sequence[Sequence[RetrievalHit]],
    *,
    top_k: int,
    rank_constant: int = 60,
) -> tuple[RetrievalHit, ...]:
    if top_k < 1:
        raise ValueError("fusion top_k must be positive")
    if rank_constant < 1:
        raise ValueError("fusion rank_constant must be positive")
    scores: dict[str, float] = defaultdict(float)
    for run in runs:
        for rank, hit in enumerate(run, start=1):
            scores[hit.document_id] += 1.0 / (rank_constant + rank)
    ranked = heapq.nlargest(
        min(top_k, len(scores)),
        scores.items(),
        key=lambda item: (item[1], item[0]),
    )
    return tuple(
        RetrievalHit(document_id=document_id, score=score) for document_id, score in ranked
    )


def evaluate_retrieval(
    run: Mapping[str, Sequence[RetrievalHit]],
    qrels: Iterable[RelevanceJudgment],
    *,
    ks: Sequence[int] = (1, 3, 5, 10, 20, 100),
) -> RetrievalMetrics:
    normalized_ks = tuple(sorted(set(ks)))
    if not normalized_ks or normalized_ks[0] < 1:
        raise ValueError("metric cutoffs must be positive")
    relevance_by_query: dict[str, dict[str, float]] = defaultdict(dict)
    for judgment in qrels:
        if judgment.relevance > 0:
            relevance_by_query[judgment.query_id][judgment.corpus_id] = judgment.relevance
    if not relevance_by_query:
        raise ValueError("qrels do not contain positive relevance judgments")

    totals: dict[str, float] = defaultdict(float)
    for query_id, relevant in relevance_by_query.items():
        hits = run.get(query_id, ())
        ideal_relevances = sorted(relevant.values(), reverse=True)
        relevant_retrieved = previous_stop = 0
        reciprocal_rank = precision_sum = gain = ideal_gain = 0.0
        # Reuse each ranked prefix across cutoffs without changing accumulation order.
        for cutoff in normalized_ks:
            stop = min(cutoff, max(len(hits), len(ideal_relevances)))
            for index in range(previous_stop, stop):
                rank = index + 1
                discount = math.log2(rank + 1.0)
                if index < len(hits):
                    document_id = hits[index].document_id
                    if document_id in relevant:
                        relevant_retrieved += 1
                        precision_sum += relevant_retrieved / rank
                        if not reciprocal_rank:
                            reciprocal_rank = 1.0 / rank
                    gain += (2.0 ** relevant.get(document_id, 0.0) - 1.0) / discount
                if index < len(ideal_relevances):
                    ideal_gain += (2.0 ** ideal_relevances[index] - 1.0) / discount
            previous_stop = stop
            totals[f"precision@{cutoff}"] += relevant_retrieved / cutoff
            totals[f"recall@{cutoff}"] += relevant_retrieved / len(relevant)
            totals[f"mrr@{cutoff}"] += reciprocal_rank
            totals[f"map@{cutoff}"] += precision_sum / min(len(relevant), cutoff)
            totals[f"ndcg@{cutoff}"] += gain / ideal_gain if ideal_gain else 0.0

    query_count = len(relevance_by_query)
    return RetrievalMetrics(
        query_count=query_count,
        values={name: value / query_count for name, value in sorted(totals.items())},
    )


def write_trec_run(
    path: Path,
    run: Mapping[str, Sequence[RetrievalHit]],
    *,
    run_name: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for query_id in sorted(run):
            for rank, hit in enumerate(run[query_id], start=1):
                handle.write(
                    f"{query_id} Q0 {hit.document_id} {rank} {hit.score:.12g} {run_name}\n"
                )
    temporary.replace(path)


def read_trec_run(path: Path) -> dict[str, tuple[RetrievalHit, ...]]:
    grouped: dict[str, list[tuple[int, RetrievalHit]]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            parts = line.split()
            if len(parts) != 6:
                raise ValueError(f"invalid TREC run row {line_number}: {path}")
            query_id, _, document_id, rank, score, _ = parts
            grouped[query_id].append(
                (int(rank), RetrievalHit(document_id=document_id, score=float(score)))
            )
    return {
        query_id: tuple(hit for _, hit in sorted(rows, key=lambda item: item[0]))
        for query_id, rows in grouped.items()
    }
