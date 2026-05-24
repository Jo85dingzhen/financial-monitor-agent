# journalist_v2.py
# Module C v2: Journalist with citation-first report generation.

import csv
import json
import os
import re
import time
from datetime import datetime
from typing import List, Optional

try:
    from openai import OpenAI
    from rich.console import Console

    console = Console()
except ImportError:
    console = None

from models import AtomicClaim, ClaimBasedReport, ClaimType, Event


class ClaimExtractor:
    """Extract atomic claims from report sections using inline [cite: X] markers."""

    def __init__(self, client):
        self.client = client

    def extract_claims(
        self,
        text: str,
        source_mapping: dict,
        claim_type: ClaimType = ClaimType.FACTUAL,
    ) -> List[AtomicClaim]:
        claims: List[AtomicClaim] = []
        pattern = r"([^。！？\n]+(?:\[cite:\s*\d+\])+[。！？]?)"
        matches = re.finditer(pattern, text)

        claim_counter = 0
        for match in matches:
            sentence = match.group(1)
            cite_matches = re.findall(r"\[cite:\s*(\d+)\]", sentence)
            if not cite_matches:
                continue

            clean_text = re.sub(r"\[cite:\s*\d+\]", "", sentence).strip()
            if not clean_text:
                continue

            claim_counter += 1
            claims.append(
                AtomicClaim(
                    claim_id=f"c_{int(time.time())}_{claim_counter}",
                    claim_text=clean_text,
                    claim_type=claim_type,
                    source_ids=cite_matches,
                    source_urls=[
                        source_mapping.get(idx, "").split("|")[2]
                        if "|" in source_mapping.get(idx, "")
                        else ""
                        for idx in cite_matches
                    ],
                )
            )

        return claims

    def extract_claims_from_sections(self, sections: dict, source_mapping: dict) -> List[AtomicClaim]:
        claims: List[AtomicClaim] = []
        section_types = {
            "summary": ClaimType.FACTUAL,
            "background": ClaimType.FACTUAL,
            "analysis": ClaimType.FACTUAL,
            "outlook": ClaimType.ANALYTICAL,
        }
        for section_name, claim_type in section_types.items():
            claims.extend(
                self.extract_claims(sections.get(section_name, ""), source_mapping, claim_type)
            )
        return claims


class JournalistAgentV2:
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self.claim_extractor = ClaimExtractor(self.client)

    def write_reports(
        self,
        events: List[Event],
        max_events: int = 3,
        word_guideline: str = "",
    ) -> List[ClaimBasedReport]:
        reports: List[ClaimBasedReport] = []
        target_events = events[:max_events]
        for event in target_events:
            try:
                report = self._generate_single_report(event, word_guideline)
                if report:
                    reports.append(report)
            except Exception as exc:
                if console:
                    console.print(f"[red]Report gen failed: {exc}[/]")

        self.save_source_log(target_events)
        return reports

    def save_source_log(self, events: List[Event], output_dir: str = "source_logs") -> str:
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(output_dir, f"source_log_{timestamp}.csv")

        rows = []
        for event in events:
            for idx, article in enumerate(event.articles, 1):
                snippet_preview = (article.full_text or article.snippet or "")[:300]
                rows.append(
                    {
                        "event_title": event.main_title,
                        "event_category": event.primary_category,
                        "event_score": event.score,
                        "source_index": idx,
                        "outlet_name": article.source.outlet_name,
                        "domain": article.source.domain,
                        "tier": article.source.tier,
                        "article_title": article.title,
                        "url": article.url,
                        "snippet_preview": snippet_preview,
                        "publish_date": article.publish_date,
                    }
                )

        if not rows:
            if console:
                console.print("[yellow]No source rows; source log skipped[/]")
            return ""

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        if console:
            console.print(f"[green]Source log saved: {filepath} ({len(rows)} rows)[/]")
        return filepath

    def _generate_single_report(self, event: Event, guideline: str) -> Optional[ClaimBasedReport]:
        context_lines = []
        source_mapping = {}
        max_chars_per_source = 1000 if len(event.articles) <= 3 else 700

        for idx, article in enumerate(event.articles, 1):
            source_mapping[str(idx)] = f"{article.source.domain}|{article.title}|{article.url}"
            snippet = article.full_text or article.snippet or ""
            context_lines.append(
                f"[Source {idx}] 【{article.source.outlet_name} / {article.source.domain}】\n"
                f"{snippet[:max_chars_per_source]}..."
            )

        context_str = "\n\n".join(context_lines)
        source_count = len(event.articles)
        domain_count = len({article.source.domain for article in event.articles})

        system_prompt = """
你是一名中立、严谨的金融新闻主笔。请基于给定素材撰写一份高质量财经简报。

【写作要求】
1. 中立客观：使用新闻报道的中性语气。
2. 可读性强：生成连贯段落，而不是零散表格。
3. 强制引用：每一句涉及事实、数据或观点的话，必须在句尾标注来源索引。
4. 多源交叉：如果多个来源提到同一事实，尽量同时引用，例如 [cite: 1][cite: 3]。

【来源使用要求】
1. 如果素材池中有 3 个及以上不同来源，summary、background、analysis 至少应使用 3 个不同来源。
2. 不允许整篇报告只引用同一个来源，除非素材池确实只有一个来源。
3. 同一事实如有多家来源支持，应使用多个 citation，例如 [cite: 1][cite: 3]。
4. 如果不同来源信息不一致，不要强行综合，必须写明“不同来源存在表述差异”。
5. 不得使用素材池之外的信息补充背景。

【输出格式】
严格输出 JSON 对象：
{
    "title": "简洁专业的标题",
    "summary": "150字左右的核心摘要，包含关键数据",
    "background": "事件背景、政策脉络或过往数据",
    "analysis": "深度分析、原因解读或市场影响",
    "outlook": "未来趋势或风险提示"
}
"""
        try:
            resp = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"【写作指引】{guideline}\n\n"
                            f"【来源数量】{source_count} 篇文章，{domain_count} 个不同来源。\n"
                            "请优先综合多个来源，不要只依赖单一来源。\n\n"
                            f"【素材池】\n{context_str}"
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            data = json.loads(resp.choices[0].message.content)
            claims = self.claim_extractor.extract_claims_from_sections(
                {
                    "summary": data.get("summary", ""),
                    "background": data.get("background", ""),
                    "analysis": data.get("analysis", ""),
                    "outlook": data.get("outlook", ""),
                },
                source_mapping,
            )

            return ClaimBasedReport(
                event_id=event.event_id,
                title=data.get("title", ""),
                summary_text=data.get("summary", ""),
                background_text=data.get("background", ""),
                analysis_text=data.get("analysis", ""),
                outlook_text=data.get("outlook", ""),
                claims=claims,
                source_mapping=source_mapping,
                generated_at=datetime.now(),
                model_used="deepseek-chat",
            )
        except Exception as exc:
            if console:
                console.print(f"[red]Journalist Error: {exc}[/]")
            return None
