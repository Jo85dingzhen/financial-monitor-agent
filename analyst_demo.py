# analyst_demo.py
# Module B: The Analyst (Hybrid Scoring Edition)
# 结构评分 50% + LLM 语义评分 50%

import os
import json
import time
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
    print("❌ 缺少 openai 或 rich 依赖，请先 pip install openai rich")
    exit()

try:
    from gather_demo import RawArticle
except ImportError:
    print("❌ 无法从 gather_demo 导入 RawArticle，请确认文件存在且可用")
    exit()


# =======================
# 数据结构：Event
# =======================
class Event(BaseModel):
    event_id: str
    main_title: str
    summary: str
    score: float                     # 最终综合得分（结构 + LLM）
    articles: List[RawArticle]
    primary_category: str            # 事件类别（macro / regulation / industry / company / other）
    semantic_level: str = "other"    # LLM 判断的层级（national / industry / company / other）
    detail: dict = {}                # 细节：结构评分、LLM评分、各维度打分


# =======================
# 权重配置（可调）
# =======================

# 媒体权威性评分
MEDIA_WEIGHT = {
    "tier1": 10,     # 国务院、央行、证监会、统计局等
    "tier2": 8,      # 财新、一财、21世纪等
    "tier3": 6,      # 预留
    "unknown": 5
}

# 事件类别评分（结构侧）
CATEGORY_WEIGHT = {
    "macro": 10,         # 宏观 & 政策
    "regulation": 9,     # 金融监管
    "industry": 7,       # 行业/板块
    "company": 5,        # 单一公司
    "general": 6,
    "other": 6
}

# 结构 vs LLM 融合权重
ALPHA_STRUCT = 0.5   # 结构评分权重
ALPHA_LLM = 0.5      # LLM 语义评分权重


# =======================
# 可视化：Analyst Dashboard
# =======================
def print_analyst_dashboard(events: List[Event]):
    console.print("\n")
    if not events:
        console.print("[dim]无重大事件。[/]")
        return

    console.rule("[bold purple]🟣 Module B: 语义聚类 & 事件评分结果[/]")

    for evt in events:
        # 颜色按总分区分
        if evt.score >= 8:
            color = "red"
        elif evt.score >= 6:
            color = "yellow"
        else:
            color = "blue"

        title = f"[bold {color}]{evt.main_title}[/] (总分: {evt.score})"
        tree = Tree(title)

        # 事件摘要
        tree.add(f"[italic]{evt.summary}[/]")

        # 细节评分展示
        detail = evt.detail or {}
        struct_score = detail.get("struct_score")
        llm_score = detail.get("llm_score")
        src_score = detail.get("source_score")
        cls_score = detail.get("cluster_count_score")
        cat_score = detail.get("category_score")
        macro_impact = detail.get("macro_impact")
        market_impact = detail.get("market_impact")
        urgency = detail.get("urgency")
        long_term = detail.get("long_term")

        # 结构评分 vs 语义评分
        if struct_score is not None and llm_score is not None:
            tree.add(
                f"[cyan]结构评分[/]: {struct_score}  |  "
                f"[magenta]LLM评分[/]: {llm_score}"
            )

        # 结构评分分解
        if src_score is not None and cls_score is not None and cat_score is not None:
            tree.add(
                f"[dim]来源权威: {src_score} / 覆盖面: {cls_score} / 类别: {cat_score}[/dim]"
            )

        # 语义维度
        if any(v is not None for v in [macro_impact, market_impact, urgency, long_term]):
            tree.add(
                f"[green]级别: {evt.semantic_level} | 宏观:{macro_impact} 市场:{market_impact} "
                f"紧迫:{urgency} 长期:{long_term}[/green]"
            )

        # 文章数
        tree.add(f"[dim]关联文章数: {len(evt.articles)}[/dim]")

        console.print(Panel(tree, border_style=color, box=box.ROUNDED))


