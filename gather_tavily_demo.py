# gather_demo.py
# Module A: The Gatherer (Configurable Edition V3.2 - Fixed Env Loading)

import os
import re
import hashlib
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

try:
    from tavily import TavilyClient
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich import box
    from rich.progress import track
    import requests
    from bs4 import BeautifulSoup
    console = Console()
except ImportError:
    print("❌ 缺少依赖库，请运行: pip install requests beautifulsoup4 rich tavily-python")
    exit()

# === 🛠️ 修复核心：手动加载 .env 文件 ===
def load_env(path=".env"):
    """手动读取 .env 文件并将变量加载到环境变量中"""
    if not os.path.exists(path):
        console.print(f"[yellow]⚠️  警告: 未找到 {path} 文件，请确认 API Key 已设置。[/]")
        return
    
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 忽略注释和空行
            if not line or line.startswith("#") or "=" not in line:
                continue
            
            key, value = line.split("=", 1)
            # 去除引号和空格
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            
            # 设置到系统环境变量
            os.environ.setdefault(key, value)

# 在程序启动时立即执行加载
load_env()

# ==========================================

# === 配置 ===
WHITELIST = {
    "tier1": {"domains": ["pbc.gov.cn", "mof.gov.cn", "gov.cn"]},
    "tier2": {"domains": ["stcn.com", "caixin.com", "cls.cn", "yicai.com"]}
}

class SourceInfo(BaseModel):
    url: str
    domain: str
    tier: str
    outlet_name: str
    whitelisted: bool

class RawArticle(BaseModel):
    article_id: str
    url: str
    title: str
    snippet: str
    full_text: str = ""
    source: SourceInfo
    eligible_for_event: bool = False

# === 核心函数 ===

def get_tavily_client():
    key = os.getenv("TAVILY_API_KEY")
    if not key: 
        # 增加更友好的报错提示
        raise ValueError("❌ 无法读取 TAVILY_API_KEY。请检查项目根目录下是否有 .env 文件，且里面填了 Key。")
    return TavilyClient(api_key=key)

def extract_body(url: str) -> str:
    """简单爬取正文"""
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200: return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        # 移除杂质
        for tag in soup(["script", "style", "nav", "footer"]): tag.decompose()
        # 找正文
        article = soup.find("article") or soup.find("div", class_=re.compile("content|article"))
        return article.get_text(separator="\n", strip=True) if article else soup.body.get_text()[:2000]
    except:
        return ""

def resolve_source(url: str) -> SourceInfo:
    domain = url.split("/")[2].replace("www.", "")
    tier = "unknown"
    whitelisted = False
    
    for t, cfg in WHITELIST.items():
        for d in cfg["domains"]:
            if d in domain:
                tier = t
                whitelisted = True
                break
    
    return SourceInfo(url=url, domain=domain, tier=tier, outlet_name=domain, whitelisted=whitelisted)

def gather(queries: List[str], days: int = 3, max_results: int = 5) -> List[RawArticle]:
    client = get_tavily_client()
    all_articles = []
    
    with console.status(f"[bold green]🔍 正在搜索 (范围: 过去{days}天)...[/]") as status:
        for query in queries:
            try:
                # 调用 API
                resp = client.search(
                    query=query, 
                    search_depth="advanced", 
                    topic="news",
                    days=days,               
                    max_results=max_results  
                )
                
                for item in resp.get("results", []):
                    source = resolve_source(item["url"])
                    
                    full_text = ""
                    # 只有白名单才去爬取全文，节省时间
                    if source.whitelisted:
                        full_text = extract_body(item["url"])
                    
                    article = RawArticle(
                        article_id=hashlib.md5(item["url"].encode()).hexdigest(),
                        url=item["url"],
                        title=item["title"],
                        snippet=item["content"],
                        full_text=full_text if len(full_text) > 50 else item["content"],
                        source=source,
                        eligible_for_event=True
                    )
                    all_articles.append(article)
                    
            except Exception as e:
                console.print(f"[red]搜索错误: {e}[/]")

    return all_articles

def print_reader_view(articles: List[RawArticle]):
    """阅读器模式展示"""
    console.print("\n")
    if not articles:
        console.print("[yellow]未找到相关文章。[/]")
        return
        
    for i, art in enumerate(articles, 1):
        color = "green" if art.source.whitelisted else "dim"
        console.print(f"[{color}]{i}. {art.title}[/]")
        console.print(f"   [dim]🔗 {art.url}[/dim]")
