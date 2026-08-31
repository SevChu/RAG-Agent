# Agentic: A General-Purpose RAG Agent Research Platform

[简体中文](README.md) | **English**

> **Repository:** [SevChu/RAG-Agent](https://github.com/SevChu/RAG-Agent) — publicly
> visible, but proprietary and not open source.
>
> **About:** A local-first RAG agent research platform built with FastAPI, Vue 3,
> LangGraph, BGE-M3, Qdrant, and multiple OpenAI-compatible model providers. Its
> long-term goal is to build a more general-purpose agent with consistently high
> answer quality through traceable retrieval, fine-tuning, and evaluation/scoring
> algorithm improvements.
>
> **License:** Copyright © 2026 Severus Chu. All rights reserved. The proprietary
> license applies only to original Agentic materials owned by Severus Chu.
> Third-party dependencies, models, and benchmark datasets remain subject to their
> respective upstream terms. See [LICENSE](LICENSE) and
> [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

> **Current language boundary:** Agentic `v1.1.1` currently provides a Chinese-only
> user interface, prompts, and user-facing error messages. This English README
> documents the project for international readers; it does not mean that the
> application itself already supports English. Product-level English support is
> planned as a future internationalization milestone.

## Project Status

- Latest release: `v1.1.1` — licensing-boundary patch.
- Functional baseline: `v1.1.0` — complete local RAG workflow, general-agent UI
  migration, FiQA/RAGTruth/RAGBench classic baselines, and baseline profile 1.0.0.
- Runtime model providers: DeepSeek plus reserved OpenAI-compatible interfaces for
  Qwen, Kimi, and GLM.
- Deployment model: local, single-user, and local-data-first.
- Interface language: Chinese only in the current release.
- English product support: planned for `v1.6.0`; not implemented yet.

## Overview

Agentic turns documents, reports, slides, and personal notes into isolated,
searchable resource spaces. It combines retrieval-augmented generation with
traceable evidence, persistent conversations, controlled web search, reproducible
evaluation, and a roadmap for per-agent fine-tuning.

The current system can:

- import PDF, PPTX, DOCX, Markdown, and TXT files;
- parse, chunk, embed, and index local documents;
- answer questions with file, page, slide, and section citations;
- combine resource-space evidence with clearly separated external information;
- generate structured summaries and mixed question sets;
- preserve quick-chat and resource-space conversation histories separately;
- switch among configured model providers without exposing API keys to the browser;
- reproduce retrieval, hallucination-detection, and RAG-scoring benchmarks;
- export aggregate benchmark results without publishing raw datasets or predictions.

The original learning-assistant functions remain available as optional capability
templates, but the product direction is now a general-purpose agent platform.

## Architecture

```mermaid
flowchart TD
    UI["Vue 3 + TypeScript"] -->|"REST / SSE"| API["FastAPI"]
    API --> GRAPH["LangGraph Agent"]

    GRAPH --> ROUTER["Intent and task routing"]
    ROUTER --> QA["Question answering"]
    ROUTER --> SUMMARY["Structured summaries"]
    ROUTER --> EXAM["Structured content / question sets"]

    QA --> RETRIEVAL["RAG retrieval pipeline"]
    SUMMARY --> RETRIEVAL
    EXAM --> RETRIEVAL

    RETRIEVAL --> QDRANT["Qdrant local vector store"]
    RETRIEVAL --> RERANKER["BGE reranker"]
    GRAPH --> LLM["OpenAI-compatible model providers"]
    GRAPH -->|"Conditional"| WEB["DeepSeek server-side web search"]

    API --> SQLITE["SQLite metadata"]
    API --> FILES["Local files and model cache"]
```

### Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Vue 3, TypeScript, Vite, Element Plus, Pinia |
| Backend | Python 3.11, FastAPI, Pydantic, SQLAlchemy, Alembic |
| Agent orchestration | LangGraph |
| Model providers | DeepSeek, Qwen, Kimi, and GLM through OpenAI-compatible APIs |
| Embeddings | `BAAI/bge-m3` |
| Reranking | `BAAI/bge-reranker-v2-m3` |
| Vector storage | Qdrant Local Mode |
| Metadata storage | SQLite |
| Document processing | pypdf, python-docx, python-pptx, PaddleOCR |
| Evaluation | pytest and custom reproducible benchmark runners |

## Core Workflows

### Document Ingestion

```text
File upload
→ type, size, and safety validation
→ SHA-256 duplicate detection
→ native text and layout extraction
→ page-level OCR fallback when required
→ structure-aware chunking
→ local embedding generation
→ Qdrant indexing
→ metadata and processing-status persistence
```

Documents are isolated by resource space. The current internal schema still uses
legacy `Course`, `course_id`, and `/api/courses` identifiers for backward
compatibility; the user-facing product is no longer limited to courses.

### Evidence-Grounded Answering

```text
User request
→ intent and resource-space resolution
→ query rewriting
→ dense and lexical candidate retrieval
→ reranking and evidence gating
→ answer generation with citations
→ faithfulness and citation checks
→ streamed response and conversation persistence
```

The system distinguishes local evidence, external supplementary information, and
model inference. If evidence is insufficient, it should abstain rather than present
unsupported content as fact.

### Model Provider Routing

Each provider has an independent Base URL, API key, and model allowlist. The backend
resolves the provider from the selected model ID and never sends secret keys to the
frontend. A provider remains disabled until both its API key and model list are
configured.

DeepSeek-specific reasoning and server-side web-search behavior is not automatically
assumed to exist on other OpenAI-compatible providers. When Qwen, Kimi, or GLM is
used for the final answer, web search still follows the separately configured
DeepSeek search path.

## Reproducible Evaluation

Agentic `v1.1.0` introduced three approved public-dataset baselines. Raw datasets,
per-sample predictions, model weights, and local caches are not committed.

| Task | Dataset | Current baseline | Selected result |
|---|---|---|---|
| Retrieval | BEIR FiQA | BGE-M3 Dense top-100 | nDCG@10 0.4126; Recall@100 0.7188 |
| Retrieval reranking | BEIR FiQA | RRF candidates + BGE reranker | nDCG@10 0.4299; MRR@10 0.5162 |
| Hallucination response detection | RAGTruth | Lexical coverage | F1 0.6245; AUROC 0.7248; AUPRC 0.5042 |
| Hallucination span localization | RAGTruth | Logistic fusion | Character F1 0.1777 |
| RAG trace scoring | RAGBench | Lexical + Dense linear | AUROC 0.7273; AUPRC 0.9292 |

These figures are research baselines, not production-quality guarantees. The most
important known gaps are equal-weight RRF degradation, weak hallucination-span
localization, and limited completeness correlation.

See:

- [Public benchmark summary](benchmarks/v1.1.0/README.md)
- [Evaluation and frozen baselines](docs/technical/evaluation-and-baselines.md)
- [Week 5 engineering log](docs/engineering-logs/week-05.md)

## Quick Start

### Prerequisites

- Windows development environment;
- Python 3.11 managed by `uv`;
- Node.js and npm;
- sufficient local storage for document indexes and approved model files;
- at least one configured model provider for real generation requests.

### 1. Configure the Environment

Copy `.env.example` to `.env`, then fill in the provider you intend to use.

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=your-key
LLM_AVAILABLE_MODELS=your-deepseek-model
LLM_MODEL=your-deepseek-model

QWEN_API_KEY=
QWEN_MODELS=
KIMI_API_KEY=
KIMI_MODELS=
GLM_API_KEY=
GLM_MODELS=
```

Do not commit `.env`. Changes to provider URLs, keys, or model lists require a
backend restart. Switching among already configured models does not require a
frontend restart.

### 2. Start the Backend

```powershell
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run fastapi dev app/main.py --host 127.0.0.1 --port 8000
```

### 3. Start the Frontend

```powershell
cd frontend
npm install
npm.cmd run dev -- --host 127.0.0.1
```

Default local endpoints:

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000/`
- OpenAPI: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/api/health`

For full setup, storage, backup, and troubleshooting details, read
[Operations](docs/technical/operations.md) and
[Configuration](docs/technical/configuration.md).

## Privacy, Security, and Data Boundaries

- Uploaded documents, resource spaces, conversations, databases, and API keys must
  remain local and are excluded from Git.
- Benchmark downloads require explicit per-dataset approval.
- The repository contains only aggregate benchmark results and reproducibility
  metadata, never raw benchmark samples or per-sample predictions.
- Uploaded material is treated as untrusted data, not as system instructions.
- The first release does not execute uploaded or generated code.
- The current system is local and single-user; it does not provide accounts,
  permissions, collaboration, or public multi-tenant deployment.

## Roadmap

| Target | Planned scope | Status |
|---|---|---|
| `v1.2.0` | Retrieval and scoring algorithm improvements | Planned |
| `v1.3.0` | Versioned AgentProfile and multi-agent configuration | Planned |
| `v1.4.0-beta.1` | Training dataset, job, adapter registry, and fine-tuning UI foundation | Planned beta |
| `v1.4.0` | First real scorer or reranker fine-tuning and rollback | Planned |
| `v1.5.0` | Dynamic long context, resource-space memory, and private gold-set tooling | Planned |
| `v1.6.0` | Chinese/English internationalization and bilingual quality validation | Planned |

The `v1.6.0` internationalization milestone is expected to cover:

1. locale resources and a persistent language preference;
2. English UI labels, validation messages, and operational errors;
3. locale-aware prompts and English answer-generation policies;
4. English ingestion, retrieval, citation, summarization, and conversation tests;
5. bilingual regression slices and language-isolation checks;
6. Chinese fallback behavior for untranslated or unsupported content.

English support will not be marked complete merely because an English README exists
or because the underlying model can answer in English. Product UI, backend errors,
prompt behavior, retrieval quality, and regression coverage must all pass the
internationalization acceptance gate.

See the detailed [Week 6–11 and later roadmap](docs/deliverables/week-06-to-11-roadmap.md).

## Repository Layout

```text
Agentic/
├── backend/                 FastAPI, RAG, agents, evaluation, and migrations
├── frontend/                Vue 3 web application
├── benchmarks/v1.1.0/       Aggregate public benchmark results only
├── docs/                    Technical docs, decisions, releases, and logs
├── data/                    Local-only data, models, indexes, and databases
├── .env.example             Safe configuration template
├── LICENSE                  Proprietary license for original Agentic materials
└── THIRD_PARTY_NOTICES.md   Third-party attribution and licensing boundaries
```

## Documentation

- [Technical documentation index](docs/technical/README.md)
- [System architecture](docs/technical/architecture.md)
- [Configuration reference](docs/technical/configuration.md)
- [API reference](docs/technical/api-reference.md)
- [Data and RAG pipeline](docs/technical/data-and-rag-pipeline.md)
- [Agent and generation pipeline](docs/technical/agent-and-generation.md)
- [Development and testing](docs/technical/development-and-testing.md)
- [Release notes: v1.1.1](docs/releases/v1.1.1.md)
- [Engineering logs](docs/engineering-logs/README.md)

Most detailed technical and historical documents are currently written in Chinese.
Their English documentation migration will follow the same terminology and review
rules as the product internationalization milestone.

## License and Ownership

Agentic is publicly visible for review and demonstration, but it is not an
open-source project. You may not use, copy, modify, merge, publish, distribute,
sublicense, or sell original Agentic materials except with explicit written
permission from the copyright owner.

Third-party dependencies, models, benchmark datasets, and derived notices are not
relicensed under the Agentic proprietary license. Review
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistribution or research
use.

**Author and copyright owner:** Severus Chu
