# verifier.py
# Module D v2: The Verifier (3-Stage Pipeline)
# Implements: Evidence Retrieval -> Deterministic Alignment -> Adversarial Check

import json
import math
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from openai import OpenAI
from rich.console import Console

from aligners import CompositeAligner
from evaluation.alignment_eval import evaluate_claim_evidence_alignment
from evaluation.citation_diversity_eval import evaluate_citation_diversity
from models import (
    ClaimBasedReport,
    ClaimType,
    Event,
    SupportingEvidence,
    VerificationResult,
    VerificationStatus,
)

console = Console()


@dataclass
class EvidenceChunk:
    chunk_id: str
    article_id: str
    source_url: str
    source_outlet: str
    ref_index: str
    text: str


class EvidenceRetriever:
    """Small in-memory TF-IDF retriever over article chunks."""

    def __init__(self, articles, chunk_size: int = 700, overlap: int = 120):
        self.chunks: List[EvidenceChunk] = []
        self.doc_tokens: List[Set[str]] = []
        self.idf: Dict[str, float] = {}
        self._build_chunks(articles, chunk_size, overlap)
        self._build_index()

    def _build_chunks(self, articles, chunk_size: int, overlap: int) -> None:
        for ref_index, article in enumerate(articles, 1):
            raw_text = article.full_text or article.snippet or ""
            text = re.sub(r"\s+", " ", raw_text).strip()
            if not text:
                continue

            step = max(1, chunk_size - overlap)
            starts = range(0, len(text), step) if len(text) > chunk_size else [0]
            for chunk_no, start in enumerate(starts, 1):
                span = text[start : start + chunk_size].strip()
                if len(span) < 20:
                    continue
                self.chunks.append(
                    EvidenceChunk(
                        chunk_id=f"{article.article_id}#{chunk_no}",
                        article_id=article.article_id,
                        source_url=article.url,
                        source_outlet=article.source.outlet_name,
                        ref_index=str(ref_index),
                        text=span,
                    )
                )

    def _build_index(self) -> None:
        doc_freq: Dict[str, int] = {}
        for chunk in self.chunks:
            tokens = set(self._tokenize(chunk.text))
            self.doc_tokens.append(tokens)
            for token in tokens:
                doc_freq[token] = doc_freq.get(token, 0) + 1

        total_docs = max(1, len(self.chunks))
        self.idf = {
            token: math.log((1 + total_docs) / (1 + freq)) + 1.0
            for token, freq in doc_freq.items()
        }

    def retrieve(
        self,
        claim_text: str,
        top_k: int = 5,
        preferred_source_ids: Optional[List[str]] = None,
    ) -> List[EvidenceChunk]:
        query_tokens = self._tokenize(claim_text)
        if not query_tokens or not self.chunks:
            return []

        preferred = set(preferred_source_ids or [])
        query_weights: Dict[str, float] = {}
        for token in query_tokens:
            query_weights[token] = query_weights.get(token, 0.0) + self.idf.get(token, 1.0)

        scored = []
        for idx, chunk_tokens in enumerate(self.doc_tokens):
            score = 0.0
            for token, weight in query_weights.items():
                if token in chunk_tokens:
                    score += weight
            if self.chunks[idx].ref_index in preferred:
                score *= 1.2
            if score > 0:
                scored.append((score, self.chunks[idx]))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        lowered = text.lower()
        latin_tokens = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)?", lowered)
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", lowered)
        cjk_bigrams = [
            "".join(cjk_chars[i : i + 2])
            for i in range(max(0, len(cjk_chars) - 1))
        ]
        numbers = re.findall(r"\d+(?:\.\d+)?%?", lowered)
        return latin_tokens + cjk_bigrams + numbers


