# main_v2.py
# The Financial Monitor Agent V2.0 (Verified Edition)
# 架构: Gather -> Analyst -> Journalist V2 -> Verifier (3-Stage) -> Publisher V2
# 核心升级: 实现了从"生成式写作"到"结构化断言+确定性核验"的闭环

import os
import sys
import textwrap
from typing import TypedDict, List, Optional
from datetime import datetime

# === 1. 环境与依赖检查 ===
try:
    from dotenv import load_dotenv
    load_dotenv(override=True, verbose=True)
    # 检查 API Key 是否存在
    if not os.getenv("DEEPSEEK_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        print("⚠️  警告: 未检测到 API Key，请在 .env 文件中配置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY")
except ImportError:
    print("⚠️  未安装 python-dotenv，正在尝试直接读取环境变量。")

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    console = Console()
except ImportError:
    print("❌ 缺少 rich 库，请运行: pip install rich")
    exit()

try:
    from langgraph.graph import StateGraph, END
except ImportError:
    print("❌ 缺少 langgraph 库，请运行: pip install langgraph")
    exit()

# === 2. 模块引入 ===
# 请确保所有 v2 模块都在同一目录下
try:
    # Module A: 采集者 (复用 V1)
    from gather_demo import gather, RawArticle, print_reader_view, get_last_time_filtered_items
    
    # Module B: 分析师 (复用 V1)
    from analyst_demo import AnalystAgent, Event
    
    # Module C V2: 原子断言撰稿人 (新)
    from journalist_v2 import JournalistAgentV2
    
    # Module D V2: 三阶段核验器 (新)
    from verifier import VerifierAgent, print_verification_dashboard
    
    # Module E V2: 审计发布商 (新)
    from publisher_v2 import PublisherAgentV2
    
    # 数据模型 (新)
    from models import ClaimBasedReport, VerificationResult
    
except ImportError as e:
    console.print(f"[bold red]❌ 模块导入失败: {e}[/]")
    console.print("[yellow]请确保 gather_demo.py, models.py, journalist_v2.py, verifier.py, publisher_v2.py 都在当前目录下。[/]")
    exit()

# ==========================================
# ⚙️ 全局配置 (CONFIG)
# ==========================================
CONFIG = {
    # [Module A] 搜索设置
    "search_days": 3,              # 搜索最近 3 天
    "search_max_results": 5,       # 每个关键词抓取数量
    "extract_full_text": True,     # 是否抓取网页完整内容（强烈建议开启以支持验证）
    "allow_undated_articles": False,  # False=严格时间过滤（无日期文章直接过滤）

    # [Module B] 聚类设置 (新增)
    "use_rule_based_clustering": False,  # False=LLM聚类, True=规则聚类
    "enable_quality_validation": True,   # 是否启用聚类质量验证

    # [Module C] 撰稿设置
    "report_max_events": 3,        # 最终产出多少篇研报
    "claim_preview_max": 12,       # Phase 3 可视化原子断言条数上限
    "claim_preview_chars": 120,    # 单条原子断言截断长度
    # 提示词中强制要求引用，这是 V2 的核心要求
    "report_guideline": "撰写一篇专业的财经研报。要求：1. 每个事实陈述必须标注来源。2. 包含摘要、背景、分析及展望。3. 严禁编造数据。",

    # [Module D] 核验设置
    "run_adversarial_check": True, # 是否开启 LLM 对抗性检查 (Layer 5)

    # [Module E] 输出设置
    "output_dir": "daily_reports_v2",
    "include_audit_trail": True    # 是否生成 JSON 审计日志
}

# ==========================================
# 3. 状态定义 (State)
# ==========================================
class AgentState(TypedDict):
    """LangGraph 传递的上下文状态"""
    queries: List[str]                  # 初始搜索词
    raw_articles: List[RawArticle]      # A阶段: 原始文章
    events: List[Event]                 # B阶段: 聚类事件
    
    # --- V2 核心变化 ---
    reports: List[ClaimBasedReport]     # C阶段: 带断言的初稿 (注意类型变化)
    verification_results: List[VerificationResult] # D阶段: 核验结果 (替代了 audit_results)
    # ------------------
    
    final_file_path: Optional[str]      # E阶段: 最终文件路径

# ==========================================
# 4. 节点定义 (Nodes)
# ==========================================

def node_gather(state: AgentState):
    """Phase 1: 全网采集"""
    console.rule("[bold blue]🔵 Phase 1: 全网采集 (Gathering)[/]")

    articles = gather(
        state["queries"],
        days=CONFIG["search_days"],
        max_results=CONFIG["search_max_results"],
        save_json=False,
        extract_full_text=CONFIG["extract_full_text"],  # 启用全文抓取
        allow_undated_articles=CONFIG["allow_undated_articles"]
    )

    print_reader_view(articles)

    # 输出时间过滤数组预览（调试）
    time_filtered = get_last_time_filtered_items()
    if time_filtered:
        preview_table = Table(
            title="Time Filtered Items (Preview)",
            box=box.SIMPLE,
            header_style="yellow"
        )
        preview_table.add_column("#", style="dim", width=3)
        preview_table.add_column("Date", width=12)
        preview_table.add_column("Reason", width=12)
        preview_table.add_column("Title", overflow="fold")

        for i, item in enumerate(time_filtered[:8], 1):
            preview_table.add_row(
                str(i),
                item.get("publish_date", ""),
                item.get("reason", ""),
                item.get("title", "")[:80]
            )

        console.print(preview_table)
        if len(time_filtered) > 8:
            console.print(f"[dim]... and {len(time_filtered) - 8} more filtered by time[/]")

    return {"raw_articles": articles}

def node_analyst(state: AgentState):
    """Phase 2: 语义聚类 + 质量验证 + 地域检测"""
    if not state["raw_articles"]:
        console.print("[yellow]⚠️ 无采集数据，跳过分析阶段[/]")
        return {"events": []}

    agent = AnalystAgent()

    # 根据配置选择聚类方法
    clustering_method = "规则驱动" if CONFIG["use_rule_based_clustering"] else "LLM语义"
    console.print(f"[cyan]使用聚类方法: {clustering_method}[/]")

    events = agent.cluster_articles(
        state["raw_articles"],
        verbose=True,
        use_rule_based=CONFIG["use_rule_based_clustering"],
        enable_quality_check=CONFIG["enable_quality_validation"]
    )

    # 质量验证已经根据配置自动运行（如果启用）
    # 地域标签已自动检测并显示在 Dashboard 中

    return {"events": events}

def node_journalist(state: AgentState):
    """Phase 3: 原子化撰稿 (Atomic Claims)"""
    console.print("\n")
    console.rule("[bold green]🟢 Phase 3: 原子化撰稿 (Claims Extraction)[/]")
    
    if not state["events"]:
        return {"reports": []}
    
    # 使用 V2 版本的撰稿人
    agent = JournalistAgentV2()
    reports = agent.write_reports(
        state["events"],
        max_events=CONFIG["report_max_events"],
        word_guideline=CONFIG["report_guideline"]
    )
    
    # 打印断言统计
    total_claims = sum(len(r.claims) for r in reports)
    console.print(Panel(
        f"生成报告数: {len(reports)}\n提取原子断言总数: {total_claims}",
        title="Journalist V2 Output",
        border_style="green"
    ))

    # Phase 3 可视化：原子断言预览（非黑箱）
    if reports:
        table = Table(
            title="Atomic Claims Preview",
            box=box.SIMPLE,
            header_style="cyan",
            show_lines=False
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Report", style="bold")
        table.add_column("Claim", overflow="fold")
        table.add_column("Sources", justify="right", width=7)

        max_rows = CONFIG["claim_preview_max"]
        max_chars = CONFIG["claim_preview_chars"]
        row_count = 0
        for ridx, report in enumerate(reports, 1):
            for claim in report.claims:
                if row_count >= max_rows:
                    break
                claim_text = textwrap.shorten(claim.claim_text, width=max_chars, placeholder="...")
                table.add_row(
                    str(row_count + 1),
                    f"{ridx}. {report.title[:28]}",
                    claim_text,
                    str(len(claim.source_ids or []))
                )
                row_count += 1
            if row_count >= max_rows:
                break

        if row_count == 0:
            table.add_row("-", "N/A", "No claims extracted", "0")

        console.print(table)
        if total_claims > row_count:
            console.print(f"[dim]... and {total_claims - row_count} more claims not shown[/]")
    
    return {"reports": reports}

def node_verifier(state: AgentState):
    """Phase 4: 三阶段核验 (3-Stage Pipeline)"""
    console.print("\n")
    console.rule("[bold yellow]🟡 Phase 4: 三阶段核验 (Verification Pipeline)[/]")
    
    if not state["reports"]:
        return {"verification_results": []}
    
    # 1. 准备证据池 (Verfier 需要基于原始文章构建检索索引)
    # 这里的关键是将所有采集到的文章传给 Verifier 用于构建 BM25 索引
    all_articles = state["raw_articles"]
    
    # 2. 初始化核验器 (Layer 2-4)
    agent = VerifierAgent(articles=all_articles)
    
    # 3. 执行批量核验 (含 Layer 5 对抗性检查)
    results = agent.batch_verify(
        state["reports"],
        state["events"],
        run_adversarial=CONFIG["run_adversarial_check"]
    )
    
    # 4. 打印仪表盘
    print_verification_dashboard(results)
    
    return {"verification_results": results}

def node_publisher(state: AgentState):
    """Phase 5: 审计发布"""
    console.print("\n")
    console.rule("[bold magenta]🟣 Phase 5: 审计发布 (Publication)[/]")
    
    if not state["verification_results"]:
        return {"final_file_path": None}
    
    # 使用 V2 版本的发布商
    publisher = PublisherAgentV2(output_dir=CONFIG["output_dir"])
    
    file_path = publisher.generate_daily_report(
        state["verification_results"],
        include_audit_trail=CONFIG["include_audit_trail"]
    )
    
    if file_path:
        publisher.print_final_delivery(file_path)
    
    return {"final_file_path": file_path}

# ==========================================
# 5. 图构建 (Graph Builder)
# ==========================================

def build_agent():
    """构建 LangGraph 工作流"""
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("gather", node_gather)
    workflow.add_node("analyst", node_analyst)
    workflow.add_node("journalist", node_journalist)
    workflow.add_node("verifier", node_verifier)  # V2 新增节点
    workflow.add_node("publisher", node_publisher) # V2 更新节点
    
    # 定义边 (线性流程)
    workflow.set_entry_point("gather")
    workflow.add_edge("gather", "analyst")
    workflow.add_edge("analyst", "journalist")
    workflow.add_edge("journalist", "verifier")   # 关键连接: 稿件 -> 核验
    workflow.add_edge("verifier", "publisher")    # 关键连接: 核验结果 -> 发布
    workflow.add_edge("publisher", END)
    
    return workflow.compile()

# ==========================================
# 6. 主程序入口
# ==========================================

def main():
    # 1. 启动画面
    console.print("\n")
    clustering_method = "规则驱动聚类" if CONFIG["use_rule_based_clustering"] else "LLM语义聚类"
    quality_check = "✅ 启用" if CONFIG["enable_quality_validation"] else "❌ 关闭"

    full_text_status = "✅ 启用" if CONFIG["extract_full_text"] else "❌ 关闭"

    console.print(Panel.fit(
        "[bold cyan]🚀 Financial Monitor Agent V2.0[/]\n"
        "[dim]Verified Edition - Atomic Claims & Deterministic Audit[/]\n\n"
        "Pipeline Features:\n"
        f"1. [Module A] Full Text Extraction: {full_text_status}\n"
        f"2. [Module B] Clustering: {clustering_method}\n"
        f"3. [Module B] Quality Validation: {quality_check}\n"
        f"4. [Module B] Region Detection: ✅ 启用 (国内/国际/混合)\n"
        "5. [Module C] Atomic Claims Extraction (Layer 1)\n"
        "6. [Module D] Deterministic Alignment (Layer 3)\n"
        "7. [Module D] Dual-Path Retrieval (Layer 4)\n"
        "8. [Module D] Adversarial Checking (Layer 5)",
        title="System Startup",
        border_style="cyan",
        box=box.DOUBLE
    ))
    
    # 2. 构建 Agent
    app = build_agent()
    
    # 3. 定义查询 —— 按分类体系分层，与 clustering taxonomy_0204.docx 对齐
    queries = [
        # === [macro / monetary_policy + economic_data] ===
        # 央行 + 统计局：货币政策、宏观数据
        "site:pbc.gov.cn OR site:stats.gov.cn LPR OR MLF OR GDP OR CPI OR PMI OR 降息 OR 降准",

        # === [macro / fiscal_policy + 国务院] ===
        # 严格限定国务院官网主域名，避免抓取地方政府转发页
        "site:www.gov.cn OR site:mof.gov.cn OR site:ndrc.gov.cn 财政 OR 专项债 OR 减税 OR 国务院常务会议",

        # === [regulation / securities + banking] ===
        # 证监会 + 金融监管总局：监管新规、处罚、IPO
        "site:csrc.gov.cn OR site:nfra.gov.cn 监管 OR 新规 OR 处罚 OR IPO OR 退市 OR 反垄断",

        # === [market / equity + bond + fx] ===
        # 资本市场行情：A股、债市、汇率
        "site:cls.cn OR site:stcn.com A股 OR 债市 OR 汇率 OR 北向资金 OR ETF OR 国债",

        # === [industry] ===
        # 行业动态：新能源/半导体/地产/消费/医保
        "site:yicai.com OR site:21jingji.com 新能源 OR 半导体 OR 地产 OR 消费 OR 医保 OR 碳市场 OR AI",

        # === [macro + regulation + company / Tier2综合] ===
        # 财新 + 界面：深度报道、政策解读、公司大事
        "site:caixin.com OR site:jiemian.com OR site:cs.com.cn OR site:cnstock.com 深度 OR 政策 OR 财报 OR 并购",
    ]
    
    # 4. 初始化状态
    initial_state = {
        "queries": queries,
        "raw_articles": [],
        "events": [],
        "reports": [],
        "verification_results": [],
        "final_file_path": None
    }
    
    # 5. 运行流水线
    try:
        start_time = datetime.now()
        result = app.invoke(initial_state)
        end_time = datetime.now()
        
        # 6. 最终统计
        console.print("\n")
        console.rule("[bold green]✅ Workflow Completed[/]")
        
        duration = (end_time - start_time).seconds
        v_results = result.get("verification_results", [])
        
        if v_results:
            total_claims = sum(r.total_claims for r in v_results)
            verified = sum(r.verified_claims for r in v_results)
            failed = sum(r.failed_claims for r in v_results)
            
            stats_text = f"""
            [bold]Execution Stats:[/bold]
            ⏱️ Duration: {duration}s
            📄 Reports: {len(v_results)}
            
            [bold]Verification Stats:[/bold]
            Total Claims: {total_claims}
            ✅ Verified: {verified}
            ❌ Failed/Conflict: {failed}
            """
            console.print(Panel(stats_text, title="Final Summary", border_style="green"))
            
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️ 用户手动中断[/]")
    except Exception as e:
        console.print(f"\n[bold red]❌ 系统运行错误: {e}[/]")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
