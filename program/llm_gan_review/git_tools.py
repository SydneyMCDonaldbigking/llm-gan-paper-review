from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CommitRecord:
    sha: str
    message: str
    author_name: str
    author_email: str
    created_at: datetime


class GitRepositoryManager:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path

    def init_repo(self) -> None:
        self.repo_path.mkdir(parents=True, exist_ok=True)
        if not (self.repo_path / ".git").exists():
            self._run("git init")
            self._run('git branch -M main')

    def commit_all(self, message: str, author_name: str, author_email: str) -> CommitRecord:
        self._run("git add .")
        self._run(f'git commit --allow-empty --author="{author_name} <{author_email}>" -m "{message}"')
        sha = self._run("git rev-parse HEAD").strip()
        return CommitRecord(
            sha=sha,
            message=message,
            author_name=author_name,
            author_email=author_email,
            created_at=datetime.now(timezone.utc),
        )

    def diff_last_commit(self) -> str:
        try:
            return self._run("git diff HEAD~1 HEAD")
        except RuntimeError:
            return ""

    def log_oneline(self) -> str:
        return self._run("git --no-pager log --oneline --decorate")

    def _run(self, command: str) -> str:
        completed = subprocess.run(
            command,
            cwd=self.repo_path,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
        return completed.stdout