class VerifierAgent:
    def __init__(self, articles):
        self.aligner = CompositeAligner()
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com") if api_key else None
        self.articles_map = {a.article_id: a for a in articles}

    def batch_verify(
        self,
        reports: List[ClaimBasedReport],
        events: List[Event],
        run_adversarial: bool = True,
    ) -> List[VerificationResult]:
        results = []
        for report in reports:
            event = next((e for e in events if e.event_id == report.event_id), None)
            if not event:
                continue

            res = self._verify_single_report(report, event, run_adversarial)
            results.append(res)
        return results

    def _verify_single_report(
        self,
        report: ClaimBasedReport,
        event: Event,
        run_adversarial: bool = True,
    ) -> VerificationResult:
        retriever = EvidenceRetriever(event.articles)
        verified_count = 0
        failed_count = 0
        not_found_count = 0
        skipped_count = 0
        issues: List[str] = []

        for claim in report.claims:
            if claim.claim_type != ClaimType.FACTUAL:
                claim.verification_status = VerificationStatus.VERIFIED
                skipped_count += 1
                continue

            evidence_chunks = retriever.retrieve(
                claim.claim_text,
                top_k=5,
                preferred_source_ids=claim.source_ids,
            )

            if not evidence_chunks:
                claim.verification_status = VerificationStatus.NOT_FOUND
                not_found_count += 1
                issues.append(f"No evidence found: {claim.claim_text}")
                continue

            full_evidence = "\n".join(chunk.text for chunk in evidence_chunks)
            align_res = self.aligner.align_claim_to_evidence(
                claim.claim_text,
                full_evidence,
                claim.metric_value,
            )

            if align_res["overall_aligned"]:
                claim.verification_status = VerificationStatus.VERIFIED
                best = evidence_chunks[0]
                claim.supporting_evidence.append(
                    SupportingEvidence(
                        source_id=best.chunk_id,
                        source_url=best.source_url,
                        source_outlet=best.source_outlet,
                        span_text=best.text[:500],
                        confidence=align_res.get("score", 0.8),
                    )
                )
                verified_count += 1
            else:
                claim.verification_status = VerificationStatus.CONFLICT
                failed_count += 1
                issues.append(f"Claim failed alignment: {claim.claim_text}")

        if run_adversarial:
            issues.extend(self._run_adversarial_check(report, event))

        factual_failures = failed_count + not_found_count
        status = "PASS" if not issues else ("PARTIAL" if verified_count and factual_failures else "FLAGGED")
        factual_claims = verified_count + failed_count + not_found_count
        verified_rate = verified_count / factual_claims if factual_claims else 0.0
        evidence_hit_rate = (verified_count + failed_count) / factual_claims if factual_claims else 0.0
        conflict_rate = failed_count / factual_claims if factual_claims else 0.0
        not_found_rate = not_found_count / factual_claims if factual_claims else 0.0
        alignment_metrics = evaluate_claim_evidence_alignment(report)
        citation_metrics = evaluate_citation_diversity(report, event)
        low_source_diversity = (
            citation_metrics["total_sources_available"] >= 3
            and citation_metrics["cited_domains"] < 3
        )

        publish_allowed = (
            status in {"PASS", "PARTIAL"}
            and verified_rate >= 0.65
            and conflict_rate <= 0.15
            and not_found_rate <= 0.25
            and not low_source_diversity
        )
        publish_reason = "PASS" if publish_allowed else "BLOCKED: verification or citation diversity gate failed"

        return VerificationResult(
            event_id=report.event_id,
            report=report,
            status=status,
            issues=issues,
            total_claims=len(report.claims),
            verified_claims=verified_count,
            failed_claims=failed_count,
            not_found_claims=not_found_count,
            skipped_claims=skipped_count,
            verified_rate=verified_rate,
            evidence_hit_rate=evidence_hit_rate,
            conflict_rate=conflict_rate,
            not_found_rate=not_found_rate,
            citation_coverage=alignment_metrics["citation_coverage"],
            total_sources_available=int(citation_metrics["total_sources_available"]),
            cited_sources=int(citation_metrics["cited_sources"]),
            cited_domains=int(citation_metrics["cited_domains"]),
            citation_diversity_rate=float(citation_metrics["citation_diversity_rate"]),
            publish_allowed=publish_allowed,
            publish_reason=publish_reason,
            low_source_diversity=low_source_diversity,
        )

    def _run_adversarial_check(self, report: ClaimBasedReport, event: Event) -> List[str]:
        if not self.client:
            return []

        source_text = "\n".join(
            (article.full_text or article.snippet or "")[:2000]
            for article in event.articles
            if (article.full_text or article.snippet or "")
        )
        report_text = "\n".join(
            [
                report.summary_text,
                report.background_text,
                report.analysis_text,
                report.outlook_text,
            ]
        )
        if not source_text.strip():
            return ["Adversarial check skipped: empty source text"]
        if not report_text.strip():
            return ["Adversarial check skipped: empty report text"]

        prompt = f"""
You are a financial fact-checking auditor.
Only use the ORIGINAL MATERIAL to inspect the REPORT for:
1. unsupported facts;
2. exaggerated wording;
3. over-inferred causal claims;
4. wrong numbers, dates, or organization names;
5. opinions written as facts.

Return JSON only:
{{
  "issues": [
    {{"type": "...", "text": "...", "reason": "..."}}
  ]
}}

ORIGINAL MATERIAL:
{source_text}

REPORT:
{report_text}
"""
        try:
            resp = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            data = json.loads(resp.choices[0].message.content)
        except Exception as exc:
            return [f"Adversarial check failed: {str(exc)[:120]}"]

        issues = []
        for item in data.get("issues", []):
            issue_type = item.get("type", "issue")
            text = item.get("text", "")
            reason = item.get("reason", "")
            issues.append(f"Adversarial {issue_type}: {text} ({reason})")
        return issues


def print_verification_dashboard(results: List[VerificationResult]):
    """Print verification results dashboard."""
    console.rule("[bold cyan]Verification Dashboard[/]")

    for res in results:
        if res.status == "PASS":
            status_icon = "[PASS]"
            color = "green"
        elif res.status == "PARTIAL":
            status_icon = "[PARTIAL]"
            color = "yellow"
        else:
            status_icon = "[FLAGGED]"
            color = "red"

        console.print(f"\n{status_icon} [bold {color}]{res.report.title}[/]")
        console.print(f"   Status: [{color}]{res.status}[/]")
        console.print(
            "   Claims: "
            f"{res.verified_claims} verified | "
            f"{res.failed_claims} failed | "
            f"{res.not_found_claims} not found | "
            f"{res.skipped_claims} skipped"
        )
        console.print(
            "   Metrics: "
            f"verified_rate={res.verified_rate:.1%} | "
            f"evidence_hit_rate={res.evidence_hit_rate:.1%} | "
            f"conflict_rate={res.conflict_rate:.1%} | "
            f"citation_diversity={res.citation_diversity_rate:.1%}"
        )
        gate = "PASS" if res.publish_allowed else "BLOCKED"
        gate_color = "green" if res.publish_allowed else "red"
        console.print(f"   Publish gate: [{gate_color}]{gate}[/] ({res.publish_reason})")

        if res.issues:
            console.print(f"   [red]Issues found: {len(res.issues)}[/]")
            for issue in res.issues:
                console.print(f"      - {issue}", style="dim red")

    console.print("")
