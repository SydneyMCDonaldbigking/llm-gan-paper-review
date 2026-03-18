from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class TableConsistencyResult:
    table_count: int
    tables_with_digits: int
    candidate_result_tables: int
    suspicious_tables: int
    structured_tables: int
    header_like_tables: int
    data_like_rows: int
    findings: list[str]


@dataclass
class ClaimAlignmentResult:
    source_claim_count: int
    claim_count: int
    aligned_claims: int
    unsupported_claims: int
    alignments: list[dict]
    findings: list[str]


class TableConsistencyChecker:
    def analyze(
        self,
        table_sections: list[str],
        table_blocks: list[list[str]] | None = None,
        table_captions: list[str] | None = None,
    ) -> TableConsistencyResult:
        findings: list[str] = []
        candidate_result_tables = 0
        suspicious_tables = 0
        tables_with_digits = 0
        structured_tables = 0
        header_like_tables = 0
        data_like_rows = 0
        normalized_sections = list(table_sections)
        if table_blocks:
            normalized_sections.extend(" | ".join(block) for block in table_blocks)
        if table_captions:
            normalized_sections.extend(table_captions)

        for section in normalized_sections:
            if not self._looks_like_table_candidate(section):
                continue
            digits = re.findall(r"\b\d+(?:\.\d+)?%?\b", section)
            if digits:
                tables_with_digits += 1
            lowered = section.lower()
            if any(token in lowered for token in ["result", "dataset", "baseline", "recall", "f1", "rank"]):
                candidate_result_tables += 1
            if digits and not any(token in lowered for token in ["table", "dataset", "result", "baseline", "recall", "f1", "rank"]):
                suspicious_tables += 1
                findings.append(f"Numeric-heavy table reference lacks obvious result labels: {section[:180]}")
            if any(token in lowered for token in ["old", "new"]) and not re.search(r"\bbug\b|\bfix\b|\bmistak", lowered):
                findings.append(f"Old/new result framing appears without nearby correction context: {section[:180]}")

        for index, block in enumerate(table_blocks or []):
            caption = table_captions[index] if table_captions and index < len(table_captions) else ""
            block_summary = self._analyze_block(block, caption)
            if block_summary["structured"]:
                structured_tables += 1
            if block_summary["header_like"]:
                header_like_tables += 1
            data_like_rows += block_summary["data_like_rows"]
            findings.extend(block_summary["findings"])

        return TableConsistencyResult(
            table_count=sum(1 for section in normalized_sections if self._looks_like_table_candidate(section)),
            tables_with_digits=tables_with_digits,
            candidate_result_tables=candidate_result_tables,
            suspicious_tables=suspicious_tables,
            structured_tables=structured_tables,
            header_like_tables=header_like_tables,
            data_like_rows=data_like_rows,
            findings=findings[:10],
        )

    def _looks_like_table_candidate(self, section: str) -> bool:
        lowered = section.lower()
        digits = re.findall(r"\b\d+(?:\.\d+)?%?\b", section)
        if "table" in lowered:
            return True
        if len(digits) >= 3 and any(token in lowered for token in ["dataset", "baseline", "recall", "f1", "rank", "old", "new", "train", "dev", "result"]):
            return True
        if len(digits) >= 4 and any(char in section for char in ["|", "\t"]):
            return True
        return False

    def _analyze_block(self, block: list[str], caption: str = "") -> dict:
        joined = " ".join(block).lower()
        first_line = block[0].lower() if block else ""
        data_like_rows = sum(1 for line in block if len(re.findall(r"\b\d+(?:\.\d+)?%?\b", line)) >= 2)
        caption_lower = caption.lower()
        header_like = any(
            token in first_line or token in caption_lower
            for token in ["dataset", "baseline", "result", "recall", "f1", "rank", "table", "subtask", "performance"]
        )
        structured = len(block) >= 2 and data_like_rows >= 1
        findings: list[str] = []
        if structured and not header_like:
            findings.append(f"Table block has data rows but weak header signal: {' | '.join(block[:3])[:180]}")
        if "old" in joined and "new" in joined and not re.search(r"\bbug\b|\bfix\b|\bmistak", joined):
            findings.append(f"Table block compares old/new values without explicit correction note: {' | '.join(block[:4])[:180]}")
        if structured and data_like_rows >= 2 and not any(token in joined for token in ["dataset", "train", "dev", "tweet", "subtask", "baseline"]):
            findings.append(f"Numeric table block lacks dataset/task labels: {' | '.join(block[:4])[:180]}")
        if caption and not any(token in caption_lower for token in ["table", "result", "dataset", "subtask", "performance"]):
            findings.append(f"Table caption is present but weakly descriptive: {caption[:180]}")
        return {
            "structured": structured,
            "header_like": header_like,
            "data_like_rows": data_like_rows,
            "findings": findings,
        }


