# gatherer_demo.py
# V3.1: Full Whitelist Update & Reader Mode

from __future__ import annotations

import os
import re
import hashlib
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any

# === 依赖库检查 ===
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("❌ 错误: 缺少必要库。请运行: pip install requests beautifulsoup4")
    exit()

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.markdown import Markdown
    from rich import box
    from rich.progress import track
    console = Console()
except ImportError:
    print("❌ 错误: 缺少 rich 库。请运行: pip install rich")
    exit()

from pydantic import BaseModel
from tavily import TavilyClient

# =============== 1. 环境配置 ===============

def load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                key, value = line.strip().split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_env()

if not os.getenv("TAVILY_API_KEY"):
    console.print("[bold red]⚠️  未找到 TAVILY_API_KEY，请检查 .env 文件[/]")

# =============== 2. 完整白名单配置 (已更新) ===============

WHITELIST = {
    # Tier 1: 核心政府/监管机构 (9个)
    "tier1": {
        "domains": {
            "pbc.gov.cn": "中国人民银行",
            "mof.gov.cn": "财政部",
            "stats.gov.cn": "国家统计局",
            "gov.cn": "国务院/中国政府网",
            "csrc.gov.cn": "证监会",
            "nfra.gov.cn": "金融监管总局",
            "safe.gov.cn": "外汇局",
            "ndrc.gov.cn": "国家发改委",
        },
        "max_age_days": 30, # 政策类允许回溯
    },

    # Tier 2: 官方/党媒/指定披露机构 (21个)
    "tier2": {
        "domains": {
            "cs.com.cn": "中证网/中国证券报",
            "financialnews.com.cn": "金融时报",
            "financialnews.com": "中国金融新闻网", # 别名
            "stcn.com": "证券时报",
            "paper.ce.cn": "经济日报(电子报)",
            "ce.cn": "中国经济网",
            "cnstock.com": "上证报",
            "bjnew.com.cn": "新京报",
            "jjckb.cn": "经济参考报",
            "ceh.com.cn": "中国经济导报", # 补全域名
            "zhonghongwang.com": "中宏网",
            "cfen.com.cn": "中国财经报网", # 修正 .com. 写法
            "chnfund.com": "中国基金报",
            "cet.com.cn": "中国经济时报/新闻网",
            "bbtnews.com.cn": "北京商报",
            "cbimc.cn": "中国银行保险报", # 修正 www.
            "eeo.com.cn": "经济观察报",
            "cb.com.cn": "中国经营报",
            "ccn.com.cn": "中国消费者报", # 补全域名
        },
        "max_age_days": 7,
    },

    # Tier 2.5: 市场化核心媒体 (15个)
    "tier2_5": {
        "domains": {
            "caixin.com": "财新",
            "21jingji.com": "21世纪经济报道",
            "cnfin.com": "新华财经",
            "nbd.com.cn": "每日经济新闻",
            "yicai.com": "第一财经",
            "jwview.com": "中新经纬",
            "lanjinger.com": "蓝鲸财经",
            "cls.cn": "财联社",
            "sfccn.com": "南方财经网",
            "time-weekly.com": "时代周报",
            "thepaper.cn": "澎湃新闻",
            "jiemian.com": "界面新闻",
            "thecover.cn": "封面新闻",
            "chinatimes.net.cn": "华夏时报",
            "shobserver.com": "上观新闻",
        },
        "max_age_days": 3, # 市场新闻时效性要求高
    }
}

# 域名别名映射 (解决 www. 或不同后缀指向同一家的情况)
DOMAIN_ALIASES = {
    "www.financialnews.com.cn": "financialnews.com.cn",
    "www.cbimc.cn": "cbimc.cn",
    "paper.ce.cn": "ce.cn", # 归类到中经网体系
}

# =============== 3. 数据模型 ===============

class SourceInfo(BaseModel):
    url: str
    domain: str
    tier: Optional[str] = None
    outlet_name: Optional[str] = None
    whitelisted: bool = False

class RawArticle(BaseModel):
    article_id: str
    url: str
    title: str
    snippet: Optional[str] = None
    full_text: Optional[str] = None
    source: SourceInfo
    category: str
    published_at: Optional[str] = None
    eligible_for_event: bool = False
    drop_reason: Optional[str] = None

# =============== 4. 核心功能 ===============

def get_tavily_client() -> TavilyClient:
    return TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def tavily_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    client = get_tavily_client()
    try:
        response = client.search(query=query, search_depth="advanced", max_results=max_results)
        return response.get("results", [])
    except Exception as e:
        console.print(f"[red]Tavily 搜索失败: {e}[/]")
        return []

def resolve_source(url: str) -> SourceInfo:
    domain = urlparse(url).netloc.lower().replace("www.", "")
    domain = DOMAIN_ALIASES.get(domain, domain)
    
    # 遍历三层白名单
    for tier, cfg in WHITELIST.items():
        if domain in cfg["domains"]:
            return SourceInfo(
                url=url, 
                domain=domain, 
                tier=tier, 
                outlet_name=cfg["domains"][domain], 
                whitelisted=True
            )
            
    return SourceInfo(url=url, domain=domain, whitelisted=False)

