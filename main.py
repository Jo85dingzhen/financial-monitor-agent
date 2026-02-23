# main.py
# The Financial Monitor Agent (V6.0 Universal Engine)
# 架构: Gather -> Analyst -> Journalist -> Auditor -> Publisher
# 功能: 全网采集 -> 语义聚类 -> 学术撰稿 -> 合规审计 -> 自动排版出版
# 适用场景： CLI（本地） / API（服务器）/ iOS后端 / Web后端

import os
import sys
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from gather_demo import gather, RawArticle, print_reader_view

# === 依赖库检查 ===
try:
    from dotenv import load_dotenv
    # override=True 确保 .env 里的值覆盖系统默认值
    # verbose=True 会在找不到文件时发出警告
    load_dotenv(override=True, verbose=True) 
    print(f"DEBUG: DEEPSEEK_API_KEY loaded? {bool(os.getenv('DEEPSEEK_API_KEY'))}")
except ImportError:
    print("❌ 严重警告：未安装 python-dotenv，无法读取 .env 文件！")
    print("请运行: pip install python-dotenv")

try:
    from rich.console import Console
    from rich.panel import Panel
    console = Console()
except ImportError:
    print("❌ 缺少 rich 库，请 pip install rich")
    exit()

# === 模块引入 ===
try:
    # Module A: 采集者
    from gather_demo import gather, RawArticle, print_reader_view
    
    # Module B: 分析师
    from analyst_demo import AnalystAgent, Event
    
    # Module C: 撰稿人
    from journalist_demo import JournalistAgent, NewsReport
    
    # Module D: 审计官
    from auditor_demo import AuditorAgent, AuditResult
    
    # Module E: 出版商 (新增)
    from publisher_demo import PublisherAgent
    
except ImportError as e:
    console.print(f"[bold red]❌ 启动失败: 缺少必要模块文件。错误信息: {e}[/]")
    console.print("[yellow]请确保 gather_demo.py, analyst_demo.py 等文件都在同一目录下。[/]")
    exit()

# ==========================================
# ⚙️ 全局配置 (CONFIG)
# 在这里控制你的 Agent 行为！
# ==========================================
CONFIG = {
    # [Module A] 搜索设置
    "search_days": 3,              # 搜索过去几天的新闻 (建议 1-3)
    "search_max_results": 5,       # 每个关键词搜索几条 (建议 5-10)
    
    # [Module C] 撰稿设置
    "report_max_events": 5,        # 最终写几个热点事件 (建议 3-5)
    
    # 字数与风格指令 (DeepSeek 会严格遵守)
    "report_word_count": "撰写一篇结构完整的财经研报。包含：摘要(100字)、背景(Background)、深度分析(Analysis)及未来展望(Outlook)。总字数控制在 400-600 字。",
    
    # [Module E] 输出设置
    "output_dir": "daily_reports"  # 日报保存的文件夹名
}

# ==========================================
# 1. 状态定义 (State)
# ==========================================
class AgentState(TypedDict):
    queries: List[str]                  # 初始搜索词
    raw_articles: List[RawArticle]      # A阶段产物
    events: List[Event]                 # B阶段产物
    reports: List[NewsReport]           # C阶段产物
    audit_results: List[AuditResult]    # D阶段产物
    final_file_path: Optional[str]      # E阶段产物 (文件路径)

# ==========================================
# 2. 节点定义 (Nodes)
# ==========================================

def node_gather(state: AgentState):
    """Module A: 全网采集"""
    console.rule("[bold blue]🔵 Phase 1: 全网采集 (Gathering)[/]")
    articles = gather(
        state["queries"], 
        days=CONFIG["search_days"], 
        max_results=CONFIG["search_max_results"],
        save_json=False  # ← 新增：server 模式不保存文件
    )
    print_reader_view(articles)
    return {"raw_articles": articles}

def node_analyst(state: AgentState):
    """Module B: 语义聚类"""
    if not state["raw_articles"]:
        return {"events": []}
    agent = AnalystAgent()
    events = agent.cluster_articles(state["raw_articles"], verbose=True)
    return {"events": events}

def node_journalist(state: AgentState):
    """Module C: 撰稿"""
    console.print("\n")
    console.rule("[bold green]🟢 Phase 3: 深度撰稿 (Drafting)[/]")
    if not state["events"]:
        return {"reports": []}
    agent = JournalistAgent()
    reports = agent.write_reports(
        state["events"],
        max_events=CONFIG["report_max_events"],
        word_guideline=CONFIG["report_word_count"]
    )
    return {"reports": reports}