class ClaimAlignmentChecker:
    def analyze(
        self,
        claim_sentences: list[str],
        table_captions: list[str],
        figure_captions: list[str],
        table_blocks: list[list[str]] | None = None,
    ) -> ClaimAlignmentResult:
        evidence_pool = list(table_captions) + list(figure_captions)
        if table_blocks:
            evidence_pool.extend(" | ".join(block) for block in table_blocks[:8])

        alignments: list[dict] = []
        findings: list[str] = []
        aligned = 0
        subclaims = self._expand_claims(claim_sentences)
        for item in subclaims:
            claim = item["claim"]
            source_claim = item["source_claim"]
            claim_tokens = self._tokens(claim)
            preferred_label, preferred_number = self._extract_reference(claim)
            best_match = ""
            best_score = 0.0
            for evidence in evidence_pool:
                label_bonus = self._reference_bonus(evidence, preferred_label, preferred_number)
                evidence_tokens = self._tokens(evidence)
                if not evidence_tokens:
                    continue
                overlap = len(claim_tokens & evidence_tokens)
                score = (
                    overlap / max(1, len(claim_tokens))
                ) + label_bonus + self._semantic_bonus(claim, evidence)
                if score > best_score:
                    best_score = score
                    best_match = evidence
            metric_support = self._metric_support_detail(claim, best_match)
            supported = best_score >= 0.18
            if metric_support["status"] == "full":
                supported = True
            elif metric_support["status"] == "partial":
                supported = False
            elif metric_support["status"] == "none" and metric_support["claim_metric_count"] > 0:
                supported = False
            unsupported_reason = "" if supported else self._classify_unsupported_reason(claim, best_match, metric_support)
            if supported:
                aligned += 1
            else:
                findings.append(f"Claim lacks clear figure/table support ({unsupported_reason or 'unknown'}): {claim[:180]}")
            alignments.append(
                {
                    "claim": claim,
                    "source_claim": source_claim,
                    "supported": supported,
                    "best_evidence": best_match[:220],
                    "overlap_score": round(best_score, 3),
                    "reference_hint": f"{preferred_label} {preferred_number}".strip(),
                    "unsupported_reason": unsupported_reason,
                    "metric_support": metric_support,
                }
            )

        return ClaimAlignmentResult(
            source_claim_count=len(claim_sentences),
            claim_count=len(subclaims),
            aligned_claims=aligned,
            unsupported_claims=max(0, len(subclaims) - aligned),
            alignments=alignments[:12],
            findings=findings[:8],
        )

    def _expand_claims(self, claim_sentences: list[str]) -> list[dict]:
        expanded: list[dict] = []
        for sentence in claim_sentences:
            pieces = self._split_claim(sentence)
            for piece in pieces:
                expanded.append({"claim": piece, "source_claim": sentence})
        return expanded

    def _split_claim(self, sentence: str) -> list[str]:
        pieces: list[str] = []
        metric_piece = re.sub(r"\([^)]*rank[^)]*\)", "", sentence, flags=re.IGNORECASE)
        metric_piece = re.sub(r",?\s*ranked\s+\d+/\d+", "", metric_piece, flags=re.IGNORECASE)
        metric_piece = re.sub(r"\s+", " ", metric_piece).strip(" ,;")
        if metric_piece != sentence and self._looks_like_metric_claim(metric_piece):
            pieces.append(metric_piece)

        rank_matches = re.findall(
            r"ranked\s+\d+/\d+",
            sentence,
            flags=re.IGNORECASE,
        )
        if rank_matches:
            rank_claim = self._normalize_rank_claim(sentence, rank_matches)
            if rank_claim:
                pieces.append(rank_claim)
        elif re.search(r"\brank(?:ed)?\b", sentence, flags=re.IGNORECASE):
            pieces.append(sentence.strip())

        if not pieces:
            pieces.append(sentence.strip())

        deduped: list[str] = []
        seen: set[str] = set()
        for piece in pieces:
            key = piece.lower()
            if key not in seen:
                deduped.append(piece)
                seen.add(key)
        return deduped

    def _tokens(self, text: str) -> set[str]:
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "our",
            "their",
            "paper",
            "results",
            "result",
            "figure",
            "table",
            "shows",
            "show",
            "using",
            "used",
            "task",
        }
        return {token for token in tokens if token not in stopwords and len(token) > 2}

    def _extract_reference(self, text: str) -> tuple[str, str]:
        match = re.search(r"\b(table|figure|fig)\s+(\d+)\b", text, flags=re.IGNORECASE)
        if not match:
            return "", ""
        label = "figure" if match.group(1).lower() == "fig" else match.group(1).lower()
        return label, match.group(2)

    def _reference_bonus(self, evidence: str, label: str, number: str) -> float:
        if not label or not number:
            return 0.0
        normalized = evidence.lower()
        alias = "fig" if label == "figure" else label
        if re.search(rf"\b{label}\s+{number}\b", normalized):
            return 0.35
        if re.search(rf"\b{alias}\.?\s+{number}\b", normalized):
            return 0.35
        if label in normalized:
            return -0.04
        return 0.0

    def _semantic_bonus(self, claim: str, evidence: str) -> float:
        claim_lower = claim.lower()
        evidence_lower = evidence.lower()
        bonus = 0.0
        if re.search(r"\brank(?:ed)?\b", claim_lower) and not re.search(r"\brank\b", evidence_lower):
            bonus -= 0.25
        if re.search(r"\brecall\b", claim_lower) and re.search(r"\brecall\b", evidence_lower):
            bonus += 0.08
        if re.search(r"\bf1|f-?measure\b", claim_lower) and re.search(r"\bf1|f-?measure\b", evidence_lower):
            bonus += 0.08
        if re.search(r"\bsubtask\s+[ab]\b", claim_lower):
            subtask = re.search(r"\bsubtask\s+([ab])\b", claim_lower)
            if subtask and re.search(rf"\bsubtask\s+{subtask.group(1)}\b", evidence_lower):
                bonus += 0.05
        return bonus

    def _classify_unsupported_reason(self, claim: str, best_evidence: str, metric_support: dict | None = None) -> str:
        claim_lower = claim.lower()
        evidence_lower = best_evidence.lower()
        if metric_support:
            if metric_support.get("status") == "partial":
                return "partial_metric_support"
            if metric_support.get("status") == "none" and metric_support.get("claim_metric_count", 0) > 0:
                if metric_support.get("evidence_metric_count", 0) > 0:
                    return "metric_mismatch_risk"
                return "missing_metric_support"
        if re.search(r"\brank(?:ed)?\b", claim_lower) and not re.search(r"\brank\b", evidence_lower):
            return "missing_rank_support"
        if re.search(r"\b(f1|f-?measure|recall|accuracy|precision)\b", claim_lower):
            if not re.search(r"\b(f1|f-?measure|recall|accuracy|precision)\b", evidence_lower):
                return "missing_metric_support"
            return "metric_mismatch_risk"
        if re.search(r"\btable\s+\d+\b|\bfigure\s+\d+\b", claim_lower):
            return "reference_not_grounded"
        return "missing_table_support"

    def _looks_like_metric_claim(self, text: str) -> bool:
        lowered = text.lower()
        return bool(
            re.search(r"\b(f1|f-?measure|recall|accuracy|precision)\b", lowered)
            and re.search(r"\b\d+\.\d+%?\b", lowered)
        )

    def _normalize_rank_claim(self, sentence: str, rank_matches: list[str]) -> str:
        lowered = sentence.lower()
        if "system ranked" in lowered:
            return sentence.strip()
        task_refs = re.findall(r"\bsubtask\s+[ab]\b", sentence, flags=re.IGNORECASE)
        if len(rank_matches) >= 2 and len(task_refs) >= 2:
            return f"The system {rank_matches[0]} for {task_refs[0]} and {rank_matches[1]} for {task_refs[1]}."
        joined = " and ".join(rank_matches[:2])
        task_suffix = f" for {' and '.join(task_refs[:2])}" if task_refs else ""
        return f"The system {joined}{task_suffix}."

    def _metric_support_detail(self, claim: str, evidence: str) -> dict:
        claim_pairs = self._extract_metric_pairs(claim)
        evidence_pairs = self._extract_metric_pairs(evidence)
        evidence_numbers = [self._as_float(value) for value in re.findall(r"\b\d+(?:\.\d+)?%?\b", evidence)]
        matched_pairs: list[dict] = []
        for pair in claim_pairs:
            metric = pair["metric"]
            value = pair["value"]
            expected = self._as_float(value)
            matched = False
            for evidence_pair in evidence_pairs:
                if evidence_pair["metric"] != metric:
                    continue
                observed = self._as_float(evidence_pair["value"])
                if expected is not None and observed is not None and abs(expected - observed) <= 0.002:
                    matched = True
                    break
            if not matched and expected is not None:
                for observed in evidence_numbers:
                    if observed is not None and abs(expected - observed) <= 0.002:
                        matched = True
                        break
            if matched:
                matched_pairs.append(pair)
        claim_count = len(claim_pairs)
        matched_count = len(matched_pairs)
        status = "na"
        if claim_count > 0:
            if matched_count == claim_count:
                status = "full"
            elif matched_count > 0:
                status = "partial"
            else:
                status = "none"
        return {
            "status": status,
            "claim_metric_count": claim_count,
            "matched_metric_count": matched_count,
            "evidence_metric_count": len(evidence_pairs),
            "matched_metrics": matched_pairs,
        }

    def _extract_metric_pairs(self, text: str) -> list[dict]:
        patterns = {
            "f1": [
                r"\b(?:f1|f-?measure)\b[^0-9]{0,12}(\d+(?:\.\d+)?%?)",
                r"(\d+(?:\.\d+)?%?)\s+(?:f1|f-?measure)\b",
            ],
            "recall": [
                r"\brecall\b[^0-9]{0,12}(\d+(?:\.\d+)?%?)",
                r"(\d+(?:\.\d+)?%?)\s+recall\b",
            ],
            "accuracy": [
                r"\baccuracy\b[^0-9]{0,12}(\d+(?:\.\d+)?%?)",
                r"(\d+(?:\.\d+)?%?)\s+accuracy\b",
            ],
            "precision": [
                r"\bprecision\b[^0-9]{0,12}(\d+(?:\.\d+)?%?)",
                r"(\d+(?:\.\d+)?%?)\s+precision\b",
            ],
        }
        pairs: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for metric, pattern_list in patterns.items():
            for pattern in pattern_list:
                for value in re.findall(pattern, text, flags=re.IGNORECASE):
                    key = (metric, value)
                    if key in seen:
                        continue
                    seen.add(key)
                    pairs.append({"metric": metric, "value": value})
        return pairs

    def _as_float(self, value: str) -> float | None:
        normalized = value.strip().rstrip("%")
        try:
            return float(normalized)
        except ValueError:
            return None
