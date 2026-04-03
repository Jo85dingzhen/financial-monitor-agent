# gather_inspector.py
# 采集调试检查器
# 运行一次完整的 gather 流程，并将每篇文章的原始 HTML 和详细信息保存到本地
#
# 输出目录结构：
#   gather_debug/
#   └── YYYYMMDD_HHMMSS/
#       ├── report.html        ← 可在浏览器打开的可视化总报告
#       ├── summary.json       ← 机器可读的完整数据
#       └── html/
#           ├── 01_cls.cn.html
#           ├── 02_caixin.com.html
#           └── ...

import os
import json
import hashlib
import requests
import time
import random
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

# ── 从项目中复用现有模块 ───────────────────────────────────────────────────
try:
    from gather_demo import (
        gather,
        WHITELIST,
        _multi_strategy_search,
        _is_valid_article_url,
        _is_within_days,
        _extract_date_from_url,
        _extract_date_from_text,
        resolve_source,
        _remove_noise_elements,
        _score_text_quality,
        RawArticle,
    )
except ImportError as e:
    raise ImportError(f"无法导入 gather_demo: {e}\n请确保 gather_inspector.py 和 gather_demo.py 在同一目录下。")

try:
    from bs4 import BeautifulSoup
except ImportError:
    raise ImportError("请安装: pip install beautifulsoup4")

# ── 配置 ─────────────────────────────────────────────────────────────────────
OUTPUT_ROOT = Path("gather_debug")

QUERIES = [
    "site:pbc.gov.cn OR site:stats.gov.cn LPR OR MLF OR GDP OR CPI OR PMI OR 降息 OR 降准",
    "site:www.gov.cn OR site:mof.gov.cn OR site:ndrc.gov.cn 财政 OR 专项债 OR 减税 OR 国务院常务会议",
    "site:csrc.gov.cn OR site:nfra.gov.cn 监管 OR 新规 OR 处罚 OR IPO OR 退市 OR 反垄断",
    "site:cls.cn OR site:stcn.com A股 OR 债市 OR 汇率 OR 北向资金 OR ETF OR 国债",
    "site:yicai.com OR site:21jingji.com 新能源 OR 半导体 OR 地产 OR 消费 OR 医保 OR 碳市场 OR AI",
    "site:caixin.com OR site:jiemian.com OR site:cs.com.cn OR site:cnstock.com 深度 OR 政策 OR 财报 OR 并购",
]

SEARCH_DAYS = 3
MAX_RESULTS_PER_QUERY = 5
FETCH_TIMEOUT = 12


