from __future__ import annotations

import json
import os
import shutil
import stat
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from batch_review import (
    _build_aggregate,
    _build_batch_insights,
    _build_batch_insights_markdown,
    _build_final_batch_report,
    _build_leaderboard_markdown,
)
from llm_gan_review.config import AppConfig
from llm_gan_review.review import ReviewOrchestrator
from runtime_paths import get_bundle_dir, get_runtime_program_dir, get_workspace_dir


ROOT_DIR = get_runtime_program_dir()
WORKSPACE_DIR = get_workspace_dir()
BUNDLE_DIR = get_bundle_dir()
WEB_DIR = BUNDLE_DIR / "web"
STATIC_DIR = WEB_DIR / "static"
CONFIG = AppConfig.load((WORKSPACE_DIR / "api_settings" / "llm_api_config.json") if (WORKSPACE_DIR / "api_settings" / "llm_api_config.json").exists() else (ROOT_DIR / "llm_api_config.json"))
app = FastAPI(title="LLM-GAN Review API", version="0.2.0")
API_RUNS_DIR = ROOT_DIR / "api_runs"
JOBS_DIR = API_RUNS_DIR / "jobs"
API_RUNS_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
RUN_LOCK = threading.Lock()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ReviewRequest(BaseModel):
    paper: str
    rounds: int = 2
    code_dir: str | None = None
    run_command: str | None = None
    simulate_busywork_round: int | None = None


class BatchEntry(BaseModel):
    paper: str
    rounds: int = 2
    code_dir: str | None = None
    run_command: str | None = None


class BatchRequest(BaseModel):
    entries: list[BatchEntry] = Field(default_factory=list)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    running_jobs = sum(1 for job in _load_jobs() if job["status"] == "running")
    return {"status": "ok", "running_jobs": running_jobs}


@app.get("/papers")
def list_papers() -> dict:
    essay_dir = WORKSPACE_DIR / "essay"
    papers = []
    if essay_dir.exists():
        for path in sorted(essay_dir.glob("*.pdf")):
            papers.append(
                {
                    "name": path.name,
                    "path": str(path),
                }
            )
    return {"papers": papers}


@app.post("/papers/upload")
async def upload_papers(files: list[UploadFile] = File(...)) -> dict:
    essay_dir = WORKSPACE_DIR / "essay"
    essay_dir.mkdir(parents=True, exist_ok=True)
    uploaded: list[dict[str, str]] = []
    for upload in files:
        filename = Path(upload.filename or "").name
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"Only PDF files are supported: {filename}")
        target = essay_dir / filename
        content = await upload.read()
        target.write_bytes(content)
        uploaded.append(
            {
                "name": filename,
                "path": str(target.resolve()),
                "saved_to_essay": str(essay_dir.resolve()),
                "size_bytes": len(content),
            }
        )
    return {"uploaded": uploaded, "paper_count": len(uploaded), "essay_dir": str(essay_dir.resolve())}


@app.get("/reviews/history")
def review_history() -> dict:
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(API_RUNS_DIR.glob("*.json"), reverse=True)[:20]]
    return {"runs": runs}


@app.get("/reviews/history/{run_id}")
def review_history_item(run_id: str) -> dict:
    path = API_RUNS_DIR / f"{run_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/reviews/run")
def run_review_sync(request: ReviewRequest) -> dict:
    orchestrator = ReviewOrchestrator(root_dir=ROOT_DIR, config=CONFIG)
    result = orchestrator.run_review(
        _resolve_paper_path(request.paper),
        rounds=request.rounds,
        simulate_busywork_round=request.simulate_busywork_round,
        code_dir=_resolve_code_dir(request.code_dir) if request.code_dir else None,
        run_command=request.run_command,
    )
    run_id = _write_api_run("review", request.model_dump(), result)
    return {"run_id": run_id, "result": result}


@app.post("/batch/run")
def run_batch_sync(request: BatchRequest) -> dict:
    payload = _execute_batch(request)
    run_id = _write_api_run("batch", request.model_dump(), payload)
    return {"run_id": run_id, "result": payload}


