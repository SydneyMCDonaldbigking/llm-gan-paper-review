from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass
class PaperArtifact:
    source_path: Path
    text_path: Path
    title: str
    text: str
    figure_mentions: int
    table_mentions: int
    figure_sections: list[str]
    table_sections: list[str]
    numeric_lines: list[str]
    table_blocks: list[list[str]]
    table_captions: list[str]
    figure_captions: list[str]
    table_block_captions: list[str]
    claim_sentences: list[str]
    metric_claims: list[dict]


class PaperParser:
    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir

    def ingest_pdf(self, pdf_path: Path) -> PaperArtifact:
        paper_dir = self.work_dir / "paper"
        paper_dir.mkdir(parents=True, exist_ok=True)
        copied_pdf = paper_dir / pdf_path.name
        shutil.copy2(pdf_path, copied_pdf)

        reader = PdfReader(str(pdf_path))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = self._normalize_text("\n\n".join(pages).strip())
        text_path = paper_dir / "submission.txt"
        text_path.write_text(text, encoding="utf-8")

        title = self._extract_title(text, pdf_path.stem)
        figure_mentions = len(re.findall(r"\bfigure\b|\bfig\.\b", text, flags=re.IGNORECASE))
        table_mentions = len(re.findall(r"\btable\b", text, flags=re.IGNORECASE))
        figure_sections = self._extract_sections(text, ["figure", "fig."])
        table_sections = self._extract_sections(text, ["table"])
        table_blocks = self._extract_table_blocks(text)
        table_captions = self._extract_captions(text, "table")
        figure_captions = self._extract_captions(text, "figure")
        return PaperArtifact(
            source_path=copied_pdf,
            text_path=text_path,
            title=title,
            text=text,
            figure_mentions=figure_mentions,
            table_mentions=table_mentions,
            figure_sections=figure_sections,
            table_sections=table_sections,
            numeric_lines=self._extract_numeric_lines(text),
            table_blocks=table_blocks,
            table_captions=table_captions,
            figure_captions=figure_captions,
            table_block_captions=self._match_table_captions(table_blocks, table_captions),
            claim_sentences=self._extract_claim_sentences(text),
            metric_claims=self._extract_metric_claims(text),
        )

    def _extract_title(self, text: str, fallback: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        head = lines[:20]
        abstract_index = next((idx for idx, line in enumerate(head) if line.lower() == "abstract"), len(head))
        search_space = head[:abstract_index]
        filtered: list[str] = []
        for line in search_space:
            lowered = line.lower()
            if "@" in line:
                break
            if re.search(r"\bpages?\b|\bproceedings\b|association for computational linguistics|san diego|california", lowered):
                continue
            if re.fullmatch(r"[\d,.\- ]+", line):
                continue
            filtered.append(line)

        title_lines: list[str] = []
        for line in filtered:
            if len(line) < 6:
                continue
            if re.search(r"\bcomputer engineering\b|\bvisual computing\b|\begypt\b|\bksa\b", line.lower()):
                break
            if self._looks_like_author_line(line):
                break
            title_lines.append(line)
            if len(title_lines) >= 3:
                break

        if title_lines:
            return " ".join(title_lines)[:200]
        return (lines[0] if lines else fallback)[:200]

    def _extract_sections(self, text: str, keywords: list[str]) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        matches: list[str] = []
        for line in lines:
            lowered = line.lower()
            if any(keyword in lowered for keyword in keywords):
                matches.append(line[:300])
        return matches[:20]

    def _normalize_text(self, text: str) -> str:
        replacements = {
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
            "\u2013": "-",
            "\u2014": "-",
            "\u00a0": " ",
            "鈥檚": "'s",
            "鈥檝e": "'ve",
            "鈥檛": "n't",
            "鈥檙e": "'re",
            "鈥檇": "'d",
            "鈥檒l": "'ll",
            "鈥檚": "'s",
            "鈥檚 sentiment": "'s sentiment",
            "鈥淭": '"T',
            "鈥淔": '"F',
            "鈥?": "-",
            "鈥": "-",
            "鈨?": "©",
            "铿乧": "fi",
            "铿乶": "fi",
            "铿乺": "fi",
            "铿乼": "fit",
            "铿乪": "er",
            "铿乨": "d",
            "篓": "o",
        }
        normalized = text
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _looks_like_author_line(self, line: str) -> bool:
        if "@" in line:
            return True
        if re.search(r"\b[a-z]+\.[a-z]+@", line.lower()):
            return True
        if re.search(r"[A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+){1,}", line) and "," in line:
            return True
        if re.search(r"[A-Za-z]+\d", line) and "," in line:
            return True
        return False

    def _extract_numeric_lines(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        numeric_lines = [line[:300] for line in lines if len(re.findall(r"\b\d+(?:\.\d+)?%?\b", line)) >= 2]
        return numeric_lines[:40]

    def _extract_table_blocks(self, text: str) -> list[list[str]]:
        lines = [line.strip() for line in text.splitlines()]
        blocks: list[list[str]] = []
        current: list[str] = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                if len(current) >= 2:
                    cleaned = self._clean_table_block(current)
                    if len(cleaned) >= 2:
                        blocks.append(cleaned[:12])
                current = []
                continue
            lowered = line.lower()
            numeric_hits = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", line))
            if "table" in lowered or numeric_hits >= 3:
                current.append(line[:300])
            else:
                if len(current) >= 2:
                    cleaned = self._clean_table_block(current)
                    if len(cleaned) >= 2:
                        blocks.append(cleaned[:12])
                current = []
        if len(current) >= 2:
            cleaned = self._clean_table_block(current)
            if len(cleaned) >= 2:
                blocks.append(cleaned[:12])
        return blocks[:12]

    def _extract_captions(self, text: str, label: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        pattern = rf"^{label}\s+\d+\b"
        captions: list[str] = []
        seen: set[str] = set()
        for line in lines:
            if not re.match(pattern, line, flags=re.IGNORECASE):
                continue
            normalized = self._clean_caption_text(re.sub(r"\s+", " ", line).strip())
            if self._is_caption_fragment(normalized, label):
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            captions.append(normalized[:300])
        return captions[:20]

    def _match_table_captions(self, table_blocks: list[list[str]], table_captions: list[str]) -> list[str]:
        matched: list[str] = []
        remaining_captions = table_captions.copy()
        for block in table_blocks:
            block_text = " ".join(block).lower()
            caption = self._best_caption_match(block_text, remaining_captions)
            if caption:
                matched.append(caption)
                if caption in remaining_captions:
                    remaining_captions.remove(caption)
                continue
            inferred = ""
            if any(token in block_text for token in ["train-", "dev-", "dataset", "subtask"]):
                inferred = "Inferred dataset split table"
            elif any(token in block_text for token in ["baseline", "old", "new", "recall", "f1", "rank"]):
                inferred = "Inferred results comparison table"
            matched.append(inferred)
        return matched

    def _best_caption_match(self, block_text: str, captions: list[str]) -> str:
        best_caption = ""
        best_score = 0.0
        block_tokens = self._caption_tokens(block_text)
        for caption in captions:
            caption_tokens = self._caption_tokens(caption.lower())
            if not caption_tokens:
                continue
            overlap = len(block_tokens & caption_tokens)
            score = overlap / len(caption_tokens)
            if score > best_score:
                best_score = score
                best_caption = caption
        if best_score >= 0.25:
            return best_caption
        return ""

    def _caption_tokens(self, text: str) -> set[str]:
        tokens = set(re.findall(r"[a-z0-9]+", text.lower()))
        stopwords = {
            "table",
            "figure",
            "the",
            "and",
            "for",
            "with",
            "from",
            "this",
            "that",
            "note",
            "shows",
            "show",
            "result",
            "results",
        }
        return {token for token in tokens if token not in stopwords and len(token) > 2}

    def _is_caption_fragment(self, text: str, label: str) -> bool:
        lowered = text.lower()
        if len(text) < 18:
            return True
        if re.fullmatch(rf"{label}\s+\d+\b", lowered):
            return True
        if re.match(rf"{label}\s+\d+\s+shows?\b", lowered):
            return True
        if lowered.endswith(("shows", "show", "the", "of", "for", "to", "in", "on", "with")):
            return True
        if re.search(r"\bto\s+[a-z]{1,4}-?$", lowered):
            return True
        if lowered.count(":") == 0 and lowered.count(".") == 0 and len(text.split()) <= 4:
            return True
        return False

    def _clean_caption_text(self, text: str) -> str:
        cleaned = text
        cleaned = re.sub(r"\b(Note|note)\s*:\s*[A-Za-z-]{1,6}$", "", cleaned)
        cleaned = re.sub(r"\b[A-Za-z]{1,4}-$", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:;,.")
        return cleaned

    def _is_non_table_noise(self, line: str) -> bool:
        lowered = line.lower()
        noisy_patterns = [
            "proceedings of",
            "association for computational linguistics",
            "san diego",
            "california",
            "computer engineering",
            "visual computing",
            "http://",
            "https://",
        ]
        return any(pattern in lowered for pattern in noisy_patterns)

    def _clean_table_block(self, lines: list[str]) -> list[str]:
        cleaned = [item for item in lines if not self._is_non_table_noise(item)]
        while cleaned and self._is_table_tail_noise(cleaned[-1]):
            cleaned.pop()
        return cleaned

    def _is_table_tail_noise(self, line: str) -> bool:
        lowered = line.lower().strip()
        if re.search(r"\b(of )?ram\b|\bgpu\b|\bintel\b|\bcore i\b", lowered):
            return True
        if re.match(r"^(table|figure|fig\.?)\s+\d+\s+shows?\b", lowered):
            return True
        if lowered.endswith("table 4 shows") or lowered.endswith("table 5 shows"):
            return True
        if re.search(r"\bshows?\b", lowered) and "table" in lowered and ":" not in lowered:
            return True
        return False

    def _extract_claim_sentences(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text)
        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        keywords = [
            "achieved",
            "outperformed",
            "improved",
            "results",
            "ranked",
            "we found",
            "we show",
            "we demonstrate",
            "performance",
            "f1",
            "recall",
            "accuracy",
            "conclusion",
        ]
        claims: list[str] = []
        for sentence in sentences:
            stripped = sentence.strip()
            lowered = stripped.lower()
            if len(stripped) < 40:
                continue
            if self._looks_like_claim_noise(lowered):
                continue
            if self._looks_like_method_sentence(lowered):
                continue
            if not self._looks_like_result_sentence(lowered):
                continue
            if any(keyword in lowered for keyword in keywords):
                claims.append(stripped[:300])
        deduped: list[str] = []
        seen: set[str] = set()
        for claim in claims:
            key = self._canonicalize_claim(claim)
            if key not in seen:
                deduped.append(claim)
                seen.add(key)
        return deduped[:20]

    def _extract_metric_claims(self, text: str) -> list[dict]:
        metric_patterns = {
            "f1": r"\b(?:f1|f-?measure)\b",
            "recall": r"\brecall\b",
            "accuracy": r"\baccuracy\b",
            "precision": r"\bprecision\b",
        }
        claims: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for sentence in self._extract_claim_sentences(text):
            lowered = sentence.lower()
            if "http" in lowered or "cpu" in lowered or "gpu" in lowered or "core i" in lowered:
                continue
            decimal_values = re.findall(r"\b\d+\.\d+%?\b", sentence)
            percent_values = re.findall(r"\b\d+%+\b", sentence)
            numbers = decimal_values or percent_values
            if not numbers:
                continue
            for metric_name, pattern in metric_patterns.items():
                if re.search(pattern, lowered):
                    key = (metric_name, sentence[:120].lower())
                    if key in seen:
                        break
                    seen.add(key)
                    claims.append(
                        {
                            "metric": metric_name,
                            "sentence": sentence[:300],
                            "values": numbers[:4],
                        }
                    )
                    break
        return claims[:20]

    def _looks_like_result_sentence(self, lowered: str) -> bool:
        result_markers = [
            "achieved",
            "ranked",
            "results",
            "improved",
            "outperformed",
            "we show",
            "we found",
            "f1",
            "recall",
            "accuracy",
            "precision",
            "table ",
            "figure ",
        ]
        if any(noise in lowered for noise in ["http", "cpu", "gpu", "dropout layers", "embedding dimension"]):
            return False
        if not any(marker in lowered for marker in result_markers):
            return False
        if not any(
            marker in lowered
            for marker in [
                "f1",
                "recall",
                "accuracy",
                "precision",
                "rank",
                "outperform",
                "improv",
                "result",
                "table ",
                "figure ",
                "perform",
                "%",
            ]
        ):
            return False
        return True

    def _looks_like_claim_noise(self, lowered: str) -> bool:
        noise_prefixes = [
            "in this paper",
            "in this work",
            "in the given example",
            "in the given exam- ple",
            "for example",
            "note:",
            "note that",
            "as shown in fig",
            "as shown in figure",
        ]
        if any(lowered.startswith(prefix) for prefix in noise_prefixes):
            return True
        if lowered.count("[") >= 2 and lowered.count("]") >= 2:
            return True
        if re.search(r"\bet al\.", lowered):
            return True
        if re.search(r"\bsection\s+\d+\b", lowered):
            return True
        if re.search(r"\btrain-[ab]\b|\bdev-[ab]\b|\bdataset\b", lowered) and len(re.findall(r"\b\d+(?:\.\d+)?%?\b", lowered)) >= 4:
            return True
        if re.search(r"\btable\s+\d+[:.]", lowered):
            return True
        if re.match(r"^(table|figure|fig\.?)\s+\d+\b", lowered) and not re.search(
            r"\b(show|shows|result|results|perform|rank|improv|outperform)\b",
            lowered,
        ):
            return True
        if re.fullmatch(r".*\bresults on\b.*", lowered) and not re.search(r"\bwe\b|\bour\b", lowered):
            return True
        if re.search(r"\btask\s+[ab]\b", lowered) and not re.search(
            r"\b(f1|recall|accuracy|precision|rank|result|results|improv|outperform|perform)\b",
            lowered,
        ):
            return True
        return False

    def _extract_reference_number(self, text: str, label: str) -> str:
        match = re.search(rf"\b{label}\s+(\d+)\b", text, flags=re.IGNORECASE)
        return match.group(1) if match else ""

    def _canonicalize_claim(self, claim: str) -> str:
        lowered = claim.lower().strip()
        lowered = re.sub(r"^(our models?|our model|we)\s+", "", lowered)
        lowered = re.sub(r"\s+", " ", lowered)
        return lowered

    def _looks_like_method_sentence(self, lowered: str) -> bool:
        method_markers = [
            "the purpose of this layer",
            "we used zero padding",
            "embedding dimension",
            "dropout layers",
            "soft-max layer",
            "gru layer",
            "tokenize",
            "preprocessing steps",
            "validate our model",
            "learning parameters",
            "training epochs",
            "optimal learning",
        ]
        return any(marker in lowered for marker in method_markers)
