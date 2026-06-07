"""Run a generated evaluation dataset against the CyberGuide API.

Purpose:
- Execute a reproducible benchmark pass against the current backend instance.

Inputs:
- A JSONL dataset generated from the local corpus.
- A reachable CyberGuide backend URL.

Outputs:
- A JSONL file with questions, system answers, sources, traces and request status.

Used by:
- Iterative regression checks and TFG evaluation evidence collection.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import httpx

from eval_shared import DEFAULT_EVAL_DIR, read_jsonl, write_jsonl


async def run_benchmark(
    *,
    dataset_path: Path,
    output_path: Path,
    base_url: str,
    top_k: int,
) -> dict[str, Any]:
    """Execute each generated question against the local CyberGuide API."""
    cases = read_jsonl(dataset_path)
    results: list[dict[str, Any]] = []

    async with httpx.AsyncClient(base_url=base_url, timeout=180.0) as client:
        for case in cases:
            # Reuse the case id as the session id so session-sensitive behavior
            # stays reproducible across benchmark runs.
            payload = {
                "message": case["question"],
                "top_k": top_k,
                "session_id": f"eval-{case['case_id']}",
            }
            try:
                response = await client.post("/query", json=payload)
                response.raise_for_status()
                body = response.json()
                results.append(
                    {
                        **case,
                        "request_payload": payload,
                        "response_status": response.status_code,
                        "system_answer": body.get("answer", ""),
                        "system_sources": body.get("sources", []),
                        "system_trace": body.get("trace"),
                        "system_mode": body.get("mode", "corpus"),
                        "system_model": body.get("model", ""),
                        "ok": True,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                # Keep failed cases in the output file so the judge can separate
                # transport problems from answer-quality problems.
                results.append(
                    {
                        **case,
                        "request_payload": payload,
                        "ok": False,
                        "error": str(exc),
                        "system_answer": "",
                        "system_sources": [],
                        "system_trace": None,
                    }
                )

    write_jsonl(output_path, results)
    return {
        "input_cases": len(cases),
        "output_path": str(output_path),
        "successful_cases": sum(1 for row in results if row.get("ok")),
        "failed_cases": sum(1 for row in results if not row.get("ok")),
        "base_url": base_url,
    }


def main() -> None:
    """Parse CLI args and run the benchmark."""
    parser = argparse.ArgumentParser(description="Run generated evaluation cases against the CyberGuide API.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_EVAL_DIR / "generated_questions.jsonl")
    parser.add_argument("--output", type=Path, default=DEFAULT_EVAL_DIR / "benchmark_results.jsonl")
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--top-k", type=int, default=4)
    args = parser.parse_args()

    # The default base URL matches the local development setup documented in
    # the repo, so the command can be run without extra flags.
    report = asyncio.run(
        run_benchmark(
            dataset_path=args.dataset,
            output_path=args.output,
            base_url=args.base_url,
            top_k=args.top_k,
        )
    )
    print(report)


if __name__ == "__main__":
    main()

