# journalist_demo.py
# Module C: The Journalist (DeepSeek & LangChain Edition)
# V5.1: Fixed Prompt Template & JSON Escaping

import os
from typing import List, Optional

# === 1. 依赖库 ===

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
# 如果这里报错，请把下方终端里的【具体红字】截图发给我！
# 可能是 "cannot import name 'Field' from 'pydantic'" 这种版本冲突

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich import box
    console = Console()
except ImportError:
    class Console:
        def print(self, *args, **kwargs): print(*args)
    console = Console()

# === 2. 引用上游数据结构 ===
try:
    from analyst_demo import Event
except ImportError:
    print("❌ 无法找到 analyst_demo.py")
    exit()

# === 3. 数据模型 ===
class NewsReport(BaseModel):
    event_id: str = Field(default="", description="内部事件ID (LLM无需填写)")
    title: str = Field(description="专业财经标题")
    summary: str = Field(description="核心执行摘要")
    background: str = Field(description="事件背景与历史回溯 (300字+)")
    analysis: str = Field(description="深度市场分析与逻辑推演 (400字+)")
    outlook: str = Field(description="未来展望与风险提示 (200字+)")
    key_points: List[str] = Field(description="关键数据点列表")
    source_refs: List[str] = Field(description="引用来源列表")
    impact_score: int = Field(description="影响力评分 0-100")

# === 4. 核心类: 撰稿人 Agent ===

class JournalistAgent:
    def __init__(self):
        # 1. 初始化 LangChain 的 ChatModel
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("❌ Missing API Key. Please set DEEPSEEK_API_KEY in .env")

        self.llm = ChatOpenAI(
            model="deepseek-chat",  # DeepSeek V3
            openai_api_key=api_key,
            openai_api_base="https://api.deepseek.com", 
            temperature=0.3,
            max_tokens=4000
        )
        
        # 2. 初始化解析器
        self.parser = PydanticOutputParser(pydantic_object=NewsReport)

    def write_reports(self, events: List[Event], max_events: int = 3, word_guideline: str = "") -> List[NewsReport]:
        """批量撰写入口"""
        reports = []
        if not events:
            return []

        target_events = events[:max_events]
        console.print(f"[cyan]✍️  DeepSeek Journalist 正在撰写 {len(target_events)} 篇深度研报...[/]")
        
        for i, event in enumerate(target_events, 1):
            try:
                # 1. 准备素材
                context_text = ""
                for art in event.articles:
                    snippet = getattr(art, 'full_text', art.snippet) or art.snippet
                    context_text += f"- Source: {art.source.outlet_name}\n  Content: {snippet[:800]}...\n\n"

                # 2. 生成单篇报告
                report = self._generate_single_report(context_text, word_guideline)
                
                if report:
                    # 补全元数据
                    report.source_refs = list(set([a.source.outlet_name for a in event.articles]))
                    report.impact_score = event.score 
                    reports.append(report)
                    
                    # 3. 实时展示
                    self._print_realtime_card(i, report)
            
            except Exception as e:
                console.print(f"[red]❌ 撰写失败 (Event #{i}): {e}[/]")
                continue
                
        return reports

    def _generate_single_report(self, article_content: str, word_guideline: str) -> Optional[NewsReport]:
        """
        LangChain 核心流水线 (修复了 Prompt 转义问题)
        """
        
        # === System Prompt ===
        # ⚠️ 关键修改 1: 去掉前面的 'f'，不要让 Python 预处理字符串
        # ⚠️ 关键修改 2: JSON 的花括号必须写成 {{ 和 }} (双花括号)
        # ⚠️ 关键修改 3: 变量 {word_guideline} 保持单花括号
        
        system_prompt = """
        你是一名华尔街顶尖的宏观经济分析师。你的任务是根据提供的素材撰写一份**深度财经研报**。

        【核心原则】
        1. **严禁编造**：所有的数字、日期、人名必须来自素材。
        2. **客观中立**：去除情绪化形容词，使用学术词汇。
        3. **格式要求**：{word_guideline}

        【输出格式】
        你必须严格输出符合以下 JSON 结构的 valid JSON：
        {{
            "title": "专业标题",
            "summary": "150字摘要",
            "background": "300字+ 深度背景，详述起因",
            "analysis": "400字+ 核心分析，包含数据支撑和逻辑推演",
            "outlook": "200字+ 展望与风险提示",
            "key_points": ["关键点1", "关键点2"],
            "impact_score": 85,
            "source_refs": []
        }}
        """

        # === User Prompt ===
        user_prompt = """
        请基于以下素材撰写研报：
        ---
        {article_content}
        ---
        """

        # === 组装 Chain ===
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", user_prompt)
        ])

        # Chain: 提示词 -> 大模型 -> 解析器
        chain = prompt | self.llm | self.parser
        
        # === 执行 ===
        # ⚠️ 关键修改 4: 在这里传入真正的变量数据
        return chain.invoke({
            "word_guideline": word_guideline,
            "article_content": article_content
        })

    def _print_realtime_card(self, index: int, report: NewsReport):
        """UI 辅助"""
        content = f"[bold]{report.title}[/bold]\n\n"
        content += f"{report.summary}\n\n"
        content += "[dim]Analysis Preview:[/dim] " + report.analysis[:100] + "..."
        
        panel = Panel(
            content,
            title=f"[bold green]Draft #{index} Generated[/]",
            border_style="green",
            box=box.ROUNDED
        )
        console.print(panel)

# 测试代码
if __name__ == "__main__":
    pass
