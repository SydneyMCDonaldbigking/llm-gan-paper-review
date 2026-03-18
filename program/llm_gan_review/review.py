from __future__ import annotations

import json
import os
import re
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

from .code_checks import CodeExecutionJudgeRunner
from .config import AppConfig
from .evidence_checks import ClaimAlignmentChecker, TableConsistencyChecker
from .git_tools import GitRepositoryManager
from .issues import IssueTracker
from .llm_clients import BaseLLMClient, build_client, classify_provider_error
from .paper import PaperArtifact, PaperParser
from .pua import PUAEngine, PUAResult
from .report_packager import FinalReportPackager
from .review_types import DiffAnalysis, ProviderHealth
from .scorecard import FinalScorecardBuilder
from .synthesis import SynthesisEngine
from .dspy_adapter import DSPyDebateAdapter, DSPyJudgeAdapter


class BusyworkDetector:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.dspy = DSPyDebateAdapter(config.gpt) if config else None

    def analyze(self, diff_text: str, content: str) -> DiffAnalysis:
        reasons: list[str] = []
        diff_text = diff_text or ""
        if len(content.split()) < 120:
            reasons.append("Response is too short to count as a substantial rebuttal.")
        if "evidence" not in content.lower() and "experiment" not in content.lower():
            reasons.append("No explicit evidence or experiment discussion detected.")
        changed_lines = [line for line in diff_text.splitlines() if line.startswith("+") or line.startswith("-")]
        if len(changed_lines) < 20:
            reasons.append("Git diff is too small and may only reflect wording changes.")
        verdict = "busywork" if len(reasons) >= 2 else "substantial"
        if self.dspy:
            try:
                dspy_verdict, dspy_reasons = self.dspy.classify_busywork(diff_text, content)
                if dspy_verdict in {"busywork", "substantial"}:
                    verdict = dspy_verdict
                reasons = list(dict.fromkeys(reasons + dspy_reasons))
            except Exception:
                pass
        return DiffAnalysis(verdict=verdict, reasons=reasons)


class EvidenceJudgeRunner:
    def __init__(self) -> None:
        self.table_checker = TableConsistencyChecker()
        self.claim_checker = ClaimAlignmentChecker()

    def run(self, paper: PaperArtifact, critique: str, rebuttal: str, history_summary: str) -> tuple[str, dict]:
        numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", paper.text[:12000])
        table_consistency = self.table_checker.analyze(
            paper.table_sections + paper.numeric_lines,
            paper.table_blocks,
            paper.table_block_captions,
        )
        claim_alignment = self.claim_checker.analyze(
            paper.claim_sentences,
            paper.table_block_captions,
            paper.figure_captions,
            paper.table_blocks,
        )
        figure_section_count = len(paper.figure_sections)
        table_section_count = len(paper.table_sections)
        figure_digit_hits = sum(1 for section in paper.figure_sections if re.search(r"\d", section))
        table_digit_hits = sum(1 for section in paper.table_sections if re.search(r"\d", section))
        scorecard = {
            "artifact_mode": "evidence",
            "figure_mentions": paper.figure_mentions,
            "table_mentions": paper.table_mentions,
            "figure_sections_found": figure_section_count,
            "table_sections_found": table_section_count,
            "figure_sections_with_digits": figure_digit_hits,
            "table_sections_with_digits": table_digit_hits,
            "numeric_tokens_sampled": len(numbers),
            "critique_word_count": len(critique.split()),
            "rebuttal_word_count": len(rebuttal.split()),
            "checks": {
                "textual_evidence_available": bool(numbers or paper.figure_mentions or paper.table_mentions),
                "figure_references_extracted": figure_section_count > 0,
                "table_references_extracted": table_section_count > 0,
                "figure_numeric_context_present": figure_digit_hits > 0,
                "table_numeric_context_present": table_digit_hits > 0,
                "figure_parsing_complete": False,
                "table_consistency_checked": table_consistency.table_count > 0,
                "candidate_result_tables_found": table_consistency.candidate_result_tables > 0,
                "suspicious_table_patterns_found": table_consistency.suspicious_tables > 0,
                "claim_alignment_checked": claim_alignment.claim_count > 0,
                "claim_support_present": claim_alignment.aligned_claims > 0,
                "image_forensics_checked": False,
            },
            "confidence": "preliminary",
            "table_consistency": {
                "table_count": table_consistency.table_count,
                "tables_with_digits": table_consistency.tables_with_digits,
                "candidate_result_tables": table_consistency.candidate_result_tables,
                "suspicious_tables": table_consistency.suspicious_tables,
                "structured_tables": table_consistency.structured_tables,
                "header_like_tables": table_consistency.header_like_tables,
                "data_like_rows": table_consistency.data_like_rows,
                "findings": table_consistency.findings,
            },
            "claim_alignment": {
                "claim_count": claim_alignment.claim_count,
                "aligned_claims": claim_alignment.aligned_claims,
                "unsupported_claims": claim_alignment.unsupported_claims,
                "alignments": claim_alignment.alignments,
                "findings": claim_alignment.findings,
            },
        }
        summary = [
            "# Evidence Verification",
            "",
            f"- Title: {paper.title}",
            f"- Figure mentions found: {paper.figure_mentions}",
            f"- Table mentions found: {paper.table_mentions}",
            f"- Numeric tokens sampled from text: {len(numbers)}",
            "",
            "## Consistency Notes",
            "- This prototype checks text-level evidence availability, not image forensics.",
            "- The paper contains enough textual structure for claim-vs-evidence debate.",
            "- Final confidence should be treated as preliminary until figure/table parsing is expanded.",
            "",
            "## Debate Inputs Considered",
            f"- Critique length: {len(critique.split())} words",
            f"- Rebuttal length: {len(rebuttal.split())} words",
            "",
            "## Scorecard Snapshot",
            f"- textual_evidence_available: {scorecard['checks']['textual_evidence_available']}",
            f"- figure_references_extracted: {scorecard['checks']['figure_references_extracted']}",
            f"- table_references_extracted: {scorecard['checks']['table_references_extracted']}",
            f"- figure_parsing_complete: {scorecard['checks']['figure_parsing_complete']}",
            f"- table_consistency_checked: {scorecard['checks']['table_consistency_checked']}",
            f"- candidate_result_tables_found: {scorecard['checks']['candidate_result_tables_found']}",
            f"- suspicious_table_patterns_found: {scorecard['checks']['suspicious_table_patterns_found']}",
            f"- claim_alignment_checked: {scorecard['checks']['claim_alignment_checked']}",
            f"- claim_support_present: {scorecard['checks']['claim_support_present']}",
            f"- confidence: {scorecard['confidence']}",
            "",
            "## Figure/Table Snapshot",
            f"- figure_sections_found: {figure_section_count}",
            f"- table_sections_found: {table_section_count}",
            f"- figure_sections_with_digits: {figure_digit_hits}",
            f"- table_sections_with_digits: {table_digit_hits}",
            f"- candidate_result_tables: {table_consistency.candidate_result_tables}",
            f"- suspicious_tables: {table_consistency.suspicious_tables}",
            f"- structured_tables: {table_consistency.structured_tables}",
            f"- header_like_tables: {table_consistency.header_like_tables}",
            f"- data_like_rows: {table_consistency.data_like_rows}",
            "",
            "## Claim Alignment Snapshot",
            f"- source_claim_count: {claim_alignment.source_claim_count}",
            f"- subclaim_count: {claim_alignment.claim_count}",
            f"- aligned_claims: {claim_alignment.aligned_claims}",
            f"- unsupported_claims: {claim_alignment.unsupported_claims}",
        ]
        if history_summary:
            summary.extend(["", "## Prior History Snapshot", history_summary[:1000]])
        if paper.figure_sections:
            summary.extend(["", "## Figure References", *[f"- {section}" for section in paper.figure_sections[:5]]])
        if paper.table_sections:
            summary.extend(["", "## Table References", *[f"- {section}" for section in paper.table_sections[:5]]])
        if paper.table_captions:
            summary.extend(["", "## Table Captions", *[f"- {caption}" for caption in paper.table_captions[:5]]])
        if table_consistency.findings:
            summary.extend(["", "## Table Consistency Findings", *[f"- {finding}" for finding in table_consistency.findings]])
        if claim_alignment.alignments:
            summary.extend(["", "## Claim Alignments"])
            summary.extend(
                f"- supported={item['supported']} reason={item.get('unsupported_reason') or 'supported'} score={item['overlap_score']} claim={item['claim'][:120]} evidence={item['best_evidence'][:120]}"
                for item in claim_alignment.alignments[:6]
            )
        if claim_alignment.findings:
            summary.extend(["", "## Claim Support Findings", *[f"- {finding}" for finding in claim_alignment.findings]])
        return "\n".join(summary), scorecard


