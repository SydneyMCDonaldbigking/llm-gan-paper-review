# LLM-GAN Paper Review System

This project is a Git-first adversarial paper review prototype.
It runs multi-round review loops where one model attacks the paper, another model defends it, and the system records every step as Git history.

## Core Idea

- `Gemini` acts as the critic.
- `GPT` or `OpenRouter` acts as the defender.
- Every round is written to disk and committed into a review repository.
- `Busywork` is flagged when edits do not add meaningful logic or evidence.
- `PUA` escalation is triggered when a round degrades, stalls, or falls back.
- The system supports both code-backed papers and evidence-backed papers.

## Current Capabilities

- Parse a PDF into a local review workspace.
- Run multi-round critic/defender loops.
- Persist prompts, responses, metadata, and raw API output.
- Track round-level issues and canonical cross-round issues.
- Feed canonical issue history back into later prompts.
- Generate defender checklists from unresolved canonical issues.
- Record provider health and stop wasting calls after quota exhaustion.
- Produce unified synthesis and final scorecards.
- Run evidence-backed judge checks for figures, tables, and numeric context.
- Run code-backed judge checks by executing a reproducibility command inside a staged source snapshot.
- Run batch reviews across multiple PDF files.
- Persist structured judge artifacts such as `execution.json`, `table_consistency.json`, `TABLE_ANALYSIS.txt`, and batch `LEADERBOARD.md`.

## Main Outputs

Each run produces a local Git repository at `review_repo/` with artifacts such as:

- `reviews/FINAL_REPORT.md`
- `reviews/TIMELINE.md`
- `reviews/ISSUES.txt`
- `reviews/TABLE_ANALYSIS.txt`
- `reviews/CANONICAL_HISTORY.txt`
- `reviews/FINAL_SCORECARD.json`
- `reviews/SYNTHESIS.txt`
- `meta/accountability.json`
- `meta/provider_health.json`
- `runs/<round>/execution.json`
- `runs/<round>/run_manifest.json`
- `runs/<round>/stdout.txt`
- `runs/<round>/stderr.txt`
- `runs/<round>/table_consistency.json`
- `runs/<round>/table_blocks.json`
- `runs/<round>/claim_alignment.json`

## Key Scripts

- `run_review.py`
  Runs one paper review.

- `batch_review.py`
  Runs multiple paper reviews from a directory and stores each result in a batch output folder.
  It also exports the user-facing reports to `../final_report/<timestamp>_batch/`.

- `review_api.py`
  Exposes FastAPI endpoints for single-review, batch-review, async job polling, and the browser console UI.
- `DSPy`
  The synthesis stage can now optionally run through DSPy first, then fall back to the existing client path if DSPy fails.

## Example Commands

Run one paper from the packaged layout:

```powershell
D:\anaconda\envs\for_codeX\python.exe run_review.py --paper "CUFE at SemEval-2016.pdf" --rounds 2
```

Run one code-backed paper review:

```powershell
D:\anaconda\envs\for_codeX\python.exe run_review.py --paper "CUFE at SemEval-2016.pdf" --rounds 2 --code-dir "." --run-command "D:\anaconda\envs\for_codeX\python.exe -m compileall llm_gan_review"
```

Run a batch:

```powershell
D:\anaconda\envs\for_codeX\python.exe batch_review.py --paper-dir "." --glob "*.pdf" --rounds 2 --limit 3
```

Run a mixed batch from a spec file:

```json
[
  {
    "paper": "paper_a.pdf",
    "rounds": 2
  },
  {
    "paper": "paper_b.pdf",
    "rounds": 2,
    "code_dir": ".",
    "run_command": "D:\\anaconda\\envs\\for_codeX\\python.exe -m compileall llm_gan_review"
  }
]
```

```powershell
D:\anaconda\envs\for_codeX\python.exe batch_review.py --paper-dir "." --batch-spec "batch_spec.json"
```

Run the API server:

```powershell
D:\anaconda\envs\for_codeX\python.exe -m uvicorn review_api:app --host 127.0.0.1 --port 8000
```

The packaged folder layout is:

- `../essay/`
  Put PDF papers here.
- `../api_settings/llm_api_config.json`
  Put model API configuration here.
- `./`
  Contains the code, frontend, outputs, and review artifacts.
- `../final_report/`
  Contains only the user-facing final reports. Internal manifests, rankings, and diagnostics stay under `batch_runs/` or `review_repo/`.

Open the browser console:

```text
http://127.0.0.1:8000/
```

The frontend can launch review jobs, poll progress, show the current debate stage, and display a round-by-round debate timeline with critic plan, critic output, defender plan, defender checklist, defender output, PUA, and judge notes.

## Config

Fill `llm_api_config.json` with:

- provider
- model
- api key
- base url

The current setup supports Google Gemini and OpenRouter-compatible chat endpoints.

## Notes

- When provider quota is exhausted, the system now blocks later calls for that provider during the same run.
- Evidence judge checks are still text-level and heuristic. They are stronger than before, but not yet image-forensics grade.
- Evidence judge now also estimates whether extracted claims are supported by nearby figure/table captions and table blocks.
- Batch output now includes `manifest.json`, `AGGREGATE_RESULTS.json`, and `BATCH_SUMMARY.txt` with ranking and average scores.
- Batch output also includes `BATCH_INSIGHTS.json`, `BATCH_INSIGHTS.md`, and `LEADERBOARD.md` for common-risk and strongest/weakest-paper summaries.
- Batch output now also includes `FINAL_BATCH_REPORT.md`, which rolls rankings, strongest/weakest papers, common risk categories, and persistent issues into one readable summary.
- Batch runs now export only the user-facing per-paper reports plus `FINAL_BATCH_REPORT.md` to the outer `../final_report/` directory, so non-technical users can just open that folder.
- Code-mode runs now also emit `runs/<round>/execution.json`; evidence-mode runs emit `runs/<round>/table_consistency.json`.
- Progress is logged in `PROJECT_STEPS.txt`.
