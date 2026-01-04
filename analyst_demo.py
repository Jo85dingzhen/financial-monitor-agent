# analyst_demo.py
# Module B: The Analyst (DeepSeek Edition)
# V4.0: LLM-based Semantic Clustering (No Embeddings/DBSCAN needed)

import os
import json
from typing import List, Dict, Optional
from datetime import datetime
from pydantic import BaseModel

# === 1. 依赖库 ===
try:
    from openai import OpenAI
except ImportError:
    print("❌ 错误: 缺少 openai 库。请运行: pip install openai")
    exit()

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.tree import Tree
    from rich import box
    console = Console()
except ImportError:
    pass

# === 2. 引用 Module A 数据结构 ===
try:
    from gather_demo import RawArticle
except ImportError:
    print("❌ 无法找到 gather_demo.py")
    exit()

# === 3. 数据模型 ===

class Event(BaseModel):
    event_id: str
    main_title: str
    summary: str
    score: float
    articles: List[RawArticle]
    primary_category: str
    
    @property
    def source_count(self):
        return len(self.articles)

# === 4. 核心类: DeepSeek 分析师 ===

class AnalystAgent:
    def __init__(self):
        # 1. 读取 DeepSeek Key
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            # 兼容：如果用户还没改 .env，尝试读 OpenAI 的（有些用户用兼容层）
            self.api_key = os.getenv("OPENAI_API_KEY")
            
        if not self.api_key:
            console.print("[bold red]⚠️  未检测到 DEEPSEEK_API_KEY！[/]")
            raise ValueError("Missing API Key")
        
        # 2. 初始化 DeepSeek 客户端
        self.client = OpenAI(
            api_key=self.api_key, 
            base_url="https://api.deepseek.com"  # 关键：指向 DeepSeek 官方地址
        )

    def cluster_articles(self, articles: List[RawArticle]) -> List[Event]:
        """
        使用 DeepSeek V3 直接进行语义聚类
        """
        if not articles:
            return []

        console.print(f"[cyan]🧠 呼叫 DeepSeek-V3，正在分析 {len(articles)} 条情报...[/]")

        # --- Step 1: 构建 Prompt ---
        # 我们把所有文章的标题和ID编好号，喂给大模型
        articles_text = ""
        for idx, art in enumerate(articles):
            articles_text += f"ID:{idx} | Title: {art.title} | Source: {art.source.outlet_name} ({art.source.tier})\n"

        system_prompt = """
        你是一个专业的金融新闻主编。你的任务是将碎片化的新闻标题聚类成核心事件。
        
        请遵循以下规则：
        1. **合并重复项**：将讨论同一件事的新闻（如“降准落地”和“央行下调准备金”）归为一个事件。
        2. **去噪**：忽略琐碎或无意义的个股波动，只保留重要宏观/行业/大公司事件。
        3. **打分 (1-10)**：
           - 10分：国家级重磅政策（央行/财政部/国务院）。
           - 7-9分：行业重大新规或龙头股（如茅台、宁德时代）重大突发。
           - 4-6分：普通市场动态。
           - 1-3分：忽略。
        
        请严格输出 JSON 格式，不要包含 Markdown 标记，格式如下：
        {
            "events": [
                {
                    "main_title": "事件的标准标题",
                    "summary": "一句话概括",
                    "article_indices": [0, 2],  <-- 对应输入的 ID
                    "score": 9.5,
                    "category": "policy/market/macro/company"
                }
            ]
        }
        """

        # --- Step 2: 调用 DeepSeek ---
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat", # 使用 V3 模型
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"待处理新闻列表：\n{articles_text}"}
                ],
                response_format={ "type": "json_object" }, # 强制 JSON 输出
                temperature=0.1 # 低温度，保证逻辑严谨
            )
            
            result_json = response.choices[0].message.content
            
        except Exception as e:
            console.print(f"[red]DeepSeek 请求失败: {e}[/]")
            return []

        # --- Step 3: 解析结果并还原对象 ---
        try:
            data = json.loads(result_json)
            events = []
            
            for item in data.get("events", []):
                # 找回原始文章对象
                indices = item["article_indices"]
                related_articles = []
                for idx in indices:
                    if 0 <= idx < len(articles):
                        related_articles.append(articles[idx])
                
                if not related_articles:
                    continue

                # 创建事件对象
                event = Event(
                    event_id=f"evt_{datetime.now().strftime('%H%M')}_{indices[0]}",
                    main_title=item["main_title"],
                    summary=item["summary"],
                    score=item["score"],
                    articles=related_articles,
                    primary_category=item["category"]
                )
                events.append(event)

            # 按分数排序
            events.sort(key=lambda x: x.score, reverse=True)
            return events

        except json.JSONDecodeError:
            console.print("[red]DeepSeek 返回了非法的 JSON 格式，解析失败。[/]")
            return []

# === 5. 可视化面板 ===

def print_analyst_dashboard(events: List[Event]):
    console.print("\n")
    console.rule("[bold purple]🧠 DeepSeek 研报 (Module B Output)[/]")
    console.print(f"[dim]DeepSeek 提炼出 {len(events)} 个核心事件[/]\n", justify="center")

    if not events:
        console.print("[yellow]⚠️ 无有效事件。[/]", justify="center")
        return

    for i, evt in enumerate(events, 1):
        if evt.score >= 8.0:
            color = "red"; icon = "🔥"
        elif evt.score >= 5.0:
            color = "magenta"; icon = "⭐"
        else:
            color = "blue"; icon = "📝"
        
        tree = Tree(f"[bold {color}]{icon} #{i} {evt.main_title}[/] (评分: {evt.score})")
        tree.add(f"[italic]{evt.summary}[/]")
        
        source_branch = tree.add(f"[dim]来源 ({len(evt.articles)})[/]")
        for art in evt.articles:
            source_branch.add(f"{art.source.outlet_name}: {art.title}")

        console.print(Panel(tree, border_style=color, box=box.ROUNDED))

# === 6. 独立测试 ===
if __name__ == "__main__":
    from gather_demo import gather
    # 测试数据
    raw = gather(["site:pbc.gov.cn 货币政策", "site:stcn.com 上市公司"])
    valid = [a for a in raw if a.eligible_for_event]
    
    agent = AnalystAgent()
    evts = agent.cluster_articles(valid)
    print_analyst_dashboard(evts)
