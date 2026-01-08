# gather_demo.py
# Module A: DuckDuckGo News Gatherer
# Compatible with main.py's Financial Monitor Agent

import hashlib
import json
import random
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

# === 依赖检查（静默模式，避免被 import 时打印） ===
try:
    from ddgs import DDGS
except ImportError:
    raise ImportError("请安装 ddgs: pip install ddgs")

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    raise ImportError("请安装: pip install requests beautifulsoup4")

try:
    from rich.console import Console
    from rich.table import Table
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    console = None

# === 配置 ===
WHITELIST = {
    "tier1": {
        "domains": ["pbc.gov.cn", "mof.gov.cn", "gov.cn", "ndrc.gov.cn", 
                   "stats.gov.cn", "csrc.gov.cn", "nfra.gov.cn", "safe.gov.cn"]
    },
    "tier2": {
        "domains": ["caixin.com", "cls.cn", "yicai.com", "21jingji.com", 
                   "sina.com.cn", "news.cn", "stcn.com", "cs.com.cn", 
                   "cnstock.com", "financialnews.com.cn", "ce.cn", 
                   "jiemian.com", "thepaper.cn", "eeo.com.cn", "nbd.com.cn"]
    }
}

# === 数据模型（与 main.py 对齐） ===
class SourceInfo(BaseModel):
    url: str
    domain: str
    tier: str
    outlet_name: str  # main.py 需要这个字段
    whitelisted: bool

class RawArticle(BaseModel):
    article_id: str
    url: str
    title: str
    snippet: str
    full_text: str = ""
    source: SourceInfo
    eligible_for_event: bool = False  # main.py 可能需要
    publish_date: str = ""

# === 工具函数 ===
def _log(msg: str, level: str = "info"):
    """内部日志（可选 Rich）"""
    if HAS_RICH and console:
        colors = {"info": "cyan", "success": "green", "warning": "yellow", 
                 "error": "red", "debug": "dim"}
        console.print(f"[{colors.get(level, 'white')}]{msg}[/]")
    else:
        print(msg)

def resolve_source(url: str) -> SourceInfo:
    """解析来源信息"""
    try:
        domain = url.split("/")[2].replace("www.", "")
    except:
        domain = "unknown"
    
    tier = "unknown"
    whitelisted = False
    
    for t, cfg in WHITELIST.items():
        if any(d in domain for d in cfg["domains"]):
            tier = t
            whitelisted = True
            break
    
    return SourceInfo(
        url=url,
        domain=domain,
        tier=tier,
        outlet_name=domain,  # 与 main.py 对齐
        whitelisted=whitelisted
    )

# === 搜索策略 ===
def _search_ddgs(query: str, region: str = 'wt-wt', timelimit: Optional[str] = None, 
                fetch_count: int = 30) -> List[Dict]:
    """
    底层 DuckDuckGo 搜索
    
    Args:
        query: 搜索词（原样传递，支持 site:A OR site:B 语法）
        region: 地区代码
        timelimit: 时间限制 ('d'/'w'/'m'/'y'/None)
        fetch_count: 内部抓取条数（不暴露给外部）
    """
    try:
        ddgs = DDGS()  # 每次调用创建实例，避免线程问题
        
        # 根据是否有时间限制调用
        if timelimit:
            results = ddgs.text(query, region=region, timelimit=timelimit, max_results=fetch_count)
        else:
            results = ddgs.text(query, region=region, max_results=fetch_count)
        
        if results is None:
            return []
        
        # 消费 generator
        return list(results)
        
    except Exception as e:
        _log(f"搜索异常: {str(e)[:100]}", "error")
        return []

def _multi_strategy_search(query: str, days: int = 7, fetch_count: int = 30) -> tuple[List[Dict], str]:
    """
    多策略搜索（带重试和回退）
    
    Returns:
        (results, strategy_path)
    """
    # 根据天数确定时间限制
    if days <= 1:
        timelimit = 'd'
    elif days <= 7:
        timelimit = 'w'
    elif days <= 30:
        timelimit = 'm'
    elif days <= 365:
        timelimit = 'y'
    else:
        timelimit = None
    
    strategy_path = []
    
    # 策略A: 带时间限制
    if timelimit:
        strategy_path.append(f"A(时限:{timelimit})")
        for attempt in range(2):  # 指数退避重试
            results = _search_ddgs(query, region='wt-wt', timelimit=timelimit, fetch_count=fetch_count)
            if results:
                return results, "→".join(strategy_path)
            if attempt < 1:
                time.sleep(1 + random.random())
    
    # 策略B: 无时间限制
    strategy_path.append("B(无时限)")
    results = _search_ddgs(query, region='wt-wt', timelimit=None, fetch_count=fetch_count)
    if results:
        return results, "→".join(strategy_path)
    
    # 策略C: 区域回退
    for region in ['us-en', 'cn-zh']:
        strategy_path.append(f"C({region})")
        results = _search_ddgs(query, region=region, timelimit=None, fetch_count=fetch_count)
        if results:
            return results, "→".join(strategy_path)
    
    return [], "→".join(strategy_path) + "(失败)"