def extract_article_body(url: str, timeout: int = 15) -> str:
    """下载并清洗网页正文"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.encoding = resp.apparent_encoding
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 移除干扰元素
        for tag in soup(["script", "style", "nav", "header", "footer", "iframe", "noscript", "aside"]):
            tag.decompose()
            
        # 智能提取正文
        article = soup.find("article")
        if not article:
            # 备选方案：找字数最多的 div
            text_blocks = []
            for div in soup.find_all("div"):
                # 简单过滤：类名包含 content, article, body 的优先 (可选优化)
                text = div.get_text(strip=True)
                if len(text) > 150: 
                    text_blocks.append((len(text), div))
            
            if text_blocks:
                text_blocks.sort(key=lambda x: x[0], reverse=True)
                article = text_blocks[0][1]
            else:
                article = soup.body

        if not article: return ""

        text = article.get_text(separator="\n\n")
        return re.sub(r'\n\s*\n', '\n\n', text).strip()

    except Exception as e:
        return f"[Error: {str(e)}]"

# =============== 5. 主流程 ===============

def gather(queries: List[str]) -> List[RawArticle]:
    all_results = []
    
    # 1. 搜索阶段
    raw_items = []
    with console.status("[bold green]🔍 正在基于新白名单全网搜索...[/]") as status:
        for q in queries:
            status.update(f"搜索: {q}")
            items = tavily_search(q, max_results=4)
            raw_items.extend(items)
    
    # 去重
    seen_urls = set()
    unique_items = []
    for item in raw_items:
        if item['url'] not in seen_urls:
            unique_items.append(item)
            seen_urls.add(item['url'])

    # 2. 抓取与过滤阶段
    console.print(f"[cyan]发现 {len(unique_items)} 条线索，开始深度过滤...[/]")
    
    for item in track(unique_items, description="下载与清洗中..."):
        url = item["url"]
        source = resolve_source(url)
        
        # 白名单检查
        if not source.whitelisted:
            all_results.append(RawArticle(
                article_id="0", url=url, title=item["title"], source=source, 
                category="unknown", content_type="mixed", eligible_for_event=False, drop_reason="非白名单"
            ))
            continue
            
        # 全文下载
        full_text = extract_article_body(url)
        
        if len(full_text) < 50:
            eligible = False
            drop_reason = "正文内容过少"
        else:
            eligible = True
            drop_reason = None

        # 简单分类
        if source.tier == "tier1":
            category = "policy"
        elif "财报" in item["title"] or "业绩" in item["title"]:
            category = "company"
        else:
            category = "market"
        
        all_results.append(RawArticle(
            article_id=hashlib.md5(url.encode()).hexdigest(),
            url=url, 
            title=item.get("title", ""), 
            snippet=item.get("snippet", ""), 
            full_text=full_text,
            source=source,
            category=category, 
            content_type="fact",
            eligible_for_event=eligible,
            drop_reason=drop_reason
        ))

    return all_results

# =============== 6. 结果展示 (Reader View) ===============

def print_reader_view(articles: List[RawArticle]):
    valid_news = [a for a in articles if a.eligible_for_event]
    
    console.print("\n")
    console.rule("[bold cyan]📰 财经深度阅读模式 (V3.1)[/]")
    console.print(f"[dim]白名单覆盖: {sum(len(v['domains']) for v in WHITELIST.values())} 家核心媒体[/]", justify="center")
    
    if not valid_news:
        console.print("\n[bold red]⚠️ 本次搜索未命中白名单媒体。建议:[/]")
        console.print("1. 检查搜索关键词是否过于冷门")
        console.print("2. 尝试添加 'site:domain.com' 指定搜索")
        return

    for i, news in enumerate(valid_news, 1):
        # 颜色区分 Tier
        color = "red" if news.source.tier == "tier1" else ("blue" if news.source.tier == "tier2" else "green")
        
        console.print(f"\n[bold white on {color}] {i}. {news.title} [/]")
        console.print(f"[dim]来源: {news.source.outlet_name} ({news.source.tier.upper()}) | 字数: {len(news.full_text)}[/]")
        console.print(f"[link={news.url}]🔗 原文链接[/link]")
        
        # 预览正文 (前800字)
        preview_text = news.full_text[:800] + "\n\n...(剩余内容省略)..." if len(news.full_text) > 800 else news.full_text
        
        text_panel = Panel(
            Markdown(preview_text),
            border_style="grey70",
            box=box.SIMPLE,
            title="📄 正文预览",
            title_align="left"
        )
        console.print(text_panel)
        console.print("-" * 40, style="dim")

# =============== 7. 执行入口 ===============

if __name__ == "__main__":
    # 测试不同层级的媒体
    QUERIES = [
        "site:pbc.gov.cn 货币政策",       # Tier 1
        "site:caixin.com 宏观数据",       # Tier 2.5
        "site:stcn.com 上市公司",         # Tier 2
        "site:eeo.com.cn 经济观察"        # Tier 2 (新增测试)
    ]
    
    results = gather(QUERIES)
    print_reader_view(results)
