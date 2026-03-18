from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llm_gan_review.config import AppConfig
from llm_gan_review.review import ReviewOrchestrator


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run a minimal LLM-GAN review round.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--simulate-busywork-round", type=int, default=None)
    parser.add_argument("--code-dir", default=None)
    parser.add_argument("--run-command", default=None)
    args = parser.parse_args()

    program_dir = Path(__file__).resolve().parent
    workspace_dir = program_dir.parent
    config = AppConfig.load(_resolve_config_path(program_dir, workspace_dir, args.config))
    orchestrator = ReviewOrchestrator(root_dir=program_dir, config=config)
    result = orchestrator.run_review(
        _resolve_paper_path(program_dir, workspace_dir, args.paper),
        rounds=args.rounds,
        simulate_busywork_round=args.simulate_busywork_round,
        code_dir=_resolve_code_dir(program_dir, workspace_dir, args.code_dir) if args.code_dir else None,
        run_command=args.run_command,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


def _resolve_config_path(program_dir: Path, workspace_dir: Path, config_arg: str | None) -> Path:
    candidates = []
    if config_arg:
        raw = Path(config_arg)
        candidates.extend([raw, program_dir / raw, workspace_dir / raw, workspace_dir / "api_settings" / raw.name])
    else:
        candidates.extend([workspace_dir / "api_settings" / "llm_api_config.json", program_dir / "llm_api_config.json"])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError("Could not find llm_api_config.json. Expected it under api_settings/.")


def _resolve_paper_path(program_dir: Path, workspace_dir: Path, paper_arg: str) -> Path:
    raw = Path(paper_arg)
    candidates = [raw, program_dir / raw, workspace_dir / raw, workspace_dir / "essay" / raw.name]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Could not find paper: {paper_arg}")


def _resolve_code_dir(program_dir: Path, workspace_dir: Path, code_arg: str) -> Path:
    raw = Path(code_arg)
    candidates = [raw, program_dir / raw, workspace_dir / raw, workspace_dir / "essay" / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Could not find code directory: {code_arg}")


if __name__ == "__main__":
    main()
