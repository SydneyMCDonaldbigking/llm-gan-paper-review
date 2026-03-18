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

## Quick Start

Start the web app:

```powershell
cd "C:\Users\zzyyds\Desktop\LLM_GAN_paper\program"
D:\anaconda\envs\for_codeX\python.exe -m uvicorn review_api:app --host 127.0.0.1 --port 8000
```

Open:

- [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

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