class ReviewOrchestrator:
    def __init__(self, root_dir: Path, config: AppConfig) -> None:
        self.root_dir = root_dir
        self.config = config
        self.repo_dir = root_dir / "review_repo"
        self.git = GitRepositoryManager(self.repo_dir)
        self.issue_tracker = IssueTracker(config.gpt)
        self.paper_parser = PaperParser(self.repo_dir)
        self.busywork = BusyworkDetector(config)
        self.pua = PUAEngine(config.gpt)
        self.evidence_judge = EvidenceJudgeRunner()
        self.code_judge = CodeExecutionJudgeRunner()
        self.dspy_judge = DSPyJudgeAdapter(config.gpt)
        self.dspy_debate = DSPyDebateAdapter(config.gpt)
        self.final_scorecard = FinalScorecardBuilder(config.gpt)
        self.synthesis = SynthesisEngine(build_client(config.gpt), config.gpt)
        self.gemini: BaseLLMClient = build_client(config.gemini)
        self.gpt: BaseLLMClient = build_client(config.gpt)
        self.report_packager = FinalReportPackager(root_dir.parent, self.gpt, config.gpt)
        self.provider_health = {
            "gemini_critic": ProviderHealth(),
            "gpt_defender": ProviderHealth(),
            "pua_recovery": ProviderHealth(),
            "synthesis": ProviderHealth(),
        }

    def run_review(
        self,
        pdf_path: Path,
        rounds: int = 2,
        simulate_busywork_round: int | None = None,
        code_dir: Path | None = None,
        run_command: str | None = None,
    ) -> dict:
        if self.repo_dir.exists():
            shutil.rmtree(self.repo_dir, onexc=self._handle_remove_readonly)
        self.git.init_repo()
        paper = self.paper_parser.ingest_pdf(pdf_path)
        review_mode = "code" if code_dir and run_command else "evidence"
        staged_code_dir = self._stage_code_snapshot(code_dir) if code_dir else None
        self._write_json(
            self.repo_dir / "meta" / "review_job.json",
            {
                "paper_title": paper.title,
                "source_file": pdf_path.name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "mode": review_mode,
                "requested_rounds": rounds,
                "code_dir": str(code_dir) if code_dir else None,
                "run_command": run_command,
            },
        )
        init_commit = self.git.commit_all(
            message="[init] ingest paper and metadata",
            author_name="System",
            author_email="system@llm-gan.local",
        )
        self.provider_health = {
            "gemini_critic": ProviderHealth(),
            "gpt_defender": ProviderHealth(),
            "pua_recovery": ProviderHealth(),
            "synthesis": ProviderHealth(),
        }

        round_results: list[dict] = []
        history_summary = ""
        canonical_context_summary = ""
        canonical_issues_context: list[dict] = []
        commit_shas = [init_commit.sha]
        for round_index in range(1, rounds + 1):
            result = self._run_round(
                paper=paper,
                round_index=round_index,
                history_summary=history_summary,
                canonical_context_summary=canonical_context_summary,
                canonical_issues_context=canonical_issues_context,
                simulate_busywork=(simulate_busywork_round == round_index),
                review_mode=review_mode,
                code_dir=staged_code_dir,
                run_command=run_command,
            )
            round_results.append(result)
            history_summary = self._extend_history_summary(history_summary, result)
            current_issue_result = self.issue_tracker.build(round_results)
            canonical_context_summary = self._build_canonical_context_summary(current_issue_result.canonical_issues)
            canonical_issues_context = current_issue_result.canonical_issues
            commit_shas.extend(result["commit_shas"])

        reviews_dir = self.repo_dir / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        issue_result = self.issue_tracker.build(round_results)
        self._write_json(
            reviews_dir / "issues.json",
            {"issues": issue_result.issues, "canonical_issues": issue_result.canonical_issues},
        )
        (reviews_dir / "ISSUES.txt").write_text(issue_result.summary_text, encoding="utf-8")
        (reviews_dir / "TABLE_ANALYSIS.txt").write_text(self._build_table_analysis_text(paper, round_results), encoding="utf-8")
        canonical_history_text = self._build_canonical_history_text(issue_result.canonical_issues)
        (reviews_dir / "CANONICAL_HISTORY.txt").write_text(canonical_history_text, encoding="utf-8")
        final_scorecard = self.final_scorecard.build(round_results, issue_result.canonical_issues)
        self._write_json(reviews_dir / "FINAL_SCORECARD.json", final_scorecard)
        synthesis_health = self.provider_health["synthesis"]
        if synthesis_health.available:
            synthesis_result = self.synthesis.synthesize(paper, round_results, issue_result.canonical_issues)
        else:
            blocked_reason = synthesis_health.blocked_reason or synthesis_health.last_error or "synthesis provider blocked"
            synthesis_result = self.synthesis.fallback_only(
                paper,
                round_results,
                issue_result.canonical_issues,
                blocked_reason,
            )
        if synthesis_result.meta["mode"] == "fallback":
            synthesis_error = synthesis_result.meta.get("error", "unknown synthesis error")
            synthesis_error_type = synthesis_result.meta.get("error_type") or classify_provider_error(synthesis_error)
            synthesis_health.mark_failure(synthesis_error)
            if synthesis_error_type == "quota_exhausted":
                synthesis_health.block("quota_exhausted", synthesis_error)
        (reviews_dir / "SYNTHESIS.txt").write_text(synthesis_result.content, encoding="utf-8")
        self._write_json(reviews_dir / "synthesis_meta.json", synthesis_result.meta)
        self._write_json(
            self.repo_dir / "meta" / "provider_health.json",
            {
                role: {
                    "available": health.available,
                    "last_error": health.last_error,
                    "blocked_reason": health.blocked_reason,
                }
                for role, health in self.provider_health.items()
            },
        )
        final_report = self._build_final_report(
            paper,
            round_results,
            commit_shas,
            synthesis_result.content,
            issue_result.summary_text,
            final_scorecard,
            canonical_history_text,
            review_mode,
        )
        (reviews_dir / "FINAL_REPORT.md").write_text(final_report, encoding="utf-8")
        packaged_report = self.report_packager.package(final_report, paper.title)
        self._write_json(self.repo_dir / "meta" / "final_report_bundle.json", packaged_report)
        (reviews_dir / "TIMELINE.md").write_text(self._build_timeline(round_results, review_mode), encoding="utf-8")
        self._write_json(
            self.repo_dir / "meta" / "accountability.json",
            self._build_accountability(round_results),
        )
        final_commit = self.git.commit_all(
            message="[final] generate review summary",
            author_name="System",
            author_email="system@llm-gan.local",
        )

        return {
            "paper_title": paper.title,
            "review_mode": review_mode,
            "review_repo": str(self.repo_dir),
            "final_commit": final_commit.sha,
            "git_log": self.git.log_oneline(),
            "rounds_completed": rounds,
            "issue_count": len(issue_result.issues),
            "canonical_issue_count": len(issue_result.canonical_issues),
            "final_recommendation": final_scorecard["recommendation"],
            "overall_score": final_scorecard["overall_score"],
            "final_report_bundle": packaged_report["bundle_dir"],
            "round_statuses": [
                {
                    "round": item["round_id"],
                    "busywork_verdict": item["diff_analysis"].verdict,
                    "pua_level": item["pua_result"].level,
                    "critic_source": item["critique_meta"]["mode"],
                    "defender_source": item["rebuttal_meta"]["mode"],
                }
                for item in round_results
            ],
            "synthesis_mode": synthesis_result.meta["mode"],
        }

    def _run_round(
        self,
        paper: PaperArtifact,
        round_index: int,
        history_summary: str,
        canonical_context_summary: str,
        canonical_issues_context: list[dict],
        simulate_busywork: bool,
        review_mode: str,
        code_dir: Path | None,
        run_command: str | None,
    ) -> dict:
        round_id = f"{round_index:04d}"
        round_dir = self.repo_dir / "reviews" / "rounds" / round_id
        round_dir.mkdir(parents=True, exist_ok=True)
        context = paper.text[:12000]
        defender_checklist = self._build_defender_checklist(canonical_issues_context)
        critique_prompt = self._build_critique_prompt(
            paper.title,
            context,
            history_summary,
            canonical_context_summary,
            round_id,
        )
        critique_plan = ""
        try:
            critique_plan = self.dspy_debate.critique_plan(paper.title, history_summary, canonical_context_summary)
            critique_prompt = f"{critique_prompt}\n\nDSPy Critic Plan\n{critique_plan}"
        except Exception:
            critique_plan = ""
        critique_dspy_draft = ""
        try:
            critique_dspy_draft = self.dspy_debate.draft_critique(
                paper.title,
                context,
                history_summary,
                canonical_context_summary,
            )
        except Exception:
            critique_dspy_draft = ""

        critique, critique_meta = self._generate_with_fallback(
            client=self.gemini,
            role="gemini_critic",
            system_prompt="You are Gemini Critic. Act like a rigorous reviewer. Focus on logic, evidence, novelty, and experimental validity.",
            user_prompt=critique_prompt,
            fallback=self._fallback_critique(paper, context, history_summary),
        )
        if critique_meta.get("mode") == "fallback" and critique_dspy_draft:
            critique = critique_dspy_draft
            critique_meta = {
                **critique_meta,
                "mode": "dspy_draft",
                "fallback_origin": critique_meta.get("error_type") or "api_failure",
            }
        (round_dir / "critic_prompt.txt").write_text(critique_prompt, encoding="utf-8")
        if critique_plan:
            (round_dir / "critic_plan.txt").write_text(critique_plan, encoding="utf-8")
        if critique_dspy_draft:
            (round_dir / "critic_dspy_draft.txt").write_text(critique_dspy_draft, encoding="utf-8")
        (round_dir / "critic.md").write_text(critique, encoding="utf-8")
        self._write_json(round_dir / "critic_meta.json", critique_meta)
        if "raw" in critique_meta:
            self._write_json(round_dir / "critic_raw.json", critique_meta["raw"])
        critique_commit = self.git.commit_all(
            message=f"[round-{round_id}][gemini_critic] critique paper",
            author_name="Gemini Critic",
            author_email="gemini@llm-gan.local",
        )

        rebuttal_prompt = self._build_rebuttal_prompt(
            paper.title,
            context,
            critique,
            history_summary,
            canonical_context_summary,
            defender_checklist,
            round_id,
        )
        rebuttal_plan = ""
        try:
            rebuttal_plan = self.dspy_debate.rebuttal_plan(critique, history_summary, defender_checklist)
            rebuttal_prompt = f"{rebuttal_prompt}\n\nDSPy Defender Plan\n{rebuttal_plan}"
        except Exception:
            rebuttal_plan = ""
        rebuttal_dspy_draft = ""
        try:
            rebuttal_dspy_draft = self.dspy_debate.draft_rebuttal(
                paper.title,
                critique,
                history_summary,
                defender_checklist,
            )
        except Exception:
            rebuttal_dspy_draft = ""
        rebuttal, rebuttal_meta = self._generate_with_fallback(
            client=self.gpt,
            role="gpt_defender",
            system_prompt="You are GPT Defender. Respond point-by-point and add concrete evidence-oriented defense.",
            user_prompt=rebuttal_prompt,
            fallback=self._fallback_rebuttal(paper, critique, history_summary),
        )
        if rebuttal_meta.get("mode") == "fallback" and rebuttal_dspy_draft:
            rebuttal = rebuttal_dspy_draft
            rebuttal_meta = {
                **rebuttal_meta,
                "mode": "dspy_draft",
                "fallback_origin": rebuttal_meta.get("error_type") or "api_failure",
            }
        elif rebuttal_meta.get("mode") == "api" and rebuttal_dspy_draft and self._is_thin_live_response(rebuttal):
            rebuttal = rebuttal_dspy_draft
            rebuttal_meta = {
                **rebuttal_meta,
                "mode": "dspy_override",
                "override_reason": "live_response_too_thin",
            }
        (round_dir / "defender_prompt.txt").write_text(rebuttal_prompt, encoding="utf-8")
        (round_dir / "defender_checklist.txt").write_text(defender_checklist, encoding="utf-8")
        if rebuttal_plan:
            (round_dir / "defender_plan.txt").write_text(rebuttal_plan, encoding="utf-8")
        if rebuttal_dspy_draft:
            (round_dir / "defender_dspy_draft.txt").write_text(rebuttal_dspy_draft, encoding="utf-8")
        if simulate_busywork:
            rebuttal = "Minor wording tweak only."
            rebuttal_meta = {
                "mode": "simulation",
                "role": "gpt_defender",
                "note": "Busywork simulation injected for escalation-path testing.",
            }
        (round_dir / "defender.md").write_text(rebuttal, encoding="utf-8")
        self._write_json(round_dir / "defender_meta.json", rebuttal_meta)
        if "raw" in rebuttal_meta:
            self._write_json(round_dir / "defender_raw.json", rebuttal_meta["raw"])
        rebuttal_commit = self.git.commit_all(
            message=f"[round-{round_id}][gpt_defender] rebut critique",
            author_name="GPT Defender",
            author_email="gpt@llm-gan.local",
        )

        diff_analysis = self.busywork.analyze(self.git.diff_last_commit(), rebuttal)
        self._write_json(
            round_dir / "busywork_check.json",
            {"verdict": diff_analysis.verdict, "reasons": diff_analysis.reasons},
        )
        busywork_commit = self.git.commit_all(
            message=f"[round-{round_id}][system] busywork check: {diff_analysis.verdict}",
            author_name="System",
            author_email="system@llm-gan.local",
        )

        pua_result = self.pua.assess(diff_analysis, critique_meta, rebuttal_meta)
        self._write_json(
            round_dir / "pua_assessment.json",
            {
                "triggered": pua_result.triggered,
                "level": pua_result.level,
                "target_agent": pua_result.target_agent,
                "reason": pua_result.reason,
            },
        )
        (round_dir / "pua.md").write_text(pua_result.interrogation, encoding="utf-8")
        pua_commit = self.git.commit_all(
            message=f"[round-{round_id}][pua-{pua_result.level.lower()}] {pua_result.reason}",
            author_name="PUA Engine",
            author_email="pua@llm-gan.local",
        )

        escalation_commit_sha = None
        escalation_meta: dict | None = None
        escalation_response = None
        if pua_result.triggered and pua_result.level != "NONE":
            try:
                escalation_plan = self.dspy_debate.escalation_plan(pua_result.level, pua_result.interrogation, critique, rebuttal)
            except Exception:
                escalation_plan = ""
            escalation_response, escalation_meta = self._generate_with_fallback(
                client=self.gpt,
                role="pua_recovery",
                system_prompt="You are under escalation review. Address the interrogation directly and provide substantive recovery only.",
                user_prompt=f"{pua_result.interrogation}\n\nPrior critique:\n{critique}\n\nPrior rebuttal:\n{rebuttal}\n\nDSPy Escalation Plan:\n{escalation_plan}",
                fallback=self._fallback_escalation(pua_result, critique, rebuttal),
            )
            (round_dir / "escalation_response.md").write_text(escalation_response, encoding="utf-8")
            if escalation_plan:
                (round_dir / "escalation_plan.txt").write_text(escalation_plan, encoding="utf-8")
            self._write_json(round_dir / "escalation_meta.json", escalation_meta)
            escalation_commit = self.git.commit_all(
                message=f"[round-{round_id}][escalation-response] answer {pua_result.level}",
                author_name="Recovery Agent",
                author_email="recovery@llm-gan.local",
            )
            escalation_commit_sha = escalation_commit.sha

        runs_dir = self.repo_dir / "runs" / round_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        if review_mode == "code" and code_dir and run_command:
            code_result = self.code_judge.run(code_dir, run_command, history_summary, paper.metric_claims)
            judge_report, judge_scorecard = code_result.report, code_result.scorecard
            self._write_json(
                runs_dir / "execution.json",
                {k: v for k, v in code_result.artifacts.items() if k not in {"stdout_text", "stderr_text"}},
            )
            (runs_dir / "stdout.txt").write_text(code_result.artifacts.get("stdout_text", ""), encoding="utf-8")
            (runs_dir / "stderr.txt").write_text(code_result.artifacts.get("stderr_text", ""), encoding="utf-8")
            self._write_json(
                runs_dir / "run_manifest.json",
                {
                    "judge_mode": "code",
                    "command": code_result.artifacts.get("command"),
                    "command_kind": code_result.artifacts.get("command_kind"),
                    "exit_code": code_result.artifacts.get("exit_code"),
                    "duration_seconds": code_result.artifacts.get("duration_seconds"),
                    "failure_signature": code_result.artifacts.get("failure_signature"),
                    "metric_alignment": code_result.artifacts.get("metric_alignment"),
                },
            )
            judge_commit_message = f"[round-{round_id}][judge-code] execute reproducibility command"
        else:
            judge_report, judge_scorecard = self.evidence_judge.run(paper, critique, rebuttal, history_summary)
            self._write_json(
                runs_dir / "table_consistency.json",
                judge_scorecard.get("table_consistency", {}),
            )
            self._write_json(
                runs_dir / "claim_alignment.json",
                judge_scorecard.get("claim_alignment", {}),
            )
            self._write_json(
                runs_dir / "table_blocks.json",
                {
                    "captions": paper.table_block_captions[:10],
                    "blocks": paper.table_blocks[:10],
                },
            )
            judge_commit_message = f"[round-{round_id}][judge-evidence] verify paper evidence"
        judge_meta = {"mode": "raw"}
        try:
            judge_report = self.dspy_judge.summarize(review_mode, judge_report, judge_scorecard)
            judge_meta = {"mode": "dspy"}
        except Exception as exc:
            judge_meta = {"mode": "raw", "dspy_error": str(exc)}
        (runs_dir / "judge.md").write_text(judge_report, encoding="utf-8")
        self._write_json(runs_dir / "judge_meta.json", judge_meta)
        artifacts_dir = self.repo_dir / "artifacts" / "scorecards"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(artifacts_dir / f"{round_id}.json", judge_scorecard)
        judge_commit = self.git.commit_all(
            message=judge_commit_message,
            author_name="Judge Runner",
            author_email="judge@llm-gan.local",
        )

        commit_shas = [
            critique_commit.sha,
            rebuttal_commit.sha,
            busywork_commit.sha,
            pua_commit.sha,
        ]
        if escalation_commit_sha:
            commit_shas.append(escalation_commit_sha)
        commit_shas.append(judge_commit.sha)
        return {
            "round_id": round_id,
            "critique": critique,
            "rebuttal": rebuttal,
            "critique_meta": critique_meta,
            "rebuttal_meta": rebuttal_meta,
            "diff_analysis": diff_analysis,
            "pua_result": pua_result,
            "escalation_meta": escalation_meta,
            "escalation_response": escalation_response,
            "judge_report": judge_report,
            "judge_scorecard": judge_scorecard,
            "judge_mode": judge_scorecard["artifact_mode"],
            "commit_shas": commit_shas,
        }

    def _build_critique_prompt(
        self,
        title: str,
        context: str,
        history_summary: str,
        canonical_context_summary: str,
        round_id: str,
    ) -> str:
        lines = [
            f"Round: {round_id}",
            f"Paper title: {title}",
            "",
            "Read the paper excerpt and produce a critical review with:",
            "1. Three strongest concerns",
            "2. Evidence-related risks",
            "3. A preliminary verdict",
        ]
        if history_summary:
            lines.extend(["", "Prior review history and pressure context:", history_summary[:2500]])
        if canonical_context_summary:
            lines.extend(
                [
                    "",
                    "Canonical issue pressure context:",
                    "Re-evaluate any issue that has persisted across rounds. Escalate only if the defender still has not materially resolved it.",
                    canonical_context_summary[:2500],
                ]
            )
        lines.extend(["", "Paper excerpt:", context])
        return "\n".join(lines)

    def _build_rebuttal_prompt(
        self,
        title: str,
        context: str,
        critique: str,
        history_summary: str,
        canonical_context_summary: str,
        defender_checklist: str,
        round_id: str,
    ) -> str:
        lines = [
            f"Round: {round_id}",
            f"Paper title: {title}",
            "",
            "Respond to the critique point-by-point. For each point, provide a defense, an evidence discussion, and one remaining risk.",
        ]
        if history_summary:
            lines.extend(["", "Prior review history and pressure context:", history_summary[:2500]])
        if canonical_context_summary:
            lines.extend(
                [
                    "",
                    "Canonical issue pressure context:",
                    "Directly address any issue that has persisted across rounds. Do not repeat prior defense without adding new evidence or a stronger concession.",
                    canonical_context_summary[:2500],
                ]
            )
        if defender_checklist:
            lines.extend(
                [
                    "",
                    "Required checklist:",
                    "Address each checklist item explicitly. If you cannot resolve one, state that it remains unresolved and explain why.",
                    defender_checklist[:2500],
                ]
            )
        lines.extend(["", "Paper excerpt:", context, "", "Critique:", critique])
        return "\n".join(lines)

    def _build_final_report(
        self,
        paper: PaperArtifact,
        round_results: list[dict],
        commit_shas: list[str],
        synthesis_text: str,
        issue_summary_text: str,
        final_scorecard: dict,
        canonical_history_text: str,
        review_mode: str,
    ) -> str:
        lines = [
            f"# Review Report: {paper.title}",
            "",
            "## Mode",
            f"- {review_mode}-backed review path",
            "",
            "## Round Summary",
        ]
        for result in round_results:
            lines.extend(
                [
                    f"### Round {result['round_id']}",
                    f"- Critic source: {result['critique_meta']['mode']}",
                    f"- Defender source: {result['rebuttal_meta']['mode']}",
                    f"- Busywork: {result['diff_analysis'].verdict}",
                    f"- PUA level: {result['pua_result'].level}",
                    f"- PUA target: {result['pua_result'].target_agent or 'None'}",
                    f"- Judge mode: {result['judge_mode']}",
                    f"- Judge confidence: {result['judge_scorecard']['confidence']}",
                    f"- Primary judge check: {self._describe_primary_judge_signal(result['judge_scorecard'])}",
                ]
            )
        lines.extend(["", "## Commit Trail", *[f"- {sha}" for sha in commit_shas], ""])
        for result in round_results:
            lines.extend(
                [
                    f"## Critique Preview Round {result['round_id']}",
                    result["critique"][:1500],
                    "",
                    f"## Rebuttal Preview Round {result['round_id']}",
                    result["rebuttal"][:1500],
                    "",
                ]
            )
        lines.extend(
            [
                "## Final Scorecard",
                f"- Overall score: {final_scorecard['overall_score']}",
                f"- Recommendation: {final_scorecard['recommendation']}",
                f"- Persistent canonical issues: {final_scorecard['issue_counts']['persistent_across_rounds']}",
                f"- Novelty: {final_scorecard['dimensions']['novelty']}/5",
                f"- Technical soundness: {final_scorecard['dimensions']['technical_soundness']}/5",
                f"- Evidence quality: {final_scorecard['dimensions']['evidence_quality']}/5",
                f"- Clarity: {final_scorecard['dimensions']['clarity']}/5",
                f"- Reproducibility: {final_scorecard['dimensions']['reproducibility']}/5",
                "",
                "## Judge Evidence Gaps",
                *self._build_judge_gap_lines(final_scorecard, round_results),
                "",
                "## Provider Health",
                *[
                    f"- {role}: available={health.available} blocked_reason={health.blocked_reason or 'none'}"
                    for role, health in self.provider_health.items()
                ],
                "",
                "## Issue Ledger",
                issue_summary_text[:4000],
                "",
                "## Canonical History",
                canonical_history_text[:3000],
                "",
                "## Unified Synthesis",
                synthesis_text[:4000],
            ]
        )
        return "\n".join(lines)

    def _build_timeline(self, round_results: list[dict], review_mode: str) -> str:
        lines = ["# Review Timeline", "", "1. System ingested the paper and created the review repository."]
        step = 2
        for result in round_results:
            lines.extend(
                [
                    f"{step}. Round {result['round_id']} Gemini Critic produced a critique via `{result['critique_meta']['mode']}` mode.",
                    f"{step + 1}. Round {result['round_id']} GPT Defender produced a rebuttal via `{result['rebuttal_meta']['mode']}` mode.",
                    f"{step + 2}. Round {result['round_id']} busywork verdict was `{result['diff_analysis'].verdict}`.",
                    f"{step + 3}. Round {result['round_id']} PUA result was `{result['pua_result'].level}`.",
                    f"{step + 4}. Round {result['round_id']} Judge Runner completed {result['judge_mode']}-backed verification.",
                ]
            )
            step += 5
        lines.extend(["", "## Commit Messages"])
        for result in round_results:
            round_id = result["round_id"]
            lines.append(f"- [round-{round_id}][gemini_critic] critique paper")
            lines.append(f"- [round-{round_id}][gpt_defender] rebut critique")
            lines.append(f"- [round-{round_id}][system] busywork check: {result['diff_analysis'].verdict}")
            lines.append(f"- [round-{round_id}][pua-{result['pua_result'].level.lower()}] {result['pua_result'].reason}")
            if result["escalation_response"]:
                lines.append(f"- [round-{round_id}][escalation-response] answer {result['pua_result'].level}")
            judge_commit_label = "judge-code" if result["judge_mode"] == "code" else "judge-evidence"
            lines.append(f"- [round-{round_id}][{judge_commit_label}] complete {result['judge_mode']} verification")
        return "\n".join(lines)

    def _build_accountability(self, round_results: list[dict]) -> dict:
        events = []
        for result in round_results:
            round_id = result["round_id"]
            events.extend(
                [
                    {
                        "round": round_id,
                        "actor": "Gemini Critic",
                        "event_type": "review_round",
                        "mode": result["critique_meta"]["mode"],
                        "status": "completed" if result["critique_meta"]["mode"] == "api" else "fallback",
                        "error_type": result["critique_meta"].get("error_type"),
                    },
                    {
                        "round": round_id,
                        "actor": "GPT Defender",
                        "event_type": "review_round",
                        "mode": result["rebuttal_meta"]["mode"],
                        "status": "completed" if result["rebuttal_meta"]["mode"] == "api" else "fallback",
                        "error_type": result["rebuttal_meta"].get("error_type"),
                    },
                    {
                        "round": round_id,
                        "actor": "System",
                        "event_type": "busywork_check",
                        "status": result["diff_analysis"].verdict,
                        "reasons": result["diff_analysis"].reasons,
                    },
                    {
                        "round": round_id,
                        "actor": "PUA Engine",
                        "event_type": "escalation" if result["pua_result"].triggered else "no_escalation",
                        "status": result["pua_result"].level,
                        "target_agent": result["pua_result"].target_agent,
                        "reason": result["pua_result"].reason,
                    },
                    {
                        "round": round_id,
                        "actor": "Judge Runner",
                        "event_type": f"{result['judge_mode']}_verification",
                        "status": "completed",
                        "confidence": result["judge_scorecard"]["confidence"],
                        "judge_mode": result["judge_mode"],
                        "primary_signal": self._describe_primary_judge_signal(result["judge_scorecard"]),
                    },
                ]
            )
            if result["escalation_response"]:
                events.append(
                    {
                        "round": round_id,
                        "actor": "Recovery Agent",
                        "event_type": "escalation_response",
                        "status": result["escalation_meta"]["mode"] if result["escalation_meta"] else "unknown",
                        "error_type": result["escalation_meta"].get("error_type") if result["escalation_meta"] else None,
                    }
                )
        return {
            "round_count": len(round_results),
            "provider_health": {
                role: {
                    "available": health.available,
                    "last_error": health.last_error,
                    "blocked_reason": health.blocked_reason,
                }
                for role, health in self.provider_health.items()
            },
            "events": events,
        }

    def _extend_history_summary(self, history_summary: str, result: dict) -> str:
        block = "\n".join(
            [
                f"Round {result['round_id']}:",
                f"Critique source={result['critique_meta']['mode']}",
                f"Defender source={result['rebuttal_meta']['mode']}",
                f"Busywork={result['diff_analysis'].verdict}",
                f"PUA={result['pua_result'].level}",
                f"PUA target={result['pua_result'].target_agent or 'None'}",
                f"PUA reason={result['pua_result'].reason}",
                f"Judge primary_signal={self._describe_primary_judge_signal(result['judge_scorecard'])}",
                f"Judge mode={result['judge_mode']}",
                f"Judge confidence={result['judge_scorecard']['confidence']}",
                f"Judge note={result['judge_report'][:250]}",
                "",
            ]
        )
        combined = f"{history_summary}\n{block}".strip()
        return combined[-4000:]

    def _build_canonical_history_text(self, canonical_issues: list[dict]) -> str:
        lines = ["Canonical Issue History"]
        for issue in canonical_issues:
            lines.extend(
                [
                    "",
                    f"{issue['canonical_id']} | {issue['status']} | {issue['title']}",
                    f"Rounds: {','.join(issue['rounds'])}",
                ]
            )
            for entry in issue.get("history", []):
                lines.append(
                    f"- round={entry['round']} status={entry['status']} busywork={entry['busywork_verdict']} pua={entry['pua_level']}"
                )
        return "\n".join(lines)

    def _build_canonical_context_summary(self, canonical_issues: list[dict]) -> str:
        if not canonical_issues:
            return ""
        lines = ["Canonical Issue Context"]
        sorted_issues = sorted(
            canonical_issues,
            key=lambda issue: (len(issue.get("history", [])), issue["status"] != "responded"),
            reverse=True,
        )
        for issue in sorted_issues[:6]:
            history_text = "; ".join(
                f"{entry['round']}:{entry['status']}" for entry in issue.get("history", [])
            )
            lines.extend(
                [
                    "",
                    f"{issue['canonical_id']} | status={issue['status']} | category={issue.get('category', 'other')}",
                    f"title={issue['title']}",
                    f"history={history_text}",
                    f"latest_rebuttal={issue['rebuttal_point'][:220]}",
                    f"required_response={issue.get('required_response', 'Provide new evidence or a direct rebuttal.')[:220]}",
                ]
            )
        return "\n".join(lines)

    def _build_defender_checklist(self, canonical_issues: list[dict]) -> str:
        if not canonical_issues:
            return ""
        lines = ["Defender Checklist"]
        sorted_issues = sorted(
            canonical_issues,
            key=lambda issue: (len(issue.get("history", [])), issue["status"] != "responded"),
            reverse=True,
        )
        for issue in sorted_issues[:6]:
            history = issue.get("history", [])
            last_status = history[-1]["status"] if history else issue["status"]
            lines.extend(
                [
                    f"- {issue['canonical_id']}: category={issue.get('category', 'other')} previous_status={last_status}",
                    f"  title={issue['title']}",
                    f"  required_response={issue.get('required_response', 'Provide new evidence, a concession, or a direct rebuttal. Do not repeat prior wording.')}",
                ]
            )
        return "\n".join(lines)

    def _build_table_analysis_text(self, paper: PaperArtifact, round_results: list[dict]) -> str:
        lines = [
            "Table Analysis",
            "",
            f"table_mentions={paper.table_mentions}",
            f"table_captions={len(paper.table_captions)}",
            f"table_blocks={len(paper.table_blocks)}",
            f"claim_sentences={len(paper.claim_sentences)}",
            "",
            "Captions",
        ]
        if paper.table_captions:
            lines.extend(f"- {caption}" for caption in paper.table_captions[:10])
        else:
            lines.append("- none")
        lines.extend(["", "Blocks"])
        if paper.table_blocks:
            for index, block in enumerate(paper.table_blocks[:6], start=1):
                caption = paper.table_block_captions[index - 1] if index - 1 < len(paper.table_block_captions) else ""
                lines.append(f"- block_{index}: caption={caption or 'none'} | {' | '.join(block)[:220]}")
        else:
            lines.append("- none")
        lines.extend(["", "Round Snapshots"])
        for result in round_results:
            table_consistency = result["judge_scorecard"].get("table_consistency", {})
            claim_alignment = result["judge_scorecard"].get("claim_alignment", {})
            if not table_consistency:
                continue
            lines.extend(
                [
                    f"- round={result['round_id']} candidate_result_tables={table_consistency.get('candidate_result_tables')} suspicious_tables={table_consistency.get('suspicious_tables')} structured_tables={table_consistency.get('structured_tables')} aligned_claims={claim_alignment.get('aligned_claims')}",
                ]
            )
        lines.extend(["", "Claims"])
        if paper.claim_sentences:
            lines.extend(f"- {claim}" for claim in paper.claim_sentences[:10])
        else:
            lines.append("- none")
        return "\n".join(lines)

    def _is_thin_live_response(self, text: str) -> bool:
        lowered = text.lower()
        if len(text.split()) < 170:
            return True
        if "evidence" not in lowered and "risk" not in lowered and "defense" not in lowered:
            return True
        return False

    def _describe_primary_judge_signal(self, judge_scorecard: dict) -> str:
        if judge_scorecard["artifact_mode"] == "code":
            metric_alignment = judge_scorecard.get("metric_alignment", {})
            return (
                f"command_succeeded={judge_scorecard['checks']['command_succeeded']},"
                f" matched_metrics={metric_alignment.get('matched_count', 0)},"
                f" partial_metrics={metric_alignment.get('partially_matched_count', 0)}"
            )
        return f"textual_evidence_available={judge_scorecard['checks']['textual_evidence_available']}"

    def _build_judge_gap_lines(self, final_scorecard: dict, round_results: list[dict]) -> list[str]:
        lines: list[str] = []
        breakdown = final_scorecard.get("evidence_checks", {}).get("unsupported_claim_breakdown", {})
        for reason, count in breakdown.items():
            if count:
                lines.append(f"- {reason}: {count}")
        latest = round_results[-1]["judge_scorecard"]
        if latest["artifact_mode"] == "code":
            metric_alignment = latest.get("metric_alignment", {})
            lines.append(
                f"- code_metric_alignment: full={metric_alignment.get('matched_count', 0)} partial={metric_alignment.get('partially_matched_count', 0)} unmatched={metric_alignment.get('unmatched_count', 0)}"
            )
        else:
            for item in latest.get("claim_alignment", {}).get("alignments", [])[:5]:
                if item.get("supported"):
                    continue
                lines.append(f"- {item.get('unsupported_reason') or 'unsupported'}: {item['claim'][:140]}")
        return lines or ["- No explicit judge gap summary available."]

    def _stage_code_snapshot(self, code_dir: Path) -> Path:
        target = self.repo_dir / "paper" / "source_snapshot"
        if target.exists():
            shutil.rmtree(target, onexc=self._handle_remove_readonly)
        shutil.copytree(code_dir, target)
        return target

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _handle_remove_readonly(self, func, path, excinfo) -> None:
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def _generate_with_fallback(
        self,
        client: BaseLLMClient,
        role: str,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
    ) -> tuple[str, dict]:
        try:
            provider_state = self.provider_health.setdefault(role, ProviderHealth())
            if not provider_state.available:
                reason = provider_state.blocked_reason or "provider blocked earlier in this run"
                error = provider_state.last_error or reason
                return fallback, {
                    "mode": "fallback",
                    "role": role,
                    "error": error,
                    "error_type": "provider_blocked",
                    "blocked_reason": reason,
                }
            response = client.generate(system_prompt=system_prompt, user_prompt=user_prompt)
            return response.content, {"mode": "api", "role": role, "raw": response.raw}
        except Exception as exc:
            error_text = str(exc)
            error_type = classify_provider_error(error_text)
            provider_state = self.provider_health.setdefault(role, ProviderHealth())
            provider_state.mark_failure(error_text)
            if error_type == "quota_exhausted":
                provider_state.block("quota_exhausted", error_text)
                if role == "gpt_defender":
                    self.provider_health.setdefault("pua_recovery", ProviderHealth()).block("upstream_gpt_quota_exhausted", error_text)
                    self.provider_health.setdefault("synthesis", ProviderHealth()).block("upstream_gpt_quota_exhausted", error_text)
                if role == "pua_recovery":
                    self.provider_health.setdefault("synthesis", ProviderHealth()).block("upstream_gpt_quota_exhausted", error_text)
            return fallback, {"mode": "fallback", "role": role, "error": error_text, "error_type": error_type}

    def _fallback_critique(self, paper: PaperArtifact, context: str, history_summary: str) -> str:
        excerpt = context[:1200]
        lines = [
            "# Fallback Critique",
            "",
            "## Strongest Concerns",
            "1. The paper excerpt needs clearer evidence linking its central claim to reported results.",
            "2. The evaluation description appears thin, so reproducibility and statistical confidence remain uncertain.",
            "3. Novelty should be positioned more explicitly against prior baselines.",
            "",
            "## Evidence Risks",
            f"- Figure mentions: {paper.figure_mentions}",
            f"- Table mentions: {paper.table_mentions}",
            "- Numeric claims should be checked against tables and appendices before trusting the final conclusion.",
        ]
        if history_summary:
            lines.extend(["", "## Prior History", history_summary[:1000]])
        lines.extend(["", "## Excerpt Used", excerpt, "", "## Preliminary Verdict", "borderline"])
        return "\n".join(lines)

    def _fallback_rebuttal(self, paper: PaperArtifact, critique: str, history_summary: str) -> str:
        lines = [
            "# Fallback Rebuttal",
            "",
            "## Point-by-Point Response",
            "1. The paper contains task framing and metric language, which provides a baseline for evidence review.",
            "2. Figure and table mentions suggest structured experimental reporting.",
            "3. Comparative novelty can be assessed more completely after related-work extraction.",
            "",
            "## Evidence Added",
            f"- Title captured: {paper.title}",
            f"- Figure mentions counted: {paper.figure_mentions}",
            f"- Table mentions counted: {paper.table_mentions}",
        ]
        if history_summary:
            lines.extend(["", "## Prior History", history_summary[:1000]])
        lines.extend(["", "## Critique Snapshot", critique[:1000]])
        return "\n".join(lines)

    def _fallback_escalation(self, pua_result: PUAResult, critique: str, rebuttal: str) -> str:
        return "\n".join(
            [
                f"# Escalation Recovery for {pua_result.level}",
                "",
                f"Reason: {pua_result.reason}",
                "",
                "## Recovery Statement",
                "The prior round did not add enough trustworthy signal, so this recovery note explicitly states the missing increment, evidence path, and residual uncertainty.",
                "",
                "## Prior Critique Snapshot",
                critique[:800],
                "",
                "## Prior Rebuttal Snapshot",
                rebuttal[:800],
            ]
        )
