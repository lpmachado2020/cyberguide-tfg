# CyberGuide Repository Guide

This file is a compact orientation guide for future iterations on `CyberGuide`.

## Project Purpose

`CyberGuide` is a TFG project about a local, safety-oriented RAG assistant for cybersecurity literacy in SMEs and self-employment contexts.

The current product direction is:

- local-first architecture,
- public official corpus,
- conservative grounded answers,
- multimodal support limited to:
  - persistent corpus chat,
  - uploaded PDF analysis,
  - OCR-first image analysis.

The scope is intentionally narrow: less breadth, more reliability.

## Core Runtime

- Backend: `backend/app/main.py`
- Frontend: `frontend/`
- Vector store: local Chroma in `data/vectorstore/chroma`
- LLM runtime: local Ollama on host
- Default chat model: `llama3.1:8b`
- Default embedding model: `bge-m3:latest`

Typical local ports used during development:

- `8000`: main local or Dockerized app
- `8010+`: ad hoc validation instances

## Key Architecture Files

- `backend/app/services/rag.py`: main RAG orchestration
- `backend/app/services/security_policy.py`: safety-first policy for sensitive OCR/image cases
- `backend/app/services/ocr_service.py`: OCR extraction
- `backend/app/services/session_store.py`: in-memory conversational session state
- `backend/app/services/ingestion.py`: document loading, PDF parsing and chunking
- `backend/app/services/vector_store.py`: Chroma integration
- `backend/app/services/ollama_client.py`: local Ollama chat/embed client
- `backend/app/prompting.py`: prompt construction

## Current Product Behavior

- Corpus mode:
  - `/query`
  - grounded in persistent INCIBE corpus
- PDF mode:
  - `/query_pdf`
  - session-scoped uploaded PDF analysis
- Image mode:
  - `/query_image`
  - OCR-first image analysis with session continuity

The frontend shows:

- chat,
- sources,
- visible pipeline trace,
- cautious safety mode when relevant.

## Safety Rules

High-risk OCR/image scenarios must prefer deterministic safe guidance over open-ended generation.

Examples:

- do not recommend clicking suspicious links,
- do not recommend entering credentials or OTP codes,
- prefer manual navigation to official sites,
- prefer independent official support channels,
- acknowledge uncertainty when the evidence is insufficient.

This is an explicit design choice, not just a prompt tweak.

## Evaluation Workflow

The repository includes a synthetic evaluation pipeline:

1. `scripts/generate_eval_dataset.py`
   - creates question/answer cases from the local corpus
2. `scripts/run_eval_benchmark.py`
   - sends those questions to the local CyberGuide API
3. `scripts/judge_eval_results.py`
   - uses the local model as a judge to score correctness, grounding and safety

Default output directory:

- `data/evals/`

## Documentation Policy

Important project notes live outside the repo narrative but inside the local workspace:

- `docs/`: working notes for the TFG memory
- `references/`: bibliography, source register, external PDFs, example memories

Both are intentionally ignored by Git.

Any relevant implementation milestone should leave evidence in:

- `docs/daily-log.md`
- `docs/validation-log.md`
- `docs/decision-log.md`

## Development Conventions

- Prefer English docstrings/comments in code.
- Keep module docstrings short and structured.
- Use `apply_patch` for manual edits.
- Avoid broad features that weaken safety or grounding.
- When in doubt, choose conservative behavior over “helpful” but risky advice.

