# journalist_v2.py
# Module C v2: The Journalist (Narrative & Citations)
# 核心目标：生成带有 标记的、流畅的中立新闻稿

import os
import csv
import json
import time
from typing import List, Optional
from datetime import datetime

try:
    from openai import OpenAI
    from rich.console import Console
    from rich.panel import Panel
    console = Console()
except ImportError:
    console = None

from models import Event, ClaimBasedReport, AtomicClaim, ClaimType
import re

class ClaimExtractor:
    """从文本中提取原子声明（带引用标记）"""
    def __init__(self, client):
        self.client = client

    def extract_claims(self, text: str, source_mapping: dict) -> List[AtomicClaim]:
        """
        从文本中提取声明
        识别 [cite: X] 标记并提取对应的句子作为声明
        """
        claims = []

        # 按句子分割文本，保留引用标记
        # 匹配模式：句子 + [cite: X] 或 [cite: X][cite: Y]
        pattern = r'([^。！？\n]+(?:\[cite:\s*\d+\])+[。！？]?)'
        matches = re.finditer(pattern, text)

        claim_counter = 0
        for match in matches:
            sentence = match.group(1)

            # 提取所有引用索引
            cite_pattern = r'\[cite:\s*(\d+)\]'
            cite_matches = re.findall(cite_pattern, sentence)

            if cite_matches:
                # 移除引用标记，得到纯文本
                clean_text = re.sub(r'\[cite:\s*\d+\]', '', sentence).strip()

                if clean_text:
                    claim_counter += 1
                    claim = AtomicClaim(
                        claim_id=f"c_{int(time.time())}_{claim_counter}",
                        claim_text=clean_text,
                        claim_type=ClaimType.FACTUAL,
                        source_ids=cite_matches,
                        source_urls=[source_mapping.get(idx, "").split("|")[2] if "|" in source_mapping.get(idx, "") else ""
                                    for idx in cite_matches]
                    )
                    claims.append(claim)

        return claims

class JournalistAgentV2:
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self.claim_extractor = ClaimExtractor(self.client) # 复用原来的提取器用于核验
    
    def write_reports(self, events: List[Event], max_events=3, word_guideline="") -> List[ClaimBasedReport]:
        reports = []
        target_events = events[:max_events]
        for i, event in enumerate(target_events, 1):
            try:
                report = self._generate_single_report(event, word_guideline)
                if report: reports.append(report)
            except Exception as e:
                if console: console.print(f"[red]Report gen failed: {e}[/]")

        # 保存来源日志
        self.save_source_log(target_events)

        return reports

    def save_source_log(self, events: List[Event], output_dir: str = "source_logs") -> str:
        """
        将所有事件中爬取的文章来源保存为 CSV 文件，便于溯源审计。
        文件名格式：source_log_YYYYMMDD_HHMMSS.csv
        """
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"source_log_{timestamp}.csv"
        filepath = os.path.join(output_dir, filename)

        rows = []
        for event in events:
            for idx, art in enumerate(event.articles, 1):
                snippet_preview = (getattr(art, 'full_text', '') or art.snippet or "")[:300]
                rows.append({
                    "事件标题": event.main_title,
                    "事件分类": event.primary_category,
                    "事件评分": event.score,
                    "来源序号": idx,
                    "媒体名称": art.source.outlet_name,
                    "媒体域名": art.source.domain,
                    "媒体等级": art.source.tier,
                    "文章标题": art.title,
                    "文章URL": art.url,
                    "内容摘要": snippet_preview,
                    "发布日期": getattr(art, 'publish_date', ''),
                })

        if not rows:
            if console: console.print("[yellow]⚠️ 无文章数据，跳过来源日志生成[/]")
            return ""

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        if console: console.print(f"[green]📄 来源日志已保存：{filepath}（共 {len(rows)} 条记录）[/]")
        return filepath
    
    def _generate_single_report(self, event: Event, guideline: str) -> Optional[ClaimBasedReport]:
        # 1. 构建带索引的素材上下文
        context_lines = []
        source_mapping = {}
        for idx, art in enumerate(event.articles, 1):
            # 记录来源元数据，供 Publisher 生成 References 列表
            source_mapping[str(idx)] = f"{art.source.domain}|{art.title}|{art.url}"
            
            snippet = getattr(art, 'full_text', art.snippet) or art.snippet
            context_lines.append(f"[Source {idx}] 【{art.source.outlet_name}】\n{snippet[:800]}...")
        
        context_str = "\n\n".join(context_lines)
        
        # 2. 生成正文 (Prose Generation)
        # ⚡️ 核心 Prompt：要求生成中立、流畅且带引用的文本
        system_prompt = """
你是一名中立、严谨的金融新闻主笔。请基于给定的素材撰写一份高质量的财经简报。

【写作要求】
1. **中立客观**：使用新闻报道的中性语气，不带个人情绪。
2. **可读性强**：生成连贯的段落（Paragraphs），而不是零散的表格。
3. **强制引用**：**每一句话**如果涉及事实、数据或观点，必须在句尾标注来源索引 ``。
   - [cite_start]✅ 正确：2025年工业利润增长0.6%，扭转了下降态势 [cite: 1][cite_start][cite: 2]。
   - ❌ 错误：2025年工业利润增长0.6%。(无引用)
4. [cite_start]**多源交叉**：如果多个来源提到同一事实，尽量同时引用，如 `[cite: 1][cite_start][cite: 3]`。

【输出格式】
严格输出 JSON 对象：
{
    "title": "简练专业的标题",
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
                    {"role": "user", "content": f"【写作指引】{guideline}\n\n【素材池】\n{context_str}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.2
            )
            data = json.loads(resp.choices[0].message.content)
            
            # 3. 后台提取 Claims (为了给 Auditor 进行核验)
            # 我们把生成的段落拼起来，提取其中的断言用于审计
            full_text = f"{data.get('summary', '')}\n{data.get('analysis', '')}"
            claims = self.claim_extractor.extract_claims(full_text, source_mapping)
            
            return ClaimBasedReport(
                event_id=event.event_id,
                title=data.get("title", ""),
                summary_text=data.get("summary", ""),     # 这里存的是给人看的文本
                background_text=data.get("background", ""),
                analysis_text=data.get("analysis", ""),
                outlook_text=data.get("outlook", ""),
                claims=claims,                            # 这里存的是给机器审的断言
                source_mapping=source_mapping,
                generated_at=datetime.now()
            )
            
        except Exception as e:
            if console: console.print(f"[red]Journalist Error: {e}[/]")
            return None