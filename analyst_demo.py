# analyst_demo.py
# Module B: The Analyst (DeepSeek Edition V4.2)

import os
import json
from typing import List
from datetime import datetime
from pydantic import BaseModel


try:
    from openai import OpenAI
    from rich.console import Console
    from rich.panel import Panel
    from rich.tree import Tree
    from rich import box
    console = Console()
except ImportError:
    exit()

try:
    from gather_demo import RawArticle
except ImportError:
    exit()

class Event(BaseModel):
    event_id: str
    main_title: str
    summary: str
    score: float
    articles: List[RawArticle]
    primary_category: str

# === 可视化函数 ===
def print_analyst_dashboard(events: List[Event]):
    console.print("\n")
    if not events:
        console.print("[dim]无重大事件。[/]")
        return

    for evt in events:
        color = "red" if evt.score >= 8 else "blue"
        tree = Tree(f"[bold {color}]{evt.main_title}[/] (评分: {evt.score})")
        tree.add(f"[italic]{evt.summary}[/]")
        console.print(Panel(tree, border_style=color, box=box.ROUNDED))

class AnalystAgent:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self.api_key: raise ValueError("Missing API Key")
        
        self.client = OpenAI(
            api_key=self.api_key, 
            base_url="https://api.deepseek.com"
        )

    # === ✨ 关键修改点：增加了 verbose 参数 ===
    def cluster_articles(self, articles: List[RawArticle], verbose: bool = True) -> List[Event]:
        if not articles: return []



       # 1. 打印 Phase 2 标题栏 (紫色风格)
        console.print("\n")
        console.rule("[bold purple]🟣 Phase 2: 语义聚类 (Clustering)[/]")
        
        # 2. 打印当前状态
        console.print(f"🧠 [cyan]DeepSeek Analyst 正在深度分析 {len(articles)} 篇新闻素材，尝试归纳热点...[/cyan]")
        

        # 1. 准备 Prompt
        articles_text = "\n".join([f"ID:{i} Title:{a.title}" for i, a in enumerate(articles)])
        
        system_prompt = """
        聚类新闻标题为核心事件。
        返回 JSON: {"events": [{"main_title": "...", "summary": "...", "article_indices": [0, 1], "score": 8.5, "category": "policy"}]}
        """

        try:
            # 2. 调用 DeepSeek
            resp = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": articles_text}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            data = json.loads(resp.choices[0].message.content)
            
            # 3. 解析结果
            events = []
            for item in data.get("events", []):
                rel_arts = [articles[i] for i in item["article_indices"] if i < len(articles)]
                if rel_arts:
                    events.append(Event(
                        event_id=f"evt_{datetime.now().timestamp()}",
                        main_title=item["main_title"],
                        summary=item["summary"],
                        score=item["score"],
                        articles=rel_arts,
                        primary_category=item.get("category", "general")
                    ))
            
            events.sort(key=lambda x: x.score, reverse=True)
            
            # === ✨ 关键修改点：如果 verbose=True，就打印面板 ===
            if verbose:
                print_analyst_dashboard(events)
                
            return events

        except Exception as e:
            console.print(f"[red]分析失败: {e}[/]")
            return []