@app.post("/jobs/review")
def start_review_job(request: ReviewRequest) -> dict:
    job_id = _create_job("review", request.model_dump())
    thread = threading.Thread(target=_run_review_job, args=(job_id, request.model_dump()), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


@app.post("/jobs/batch")
def start_batch_job(request: BatchRequest) -> dict:
    job_id = _create_job("batch", request.model_dump())
    thread = threading.Thread(target=_run_batch_job, args=(job_id, request.model_dump()), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs")
def list_jobs() -> dict:
    return {"jobs": _load_jobs()}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return _read_job(job_id)


@app.get("/jobs/{job_id}/artifacts")
def get_job_artifacts(job_id: str) -> dict:
    job = _read_job(job_id)
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job.get("progress", {}),
        "artifacts": job.get("artifacts") or _collect_artifact_snapshot(),
    }


@app.post("/admin/cleanup")
def cleanup_runtime_data() -> dict:
    removed: list[str] = []
    recreated: list[str] = []
    targets = [
        ROOT_DIR / "review_repo",
        ROOT_DIR / "batch_runs",
        ROOT_DIR / "api_runs",
        WORKSPACE_DIR / "final_report",
    ]
    for target in targets:
        if target.exists():
            shutil.rmtree(target, onexc=_handle_remove_readonly)
            removed.append(str(target))
        target.mkdir(parents=True, exist_ok=True)
        recreated.append(str(target))

    # Recreate nested runtime folders expected by the app.
    for nested in [ROOT_DIR / "api_runs" / "jobs"]:
        nested.mkdir(parents=True, exist_ok=True)
        recreated.append(str(nested))

    return {
        "status": "ok",
        "removed": removed,
        "recreated": recreated,
        "preserved": [
            str(WORKSPACE_DIR / "essay"),
            str(WORKSPACE_DIR / "api_settings"),
            str(ROOT_DIR),
        ],
    }


def _run_review_job(job_id: str, request_body: dict) -> None:
    _update_job(job_id, {"status": "queued", "progress": {"phase": "queued", "message": "Waiting for execution slot.", "percent": 0}})
    with RUN_LOCK:
        stop_event = threading.Event()
        monitor = threading.Thread(
            target=_monitor_review_progress,
            args=(job_id, request_body.get("rounds", 2), stop_event),
            daemon=True,
        )
        try:
            _update_job(
                job_id,
                {
                    "status": "running",
                    "started_at": _utc_now(),
                    "progress": {"phase": "initializing", "message": "Preparing review repository.", "percent": 3},
                },
            )
            monitor.start()
            orchestrator = ReviewOrchestrator(root_dir=ROOT_DIR, config=CONFIG)
            result = orchestrator.run_review(
                _resolve_paper_path(request_body["paper"]),
                rounds=request_body.get("rounds", 2),
                simulate_busywork_round=request_body.get("simulate_busywork_round"),
                code_dir=_resolve_code_dir(request_body["code_dir"]) if request_body.get("code_dir") else None,
                run_command=request_body.get("run_command"),
            )
            run_id = _write_api_run("review", request_body, result)
            stop_event.set()
            monitor.join(timeout=2)
            _update_job(
                job_id,
                {
                    "status": "completed",
                    "finished_at": _utc_now(),
                    "run_id": run_id,
                    "result": result,
                    "artifacts": _collect_artifact_snapshot(),
                    "progress": {
                        **_collect_review_progress(request_body.get("rounds", 2)),
                        "phase": "completed",
                        "message": "Review completed.",
                        "percent": 100,
                    },
                },
            )
        except Exception as exc:
            stop_event.set()
            monitor.join(timeout=2)
            _update_job(
                job_id,
                {
                    "status": "failed",
                    "finished_at": _utc_now(),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "artifacts": _collect_artifact_snapshot(),
                    "progress": {
                        **_collect_review_progress(request_body.get("rounds", 2)),
                        "phase": "failed",
                        "message": "Review failed.",
                    },
                },
            )


def _run_batch_job(job_id: str, request_body: dict) -> None:
    entries = request_body.get("entries", [])
    _update_job(job_id, {"status": "queued", "progress": {"phase": "queued", "message": "Waiting for execution slot.", "percent": 0}})
    with RUN_LOCK:
        try:
            _update_job(
                job_id,
                {
                    "status": "running",
                    "started_at": _utc_now(),
                    "progress": {"phase": "batch_running", "message": "Batch review started.", "percent": 2, "completed_entries": 0, "total_entries": len(entries)},
                },
            )
            manifest: list[dict[str, Any]] = []
            for index, entry in enumerate(entries, start=1):
                _update_job(
                    job_id,
                    {
                        "progress": {
                            "phase": "batch_running",
                            "message": f"Running paper {index}/{len(entries)}: {Path(entry['paper']).name}",
                            "percent": min(95, int(((index - 1) / max(len(entries), 1)) * 100)),
                            "completed_entries": index - 1,
                            "total_entries": len(entries),
                            "current_entry": Path(entry["paper"]).name,
                        }
                    },
                )
                orchestrator = ReviewOrchestrator(root_dir=ROOT_DIR, config=CONFIG)
                result = orchestrator.run_review(
                    _resolve_paper_path(entry["paper"]),
                    rounds=entry.get("rounds", 2),
                    code_dir=_resolve_code_dir(entry["code_dir"]) if entry.get("code_dir") else None,
                    run_command=entry.get("run_command"),
                )
                manifest.append(
                    {
                        "paper": Path(entry["paper"]).name,
                        "paper_title": result["paper_title"],
                        "review_mode": result["review_mode"],
                        "requested_rounds": entry.get("rounds", 2),
                        "final_recommendation": result["final_recommendation"],
                        "overall_score": result["overall_score"],
                        "canonical_issue_count": result["canonical_issue_count"],
                        "issues_path": str(ROOT_DIR / "review_repo" / "reviews" / "issues.json"),
                        "scorecard_path": str(ROOT_DIR / "review_repo" / "reviews" / "FINAL_SCORECARD.json"),
                        "target_dir": str(ROOT_DIR / "review_repo"),
                    }
                )
            aggregate = _build_aggregate(manifest)
            insights = _build_batch_insights(manifest)
            payload = {
                "paper_count": len(manifest),
                "manifest": manifest,
                "aggregate": aggregate,
                "insights": insights,
                "leaderboard_markdown": _build_leaderboard_markdown(aggregate),
                "insights_markdown": _build_batch_insights_markdown(insights),
                "final_batch_report_markdown": _build_final_batch_report(aggregate, insights, manifest),
            }
            run_id = _write_api_run("batch", request_body, payload)
            _update_job(
                job_id,
                {
                    "status": "completed",
                    "finished_at": _utc_now(),
                    "run_id": run_id,
                    "result": payload,
                    "artifacts": {
                        "final_report": payload["final_batch_report_markdown"],
                        "judge": payload["insights_markdown"],
                        "scorecard": payload["aggregate"],
                        "timeline": payload["leaderboard_markdown"],
                    },
                    "progress": {
                        "phase": "completed",
                        "message": "Batch review completed.",
                        "percent": 100,
                        "completed_entries": len(entries),
                        "total_entries": len(entries),
                    },
                },
            )
        except Exception as exc:
            _update_job(
                job_id,
                {
                    "status": "failed",
                    "finished_at": _utc_now(),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "artifacts": {},
                    "progress": {"phase": "failed", "message": "Batch review failed."},
                },
            )


def _monitor_review_progress(job_id: str, requested_rounds: int, stop_event: threading.Event) -> None:
    previous_payload: dict[str, Any] | None = None
    while not stop_event.wait(1.0):
        payload = _collect_review_progress(requested_rounds)
        if payload != previous_payload:
            _update_job(job_id, {"progress": payload})
            previous_payload = payload


def _collect_review_progress(requested_rounds: int) -> dict:
    repo_dir = ROOT_DIR / "review_repo"
    reviews_dir = repo_dir / "reviews"
    rounds_dir = reviews_dir / "rounds"
    progress = {
        "phase": "initializing",
        "message": "Preparing review repository.",
        "percent": 2,
        "requested_rounds": requested_rounds,
        "rounds_detected": 0,
        "current_round": None,
        "round_phase": None,
        "review_mode": None,
    }
    review_job_path = repo_dir / "meta" / "review_job.json"
    if review_job_path.exists():
        try:
            progress["review_mode"] = json.loads(review_job_path.read_text(encoding="utf-8")).get("mode")
            progress["phase"] = "repo_ready"
            progress["message"] = "Review repository initialized."
            progress["percent"] = 8
        except json.JSONDecodeError:
            pass
    if not rounds_dir.exists():
        if (reviews_dir / "FINAL_REPORT.md").exists():
            progress.update({"phase": "finalizing", "message": "Generating final report.", "percent": 95})
        return progress

    round_dirs = sorted(path for path in rounds_dir.iterdir() if path.is_dir() and path.name.isdigit())
    if not round_dirs:
        return progress

    current_round_dir = round_dirs[-1]
    current_round = int(current_round_dir.name)
    base_percent = 10 + int(((current_round - 1) / max(requested_rounds, 1)) * 80)
    round_phase = "started"
    phase_bonus = 0
    message = f"Round {current_round} started."
    if (current_round_dir / "critic.md").exists():
        round_phase = "critic_complete"
        phase_bonus = 12
        message = f"Round {current_round}: Gemini Critic finished."
    if (current_round_dir / "defender.md").exists():
        round_phase = "defender_complete"
        phase_bonus = 26
        message = f"Round {current_round}: GPT Defender finished."
    if (current_round_dir / "busywork_check.json").exists():
        round_phase = "busywork_checked"
        phase_bonus = 36
        message = f"Round {current_round}: Busywork check completed."
    if (current_round_dir / "pua_assessment.json").exists():
        round_phase = "pua_checked"
        phase_bonus = 48
        message = f"Round {current_round}: PUA assessment recorded."
    if (repo_dir / "runs" / current_round_dir.name / "judge.md").exists():
        round_phase = "judge_complete"
        phase_bonus = 66
        message = f"Round {current_round}: Judge finished verification."
    if current_round >= requested_rounds and (reviews_dir / "FINAL_REPORT.md").exists():
        round_phase = "finalizing"
        phase_bonus = 80
        message = "Final report generated."

    progress.update(
        {
            "phase": "running",
            "message": message,
            "percent": min(95, base_percent + phase_bonus),
            "rounds_detected": len(round_dirs),
            "current_round": current_round_dir.name,
            "round_phase": round_phase,
            "latest_round_files": sorted(path.name for path in current_round_dir.iterdir() if path.is_file())[:12],
        }
    )
    return progress


def _collect_artifact_snapshot() -> dict:
    repo_dir = ROOT_DIR / "review_repo"
    reviews_dir = repo_dir / "reviews"
    rounds_dir = reviews_dir / "rounds"
    latest_round = None
    if rounds_dir.exists():
        round_dirs = sorted(path for path in rounds_dir.iterdir() if path.is_dir() and path.name.isdigit())
        latest_round = round_dirs[-1] if round_dirs else None
    snapshot = {
        "final_report": _read_text_preview(reviews_dir / "FINAL_REPORT.md"),
        "timeline": _read_text_preview(reviews_dir / "TIMELINE.md", 12000),
        "issues": _read_text_preview(reviews_dir / "ISSUES.txt", 12000),
        "table_analysis": _read_text_preview(reviews_dir / "TABLE_ANALYSIS.txt", 12000),
        "latest_round": latest_round.name if latest_round else None,
        "rounds": _collect_round_snapshots(repo_dir, round_dirs if rounds_dir.exists() else []),
        "critic": _read_text_preview(latest_round / "critic.md" if latest_round else None, 6000),
        "defender": _read_text_preview(latest_round / "defender.md" if latest_round else None, 6000),
        "pua": _read_text_preview(latest_round / "pua.md" if latest_round else None, 4000),
        "judge": _read_text_preview(repo_dir / "runs" / latest_round.name / "judge.md" if latest_round else None, 8000),
    }
    scorecard_path = reviews_dir / "FINAL_SCORECARD.json"
    snapshot["scorecard"] = json.loads(scorecard_path.read_text(encoding="utf-8")) if scorecard_path.exists() else None
    return snapshot


def _read_text_preview(path: Path | None, limit: int | None = None) -> str:
    if not path or not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text if limit is None else text[:limit]


def _collect_round_snapshots(repo_dir: Path, round_dirs: list[Path]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for round_dir in round_dirs:
        run_dir = repo_dir / "runs" / round_dir.name
        snapshots.append(
            {
                "round": round_dir.name,
                "critic_plan": _read_text_preview(round_dir / "critic_plan.txt", 2000),
                "critic_prompt": _read_text_preview(round_dir / "critic_prompt.txt", 2500),
                "critic": _read_text_preview(round_dir / "critic.md", 2500),
                "critic_dspy_draft": _read_text_preview(round_dir / "critic_dspy_draft.txt", 2000),
                "defender_plan": _read_text_preview(round_dir / "defender_plan.txt", 2000),
                "defender_checklist": _read_text_preview(round_dir / "defender_checklist.txt", 2000),
                "defender_prompt": _read_text_preview(round_dir / "defender_prompt.txt", 2500),
                "defender": _read_text_preview(round_dir / "defender.md", 2500),
                "defender_dspy_draft": _read_text_preview(round_dir / "defender_dspy_draft.txt", 2000),
                "busywork": _read_text_preview(round_dir / "busywork_check.json", 1200),
                "pua": _read_text_preview(round_dir / "pua.md", 1800),
                "escalation_plan": _read_text_preview(round_dir / "escalation_plan.txt", 1800),
                "judge": _read_text_preview(run_dir / "judge.md", 2200),
                "judge_meta": _read_text_preview(run_dir / "judge_meta.json", 1200),
            }
        )
    return snapshots


def _create_job(kind: str, request_body: dict) -> str:
    job_id = f"{kind}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    record = {
        "job_id": job_id,
        "kind": kind,
        "status": "queued",
        "created_at": _utc_now(),
        "request": request_body,
        "result": None,
        "error": None,
        "progress": {"phase": "queued", "message": "Queued.", "percent": 0},
    }
    _write_job_record(job_id, record)
    return job_id


def _write_job_record(job_id: str, record: dict) -> None:
    (JOBS_DIR / f"{job_id}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_job(job_id: str) -> dict:
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _update_job(job_id: str, patch: dict) -> None:
    record = _read_job(job_id)
    _deep_update(record, patch)
    _write_job_record(job_id, record)


def _load_jobs() -> list[dict]:
    jobs = [json.loads(path.read_text(encoding="utf-8")) for path in JOBS_DIR.glob("*.json")]
    return sorted(jobs, key=lambda item: item.get("created_at", ""), reverse=True)


def _deep_update(target: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _write_api_run(kind: str, request_body: dict, result: dict) -> str:
    run_id = f"{kind}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"
    record = {
        "run_id": run_id,
        "kind": kind,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "request": request_body,
        "result": result,
    }
    (API_RUNS_DIR / f"{run_id}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return run_id


def _execute_batch(request: BatchRequest) -> dict:
    manifest: list[dict] = []
    for entry in request.entries:
        orchestrator = ReviewOrchestrator(root_dir=ROOT_DIR, config=CONFIG)
        result = orchestrator.run_review(
            _resolve_paper_path(entry.paper),
            rounds=entry.rounds,
            code_dir=_resolve_code_dir(entry.code_dir) if entry.code_dir else None,
            run_command=entry.run_command,
        )
        manifest.append(
            {
                "paper": Path(entry.paper).name,
                "paper_title": result["paper_title"],
                "review_mode": result["review_mode"],
                "requested_rounds": entry.rounds,
                "final_recommendation": result["final_recommendation"],
                "overall_score": result["overall_score"],
                "canonical_issue_count": result["canonical_issue_count"],
                "issues_path": str(ROOT_DIR / "review_repo" / "reviews" / "issues.json"),
                "scorecard_path": str(ROOT_DIR / "review_repo" / "reviews" / "FINAL_SCORECARD.json"),
                "target_dir": str(ROOT_DIR / "review_repo"),
            }
        )
    aggregate = _build_aggregate(manifest)
    insights = _build_batch_insights(manifest)
    return {
        "paper_count": len(manifest),
        "manifest": manifest,
        "aggregate": aggregate,
        "insights": insights,
        "leaderboard_markdown": _build_leaderboard_markdown(aggregate),
        "insights_markdown": _build_batch_insights_markdown(insights),
        "final_batch_report_markdown": _build_final_batch_report(aggregate, insights, manifest),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_paper_path(paper_arg: str) -> Path:
    raw = Path(paper_arg)
    candidates = [raw, ROOT_DIR / raw, WORKSPACE_DIR / raw, WORKSPACE_DIR / "essay" / raw.name]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Could not find paper: {paper_arg}")


def _resolve_code_dir(code_arg: str) -> Path:
    raw = Path(code_arg)
    candidates = [raw, ROOT_DIR / raw, WORKSPACE_DIR / raw, WORKSPACE_DIR / "essay" / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Could not find code directory: {code_arg}")


def _handle_remove_readonly(func, path, excinfo) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)
