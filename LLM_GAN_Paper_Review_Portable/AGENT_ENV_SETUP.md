# Agent Environment Setup

This document is for a new operator or coding agent who needs to run the project from scratch on Windows.

## Workspace Layout

Root workspace:

- `C:\Users\zzyyds\Desktop\全自动化胡说八道学术机`

Important folders:

- `program/`
  Contains backend, frontend, scripts, and runtime outputs.
- `essay/`
  Put PDF papers here if using the file-based workflow.
- `api_settings/`
  Stores `llm_api_config.json`.
- `final_report/`
  User-facing exported reports.

## Recommended Python Environment

This project is currently known to work with:

- Anaconda environment name: `for_codeX`
- Python version: `3.12.x`

If the environment already exists, activate it:

```powershell
conda activate for_codeX
```

If the environment does not exist yet, create it:

```powershell
conda create -n for_codeX python=3.12 -y
conda activate for_codeX
```

## Install Dependencies

From the workspace root:

```powershell
cd "C:\Users\zzyyds\Desktop\全自动化胡说八道学术机\program"
D:\anaconda\envs\for_codeX\python.exe -m pip install -r requirements.txt
```

If `python-multipart` is missing for file uploads, install explicitly:

```powershell
D:\anaconda\envs\for_codeX\python.exe -m pip install python-multipart
```

## API Configuration

Config file location:

- `C:\Users\zzyyds\Desktop\全自动化胡说八道学术机\api_settings\llm_api_config.json`

The project expects that file to exist before running reviews.

Supported providers in the current codebase:

- Google Gemini / Gemma
- OpenRouter-compatible GPT endpoint

## Run The Web App

Start from:

```powershell
cd "C:\Users\zzyyds\Desktop\全自动化胡说八道学术机\program"
```

Launch the local server:

```powershell
D:\anaconda\envs\for_codeX\python.exe -m uvicorn review_api:app --host 127.0.0.1 --port 8000
```

Open in browser:

- `http://127.0.0.1:8000/`

There is also a shortcut at:

- `C:\Users\zzyyds\Desktop\全自动化胡说八道学术机\start_program.url`

Important:

- The shortcut only opens the browser.
- The FastAPI server must already be running.

## Run Single Review From Command Line

```powershell
cd "C:\Users\zzyyds\Desktop\全自动化胡说八道学术机\program"
D:\anaconda\envs\for_codeX\python.exe run_review.py --paper "CUFE at SemEval-2016.pdf" --rounds 1
```

The `--paper` value can be:

- a filename already present in `essay/`
- or an explicit path if needed

## Run Batch Review From Command Line

To process every PDF in `essay/`:

```powershell
cd "C:\Users\zzyyds\Desktop\全自动化胡说八道学术机\program"
D:\anaconda\envs\for_codeX\python.exe batch_review.py --rounds 1
```

## Outputs

Internal runtime outputs:

- `program/review_repo/`
- `program/batch_runs/`
- `program/api_runs/`

User-facing outputs:

- `final_report/`

## File Upload Workflow In The Frontend

Current frontend behavior:

- Click `选择论文文件`
- Pick one or more PDF files
- Files are uploaded into `essay/`
- Then select one or more papers from the rendered paper list
- One selected paper starts a single review
- Multiple selected papers start a batch review

## Sanity Checks

Check that the API can boot:

```powershell
cd "C:\Users\zzyyds\Desktop\全自动化胡说八道学术机\program"
D:\anaconda\envs\for_codeX\python.exe -m compileall review_api.py web\static\app.js
```

Check that papers are visible:

```powershell
@'
import sys, json
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import review_api
print(json.dumps(review_api.list_papers(), ensure_ascii=False, indent=2))
'@ | D:\anaconda\envs\for_codeX\python.exe -
```

## Common Problems

If the frontend opens but uploads fail:

- confirm `python-multipart` is installed

If papers do not appear:

- confirm PDF files are inside `essay/`
- confirm the server was restarted after code changes

If the browser looks stale:

- hard refresh with `Ctrl+F5`

If model calls fail:

- check `api_settings/llm_api_config.json`
- check provider quota and API keys

## Current Status

This project is suitable for:

- personal use
- internal testing
- small-scale pilot runs

It should still be treated as a beta system rather than a hardened production service.
