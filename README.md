# llm-gan-paper-review

Git-first adversarial paper review system with multi-round LLM debate, DSPy orchestration, judge pipelines, and multilingual final reports.

## What It Does

This project turns paper reviewing into a tracked debate workflow:

- `Gemini / Gemma` acts as the critic
- `GPT / OpenRouter` acts as the defender
- `DSPy` helps orchestrate synthesis, issue merge, checklists, judge summaries, and recommendation logic
- every round is written to disk and committed into a Git review repository
- final reports are exported in Chinese, Japanese, and English

The system supports both:

- evidence-backed papers
- code-backed papers with executable reproducibility commands

## Why It Is Different

Instead of producing a one-shot review summary, this system keeps the full review history:

- who attacked what
- how the defense responded
- whether a round was real progress or just busywork
- when escalation happened
- how the final verdict was reached

That makes the review process:

- auditable
- replayable
- easier to debug
- easier to present

## Main Features

- Multi-round critic vs defender debate
- Git-first round tracking
- Busywork detection
- PUA-style escalation
- DSPy-assisted orchestration
- Evidence judge for claims, tables, and report alignment
- Code judge for reproducibility commands and metric checks
- Frontend console for progress and debate viewing
- Single-paper and batch review flows
- Multilingual final report packaging

## Folder Layout

- `program/`
  Main codebase, API server, frontend, and scripts
- `essay/`
  PDF papers for review
- `api_settings/`
  API configuration
- `final_report/`
  User-facing exported reports

## Portable EXE

If you want the download-and-run version, use:

- `LLM_GAN_Paper_Review_Portable/LLM_GAN_Paper_Review.exe`

The portable app reads and writes files next to the exe:

- `LLM_GAN_Paper_Review_Portable/api_settings/`
- `LLM_GAN_Paper_Review_Portable/essay/`
- `LLM_GAN_Paper_Review_Portable/final_report/`

## API Configuration Reminder

Both model providers should be configured before running:

- Google / Gemini
- OpenRouter / GPT-side model

For the source-code workflow, edit:

- `api_settings/llm_api_config.json`

For the portable exe workflow, edit:

- `LLM_GAN_Paper_Review_Portable/api_settings/llm_api_config.json`

If only one side is configured, the debate can fall back or degrade.

## Quick Start

Start the web app:

```powershell
cd "C:\Users\zzyyds\Desktop\LLM_GAN_paper\program"
D:\anaconda\envs\for_codeX\python.exe -m uvicorn review_api:app --host 127.0.0.1 --port 8000
```

Open:

- [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

## Output Locations

If you run from command line / source code:

- final user-facing reports: `final_report/`
- review runtime repository: `program/review_repo/`
- batch runtime outputs: `program/batch_runs/`
- API/job runtime state: `program/api_runs/`

If you run from the portable exe:

- final user-facing reports: `LLM_GAN_Paper_Review_Portable/final_report/`
- uploaded papers: `LLM_GAN_Paper_Review_Portable/essay/`
- API config: `LLM_GAN_Paper_Review_Portable/api_settings/`
- runtime internals: `LLM_GAN_Paper_Review_Portable/program_runtime/`

## Docs

- [AGENT_ENV_SETUP.md](AGENT_ENV_SETUP.md)
- [USER_QUICKSTART.md](USER_QUICKSTART.md)
- [program/README.md](program/README.md)

## Current Status

This repository is suitable for:

- personal use
- internal demos
- pilot testing

It should still be treated as a beta system rather than a hardened production service.
