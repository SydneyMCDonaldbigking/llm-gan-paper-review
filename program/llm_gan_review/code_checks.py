from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodeExecutionResult:
    report: str
    scorecard: dict
    artifacts: dict


class CodeExecutionJudgeRunner:
    def run(
        self,
        code_dir: Path,
        command: str,
        history_summary: str,
        expected_metrics: list[dict] | None = None,
    ) -> CodeExecutionResult:
        started_at = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=code_dir,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=True,
        )
        duration_seconds = round(time.perf_counter() - started_at, 3)
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        success = completed.returncode == 0
        command_kind = self._classify_command(command)
        stdout_preview = self._preview_lines(stdout)
        stderr_preview = self._preview_lines(stderr)
        failure_signature = self._failure_signature(stderr, completed.returncode)
        metric_alignment = self._align_metrics(expected_metrics or [], stdout, stderr)
        environment_snapshot = self._environment_snapshot(code_dir)
        test_summary = self._test_summary(command_kind, stdout, stderr)
        scorecard = {
            "artifact_mode": "code",
            "command": command,
            "command_kind": command_kind,
            "exit_code": completed.returncode,
            "duration_seconds": duration_seconds,
            "stdout_lines": len(stdout.splitlines()) if stdout else 0,
            "stderr_lines": len(stderr.splitlines()) if stderr else 0,
            "stdout_preview": stdout_preview,
            "stderr_preview": stderr_preview,
            "failure_signature": failure_signature,
            "environment_snapshot": environment_snapshot,
            "test_summary": test_summary,
            "metric_alignment": metric_alignment,
            "checks": {
                "command_executed": True,
                "command_succeeded": success,
                "stderr_present": bool(stderr),
                "history_available": bool(history_summary),
                "stdout_present": bool(stdout),
                "test_like_command": command_kind in {"pytest", "unittest", "compileall"},
                "metric_alignment_checked": bool(expected_metrics),
                "claimed_metrics_matched": metric_alignment["matched_count"] > 0,
                "partial_metric_alignment": metric_alignment["partially_matched_count"] > 0,
            },
            "confidence": "stable" if success else "preliminary",
        }
        artifacts = {
            "command": command,
            "command_kind": command_kind,
            "exit_code": completed.returncode,
            "duration_seconds": duration_seconds,
            "stdout_preview": stdout_preview,
            "stderr_preview": stderr_preview,
            "failure_signature": failure_signature,
            "environment_snapshot": environment_snapshot,
            "test_summary": test_summary,
            "metric_alignment": metric_alignment,
            "stdout_text": stdout,
            "stderr_text": stderr,
            "stdout_excerpt": stdout[:4000],
            "stderr_excerpt": stderr[:4000],
        }
        lines = [
            "# Code Reproducibility Verification",
            "",
            f"- Command: {command}",
            f"- Command kind: {command_kind}",
            f"- Exit code: {completed.returncode}",
            f"- Success: {success}",
            f"- Duration seconds: {duration_seconds}",
            f"- stdout lines: {scorecard['stdout_lines']}",
            f"- stderr lines: {scorecard['stderr_lines']}",
            f"- Failure signature: {failure_signature}",
            f"- Claimed metrics matched: {metric_alignment['matched_count']}/{metric_alignment['claim_count']}",
            f"- Claimed metrics partially matched: {metric_alignment['partially_matched_count']}",
            "",
            "## Checks",
            f"- command_executed: {scorecard['checks']['command_executed']}",
            f"- command_succeeded: {scorecard['checks']['command_succeeded']}",
            f"- stderr_present: {scorecard['checks']['stderr_present']}",
            f"- stdout_present: {scorecard['checks']['stdout_present']}",
            f"- test_like_command: {scorecard['checks']['test_like_command']}",
            f"- metric_alignment_checked: {scorecard['checks']['metric_alignment_checked']}",
            f"- partial_metric_alignment: {scorecard['checks']['partial_metric_alignment']}",
            f"- confidence: {scorecard['confidence']}",
        ]
        lines.extend(
            [
                "",
                "## Environment Snapshot",
                f"- python: {environment_snapshot['python_executable']}",
                f"- workdir_name: {environment_snapshot['workdir_name']}",
                f"- visible_files: {environment_snapshot['visible_files']}",
            ]
        )
        if test_summary["detected"]:
            lines.extend(
                [
                    "",
                    "## Test Summary",
                    f"- passed: {test_summary['passed']}",
                    f"- failed: {test_summary['failed']}",
                    f"- errors: {test_summary['errors']}",
                ]
            )
        if metric_alignment["alignments"]:
            lines.extend(["", "## Metric Alignment"])
            lines.extend(
                f"- metric={item['metric']} status={item['status']} expected={item['expected_values']} observed={item['observed_values']}"
                for item in metric_alignment["alignments"][:8]
            )
        if history_summary:
            lines.extend(["", "## Prior History Snapshot", history_summary[:1000]])
        if stdout:
            lines.extend(["", "## stdout", stdout[:4000]])
        if stderr:
            lines.extend(["", "## stderr", stderr[:4000]])
        return CodeExecutionResult(report="\n".join(lines), scorecard=scorecard, artifacts=artifacts)

    def _classify_command(self, command: str) -> str:
        lowered = command.lower()
        if "pytest" in lowered:
            return "pytest"
        if "unittest" in lowered:
            return "unittest"
        if "compileall" in lowered:
            return "compileall"
        if "python" in lowered:
            return "python"
        return "shell"

    def _preview_lines(self, text: str) -> list[str]:
        if not text:
            return []
        return [line[:200] for line in text.splitlines()[:5]]

    def _failure_signature(self, stderr: str, exit_code: int) -> str:
        lowered = stderr.lower()
        if exit_code == 0:
            return "none"
        if "modulenotfounderror" in lowered:
            return "missing_module"
        if "filenotfounderror" in lowered:
            return "missing_file"
        if "assert" in lowered:
            return "assertion_failure"
        if "syntaxerror" in lowered:
            return "syntax_error"
        if "permission" in lowered:
            return "permission_error"
        return "generic_failure"

    def _align_metrics(self, expected_metrics: list[dict], stdout: str, stderr: str) -> dict:
        observed_text = f"{stdout}\n{stderr}".lower()
        observed_numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", observed_text)
        observed_floats = [self._as_float(value) for value in observed_numbers]
        tagged_metrics = self._extract_tagged_metric_values(observed_text)
        alignments: list[dict] = []
        matched_count = 0
        partially_matched_count = 0
        for claim in expected_metrics:
            metric = claim.get("metric", "unknown")
            expected_values = claim.get("values", [])
            matched_values = [value for value in expected_values if value.lower() in observed_text]
            approx_matches = [
                value
                for value in expected_values
                if self._has_numeric_match(value, observed_floats)
            ]
            tagged_matches = self._match_tagged_metric_values(metric, expected_values, tagged_metrics)
            unique_matches = []
            for value in matched_values + tagged_matches + approx_matches:
                if value not in unique_matches:
                    unique_matches.append(value)
            matched = bool(unique_matches) or (metric in observed_text and bool(observed_numbers))
            status = "unmatched"
            if expected_values:
                if len(unique_matches) >= len(expected_values):
                    status = "full"
                elif unique_matches:
                    status = "partial"
            elif matched:
                status = "full"
            if status == "full":
                matched_count += 1
            elif status == "partial":
                partially_matched_count += 1
            alignments.append(
                {
                    "metric": metric,
                    "matched": matched,
                    "status": status,
                    "expected_values": expected_values,
                    "observed_values": (unique_matches[:4] or observed_numbers[:4]),
                    "sentence": claim.get("sentence", "")[:220],
                }
            )
        return {
            "claim_count": len(expected_metrics),
            "matched_count": matched_count,
            "partially_matched_count": partially_matched_count,
            "unmatched_count": max(0, len(expected_metrics) - matched_count),
            "alignments": alignments,
        }

    def _has_numeric_match(self, expected_value: str, observed_values: list[float | None]) -> bool:
        expected = self._as_float(expected_value)
        if expected is None:
            return False
        for observed in observed_values:
            if observed is None:
                continue
            if abs(expected - observed) <= 0.002:
                return True
        return False

    def _as_float(self, value: str) -> float | None:
        normalized = value.strip().rstrip("%")
        try:
            return float(normalized)
        except ValueError:
            return None

    def _extract_tagged_metric_values(self, observed_text: str) -> dict[str, list[str]]:
        patterns = {
            "f1": r"\b(?:f1|f-?measure)\b[^0-9]{0,20}(\d+(?:\.\d+)?%?)",
            "recall": r"\brecall\b[^0-9]{0,20}(\d+(?:\.\d+)?%?)",
            "accuracy": r"\baccuracy\b[^0-9]{0,20}(\d+(?:\.\d+)?%?)",
            "precision": r"\bprecision\b[^0-9]{0,20}(\d+(?:\.\d+)?%?)",
        }
        tagged: dict[str, list[str]] = {}
        for metric, pattern in patterns.items():
            values = re.findall(pattern, observed_text, flags=re.IGNORECASE)
            if values:
                tagged[metric] = values[:8]
        return tagged

    def _match_tagged_metric_values(self, metric: str, expected_values: list[str], tagged_metrics: dict[str, list[str]]) -> list[str]:
        observed = tagged_metrics.get(metric, [])
        if not observed:
            return []
        matches: list[str] = []
        observed_floats = [self._as_float(value) for value in observed]
        for expected_value in expected_values:
            if expected_value in observed:
                matches.append(expected_value)
                continue
            if self._has_numeric_match(expected_value, observed_floats):
                matches.append(expected_value)
        return matches[:4]

    def _environment_snapshot(self, code_dir: Path) -> dict:
        import sys

        visible_files = sorted(path.name for path in code_dir.iterdir())[:12]
        return {
            "python_executable": sys.executable,
            "workdir_name": code_dir.name,
            "visible_files": visible_files,
        }

    def _test_summary(self, command_kind: str, stdout: str, stderr: str) -> dict:
        combined = f"{stdout}\n{stderr}"
        summary = {"detected": False, "passed": 0, "failed": 0, "errors": 0}
        if command_kind == "pytest":
            summary["detected"] = True
            passed = re.search(r"(\d+)\s+passed", combined)
            failed = re.search(r"(\d+)\s+failed", combined)
            errors = re.search(r"(\d+)\s+error", combined)
            summary["passed"] = int(passed.group(1)) if passed else 0
            summary["failed"] = int(failed.group(1)) if failed else 0
            summary["errors"] = int(errors.group(1)) if errors else 0
        elif command_kind == "unittest":
            summary["detected"] = True
            failures = re.search(r"FAILED\s+\(failures=(\d+)", combined)
            errors = re.search(r"errors=(\d+)", combined)
            ok = re.search(r"\bOK\b", combined)
            summary["failed"] = int(failures.group(1)) if failures else 0
            summary["errors"] = int(errors.group(1)) if errors else 0
            summary["passed"] = 1 if ok and not summary["failed"] and not summary["errors"] else 0
        return summary
