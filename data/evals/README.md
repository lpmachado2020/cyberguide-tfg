# Evaluation Artifacts

This directory stores generated evaluation assets for CyberGuide.

Typical contents:

- generated datasets
- benchmark runs against the API
- judged results
- summary reports

Suggested workflow:

1. generate question cases from the local corpus
2. run the cases against the current backend
3. score the responses with the judge script
4. inspect failures and refine the system

Recommended scripts:

- `scripts/generate_eval_dataset.py`
- `scripts/run_eval_benchmark.py`
- `scripts/judge_eval_results.py`

