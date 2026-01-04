# main.py
# The Financial Monitor Agent - LangGraph Orchestrator (Full Pipeline)
# 架构: Gather(A) -> Analyst(B) -> Journalist(C) -> Auditor(D) -> Output

import os
from typing import TypedDict, List
from langgraph.graph import StateGraph, END

# === 引用四个核心模块 ===
try:
    from gather_demo import gather, RawArticle
    from analyst_demo import AnalystAgent, Event
    from journalist_demo import JournalistAgent, NewsReport
    # 新增 Module D
    from auditor_demo import AuditorAgent, AuditResult, print_audit_dashboard
except ImportError as e:
    print(f"❌ 启动失败: 缺少核心文件。\n详情: {e}")
    exit()

# === UI ===
try:
    from rich.console import Console
    console = Console()
except ImportError:
    class Console:
        def print(self, *args, **kwargs): print(*args)
    console = Console()

# ==========================================
# 1. 定义图的状态 (Shared Memory)
# ==========================================

class AgentState(TypedDict):
    queries: List[str]             # 初始输入
    raw_articles: List[RawArticle] # Module A 产出
    events: List[Event]            # Module B 产出
    reports: List[NewsReport]      # Module C 产出
    audit_results: List[AuditResult] # Module D 产出 (最终结果)
    status: str

# ==========================================
# 2. 定义节点 (Workflow Nodes)
# ==========================================

def node_gather(state: AgentState):
    """Module A: 采集"""
    console.print(f"\n[bold blue]🔵 [Node A] 启动采集器 (Gatherer)...[/]")
    queries = state["queries"]
    articles = gather(queries)
    valid_articles = [a for a in articles if a.eligible_for_event]
    console.print(f"[dim]采集完成，获取 {len(valid_articles)} 条有效线索。[/]")
    return {"raw_articles": valid_articles, "status": "gathered"}

def node_analyst(state: AgentState):
    """Module B: 分析"""
    console.print(f"\n[bold purple]🟣 [Node B] 启动分析师 (Analyst)...[/]")
    articles = state["raw_articles"]
    if not articles:
        return {"events": [], "status": "skipped_no_data"}
    
    try:
        agent = AnalystAgent()
        events = agent.cluster_articles(articles)
        return {"events": events, "status": "analyzed"}
    except Exception as e:
        console.print(f"[red]❌ 分析失败: {e}[/]")
        return {"events": [], "status": "error"}

def node_journalist(state: AgentState):
    """Module C: 撰稿"""
    console.print(f"\n[bold green]🟢 [Node C] 启动撰稿人 (Journalist)...[/]")
    events = state["events"]
    if not events:
        return {"reports": [], "status": "skipped_no_events"}
    
    try:
        agent = JournalistAgent()
        reports = agent.write_reports(events)
        return {"reports": reports, "status": "drafted"}
    except Exception as e:
        console.print(f"[red]❌ 撰稿失败: {e}[/]")
        return {"reports": [], "status": "error"}

def node_auditor(state: AgentState):
    """Module D: 审计 (新加入的节点)"""
    console.print(f"\n[bold yellow]🛡️ [Node D] 启动审计官 (Auditor)...[/]")
    reports = state["reports"]
    events = state["events"]
    
    if not reports:
        return {"audit_results": [], "status": "skipped_no_reports"}

    try:
        agent = AuditorAgent()
        # 审计官需要拿着“稿子(reports)”对照“原始素材(events)”去核查
        results = agent.batch_audit(reports, events)
        return {"audit_results": results, "status": "audited"}
    except Exception as e:
        console.print(f"[red]❌ 审计失败: {e}[/]")
        return {"audit_results": [], "status": "error"}

# ==========================================
# 3. 构建图 (Graph Construction)
# ==========================================

def build_graph():
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("gather", node_gather)
    workflow.add_node("analyst", node_analyst)
    workflow.add_node("journalist", node_journalist)
    workflow.add_node("auditor", node_auditor) # 新增

    # 定义流程：A -> B -> C -> D -> End
    workflow.set_entry_point("gather")
    workflow.add_edge("gather", "analyst")
    workflow.add_edge("analyst", "journalist")
    workflow.add_edge("journalist", "auditor") # 连接 C 和 D
    workflow.add_edge("auditor", END)

    return workflow.compile()

# ==========================================
# 4. 主程序入口
# ==========================================

def main():
    # 欢迎信息
    console.print("\n")
    console.rule("[bold cyan]🚀 Financial Monitor Agent (Final Edition)[/]")
    console.print("[dim]Architecture: Gather -> Analyst -> Journalist -> Auditor[/dim]\n", justify="center")

    # 定义监控任务
    initial_state = {
        "queries": [
            "site:pbc.gov.cn 货币政策",        # 央行
            "site:mof.gov.cn 财政数据",        # 财政部
            "site:stcn.com 上市公司 业绩",      # 证券时报
            "site:caixin.com 宏观经济"         # 财新
        ],
        "raw_articles": [],
        "events": [],
        "reports": [],
        "audit_results": [],
        "status": "start"
    }

    # 构建并运行图
    app = build_graph()
    final_state = app.invoke(initial_state)

    # 最终展示 Module D 的成果 (只展示经过审计的合规结果)
    if final_state["audit_results"]:
        print_audit_dashboard(final_state["audit_results"])
        
        # 统计
        passed = sum(1 for r in final_state["audit_results"] if r.status == "PASS")
        fixed = sum(1 for r in final_state["audit_results"] if r.status == "FIXED")
        console.print(f"\n[bold cyan]🎉 流程结束。合规发布: {passed} 篇, 自动修正: {fixed} 篇。[/]")
    else:
        console.print("\n[yellow]流程结束，无内容发布。[/]")

if __name__ == "__main__":
    main()
