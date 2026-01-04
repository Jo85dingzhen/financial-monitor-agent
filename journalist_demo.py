# journalist_demo.py
# Module C: The Journalist (Structured Drafting)
# V1.0: DeepSeek-Powered Academic Writer

import os
import json
from typing import List, Dict, Optional
from pydantic import BaseModel

# === 1. 依赖库 ===
try:
    from openai import OpenAI
except ImportError:
    print("❌ 错误: 缺少 openai 库。")
    exit()

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich import box
    console = Console()
except ImportError:
    pass

# === 2. 引用上游数据结构 ===
try:
    from analyst_demo import Event
except ImportError:
    print("❌ 无法找到 analyst_demo.py")
    exit()

# === 3. 定义 Module C 的输出结构 ===

class NewsReport(BaseModel):
    event_id: str
    title: str          # 学术级标题
    summary: str        # 100字以内的核心摘要
    key_points: List[str] # 3-5个关键事实/数据
    source_refs: List[str] # 引用来源 (用于溯源)
    impact_score: float

# === 4. 核心类: 撰稿人 Agent ===

class JournalistAgent:
    def __init__(self):
        # 复用 DeepSeek Key
        self.api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Missing API Key for Journalist")
        
        self.client = OpenAI(
            api_key=self.api_key, 
            base_url="https://api.deepseek.com"
        )

    def _generate_single_report(self, event: Event) -> Optional[NewsReport]:
        """对单个事件进行学术化撰写"""
        
        # 1. 准备上下文素材 (Strict Context)
        # 我们把 Module A 抓到的正文片段喂给它，要求它只能用这些信息
        context_text = ""
        for i, art in enumerate(event.articles):
            context_text += f"Source [{i+1}] ({art.source.outlet_name}): {art.title}\nContent: {art.snippet}\n---\n"

        # 2. 构建 Prompt (Zero-Trust Logic)
        system_prompt = """
        你是一名专业的宏观经济分析师和学术编辑。你的任务是根据提供的素材撰写一份"财经事件简报"。
        
        核心原则 (Zero-Trust)：
        1. **严禁编造**：所有的数字、日期、人名必须来自提供的 [Source] 素材。如果素材里没提，就不要写。
        2. **客观中立**：去除所有情绪化形容词（如"震惊"、"暴跌"、"血洗"）。使用学术词汇（如"下行"、"调整"、"波动"）。
        3. **格式严格**：必须返回合法的 JSON 格式。
        
        输出结构要求：
        - title: 不超过 20 字，包含核心主体与动作。
        - summary: 80-100 字，概括事件全貌。
        - key_points: 提取 3 个关键数据或事实（如金额、利率变化幅度、具体时间）。
        """

        user_prompt = f"""
        请根据以下素材撰写报告：
        {context_text}
        
        请输出如下 JSON 格式：
        {{
            "title": "...",
            "summary": "...",
            "key_points": ["点1", "点2", "点3"]
        }}
        """

        # 3. 调用 LLM
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={ "type": "json_object" },
                temperature=0.2 # 低温，确保事实准确
            )
            data = json.loads(response.choices[0].message.content)
            
            # 4. 组装结果
            return NewsReport(
                event_id=event.event_id,
                title=data.get("title", event.main_title),
                summary=data.get("summary", event.summary),
                key_points=data.get("key_points", []),
                source_refs=[a.source.outlet_name for a in event.articles],
                impact_score=event.score
            )
            
        except Exception as e:
            console.print(f"[red]撰稿失败 (Event ID: {event.event_id}): {e}[/]")
            return None

    def write_reports(self, events: List[Event]) -> List[NewsReport]:
        """批量处理入口"""
        reports = []
        if not events:
            return []

        console.print(f"[cyan]✍️ 撰稿人 (Journalist) 正在撰写 {len(events)} 份研报...[/]")
        
        # 限制：只处理前 10 大事件 (根据设计文档)
        top_events = events[:10]
        
        for event in top_events:
            report = self._generate_single_report(event)
            if report:
                reports.append(report)
                
        return reports

# === 5. 可视化面板 ===

def print_journalist_dashboard(reports: List[NewsReport]):
    console.print("\n")
    console.rule("[bold green]📜 Module C: 最终财经简报 (Final Report)[/]")
    
    for i, r in enumerate(reports, 1):
        # 样式构建
        content = f"[bold]{r.summary}[/bold]\n\n"
        
        if r.key_points:
            content += "[dim]关键事实 (Key Points):[/dim]\n"
            for kp in r.key_points:
                content += f"• {kp}\n"
        
        content += "\n[italic grey50]来源: " + ", ".join(set(r.source_refs)) + "[/]"
        
        panel = Panel(
            content,
            title=f"[bold green]#{i} {r.title}[/] (Impact: {r.impact_score})",
            border_style="green",
            box=box.HEAVY,
            expand=True
        )
        console.print(panel)
