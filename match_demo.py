# match_demo.py
# 演示：如何使用 EventMatcher 检测新文章是否属于现有事件

import os
from dotenv import load_dotenv

load_dotenv(override=True)

from event_matcher import EventMatcher
from analyst_demo import AnalystAgent, Event
from gather_demo import gather
from models import RawArticle, SourceInfo

from rich.console import Console
from rich.panel import Panel

console = Console()


def demo_single_match():
    """演示：单篇文章匹配"""

    console.rule("[bold cyan]示例 1: 单篇文章匹配[/]")

    # Step 1: 准备现有事件（模拟）
    # 在实际使用中，这些事件来自 AnalystAgent.cluster_articles()
    existing_events = [
        Event(
            event_id="evt_1",
            main_title="2025年中国规模以上工业企业利润实现增长",
            summary="2025年工业企业利润总额增长0.6%，扭转三年下降态势",
            score=9.5,
            articles=[],
            primary_category="Macro_Economy",
            detail={}
        ),
        Event(
            event_id="evt_2",
            main_title="美联储维持利率不变",
            summary="美联储在1月会议决定维持联邦基金利率目标区间不变",
            score=10.0,
            articles=[],
            primary_category="Monetary_Liquidity",
            detail={}
        )
    ]

    # Step 2: 准备新文章（模拟）
    new_article = RawArticle(
        article_id="new_001",
        url="https://example.com/article",
        title="统计局：2025年工业企业利润扭转下滑趋势，新动能支撑明显",
        snippet="国家统计局今日发布数据，2025年全国规模以上工业企业实现利润总额73982亿元，同比增长0.6%。",
        source=SourceInfo(
            url="https://example.com",
            domain="example.com",
            tier="tier1",
            outlet_name="财经新闻网",
            whitelisted=True
        )
    )

    # Step 3: 使用匹配器
    matcher = EventMatcher()
    result = matcher.match_article_to_events(
        new_article=new_article,
        existing_events=existing_events,
        threshold=0.7  # 相似度阈值：70%
    )

    # Step 4: 处理匹配结果
    if result:
        matched_event, confidence, reason = result
        console.print(Panel(
            f"[green]✓ 新文章属于现有事件[/]\n\n"
            f"事件: {matched_event.main_title}\n"
            f"相似度: {confidence:.1%}\n"
            f"原因: {reason}",
            title="匹配成功",
            border_style="green"
        ))
    else:
        console.print(Panel(
            "[yellow]✗ 新文章不属于任何现有事件[/]\n"
            "建议：可能需要创建新的事件聚类",
            title="未匹配",
            border_style="yellow"
        ))


def demo_batch_match():
    """演示：批量文章匹配"""

    console.rule("[bold cyan]示例 2: 批量文章匹配[/]")

    # 模拟现有事件
    existing_events = [
        Event(
            event_id="evt_1",
            main_title="2025年中国工业企业利润增长",
            summary="工业利润增长0.6%",
            score=9.5,
            articles=[],
            primary_category="Macro_Economy",
            detail={}
        )
    ]

    # 模拟多篇新文章
    new_articles = [
        RawArticle(
            article_id="new_001",
            url="https://example.com/1",
            title="统计局解读工业企业利润数据",
            snippet="2025年工业利润实现正增长...",
            source=SourceInfo(
                url="https://example.com",
                domain="example.com",
                tier="tier1",
                outlet_name="财经网",
                whitelisted=True
            )
        ),
        RawArticle(
            article_id="new_002",
            url="https://example.com/2",
            title="A股三大指数收盘涨跌不一",
            snippet="今日A股市场震荡整理...",
            source=SourceInfo(
                url="https://example.com",
                domain="example.com",
                tier="tier2",
                outlet_name="证券日报",
                whitelisted=True
            )
        )
    ]

    # 批量匹配
    matcher = EventMatcher()
    matches = matcher.batch_match_articles(
        new_articles=new_articles,
        existing_events=existing_events,
        threshold=0.7
    )

    # 查看结果
    console.print("\n[bold]匹配结果详情:[/]")
    for event_id, data in matches.items():
        if event_id == "unmatched":
            console.print(f"\n[yellow]未匹配文章 ({len(data)} 篇):[/]")
            for article in data:
                console.print(f"  - {article.title}")
        else:
            console.print(f"\n[green]事件 {event_id}:[/]")
            for item in data:
                article = item["article"]
                confidence = item["confidence"]
                console.print(f"  - {article.title} ({confidence:.1%})")


def demo_with_real_data():
    """演示：使用真实采集数据"""

    console.rule("[bold cyan]示例 3: 使用真实数据[/]")

    console.print("[yellow]正在采集最新新闻...[/]")

    # Step 1: 采集新闻
    keywords = ["中国经济", "工业利润"]
    articles = gather(keywords, max_results_per_keyword=5)

    if not articles:
        console.print("[red]未采集到文章[/]")
        return

    console.print(f"[green]✓ 采集到 {len(articles)} 篇文章[/]")

    # Step 2: 生成事件聚类
    analyst = AnalystAgent()
    events = analyst.cluster_articles(articles, verbose=False)

    if not events:
        console.print("[red]未生成事件聚类[/]")
        return

    console.print(f"[green]✓ 生成了 {len(events)} 个事件聚类[/]")

    # Step 3: 模拟新文章到达
    if len(articles) > 5:
        # 取最后一篇作为"新文章"
        new_article = articles[-1]
        existing_events = events

        console.print(f"\n[yellow]测试新文章:[/] {new_article.title}")

        # Step 4: 匹配
        matcher = EventMatcher()
        result = matcher.match_article_to_events(
            new_article=new_article,
            existing_events=existing_events,
            threshold=0.7
        )

        if result:
            console.print("[green]✓ 匹配成功！此文章属于现有事件。[/]")
        else:
            console.print("[yellow]✗ 未匹配。此文章可能需要创建新事件。[/]")


if __name__ == "__main__":
    console.print(Panel(
        "[bold cyan]事件匹配演示程序[/]\n\n"
        "本程序演示如何检测新文章是否属于现有事件聚类",
        title="EventMatcher Demo",
        border_style="cyan"
    ))

    # 选择演示模式
    console.print("\n[bold]可用演示:[/]")
    console.print("1. 单篇文章匹配（使用模拟数据）")
    console.print("2. 批量文章匹配（使用模拟数据）")
    console.print("3. 使用真实采集数据（需要 API）")

    choice = input("\n请选择 (1/2/3): ").strip()

    if choice == "1":
        demo_single_match()
    elif choice == "2":
        demo_batch_match()
    elif choice == "3":
        demo_with_real_data()
    else:
        console.print("[red]无效选择[/]")