# =======================
# Analyst Agent
# =======================
class AnalystAgent:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Missing API Key for AnalystAgent (DEEPSEEK_API_KEY / OPENAI_API_KEY)")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com"
        )

    # ---------- 内部：结构评分 ----------
    def _compute_struct_score(self, rel_arts: List[RawArticle], category: str) -> dict:
        """基于来源权威性 + 覆盖面 + 类别，计算结构评分及各分量"""
        if not rel_arts:
            return {
                "struct_score": 5.0,
                "source_score": 5.0,
                "cluster_count_score": 0.0,
                "category_score": CATEGORY_WEIGHT.get(category, 6)
            }

        # (1) 来源权威性：取平均
        media_scores = []
        for art in rel_arts:
            tier = getattr(art.source, "tier", "unknown") or "unknown"
            media_scores.append(MEDIA_WEIGHT.get(tier, 5))
        source_score = sum(media_scores) / len(media_scores)

        # (2) 覆盖面：文章数量封顶 10
        cluster_count_score = min(len(rel_arts), 10)

        # (3) 事件类别评分
        category_score = CATEGORY_WEIGHT.get(category, CATEGORY_WEIGHT["other"])

        # (4) 综合结构评分（可以按需调整权重）
        struct_score = (
            0.5 * source_score +
            0.3 * cluster_count_score +
            0.2 * category_score
        )

        return {
            "struct_score": round(struct_score, 2),
            "source_score": round(source_score, 2),
            "cluster_count_score": float(cluster_count_score),
            "category_score": float(category_score)
        }

    # ---------- 内部：LLM 语义评分 ----------
    def _semantic_score_event(self, main_title: str, summary: str, rel_arts: List[RawArticle]) -> dict:
        """
        让 DeepSeek 对单个事件做语义重要性评估，输出多个维度：
        level / macro_impact / market_impact / urgency / long_term / llm_score
        """
        # 准备文章标题列表
        titles_block = "\n".join(
            f"- {art.title} ({art.source.outlet_name})"
            for art in rel_arts
        )

        prompt = f"""
你是一名专业的宏观与金融市场分析师。请根据以下信息判断该事件的重要程度。

【事件标题】
{main_title}

【事件摘要】
{summary}

【相关新闻标题列表】
{titles_block}

请综合考虑：
- 事件是否为国家级 / 行业级 / 单个公司级别
- 对宏观经济的潜在影响
- 对金融市场（股市、汇率、利率等）的潜在影响
- 紧迫性（是否需要近期高度关注）
- 是否具有中长期结构性影响

请严格输出一个 JSON，格式为：
{{
  "level": "national" 或 "industry" 或 "company" 或 "other",
  "macro_impact": 0-10 的整数,
  "market_impact": 0-10 的整数,
  "urgency": 0-10 的整数,
  "long_term": 0-10 的整数,
  "llm_score": 0-10 的整数
}}

要求：
- 所有分数必须是 0 到 10 的整数。
- 不要输出任何解释性文字，只输出 JSON。
"""

        try:
            resp = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            data = json.loads(resp.choices[0].message.content)

            # 安全兜底
            level = data.get("level", "other") or "other"

            def _int_or_default(key, default=5):
                try:
                    v = int(data.get(key, default))
                    return max(0, min(10, v))
                except Exception:
                    return default

            macro_impact = _int_or_default("macro_impact", 5)
            market_impact = _int_or_default("market_impact", 5)
            urgency = _int_or_default("urgency", 5)
            long_term = _int_or_default("long_term", 5)
            llm_score = _int_or_default("llm_score", 5)

            return {
                "level": level,
                "macro_impact": macro_impact,
                "market_impact": market_impact,
                "urgency": urgency,
                "long_term": long_term,
                "llm_score": llm_score
            }

        except Exception as e:
            console.print(f"[red]LLM 语义评分失败，使用默认值。错误: {e}[/]")
            # 兜底
            return {
                "level": "other",
                "macro_impact": 5,
                "market_impact": 5,
                "urgency": 5,
                "long_term": 5,
                "llm_score": 5
            }

    # ---------- 主函数：聚类 + 评分 ----------
    def cluster_articles(self, articles: List[RawArticle], verbose: bool = True) -> List[Event]:
        if not articles:
            return []

        console.print("\n")
        console.rule("[bold purple]🟣 Phase 2: 语义聚类 (Clustering)[/]")
        console.print(
            f"🧠 [cyan]DeepSeek Analyst 正在分析 {len(articles)} 篇新闻，尝试聚类为事件并打分...[/cyan]"
        )

        # 1. 准备传给 DeepSeek 的标题列表
        articles_text = "\n".join(
            [f"ID:{i} Title:{a.title}" for i, a in enumerate(articles)]
        )

        # 2. 聚类 Prompt（让 DeepSeek 输出事件 + article_indices + 粗略类别）
        system_prompt = """
你是一个金融新闻聚类助手，请将相似新闻标题聚类为“事件”。

【要求】
1. 每个事件对应若干新闻标题（通过 article_indices 指定）。
2. 为每个事件生成一个简洁的 main_title（概括核心事件）。
3. 为每个事件写一个简短 summary（2-3 句，说明发生了什么、涉及哪些主体）。
4. 为每个事件打上一个粗分类 category，必须从以下集合中选择之一：
   - "macro"      宏观经济 / 货币财政政策 / 重要统计数据
   - "regulation" 金融监管 / 证监会 / 银保监 / 交易所规则
   - "industry"   行业政策 / 行业趋势 / 板块消息
   - "company"    单个公司或少量公司的微观事件
   - "other"      无法归类或杂项

【输出格式】
请严格输出 JSON：
{
  "events": [
    {
      "main_title": "...",
      "summary": "...",
      "article_indices": [0, 1, 2],
      "category": "macro"
    }
  ]
}
"""

        try:
            # 3. 调用 DeepSeek 聚类
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
        except Exception as e:
            console.print(f"[red]聚类失败: {e}[/]")
            return []

        # 4. 解析聚类结果 + 结构评分 + LLM 评分 + 融合
        events: List[Event] = []

        for item in data.get("events", []):
            idx_list = item.get("article_indices", [])
            rel_arts = [articles[i] for i in idx_list if 0 <= i < len(articles)]
            if not rel_arts:
                continue

            main_title = item.get("main_title", "未命名事件")
            summary = item.get("summary", "")
            category = item.get("category", "other")

            # --- 结构评分 ---
            struct_info = self._compute_struct_score(rel_arts, category)
            struct_score = struct_info["struct_score"]

            # --- LLM 语义评分 ---
            sem_info = self._semantic_score_event(main_title, summary, rel_arts)
            llm_score = sem_info["llm_score"]

            # --- 融合评分：结构 50% + LLM 50% ---
            final_score = round(
                ALPHA_STRUCT * struct_score +
                ALPHA_LLM * llm_score,
                2
            )

            # detail 合并
            detail = {
                **struct_info,
                "macro_impact": sem_info["macro_impact"],
                "market_impact": sem_info["market_impact"],
                "urgency": sem_info["urgency"],
                "long_term": sem_info["long_term"],
                "llm_score": float(llm_score)
            }

            evt = Event(
                event_id=f"evt_{time.time()}",
                main_title=main_title,
                summary=summary,
                score=final_score,
                articles=rel_arts,
                primary_category=category,
                semantic_level=sem_info["level"],
                detail=detail
            )
            events.append(evt)

        # 5. 按最终分数排序
        events.sort(key=lambda x: x.score, reverse=True)

        # 6. 可视化输出
        if verbose:
            print_analyst_dashboard(events)

        return events


# 独立测试入口（可选）
if __name__ == "__main__":
    console.print("[dim]AnalystAgent 模块测试入口（需要构造 RawArticle 列表）[/dim]")
