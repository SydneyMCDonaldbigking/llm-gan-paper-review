from __future__ import annotations

import argparse
import json
import os
import stat
import shutil
import sys
from datetime import datetime
from pathlib import Path

from llm_gan_review.config import AppConfig
from llm_gan_review.llm_clients import build_client
from llm_gan_review.review import ReviewOrchestrator


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run batch LLM-GAN paper reviews.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--paper-dir", default=None)
    parser.add_argument("--glob", default="*.pdf")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--batch-output-dir", default="batch_runs")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-spec", default=None)
    args = parser.parse_args()

    program_dir = Path(__file__).resolve().parent
    workspace_dir = program_dir.parent
    config = AppConfig.load(_resolve_config_path(program_dir, workspace_dir, args.config))
    paper_dir = _resolve_paper_dir(program_dir, workspace_dir, args.paper_dir)
    batch_root = program_dir / args.batch_output_dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    batch_dir = batch_root / timestamp
    batch_dir.mkdir(parents=True, exist_ok=True)
    external_report_dir = _create_external_report_dir(workspace_dir, timestamp)

    manifest: list[dict] = []
    entries = _load_entries(program_dir, workspace_dir, paper_dir, args)
    if args.limit is not None:
        entries = entries[: args.limit]

    for index, entry in enumerate(entries, start=1):
        paper_path = entry["paper_path"]
        orchestrator = ReviewOrchestrator(root_dir=program_dir, config=config)
        result = orchestrator.run_review(
            paper_path,
            rounds=entry["rounds"],
            code_dir=entry.get("code_dir"),
            run_command=entry.get("run_command"),
        )
        safe_stem = _safe_name(paper_path.stem)
        target_dir = batch_dir / f"{index:02d}_{result['review_mode']}_{safe_stem}"
        if target_dir.exists():
            shutil.rmtree(target_dir, onexc=_handle_remove_readonly)
        shutil.copytree(program_dir / "review_repo", target_dir)
        exported_report_dir = _export_paper_reports(
            target_dir=target_dir,
            external_report_dir=external_report_dir,
            index=index,
            paper_stem=safe_stem,
            final_report_bundle=result.get("final_report_bundle"),
        )
        manifest.append(
            {
                "paper": paper_path.name,
                "paper_title": result["paper_title"],
                "target_dir": str(target_dir),
                "exported_report_dir": str(exported_report_dir),
                "review_mode": result["review_mode"],
                "requested_rounds": entry["rounds"],
                "code_dir": str(entry["code_dir"]) if entry.get("code_dir") else None,
                "run_command": entry.get("run_command"),
                "final_recommendation": result["final_recommendation"],
                "overall_score": result["overall_score"],
                "rounds_completed": result["rounds_completed"],
                "canonical_issue_count": result["canonical_issue_count"],
                "synthesis_mode": result["synthesis_mode"],
                "issues_path": str(target_dir / "reviews" / "issues.json"),
                "scorecard_path": str(target_dir / "reviews" / "FINAL_SCORECARD.json"),
            }
        )

    manifest_path = batch_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    aggregate = _build_aggregate(manifest)
    aggregate_path = batch_dir / "AGGREGATE_RESULTS.json"
    aggregate_path.write_text(json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8")
    leaderboard_path = batch_dir / "LEADERBOARD.md"
    leaderboard_path.write_text(_build_leaderboard_markdown(aggregate), encoding="utf-8")
    insights = _build_batch_insights(manifest)
    insights_path = batch_dir / "BATCH_INSIGHTS.json"
    insights_path.write_text(json.dumps(insights, indent=2, ensure_ascii=False), encoding="utf-8")
    insights_md_path = batch_dir / "BATCH_INSIGHTS.md"
    insights_md_path.write_text(_build_batch_insights_markdown(insights), encoding="utf-8")
    final_batch_report_path = batch_dir / "FINAL_BATCH_REPORT.md"
    final_batch_report_path.write_text(_build_final_batch_report(aggregate, insights, manifest), encoding="utf-8")
    batch_translation_paths = _write_batch_translations(
        report_text=final_batch_report_path.read_text(encoding="utf-8"),
        external_report_dir=external_report_dir,
        config=config,
    )
    batch_literature_paths = _write_batch_literature_reviews(
        report_text=final_batch_report_path.read_text(encoding="utf-8"),
        external_report_dir=external_report_dir,
        config=config,
    )
    exported_batch_files = _export_batch_reports(
        external_report_dir=external_report_dir,
        paths=[final_batch_report_path, *batch_translation_paths, *batch_literature_paths],
    )
    summary_path = batch_dir / "BATCH_SUMMARY.txt"
    summary_lines = ["Batch Review Summary", "", f"papers={len(manifest)}", ""]
    summary_lines.extend(
        [
            "Aggregate",
            f"- average_score={aggregate['average_score']}",
            f"- recommendation_counts={aggregate['recommendation_counts']}",
            f"- highest_score={aggregate['highest_score']}",
            f"- lowest_score={aggregate['lowest_score']}",
            f"- top_categories={insights['top_issue_categories']}",
            "",
            "Ranking",
        ]
    )
    for index, item in enumerate(aggregate["ranking"], start=1):
        summary_lines.append(
            f"{index}. {item['paper']} | score={item['overall_score']} | recommendation={item['final_recommendation']}"
        )
    summary_lines.append("")
    for item in manifest:
        summary_lines.extend(
            [
                f"- {item['paper']}",
                f"  title={item['paper_title']}",
                f"  review_mode={item['review_mode']}",
                f"  requested_rounds={item['requested_rounds']}",
                f"  recommendation={item['final_recommendation']} score={item['overall_score']}",
                f"  canonical_issues={item['canonical_issue_count']} synthesis_mode={item['synthesis_mode']}",
                f"  output={item['target_dir']}",
                f"  exported_report_dir={item['exported_report_dir']}",
            ]
        )
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    export_manifest = {
        "external_report_dir": str(external_report_dir),
        "paper_count": len(manifest),
        "reports": manifest,
        "batch_files": exported_batch_files,
    }
    export_manifest_path = batch_dir / "EXPORT_MANIFEST.json"
    export_manifest_path.write_text(json.dumps(export_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "batch_dir": str(batch_dir),
                "external_report_dir": str(external_report_dir),
                "paper_count": len(manifest),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def _build_aggregate(manifest: list[dict]) -> dict:
    if not manifest:
        return {
            "paper_count": 0,
            "average_score": 0.0,
            "recommendation_counts": {},
            "highest_score": None,
            "lowest_score": None,
            "ranking": [],
        }
    scores = [item["overall_score"] for item in manifest]
    recommendation_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    unsupported_breakdown: dict[str, int] = {}
    for item in manifest:
        recommendation_counts[item["final_recommendation"]] = recommendation_counts.get(item["final_recommendation"], 0) + 1
        mode_counts[item["review_mode"]] = mode_counts.get(item["review_mode"], 0) + 1
        scorecard_path = Path(item["scorecard_path"])
        if scorecard_path.exists():
            scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
            for reason, count in scorecard.get("evidence_checks", {}).get("unsupported_claim_breakdown", {}).items():
                unsupported_breakdown[reason] = unsupported_breakdown.get(reason, 0) + count
    ranking = sorted(manifest, key=lambda item: (-item["overall_score"], item["paper"]))
    return {
        "paper_count": len(manifest),
        "average_score": round(sum(scores) / len(scores), 2),
        "recommendation_counts": recommendation_counts,
        "mode_counts": mode_counts,
        "unsupported_claim_breakdown": unsupported_breakdown,
        "highest_score": max(scores),
        "lowest_score": min(scores),
        "ranking": [
            {
                "paper": item["paper"],
                "paper_title": item["paper_title"],
                "review_mode": item["review_mode"],
                "requested_rounds": item["requested_rounds"],
                "overall_score": item["overall_score"],
                "final_recommendation": item["final_recommendation"],
                "canonical_issue_count": item["canonical_issue_count"],
            }
            for item in ranking
        ],
    }


def _build_batch_insights(manifest: list[dict]) -> dict:
    category_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    persistent_titles: dict[str, int] = {}
    category_examples: dict[str, list[str]] = {}
    unsupported_breakdown: dict[str, int] = {}
    strongest = None
    weakest = None

    for item in manifest:
        issue_path = Path(item["issues_path"])
        if issue_path.exists():
            data = json.loads(issue_path.read_text(encoding="utf-8"))
            for issue in data.get("canonical_issues", []):
                category = issue.get("category", "other")
                status = issue.get("status", "unknown")
                category_counts[category] = category_counts.get(category, 0) + 1
                status_counts[status] = status_counts.get(status, 0) + 1
                category_examples.setdefault(category, [])
                title = issue.get("title", "untitled")
                if title not in category_examples[category] and len(category_examples[category]) < 4:
                    category_examples[category].append(title)
                if len(issue.get("history", [])) > 1:
                    persistent_titles[title] = persistent_titles.get(title, 0) + 1
        scorecard_path = Path(item["scorecard_path"])
        if scorecard_path.exists():
            scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
            for reason, count in scorecard.get("evidence_checks", {}).get("unsupported_claim_breakdown", {}).items():
                unsupported_breakdown[reason] = unsupported_breakdown.get(reason, 0) + count
        candidate = {
            "paper": item["paper"],
            "paper_title": item["paper_title"],
            "overall_score": item["overall_score"],
            "recommendation": item["final_recommendation"],
            "review_mode": item["review_mode"],
        }
        if strongest is None or candidate["overall_score"] > strongest["overall_score"]:
            strongest = candidate
        if weakest is None or candidate["overall_score"] < weakest["overall_score"]:
            weakest = candidate

    top_issue_categories = sorted(category_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
    top_statuses = sorted(status_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
    common_persistent_issues = sorted(persistent_titles.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
    return {
        "top_issue_categories": top_issue_categories,
        "category_examples": category_examples,
        "top_statuses": top_statuses,
        "common_persistent_issues": common_persistent_issues,
        "unsupported_claim_breakdown": unsupported_breakdown,
        "strongest_paper": strongest,
        "weakest_paper": weakest,
    }


def _build_batch_insights_markdown(insights: dict) -> str:
    lines = [
        "# Batch Insights",
        "",
        "## Strongest Paper",
        _format_paper_insight(insights.get("strongest_paper")),
        "",
        "## Weakest Paper",
        _format_paper_insight(insights.get("weakest_paper")),
        "",
        "## Top Issue Categories",
    ]
    if insights.get("top_issue_categories"):
        lines.extend(f"- {category}: {count}" for category, count in insights["top_issue_categories"])
    else:
        lines.append("- none")
    lines.extend(["", "## Category Examples"])
    if insights.get("category_examples"):
        for category, titles in sorted(insights["category_examples"].items()):
            lines.append(f"- {category}: {', '.join(titles)}")
    else:
        lines.append("- none")
    lines.extend(["", "## Top Statuses"])
    if insights.get("top_statuses"):
        lines.extend(f"- {status}: {count}" for status, count in insights["top_statuses"])
    else:
        lines.append("- none")
    lines.extend(["", "## Unsupported Claim Breakdown"])
    if insights.get("unsupported_claim_breakdown"):
        for reason, count in insights["unsupported_claim_breakdown"].items():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Common Persistent Issues"])
    if insights.get("common_persistent_issues"):
        lines.extend(f"- {title}: {count}" for title, count in insights["common_persistent_issues"])
    else:
        lines.append("- none")
    return "\n".join(lines)


def _format_paper_insight(item: dict | None) -> str:
    if not item:
        return "- none"
    return (
        f"- {item['paper']} | title={item['paper_title']} | mode={item['review_mode']} "
        f"| score={item['overall_score']} | recommendation={item['recommendation']}"
    )


def _build_final_batch_report(aggregate: dict, insights: dict, manifest: list[dict]) -> str:
    lines = [
        "# Final Batch Report",
        "",
        "## Overview",
        f"- Papers reviewed: {aggregate['paper_count']}",
        f"- Average score: {aggregate['average_score']}",
        f"- Recommendation counts: {aggregate['recommendation_counts']}",
        f"- Review mode counts: {aggregate.get('mode_counts', {})}",
        f"- Unsupported claim breakdown: {aggregate.get('unsupported_claim_breakdown', {})}",
        "",
        "## Strongest Paper",
        _format_paper_insight(insights.get("strongest_paper")),
        "",
        "## Weakest Paper",
        _format_paper_insight(insights.get("weakest_paper")),
        "",
        "## Common Risk Categories",
    ]
    if insights.get("top_issue_categories"):
        for category, count in insights["top_issue_categories"]:
            examples = ", ".join(insights.get("category_examples", {}).get(category, [])[:3]) or "no example titles"
            lines.append(f"- {category}: {count} papers/issues surfaced this risk. Examples: {examples}")
    else:
        lines.append("- none")
    lines.extend(["", "## Status Distribution"])
    if insights.get("top_statuses"):
        for status, count in insights["top_statuses"]:
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Persistent Risks"])
    if insights.get("common_persistent_issues"):
        for title, count in insights["common_persistent_issues"]:
            lines.append(f"- {title}: persisted across rounds in {count} paper(s)")
    else:
        lines.append("- none")
    lines.extend(["", "## Ranking"])
    for index, item in enumerate(aggregate["ranking"], start=1):
        lines.append(
            f"{index}. {item['paper']} | mode={item['review_mode']} | score={item['overall_score']} | recommendation={item['final_recommendation']}"
        )
    lines.extend(["", "## Per-Paper Outputs"])
    for item in manifest:
        lines.append(
            f"- {item['paper']} -> {item['target_dir']} | mode={item['review_mode']} | score={item['overall_score']} | recommendation={item['final_recommendation']}"
        )
    return "\n".join(lines)


def _load_entries(program_dir: Path, workspace_dir: Path, paper_dir: Path, args: argparse.Namespace) -> list[dict]:
    if args.batch_spec:
        spec_path = _resolve_batch_spec(program_dir, workspace_dir, args.batch_spec)
        data = json.loads(spec_path.read_text(encoding="utf-8-sig"))
        entries: list[dict] = []
        for index, item in enumerate(data, start=1):
            if "paper" not in item:
                raise ValueError(f"batch-spec entry {index} is missing 'paper'")
            if ("code_dir" in item) ^ ("run_command" in item):
                raise ValueError(f"batch-spec entry {index} must provide both 'code_dir' and 'run_command' together")
            entries.append(
                {
                    "paper_path": _resolve_paper_path(program_dir, workspace_dir, item["paper"]),
                    "rounds": item.get("rounds", args.rounds),
                    "code_dir": _resolve_code_dir(program_dir, workspace_dir, item["code_dir"]) if item.get("code_dir") else None,
                    "run_command": item.get("run_command"),
                }
            )
        return entries
    papers = sorted(paper_dir.glob(args.glob))
    return [{"paper_path": paper_path, "rounds": args.rounds, "code_dir": None, "run_command": None} for paper_path in papers]


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


def _resolve_paper_dir(program_dir: Path, workspace_dir: Path, paper_dir_arg: str | None) -> Path:
    if not paper_dir_arg:
        default_dir = workspace_dir / "essay"
        return default_dir.resolve() if default_dir.exists() else workspace_dir.resolve()
    raw = Path(paper_dir_arg)
    candidates = [raw, program_dir / raw, workspace_dir / raw, workspace_dir / "essay" / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Could not find paper directory: {paper_dir_arg}")


def _resolve_batch_spec(program_dir: Path, workspace_dir: Path, batch_spec_arg: str) -> Path:
    raw = Path(batch_spec_arg)
    candidates = [raw, program_dir / raw, workspace_dir / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Could not find batch spec: {batch_spec_arg}")


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


def _build_leaderboard_markdown(aggregate: dict) -> str:
    lines = [
        "# Batch Leaderboard",
        "",
        f"- paper_count: {aggregate['paper_count']}",
        f"- average_score: {aggregate['average_score']}",
        f"- recommendation_counts: {aggregate['recommendation_counts']}",
        f"- mode_counts: {aggregate.get('mode_counts', {})}",
        "",
        "| Rank | Paper | Mode | Score | Recommendation | Canonical Issues |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for index, item in enumerate(aggregate["ranking"], start=1):
        lines.append(
            f"| {index} | {item['paper']} | {item['review_mode']} | {item['overall_score']} | {item['final_recommendation']} | {item['canonical_issue_count']} |"
        )
    return "\n".join(lines)


def _handle_remove_readonly(func, path, excinfo) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _create_external_report_dir(workspace_dir: Path, timestamp: str) -> Path:
    root = workspace_dir / "final_report"
    root.mkdir(parents=True, exist_ok=True)
    batch_dir = root / f"final_{timestamp}"
    counter = 1
    while batch_dir.exists():
        counter += 1
        batch_dir = root / f"final_{timestamp}_{counter:02d}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    return batch_dir


def _export_paper_reports(
    target_dir: Path,
    external_report_dir: Path,
    index: int,
    paper_stem: str,
    final_report_bundle: str | None,
) -> Path:
    paper_report_dir = external_report_dir / f"{index:02d}_{paper_stem}"
    paper_report_dir.mkdir(parents=True, exist_ok=True)
    report_dir = paper_report_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_finalreport"
    report_dir.mkdir(parents=True, exist_ok=True)
    review_dir = target_dir / "reviews"
    _copy_if_exists(review_dir / "FINAL_REPORT.md", report_dir / "FINAL_REPORT.md")
    if final_report_bundle:
        bundle_path = Path(final_report_bundle)
        for name in (
            "FINAL_REPORT_CN.md",
            "FINAL_REPORT_JP.md",
            "FINAL_REPORT_EG.md",
        ):
            _copy_if_exists(bundle_path / name, report_dir / name)
        for name in (
            "LITERATURE_REVIEW_CN.md",
            "LITERATURE_REVIEW_JP.md",
            "LITERATURE_REVIEW_EG.md",
        ):
            _copy_if_exists(bundle_path / name, paper_report_dir / name)
    return paper_report_dir


def _export_batch_reports(external_report_dir: Path, paths: list[Path]) -> list[str]:
    report_dir = external_report_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_finalreport"
    report_dir.mkdir(parents=True, exist_ok=True)
    exported: list[str] = []
    for path in paths:
        if path.exists():
            target = report_dir / path.name
            if path.resolve() != target.resolve():
                shutil.copy2(path, target)
            exported.append(str(target))
    return exported


def _copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        shutil.copy2(source, target)


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return cleaned.strip("_") or "paper"


def _write_batch_translations(report_text: str, external_report_dir: Path, config: AppConfig) -> list[Path]:
    client = build_client(config.gpt)
    generated_paths: list[Path] = []
    for code, language in [("CN", "Simplified Chinese"), ("JP", "Japanese"), ("EG", "English")]:
        translated, _mode = _translate_report(client, report_text, language)
        path = external_report_dir / f"FINAL_BATCH_REPORT_{code}.md"
        path.write_text(translated, encoding="utf-8")
        generated_paths.append(path)
    return generated_paths


def _write_batch_literature_reviews(report_text: str, external_report_dir: Path, config: AppConfig) -> list[Path]:
    client = build_client(config.gpt)
    literature_review_en, _mode = _generate_batch_literature_review(client, report_text)
    generated_paths: list[Path] = []
    for code, language in [("CN", "Simplified Chinese"), ("JP", "Japanese"), ("EG", "English")]:
        if code == "EG":
            translated = literature_review_en
        else:
            translated, _ = _translate_report(client, literature_review_en, language)
        path = external_report_dir / f"BATCH_LITERATURE_REVIEW_{code}.md"
        path.write_text(translated, encoding="utf-8")
        generated_paths.append(path)
    return generated_paths


def _translate_report(client, report_text: str, target_language: str) -> tuple[str, str]:
    if target_language == "English":
        return report_text, "source"
    prompt = "\n".join(
        [
            f"Target language: {target_language}",
            "Translate the following batch paper review report.",
            "Keep the markdown structure, headings, bullets, and code blocks.",
            "Do not summarize. Preserve file names, scores, labels, and recommendation names where sensible.",
            "",
            report_text,
        ]
    )
    try:
        response = client.generate(
            system_prompt="You are a precise technical translator for software and research review reports.",
            user_prompt=prompt,
        )
        return response.content, "api"
    except Exception:
        return _fallback_translation(report_text, target_language), "fallback"


def _generate_batch_literature_review(client, report_text: str) -> tuple[str, str]:
    prompt = "\n".join(
        [
            "Write a literature-review style comparative synthesis based only on the batch final report below.",
            "Use markdown.",
            "Include these sections exactly:",
            "1. Batch Scope",
            "2. Common Strengths",
            "3. Common Weaknesses",
            "4. Evidence and Evaluation Trends",
            "5. Cross-Paper Positioning",
            "6. Overall Takeaway",
            "Do not invent new claims beyond the report.",
            "",
            report_text,
        ]
    )
    try:
        response = client.generate(
            system_prompt="You are a precise research writing assistant producing literature-review style comparative summaries.",
            user_prompt=prompt,
        )
        return response.content, "api"
    except Exception:
        fallback = "\n".join(
            [
                "# Batch Literature Review",
                "",
                "## Batch Scope",
                "- Derived from the final batch report.",
                "",
                "## Common Strengths",
                "- See the batch report for aggregate strengths and strongest papers.",
                "",
                "## Common Weaknesses",
                "- See the batch report for recurring weaknesses and risk categories.",
                "",
                "## Evidence and Evaluation Trends",
                "- This fallback preserves report-grounded conclusions without inventing new evidence.",
                "",
                "## Cross-Paper Positioning",
                "- Interpret comparative standing using the batch ranking and recommendation counts.",
                "",
                "## Overall Takeaway",
                "- The overall takeaway should follow the final batch report and its evidence gaps.",
            ]
        )
        return fallback, "fallback"


def _fallback_translation(report_text: str, target_language: str) -> str:
    header = f"# {target_language} Translation Fallback"
    note = (
        "Translation API was unavailable for this language, so the original report is preserved below "
        "to avoid losing deliverables."
    )
    return f"{header}\n\n{note}\n\n{report_text}"


if __name__ == "__main__":
    main()
