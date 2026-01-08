# gather_duck_debug.py
# 调试版：输出每一步执行情况

import sys
import time
import hashlib
from typing import List, Dict, Any

print("=" * 60)
print("🚀 启动 DuckDuckGo 采集器 (调试模式)")
print("=" * 60)

# === 步骤 1: 导入依赖 ===
print("\n[1/7] 导入依赖...")

try:
    from ddgs import DDGS
    print("  ✓ ddgs")
except ImportError as e:
    print(f"  ✗ ddgs 导入失败: {e}")
    sys.exit(1)

try:
    from pydantic import BaseModel
    print("  ✓ pydantic")
except ImportError as e:
    print(f"  ✗ pydantic 导入失败: {e}")
    sys.exit(1)

try:
    import requests
    from bs4 import BeautifulSoup
    print("  ✓ requests, beautifulsoup4")
except ImportError as e:
    print(f"  ✗ requests/bs4 导入失败: {e}")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.table import Table
    console = Console()
    HAS_RICH = True
    print("  ✓ rich")
except ImportError:
    HAS_RICH = False
    console = None
    print("  ⚠ rich 未安装 (可选)")

print("\n✅ 所有依赖导入成功")

# === 步骤 2: 配置 ===
print("\n[2/7] 加载配置...")

WHITELIST = {
    "tier1": {"domains": ["pbc.gov.cn", "mof.gov.cn", "gov.cn", "ndrc.gov.cn"]},
    "tier2": {"domains": ["caixin.com", "cls.cn", "yicai.com"]}
}

print(f"  白名单域名数: {sum(len(v['domains']) for v in WHITELIST.values())}")

# === 步骤 3: 数据模型 ===
print("\n[3/7] 定义数据模型...")

class SourceInfo(BaseModel):
    url: str
    domain: str
    tier: str
    whitelisted: bool

class RawArticle(BaseModel):
    article_id: str
    url: str
    title: str
    snippet: str
    full_text: str = ""
    source: SourceInfo

print("  ✓ 模型定义完成")

# === 步骤 4: 工具函数 ===
print("\n[4/7] 定义工具函数...")

def resolve_source(url: str) -> SourceInfo:
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
    
    return SourceInfo(url=url, domain=domain, tier=tier, whitelisted=whitelisted)

print("  ✓ resolve_source")

# === 步骤 5: 搜索函数 ===
print("\n[5/7] 定义搜索函数...")

def search_simple(query: str, max_results: int = 20) -> List[Dict]:
    """简化版搜索"""
    print(f"\n  🔍 开始搜索: {query}")
    print(f"      参数: max_results={max_results}")
    
    try:
        print("      创建 DDGS 实例...")
        ddgs = DDGS()
        print("      ✓ DDGS 实例创建成功")
        
        print("      调用 ddgs.text()...")
        results = ddgs.text(keywords=query, max_results=max_results)
        print(f"      ✓ ddgs.text() 返回: {type(results)}")
        
        if results is None:
            print("      ⚠ 返回值为 None")
            return []
        
        print("      转换为列表...")
        results_list = list(results)
        print(f"      ✓ 获得 {len(results_list)} 条结果")
        
        return results_list
        
    except Exception as e:
        print(f"      ✗ 搜索异常: {type(e).__name__}: {str(e)[:100]}")
        import traceback
        traceback.print_exc()
        return []

print("  ✓ search_simple")

# === 步骤 6: 主采集函数 ===
print("\n[6/7] 定义主采集函数...")

def gather(queries: List[str], max_per_query: int = 2) -> List[RawArticle]:
    """主采集"""
    print(f"\n📊 开始采集:")
    print(f"   查询数: {len(queries)}")
    print(f"   每查询最多: {max_per_query} 条")
    
    articles = []
    
    for idx, query in enumerate(queries, 1):
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(queries)}] 处理查询: {query}")
        print('='*60)
        
        results = search_simple(query, max_results=30)
        
        if not results:
            print(f"  ✗ 无结果，跳过")
            continue
        
        print(f"\n  📊 原始结果: {len(results)} 条")
        print(f"  开始过滤...")
        
        found = 0
        filtered = 0
        
        for i, item in enumerate(results, 1):
            url = item.get("href", "")
            title = item.get("title", "")
            
            if not url:
                print(f"    [{i}] 跳过: 无 URL")
                continue
            
            source = resolve_source(url)
            
            if not source.whitelisted:
                filtered += 1
                print(f"    [{i}] 过滤: {source.domain}")
                continue
            
            # 去重
            if any(a.url == url for a in articles):
                print(f"    [{i}] 跳过: 重复 URL")
                continue
            
            print(f"    [{i}] ✓ 命中: {source.tier} - {source.domain}")
            print(f"         {title[:60]}...")
            
            article = RawArticle(
                article_id=hashlib.md5(url.encode()).hexdigest(),
                url=url,
                title=title,
                snippet=item.get("body", ""),
                full_text="",
                source=source
            )
            
            articles.append(article)
            found += 1
            
            if found >= max_per_query:
                print(f"\n  ✓ 达到上限 ({max_per_query} 条)，停止")
                break
        
        print(f"\n  📈 统计: 命中 {found}, 过滤 {filtered}")
    
    return articles

print("  ✓ gather")

# === 步骤 7: 执行测试 ===
print("\n[7/7] 开始测试...")
print("="*60)

test_queries = [
    "python programming",           # 通用测试
    "machine learning tutorial"     # 通用测试
]

print(f"\n测试查询: {test_queries}")

try:
    print("\n调用 gather()...")
    articles = gather(test_queries, max_per_query=2)
    
    print("\n" + "="*60)
    print(f"✅ 采集完成: 共 {len(articles)} 条结果")
    print("="*60)
    
    if articles:
        for i, art in enumerate(articles, 1):
            print(f"\n[{i}] {art.title}")
            print(f"    来源: {art.source.domain} ({art.source.tier})")
            print(f"    URL: {art.url[:80]}...")
    else:
        print("\n⚠ 无命中结果")
        print("\n可能原因:")
        print("1. 搜索结果中没有白名单域名")
        print("2. 白名单配置过于严格")
        print("3. DuckDuckGo 返回结果质量问题")

except Exception as e:
    print(f"\n❌ 采集过程出错:")
    print(f"   错误类型: {type(e).__name__}")
    print(f"   错误信息: {str(e)}")
    import traceback
    print("\n完整堆栈:")
    traceback.print_exc()

print("\n" + "="*60)
print("🏁 程序结束")
print("="*60)