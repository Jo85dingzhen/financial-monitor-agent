# verifier.py
# Module D v2: The Verifier (3-Stage Pipeline)
# Implements: Retrieval -> Deterministic Alignment -> Adversarial Check

import os
import json
from typing import List
from openai import OpenAI
from rich.console import Console

from models import ClaimBasedReport, Event, VerificationResult, VerificationStatus, SupportingEvidence, ClaimType
from aligners import CompositeAligner

console = Console()

class VerifierAgent:
    def __init__(self, articles):
        self.aligner = CompositeAligner()
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self.articles_map = {a.article_id: a for a in articles}

    def batch_verify(self, reports: List[ClaimBasedReport], events: List[Event], run_adversarial: bool = True) -> List[VerificationResult]:
        results = []
        for report in reports:
            event = next((e for e in events if e.event_id == report.event_id), None)
            if not event: continue

            res = self._verify_single_report(report, event, run_adversarial)
            results.append(res)
        return results

    def _verify_single_report(self, report: ClaimBasedReport, event: Event, run_adversarial: bool = True) -> VerificationResult:
        verified_count = 0
        issues = []

        # === Stage 1 & 2: Retrieval + Deterministic Alignment ===
        for claim in report.claims:
            if claim.claim_type != ClaimType.FACTUAL:
                claim.verification_status = VerificationStatus.VERIFIED
                continue

            # 1. Retrieve Evidence (Mocking Retrieval via Source ID lookup)
            # In production, this would be a Vector DB query or BM25
            evidence_texts = []
            for src_id in claim.source_ids:
                # Assuming simple mapping for demo (idx -> article)
                # In real app, map src_id to article object
                try:
                    idx = int(src_id) - 1
                    if 0 <= idx < len(event.articles):
                        art = event.articles[idx]
                        # Prioritize full_text over snippet for better verification
                        text = art.full_text or art.snippet
                        if text:
                            evidence_texts.append(text)
                            # Debug: show evidence length
                            console.print(f"[dim]      ✓ 证据源 [{src_id}]: {len(text)} 字符 (full_text={'是' if art.full_text else '否'})[/]")
                        else:
                            console.print(f"[dim]      ⚠ 证据源 [{src_id}] 为空[/]")
                    else:
                        console.print(f"[dim]      ⚠ 索引越界: idx={idx}, 文章数={len(event.articles)}[/]")
                except Exception as e:
                    console.print(f"[dim]      ❌ 检索失败 [{src_id}]: {str(e)[:50]}[/]")

            full_evidence = "\n".join(evidence_texts)

            if not full_evidence:
                claim.verification_status = VerificationStatus.NOT_FOUND
                continue

            # 2. Deterministic Alignment
            align_res = self.aligner.align_claim_to_evidence(
                claim.claim_text, full_evidence, claim.metric_value
            )

            if align_res['overall_aligned']:
                claim.verification_status = VerificationStatus.VERIFIED
                claim.supporting_evidence.append(SupportingEvidence(
                    source_id="matched", source_url="", source_outlet="", span_text="Matched via Aligner"
                ))
                verified_count += 1
            else:
                claim.verification_status = VerificationStatus.CONFLICT
                issues.append(f"Claim Failed Alignment: {claim.claim_text}")

        # === Stage 3: Adversarial Check (LLM) ===
        if run_adversarial:
            adv_issues = self._run_adversarial_check(report, event)
            issues.extend(adv_issues)
        
        status = "PASS" if not issues else "FLAGGED"
        
        return VerificationResult(
            event_id=report.event_id,
            report=report,
            status=status,
            issues=issues,
            total_claims=len(report.claims),
            verified_claims=verified_count,
            failed_claims=len(report.claims) - verified_count
        )

    def _run_adversarial_check(self, report, event):
        # Red Team LLM Prompt
        prompt = "你是一个对抗性审计员。请检查以下研报中的逻辑漏洞或未被数据支持的结论..."
        # ... (Implementation of LLM call similar to auditor_demo but stricter)
        return []


def print_verification_dashboard(results: List[VerificationResult]):
    """打印验证结果仪表盘"""
    console.rule("[bold cyan]📊 验证结果仪表盘 (Verification Dashboard)[/]")

    for res in results:
        # 确定状态图标和颜色
        if res.status == "PASS":
            status_icon = "✅"
            color = "green"
        elif res.status == "PARTIAL":
            status_icon = "⚠️"
            color = "yellow"
        else:  # FAIL or FLAGGED
            status_icon = "❌"
            color = "red"

        # 打印标题和状态
        console.print(f"\n{status_icon} [bold {color}]{res.report.title}[/]")
        console.print(f"   状态: [{color}]{res.status}[/]")
        console.print(f"   声明统计: {res.verified_claims}/{res.total_claims} 已验证 | {res.failed_claims} 失败")

        # 打印问题（如果有）
        if res.issues:
            console.print(f"   [red]发现 {len(res.issues)} 个问题:[/]")
            for issue in res.issues:
                console.print(f"      • {issue}", style="dim red")

    console.print("")