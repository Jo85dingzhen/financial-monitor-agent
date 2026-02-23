# journalist_demo.py
# Module C: The Journalist (Citation & Evidence Based)
# 响应评审要求：句句有出处 (Sentence-level Citations)

import os
import csv
from datetime import datetime
from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich import box
    console = Console()
except ImportError:
    pass

try:
    from analyst_demo import Event
except ImportError:
    exit()

# === 数据模型 ===
class NewsReport(BaseModel):
    event_id: str = Field(default="")
    title: str = Field(description="专业财经标题")
    summary: str = Field(description="摘要")
    # ⚠️ 这里的文本字段，Prompt 会要求包含 标记
    background: str = Field(description="背景")
    analysis: str = Field(description="分析")
    outlook: str = Field(description="展望")
    
    source_mapping: dict = Field(default={}, description="索引到URL的映射，如 {'1': 'http://...'}")

# === Journalist Agent ===
class JournalistAgent:
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.llm = ChatOpenAI(
            model="deepseek-chat",
            openai_api_key=api_key,
            openai_api_base="https://api.deepseek.com", 
            temperature=0.2 # 降低温度，确保忠实引用
        )
        self.parser = PydanticOutputParser(pydantic_object=NewsReport)

    def write_reports(self, events: List[Event], max_events=3, word_guideline="") -> List[NewsReport]:
        reports = []
        target_events = events[:max_events]
        console.print(f"[cyan]✍️  DeepSeek Journalist 正在基于证据撰写 {len(target_events)} 篇研报...[/]")

        for i, event in enumerate(target_events, 1):
            try:
                # 1. 构建带索引的 Context
                # 格式：
                # [Source 1] 财新网: 央行今日降准...
                # [Source 2] 证监会官网: 发布新规...
                context_lines = []
                mapping = {}
                for idx, art in enumerate(event.articles, 1):
                    snippet = getattr(art, 'full_text', art.snippet) or art.snippet
                    context_lines.append(f"[Source {idx}] 【{art.source.outlet_name}】\n内容: {snippet[:600]}...")
                    mapping[str(idx)] = f"{art.source.outlet_name}|{art.title}|{art.url}"

                context_str = "\n\n".join(context_lines)

                # 2. 生成报告
                report = self._generate_report(context_str, word_guideline)

                if report:
                    report.event_id = event.event_id
                    report.source_mapping = mapping
                    reports.append(report)
                    self._print_preview(report)

            except Exception as e:
                console.print(f"[red]撰写错误: {e}[/]")

        # 3. 保存来源日志
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

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
            writer.writeheader()
            writer.writerows(rows)

        console.print(f"[green]📄 来源日志已保存：{filepath}（共 {len(rows)} 条记录）[/]")
        return filepath

    def _generate_report(self, context: str, guideline: str):
        # ⚡️ 核心 Prompt：强制行内引用 [来源: 媒体名称]
        system_prompt = """
你是一名严谨的金融分析师。请基于给定的【Source x】素材撰写研报。

【关键规则：行内溯源机制】
1. **必须行内引用**：background 和 analysis 中每一句包含事实的陈述（数字、日期、政策、观点），
   必须在该句末尾紧接着写上来源媒体名称，格式为 [来源: 媒体名称]。
   - 正确示例："央行宣布下调MLF利率10个基点 [来源: 财新网]，流动性持续宽松 [来源: 证券时报]。"
   - 正确示例（多源）："市场成交量创年内新高 [来源: 新浪财经][来源: 第一财经]。"
   - 错误示例："央行宣布下调MLF利率。"（没有来源标注）
2. **媒体名称取自素材**：每个 Source 开头标注了【媒体名称】，引用时直接使用该名称，不得自行编造。
3. **严禁编造内容**：如果素材中没有提到某信息，绝对不要写。
4. **多源交叉**：同一事实被多家媒体报道时，优先引用官方源（央行、证监会、发改委等）。
5. summary 和 outlook 不需要行内引用标注。

【输出格式】
输出 JSON，包含 title, summary, background, analysis, outlook。
"""
        user_prompt = f"""
【写作指引】: {guideline}

【可用素材】:
{context}

请开始撰写：
"""
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("user", user_prompt)])
        chain = prompt | self.llm | self.parser
        return chain.invoke({})

    def _print_preview(self, report):
        console.print(Panel(
            f"[bold]{report.title}[/bold]\n\n{report.summary[:150]}...",
            title="Draft Generated (With Citations)", border_style="green"
        ))