def node_auditor(state: AgentState):
    """Module D: 合规审计"""
    console.print("\n")
    if not state["reports"]:
        return {"audit_results": []}
    agent = AuditorAgent()
    results = agent.batch_audit(state["reports"], state["events"])
    return {"audit_results": results}

def node_publisher(state: AgentState):
    """Module E: 出版与发布"""
    if not state["audit_results"]:
        return {"final_file_path": None}
    publisher = PublisherAgent(output_dir=CONFIG["output_dir"])
    file_path = publisher.generate_daily_report(state["audit_results"])
    if file_path:
        publisher.print_final_delivery(file_path)
    return {"final_file_path": file_path}

# ==========================================
# ✨✨ 3. 通用构建函数 (工厂模式) ✨✨
# 这里的代码被 Server.py 调用
# ==========================================
def build_agent():
    """
    只负责组装机器，不负责运行。
    返回一个编译好的 app 对象。
    """
    # 构建图
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("gather", node_gather)
    workflow.add_node("analyst", node_analyst)
    workflow.add_node("journalist", node_journalist)
    workflow.add_node("auditor", node_auditor)
    workflow.add_node("publisher", node_publisher)

    # 定义流程边
    workflow.set_entry_point("gather")
    workflow.add_edge("gather", "analyst")
    workflow.add_edge("analyst", "journalist")
    workflow.add_edge("journalist", "auditor")
    workflow.add_edge("auditor", "publisher")
    workflow.add_edge("publisher", END)

    # 编译并返回
    return workflow.compile()

# ==========================================
# 4. 本地运行入口 (CLI Mode)
# ==========================================
def main():
    # 1. 欢迎界面
    console.print("\n")
    console.rule("[bold cyan]🚀 Financial Monitor Agent (V6.0 Pro Edition)[/]")
    console.print(f"[dim]配置: 过去{CONFIG['search_days']}天 | 上限{CONFIG['report_max_events']}篇 | {CONFIG['output_dir']}[/dim]", justify="center")
    
    # 2. 调用构建函数拿到机器
    app = build_agent()
    
    # 3. 初始输入 (使用组合查询优化搜索效率)
    # 提示：使用 "site:A OR site:B 关键词" 的语法可以一次搜多个网站
    initial_state = {
        "queries": [
            # === Tier 1: 核心部委 (关注政策与宏观数据) ===
            "site:pbc.gov.cn OR site:mof.gov.cn OR site:stats.gov.cn OR site:ndrc.gov.cn 宏观政策",
            "site:csrc.gov.cn OR site:nfra.gov.cn OR site:safe.gov.cn 金融监管",
            "site:gov.cn 国务院重磅",

            # === Tier 2: 官方权威媒体 (关注资本市场与行业导向) ===
            # 证券三报 (中证报、上证报、证券时报)
            "site:cs.com.cn OR site:cnstock.com OR site:stcn.com 资本市场",
            # 经济与金融核心央媒
            "site:financialnews.com.cn OR site:ce.cn OR site:jjckb.cn 金融要闻",
            # 综合类官方财经 (中国财经报、中国经济导报等)
            "site:cfen.com.cn OR site:zhonghongwang.com OR site:cet.com.cn 经济动态",
            # 行业垂直 (基金报、银行保险报等)
            "site:chnfund.com OR site:cbimc.cn OR site:bbtnews.com.cn 行业分析",

            # === Tier 2.5: 市场化/深度媒体 (关注深度分析与独家) ===
            # 核心深度 (财新、一财、21世纪)
            "site:caixin.com OR site:yicai.com OR site:21jingji.com 深度报道",
            # 快讯与新媒体 (财联社、界面、澎湃、中新经纬)
            "site:cls.cn OR site:jiemian.com OR site:thepaper.cn OR site:jwview.com 财经快讯",
            # 商业观察 (经观、中经、每日经济、蓝鲸)
            "site:eeo.com.cn OR site:cb.com.cn OR site:nbd.com.cn OR site:lanjinger.com 商业观察",
            # 区域与综合 (新京报、封面、上观、华夏时报、时代周报)
            "site:bjnews.com.cn OR site:thecover.cn OR site:shobserver.com OR site:chinatimes.net.cn 财经热点"
        ],
        "raw_articles": [], 
        "events": [], 
        "reports": [], 
        "audit_results": [],
        "final_file_path": None
    }

    # 4. 启动！
    app.invoke(initial_state)

if __name__ == "__main__":
    main()