# ── 核心：保存原始 HTML ────────────────────────────────────────────────────────
def fetch_and_save_html(url: str, save_path: Path, timeout: int = FETCH_TIMEOUT) -> Dict:
    """
    抓取 URL，将原始 HTML 保存到文件，同时返回解析摘要。

    Returns:
        {
            "success": bool,
            "status_code": int | None,
            "content_type": str,
            "raw_size_bytes": int,
            "text_preview": str,       # 前 500 字的正文预览
            "text_quality_score": float,
            "html_file": str,          # 相对于输出根目录的路径
            "error": str | None
        }
    """
    result = {
        "success": False,
        "status_code": None,
        "content_type": "",
        "raw_size_bytes": 0,
        "text_preview": "",
        "text_quality_score": 0.0,
        "html_file": str(save_path.name),
        "error": None,
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        result["status_code"] = resp.status_code
        result["content_type"] = resp.headers.get("Content-Type", "")
        resp.raise_for_status()

        raw_bytes = resp.content
        result["raw_size_bytes"] = len(raw_bytes)

        # 保存原始 HTML（PDF 也原样保存）
        save_path.write_bytes(raw_bytes)

        # 解析正文预览（仅对 HTML）
        if "text/html" in result["content_type"] or url.endswith((".html", ".htm", ".shtml")):
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(raw_bytes, "html.parser")
            _remove_noise_elements(soup)
            body = soup.find("body")
            if body:
                text = body.get_text(separator=" ", strip=True)
                result["text_quality_score"] = _score_text_quality(text)
                result["text_preview"] = text[:500]

        result["success"] = True

    except requests.exceptions.Timeout:
        result["error"] = f"超时 (>{timeout}s)"
    except requests.exceptions.HTTPError as e:
        result["error"] = f"HTTP {e.response.status_code}"
    except requests.exceptions.RequestException as e:
        result["error"] = str(e)[:120]
    except Exception as e:
        result["error"] = f"未知错误: {str(e)[:100]}"

    return result


# ── 主采集 + 检查逻辑 ─────────────────────────────────────────────────────────
def run_inspection(
    queries: List[str] = QUERIES,
    days: int = SEARCH_DAYS,
    max_results: int = MAX_RESULTS_PER_QUERY,
) -> Path:
    """
    执行完整的采集检查，返回本次输出目录路径。
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_ROOT / timestamp
    html_dir = run_dir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"🔍 gather_inspector 启动")
    print(f"   时间戳   : {timestamp}")
    print(f"   查询数   : {len(queries)}")
    print(f"   时间范围 : {days} 天")
    print(f"   每查询上限: {max_results} 条")
    print(f"   输出目录  : {run_dir}")
    print(f"{'='*60}\n")

    # 调用现有的 gather()，启用全文抓取
    articles = gather(
        queries=queries,
        days=days,
        max_results=max_results,
        save_json=False,
        extract_full_text=True,
        allow_undated_articles=False,
    )

    print(f"\n✅ gather() 完成，共获得 {len(articles)} 篇文章")
    print(f"📥 开始逐篇抓取原始 HTML...\n")

    inspection_records = []

    for idx, art in enumerate(articles, 1):
        safe_domain = art.source.domain.replace(".", "_").replace("/", "_")
        html_filename = f"{idx:02d}_{safe_domain}.html"
        save_path = html_dir / html_filename

        print(f"  [{idx:02d}/{len(articles)}] {art.source.domain}  {art.title[:50]}...")

        # 避免被封禁，随机等待
        time.sleep(0.5 + random.random() * 1.0)

        fetch_info = fetch_and_save_html(art.url, save_path)

        status_icon = "✅" if fetch_info["success"] else "❌"
        print(
            f"         {status_icon} "
            f"{'HTTP ' + str(fetch_info['status_code']) if fetch_info['status_code'] else ''} "
            f"| {fetch_info['raw_size_bytes'] / 1024:.1f} KB"
            f"{' | 质量: ' + str(fetch_info['text_quality_score']) if fetch_info['success'] else ''}"
            f"{' | ERR: ' + fetch_info['error'] if fetch_info['error'] else ''}"
        )

        record = {
            "index": idx,
            "article_id": art.article_id,
            "title": art.title,
            "url": art.url,
            "publish_date": art.publish_date,
            "snippet": art.snippet,
            "full_text_length": len(art.full_text),
            "full_text_preview": art.full_text[:300] if art.full_text else "",
            "source": {
                "domain": art.source.domain,
                "tier": art.source.tier,
                "whitelisted": art.source.whitelisted,
                "outlet_name": art.source.outlet_name,
            },
            "eligible_for_event": art.eligible_for_event,
            "html_fetch": fetch_info,
        }
        inspection_records.append(record)

    # ── 保存 summary.json ──────────────────────────────────────────────────
    summary = {
        "run_timestamp": timestamp,
        "config": {
            "queries": queries,
            "days": days,
            "max_results_per_query": max_results,
        },
        "stats": {
            "total_articles": len(articles),
            "html_fetch_success": sum(1 for r in inspection_records if r["html_fetch"]["success"]),
            "html_fetch_failed": sum(1 for r in inspection_records if not r["html_fetch"]["success"]),
            "avg_text_quality": round(
                sum(r["html_fetch"]["text_quality_score"] for r in inspection_records) / max(len(inspection_records), 1),
                3,
            ),
        },
        "articles": inspection_records,
    }

    summary_path = run_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n💾 summary.json 已保存: {summary_path}")

    # ── 生成 report.html ──────────────────────────────────────────────────
    report_path = run_dir / "report.html"
    _generate_html_report(summary, report_path)
    print(f"📊 report.html 已生成: {report_path}")

    # ── 打印最终统计 ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"📦 采集检查完成")
    print(f"   文章总数        : {summary['stats']['total_articles']}")
    print(f"   HTML 抓取成功   : {summary['stats']['html_fetch_success']}")
    print(f"   HTML 抓取失败   : {summary['stats']['html_fetch_failed']}")
    print(f"   平均正文质量分  : {summary['stats']['avg_text_quality']}")
    print(f"   原始 HTML 目录  : {html_dir}")
    print(f"   可视化报告      : {report_path}")
    print(f"{'='*60}\n")

    return run_dir


# ── HTML 报告生成器 ────────────────────────────────────────────────────────────
def _tier_badge(tier: str) -> str:
    colors = {"tier1": "#c0392b", "tier2": "#2980b9", "unknown": "#7f8c8d"}
    color = colors.get(tier, "#7f8c8d")
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{tier}</span>'


def _status_badge(success: bool, error: Optional[str]) -> str:
    if success:
        return '<span style="color:#27ae60;font-weight:bold">✅ 成功</span>'
    return f'<span style="color:#e74c3c;font-weight:bold">❌ {error or "失败"}</span>'


def _generate_html_report(summary: Dict, output_path: Path):
    """生成可在浏览器直接打开的 HTML 总报告"""
    run_ts = summary["run_timestamp"]
    stats = summary["stats"]
    articles = summary["articles"]
    queries = summary["config"]["queries"]

    # ── 查询列表 ───────────────────────────────────────────────────────────
    query_rows = "".join(
        f'<tr><td style="color:#7f8c8d">{i+1}</td><td><code style="font-size:12px">{q}</code></td></tr>'
        for i, q in enumerate(queries)
    )

    # ── 文章卡片 ───────────────────────────────────────────────────────────
    article_cards = ""
    for rec in articles:
        hf = rec["html_fetch"]
        kb = hf["raw_size_bytes"] / 1024
        html_link = f'<a href="html/{hf["html_file"]}" target="_blank" style="color:#2980b9">打开原始 HTML</a>' if hf["success"] else "—"

        preview_text = (rec["full_text_preview"] or rec["snippet"] or "（无预览）").replace("<", "&lt;").replace(">", "&gt;")
        text_preview_html = (
            f'<details><summary style="cursor:pointer;color:#2980b9">展开正文预览（前300字）</summary>'
            f'<pre style="white-space:pre-wrap;font-size:12px;background:#f8f8f8;padding:10px;border-radius:4px;margin-top:8px">{preview_text}</pre></details>'
            if preview_text != "（无预览）"
            else "<span style='color:#999'>无正文</span>"
        )

        article_cards += f"""
        <div style="border:1px solid #e0e0e0;border-radius:8px;padding:18px;margin-bottom:18px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.06)">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px">
            <div>
              <span style="font-size:18px;color:#bbb;margin-right:6px">#{rec['index']:02d}</span>
              <strong style="font-size:15px">{rec['title']}</strong>
              {_tier_badge(rec['source']['tier'])}
            </div>
            <div>{_status_badge(hf['success'], hf['error'])}</div>
          </div>

          <table style="margin-top:12px;width:100%;font-size:13px;border-collapse:collapse">
            <tr style="background:#f9f9f9">
              <td style="padding:5px 10px;width:120px;color:#555;font-weight:600">来源域名</td>
              <td style="padding:5px 10px">{rec['source']['domain']}</td>
              <td style="padding:5px 10px;width:120px;color:#555;font-weight:600">发布日期</td>
              <td style="padding:5px 10px">{rec['publish_date'] or '<span style="color:#e67e22">未知</span>'}</td>
            </tr>
            <tr>
              <td style="padding:5px 10px;color:#555;font-weight:600">URL</td>
              <td colspan="3" style="padding:5px 10px"><a href="{rec['url']}" target="_blank" style="color:#2980b9;word-break:break-all;font-size:12px">{rec['url']}</a></td>
            </tr>
            <tr style="background:#f9f9f9">
              <td style="padding:5px 10px;color:#555;font-weight:600">全文长度</td>
              <td style="padding:5px 10px">{rec['full_text_length']} 字符</td>
              <td style="padding:5px 10px;color:#555;font-weight:600">eligible</td>
              <td style="padding:5px 10px">{'✅' if rec['eligible_for_event'] else '❌'}</td>
            </tr>
            <tr>
              <td style="padding:5px 10px;color:#555;font-weight:600">HTML 大小</td>
              <td style="padding:5px 10px">{kb:.1f} KB</td>
              <td style="padding:5px 10px;color:#555;font-weight:600">正文质量分</td>
              <td style="padding:5px 10px">{hf['text_quality_score']}</td>
            </tr>
            <tr style="background:#f9f9f9">
              <td style="padding:5px 10px;color:#555;font-weight:600">HTTP 状态</td>
              <td style="padding:5px 10px">{hf['status_code'] or '—'}</td>
              <td style="padding:5px 10px;color:#555;font-weight:600">原始 HTML</td>
              <td style="padding:5px 10px">{html_link}</td>
            </tr>
          </table>

          <div style="margin-top:12px">
            <div style="font-size:12px;color:#555;margin-bottom:4px"><strong>摘要 (snippet):</strong></div>
            <div style="font-size:13px;color:#444;padding:8px;background:#fffde7;border-radius:4px">{(rec['snippet'] or '—').replace('<','&lt;').replace('>','&gt;')}</div>
          </div>

          <div style="margin-top:10px">{text_preview_html}</div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Gather Inspector — {run_ts}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f4f6f9; margin:0; padding:20px; color:#333 }}
    .container {{ max-width:1000px; margin:0 auto }}
    h1 {{ color:#2c3e50; margin-bottom:4px }}
    .meta {{ color:#7f8c8d; font-size:13px; margin-bottom:24px }}
    .stat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-bottom:28px }}
    .stat-box {{ background:#fff; border-radius:8px; padding:16px; text-align:center; box-shadow:0 1px 3px rgba(0,0,0,.08) }}
    .stat-num {{ font-size:32px; font-weight:700; color:#2c3e50 }}
    .stat-label {{ font-size:12px; color:#7f8c8d; margin-top:4px }}
    .section-title {{ font-size:16px; font-weight:700; color:#2c3e50; margin:24px 0 12px; padding-bottom:6px; border-bottom:2px solid #e0e0e0 }}
    table {{ width:100%; border-collapse:collapse }}
    td, th {{ padding:6px 10px; font-size:13px }}
    tr:nth-child(even) {{ background:#f9f9f9 }}
  </style>
</head>
<body>
<div class="container">
  <h1>🔍 Gather Inspector Report</h1>
  <div class="meta">运行时间: {run_ts} &nbsp;|&nbsp; 时间范围: {summary['config']['days']} 天 &nbsp;|&nbsp; 每查询上限: {summary['config']['max_results_per_query']} 条</div>

  <div class="stat-grid">
    <div class="stat-box"><div class="stat-num">{stats['total_articles']}</div><div class="stat-label">采集文章总数</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#27ae60">{stats['html_fetch_success']}</div><div class="stat-label">HTML 抓取成功</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#e74c3c">{stats['html_fetch_failed']}</div><div class="stat-label">HTML 抓取失败</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#2980b9">{stats['avg_text_quality']}</div><div class="stat-label">平均正文质量分</div></div>
    <div class="stat-box"><div class="stat-num">{len(queries)}</div><div class="stat-label">搜索查询数</div></div>
  </div>

  <div class="section-title">📋 搜索查询列表</div>
  <div style="background:#fff;border-radius:8px;padding:14px;margin-bottom:24px;box-shadow:0 1px 3px rgba(0,0,0,.06)">
    <table>{query_rows}</table>
  </div>

  <div class="section-title">📰 采集文章详情（共 {len(articles)} 篇）</div>
  {article_cards if article_cards else '<p style="color:#999">本次未采集到任何文章。</p>'}

</div>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")


# ── 入口 ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_dir = run_inspection(
        queries=QUERIES,
        days=SEARCH_DAYS,
        max_results=MAX_RESULTS_PER_QUERY,
    )
    print(f"✨ 全部完成。请用浏览器打开：\n   {run_dir / 'report.html'}\n")