# === 主采集函数（对外接口） ===
def gather(queries: List[str], days: int = 3, max_results: int = 5, 
          save_json: bool = False, output_path: str = "gathered_results.json",
          **kwargs) -> List[RawArticle]:
    """
    主采集函数（与 main.py 接口对齐）
    
    Args:
        queries: 查询词列表（支持 site:A OR site:B 语法）
        days: 时间范围（天数）
            - 1 = 最近1天
            - 7 = 最近1周
            - 30 = 最近1月
            - 365 = 最近1年
            - 9999 = 不限制
        max_results: 每个 query 最多返回多少条"白名单命中且去重后"的 RawArticle
        save_json: 是否保存 JSON（CLI 调试用，server 模式建议关闭）
        output_path: JSON 保存路径
        **kwargs: 预留扩展参数（如 extract_full_text, proxy 等）
    
    Returns:
        List[RawArticle]: 采集结果列表
    """
    articles = []
    
    # 局部统计（避免全局污染）
    stats = {
        "total_queries": len(queries),
        "total_raw_results": 0,
        "total_filtered": 0,
        "total_hits": 0,
        "strategy_paths": {}
    }
    
    _log(f"🔍 启动采集 (查询数: {len(queries)}, 时间范围: {days}天, 每查询上限: {max_results}条)", "info")
    
    for idx, query in enumerate(queries, 1):
        _log(f"\n[{idx}/{len(queries)}] 查询: {query[:60]}...", "info")
        
        # 多策略搜索（内部抓取 30 条原始结果）
        results, strategy_path = _multi_strategy_search(query, days=days, fetch_count=30)
        stats["strategy_paths"][query] = strategy_path
        
        if not results:
            _log(f"  ✗ 无结果 (策略: {strategy_path})", "error")
            continue
        
        _log(f"  ✓ 获得 {len(results)} 条原始结果 (策略: {strategy_path})", "success")
        stats["total_raw_results"] += len(results)
        
        found = 0
        filtered = 0
        
        for item in results:
            url = item.get("href", "")
            title = item.get("title", "")
            snippet = item.get("body", "")
            
            if not url or not title:
                continue
            
            source = resolve_source(url)
            
            # 白名单过滤
            if not source.whitelisted:
                filtered += 1
                if filtered <= 3:  # 只显示前3条
                    _log(f"    - 过滤: {source.domain}", "debug")
                continue
            
            # 去重
            if any(a.url == url for a in articles):
                continue
            
            _log(f"    ✓ 命中: {source.tier} - {source.domain}", "success")
            _log(f"      {title[:60]}...", "debug")
            
            # 构造 RawArticle
            article = RawArticle(
                article_id=hashlib.md5(url.encode()).hexdigest(),
                url=url,
                title=title,
                snippet=snippet,
                full_text="",  # 如果需要提取全文，在这里调用 extract_body()
                source=source,
                eligible_for_event=True,
                publish_date=""  # DuckDuckGo 不提供日期，保持为空
            )
            
            articles.append(article)
            found += 1
            
            if found >= max_results:
                break
        
        if filtered > 3:
            _log(f"    ... (过滤了其他 {filtered - 3} 条)", "debug")
        
        stats["total_filtered"] += filtered
        stats["total_hits"] += found
        
        _log(f"  📈 本查询: 命中 {found}, 过滤 {filtered}", "info")
    
    # 打印统计摘要
    _log(f"\n{'='*60}", "info")
    _log(f"📊 采集完成: 共 {len(articles)} 条结果", "success")
    _log(f"  总查询数: {stats['total_queries']}", "info")
    _log(f"  原始结果数: {stats['total_raw_results']}", "info")
    _log(f"  过滤结果数: {stats['total_filtered']}", "info")
    _log(f"  命中白名单: {stats['total_hits']}", "info")
    _log(f"{'='*60}", "info")
    
    # 可选：保存 JSON
    if save_json and articles:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump([art.model_dump() for art in articles], f, ensure_ascii=False, indent=2)
            _log(f"💾 已保存: {output_path}", "success")
        except Exception as e:
            _log(f"⚠ 保存失败: {e}", "warning")
    
    return articles

# === 可视化函数（供 main.py 调用） ===
def print_reader_view(articles: List[RawArticle]):
    """打印采集结果的阅读视图"""
    if not articles:
        _log("\n⚠ 无采集结果", "warning")
        return
    
    if HAS_RICH and console:
        table = Table(title="📰 采集结果预览", show_lines=True)
        table.add_column("ID", width=4, justify="center")
        table.add_column("标题", width=50)
        table.add_column("来源", width=20)
        table.add_column("层级", width=8)
        
        for i, art in enumerate(articles, 1):
            table.add_row(
                str(i),
                art.title[:47] + "..." if len(art.title) > 50 else art.title,
                art.source.domain,
                art.source.tier
            )
        
        console.print("\n")
        console.print(table)
    else:
        print("\n" + "="*60)
        print("📰 采集结果预览")
        print("="*60)
        for i, art in enumerate(articles, 1):
            print(f"\n[{i}] {art.title}")
            print(f"    来源: {art.source.domain} ({art.source.tier})")
            print(f"    URL: {art.url}")

# === CLI 测试入口（不会被 import 时执行） ===
if __name__ == "__main__":
    test_queries = [
        "site:pbc.gov.cn 货币政策",
        "site:caixin.com 金融监管"
    ]
    
    articles = gather(
        queries=test_queries,
        days=7,
        max_results=3,
        save_json=True
    )
    
    print_reader_view(articles)