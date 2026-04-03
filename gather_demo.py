# gather_demo.py
# Module A: DuckDuckGo News Gatherer
# Compatible with main.py's Financial Monitor Agent

import hashlib
import json
import random
import time
import re
from datetime import datetime, timezone, timedelta
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

# === 数据模型（统一从 models.py 导入，避免类型不一致导致 Pydantic 校验失败） ===
try:
    from models import SourceInfo, RawArticle
except ImportError:
    from pydantic import BaseModel
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
        publish_date: str = ""

# 最近一次采集的时间过滤数组（调试用）
LAST_TIME_FILTERED_ITEMS: List[Dict[str, str]] = []

# === 工具函数 ===
def _log(msg: str, level: str = "info"):
    """内部日志（可选 Rich）"""
    if HAS_RICH and console:
        colors = {"info": "cyan", "success": "green", "warning": "yellow", 
                 "error": "red", "debug": "dim"}
        console.print(f"[{colors.get(level, 'white')}]{msg}[/]")
    else:
        print(msg)

def _is_valid_article_url(url: str, title: str, snippet: str) -> tuple[bool, str]:
    """
    URL 质量过滤（四层防线）：
      Layer 1 — 全局污染检测：查询参数/标题含垃圾内容 → 直接拒绝
      Layer 2 — 全局非文章路径：首页/搜索/列表/数据查询页 → 直接拒绝
      Layer 3 — 域名专属路径白名单：tier1 政府域名只接受已知合法路径格式
      Layer 4 — 内容相关性：标题/摘要须含至少 1 个金融/经济关键词

    返回 (is_valid, reject_reason)
    """
    import re
    from urllib.parse import urlparse, unquote

    parsed        = urlparse(url)
    domain        = parsed.netloc.lower().replace("www.", "")
    path          = parsed.path
    path_lower    = path.lower()
    query_decoded = unquote(parsed.query).lower()
    combined_text = (title + " " + snippet).lower()

    # ── Layer 1：全局污染检测 ───────────────────────────────────────
    POLLUTION_SIGNALS = (
        # 已知污染域名后缀混入查询参数
        "chachawa", ".top", ".xyz", ".cc", ".vip", ".pw",
        # 垃圾内容关键词
        "社工库", "骚操作", "司法冻结", "查询在线", "你懂的",
        "技巧", "破解", "黑客", "赌博", "博彩",
    )
    for sig in POLLUTION_SIGNALS:
        if sig in query_decoded:
            return False, f"Layer1-查询参数污染: {sig}"
        if sig in combined_text:
            return False, f"Layer1-标题/摘要污染: {sig}"

    # ── Layer 2：全局非文章路径 ─────────────────────────────────────
    # 路径为空 = 首页
    path_parts = [p for p in path_lower.split("/") if p]
    if not path_parts:
        return False, "Layer2-首页URL"

    # 明确的非文章路径前缀
    NON_ARTICLE_PREFIXES = (
        "/search", "/easyquery",          # 搜索/查询页
        "/list", "/category", "/tag",     # 列表/分类页
        "/sitemap", "/rss",               # 站点地图/订阅
    )
    for prefix in NON_ARTICLE_PREFIXES:
        if path_lower.startswith(prefix):
            return False, f"Layer2-非文章路径: {path_lower[:50]}"

    # 纯目录末尾（如 /english/PressRelease/ 末尾是 /，无文件名）
    # 合法文章 URL 末尾通常是 .html / .htm / .shtml / .aspx
    ARTICLE_EXTENSIONS = (".html", ".htm", ".shtml", ".aspx", ".php", ".jsp")
    has_article_ext = any(path_lower.endswith(ext) for ext in ARTICLE_EXTENSIONS)
    # 允许末尾无扩展名但路径有日期段（部分现代新闻URL）
    has_date_in_path = bool(re.search(r'/20\d{2}[/-]\d{2}', path_lower)
                            or re.search(r'/20\d{6}/', path_lower))
    if not has_article_ext and not has_date_in_path:
        return False, f"Layer2-疑似列表页(无文章扩展名且无日期路径): {path_lower[:60]}"

    # ── Layer 3：tier1 政府域名专属白名单 ──────────────────────────
    # 合法政府文章 URL 特征：路径含 tYYYYMMDD_ 或 YYYYMM 目录
    GOV_ARTICLE_PATTERNS = [
        r"/t\d{8}_\d+\.(html|htm|shtml)$",   # 最常见: tYYYYMMDD_ID.html
        r"/\d{8}_\d+\.(html|htm|shtml)$",    # 另一种政府格式
        r"/20\d{6}/",                          # 含 YYYYMM 目录
        r"/20\d{2}-\d{2}-\d{2}/",             # 含 YYYY-MM-DD 目录
        r"/\d{4}/\d{2}/",                      # /YYYY/MM/ 目录
    ]

    GOV_DOMAINS = {
        "pbc.gov.cn", "mof.gov.cn", "ndrc.gov.cn",
        "stats.gov.cn", "csrc.gov.cn", "nfra.gov.cn",
        "safe.gov.cn", "gov.cn",
    }

    is_gov = any(d in domain for d in GOV_DOMAINS)
    if is_gov:
        matched = any(re.search(pat, path_lower) for pat in GOV_ARTICLE_PATTERNS)
        if not matched:
            return False, f"Layer3-政府域名但路径不符合文章格式: {path_lower[:60]}"

    # ── Layer 4：内容相关性（标题或摘要须含金融/经济词）────────────
    FINANCE_KW = (
        "gdp", "cpi", "ppi", "pmi", "lpr", "mlf", "降息", "降准",
        "经济", "金融", "财政", "货币", "利率", "通胀", "通缩",
        "股市", "债券", "汇率", "人民币", "a股", "外汇",
        "统计", "数据", "增长", "政策", "监管", "证监会", "银行",
        "制造业", "消费", "就业", "贸易", "进出口", "投资",
    )
    has_finance = any(kw in combined_text for kw in FINANCE_KW)
    if not has_finance:
        return False, f"Layer4-标题/摘要不含金融经济关键词: {title[:40]}"

    return True, ""


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


def _title_similarity(title_a: str, title_b: str) -> float:
    """
    基于字符级 bigram Jaccard 相似度计算两个标题的相似度（0.0–1.0）。
    用于检测转载重复：同一新闻被不同媒体以微调标题转载。

    选择 bigram Jaccard 的原因：
    - 无需分词，对中文天然友好
    - 对词序变化鲁棒（"央行降准" vs "降准：央行宣布"）
    - 计算开销极低（O(n) 集合操作）
    """
    def bigrams(s: str):
        s = re.sub(r'\s+', '', s)   # 去除所有空格
        return set(s[i:i+2] for i in range(len(s) - 1))

    set_a = bigrams(title_a)
    set_b = bigrams(title_b)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union        = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _is_near_duplicate(
    new_title: str,
    existing_articles: list,
    threshold: float = 0.72,
) -> tuple[bool, str]:
    """
    检查新文章标题是否与已采集文章标题高度相似（转载去重）。

    Args:
        new_title:         当前待加入文章的标题
        existing_articles: 已采集的 RawArticle 列表
        threshold:         Jaccard 相似度阈值（0.72 = 约 72% bigram 重叠视为重复）
                           可调范围建议 0.65–0.80：越低越激进去重

    Returns:
        (is_duplicate, reason_str)
    """
    for art in existing_articles:
        sim = _title_similarity(new_title, art.title)
        if sim >= threshold:
            return True, (
                f"标题重复(Jaccard={sim:.2f}) "
                f"已有: 「{art.title[:30]}」"
            )
    return False, ""


def _extract_pdf_text(pdf_content: bytes, url: str) -> str:
    """
    从 PDF 内容中提取文本

    Args:
        pdf_content: PDF 文件的字节内容
        url: PDF 的 URL（用于日志）

    Returns:
        提取的文本，失败则返回空字符串
    """
    try:
        # 尝试使用 PyPDF2
        from PyPDF2 import PdfReader
        from io import BytesIO

        pdf_file = BytesIO(pdf_content)
        reader = PdfReader(pdf_file)

        text_parts = []
        # 限制最多读取前 50 页
        max_pages = min(50, len(reader.pages))

        for page_num in range(max_pages):
            page = reader.pages[page_num]
            text = page.extract_text()
            if text:
                text_parts.append(text)

        full_text = '\n'.join(text_parts)

        # 清理空白字符
        full_text = ' '.join(full_text.split())

        # 限制长度
        max_length = 50000
        if len(full_text) > max_length:
            full_text = full_text[:max_length]

        _log(f"      ✓ PDF 文本已提取 ({len(full_text)} 字符, {max_pages} 页)", "debug")
        return full_text

    except ImportError:
        _log(f"      ⚠ PyPDF2 未安装，跳过 PDF: {url[:60]}", "debug")
        _log(f"      💡 提示: pip install PyPDF2", "debug")
        return ""
    except Exception:
        _log(f"      ⚠ PDF 解析失败: {url[:60]}", "debug")
        return ""


def _remove_noise_elements(soup) -> None:
    """
    从 BeautifulSoup 树中移除所有噪声元素。
    涵盖三类污染源：
      1. 网页噪声：广告、导航、评论区、侧边栏、社交分享按钮
      2. 结构噪声：面包屑、推荐阅读、版权声明区块
      3. 动态占位：script/style/noscript
    """
    # --- 标签名级别 ---
    NOISE_TAGS = [
        "script", "style", "noscript",
        "nav", "header", "footer",
        "aside",                        # 侧边栏
        "iframe", "embed", "object",    # 内嵌媒体
        "figure",                       # 图片容器（只保留文字）
    ]
    for tag in NOISE_TAGS:
        for el in soup.find_all(tag):
            el.decompose()

    # --- class / id 关键词级别（广告、评论、推荐、导航等） ---
    NOISE_PATTERNS = [
        # 广告
        "ad", "ads", "advert", "advertisement", "sponsor", "promo",
        "guanggao",                     # 拼音：广告
        # 导航 / 菜单
        "nav", "menu", "breadcrumb", "bread-crumb", "crumb",
        "sidebar", "side-bar", "widget",
        # 评论区
        "comment", "comments", "disqus", "reply", "replies",
        "pinglun",                      # 拼音：评论
        # 相关推荐 / 热门文章
        "related", "recommend", "recommended", "hot-news", "hot_news",
        "tuijian", "jingxuan",          # 拼音：推荐、精选
        # 社交分享
        "share", "social", "follow", "subscribe",
        # 版权 / 免责
        "copyright", "disclaimer", "statement",
        # 标签云 / 作者信息
        "tags", "tag-list", "author-info", "byline",
        # 页脚类内容
        "footer", "foot",
    ]

    import re as _re
    pattern = _re.compile(
        r'\b(' + '|'.join(_re.escape(p) for p in NOISE_PATTERNS) + r')\b',
        _re.IGNORECASE
    )
    for el in soup.find_all(True):
        cls = ' '.join(el.get('class', []))
        eid = el.get('id', '')
        if pattern.search(cls) or pattern.search(eid):
            el.decompose()


def _score_text_quality(text: str) -> float:
    """
    对提取到的文本进行质量评分 (0.0 – 1.0)。
    综合三个维度：
      1. 中文字符占比（财经正文以中文为主）
      2. 平均句子长度（正文句子较长，导航/标签短句多）
      3. 有效字符密度（去除空白后的比例）
    """
    if not text or len(text) < 50:
        return 0.0

    import re as _re

    # 1. 中文字符占比
    chinese_chars = len(_re.findall(r'[\u4e00-\u9fff]', text))
    chinese_ratio = chinese_chars / max(len(text), 1)

    # 2. 平均句子长度（以句号/换行分割）
    sentences = [s.strip() for s in _re.split(r'[。\n！？]', text) if len(s.strip()) > 5]
    avg_sent_len = sum(len(s) for s in sentences) / max(len(sentences), 1)
    # 正文句子通常 20–100 字；导航/标签往往 < 10 字
    sent_score = min(1.0, avg_sent_len / 40)

    # 3. 有效字符密度
    non_space = len(text.replace(' ', '').replace('\n', ''))
    density = non_space / max(len(text), 1)

    # 加权合成
    score = 0.5 * chinese_ratio + 0.3 * sent_score + 0.2 * density
    return round(min(1.0, score), 3)


def fetch_full_text(url: str, timeout: int = 10) -> str:
    """
    抓取网页完整正文（支持 HTML 和 PDF）。

    改进点（对应三类数据污染问题）：
      1. 网页噪声：_remove_noise_elements() 移除广告/评论/导航/侧边栏等
      2. 正文定位：扩充中文财经媒体专用 CSS 选择器，按质量分取最优区块
      3. 内容质量：_score_text_quality() 评分，低质量内容降级为 snippet

    Args:
        url:     网页 URL
        timeout: HTTP 超时（秒）

    Returns:
        清洗后的正文文本，失败返回空字符串
    """
    try:
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        }

        response = requests.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        # PDF 分支
        content_type = response.headers.get('Content-Type', '').lower()
        is_pdf = url.lower().endswith('.pdf') or 'application/pdf' in content_type
        if is_pdf:
            return _extract_pdf_text(response.content, url)

        response.encoding = response.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(response.content, 'html.parser')

        # ── 第一步：噪声元素清除 ──────────────────────────────────
        _remove_noise_elements(soup)

        # ── 第二步：候选正文区块提取（按优先级排序）──────────────
        # 覆盖：政府网站 / 通用新闻 / 中文财经媒体专用选择器
        ARTICLE_SELECTORS = [
            # 政府网站
            (".TRS_Editor",       "class"),   # 国家统计局、央行等
            (".pages_content",    "class"),   # gov.cn 通用
            (".article",          "class"),
            # HTML5 语义标签
            ("article",           "tag"),
            ("main",              "tag"),
            # 通用正文容器
            ("#article-content",  "id"),
            ("#content",          "id"),
            ("#main-content",     "id"),
            (".article-content",  "class"),
            (".article-body",     "class"),
            (".post-content",     "class"),
            (".entry-content",    "class"),
            (".detail-content",   "class"),
            (".news-content",     "class"),
            (".main-content",     "class"),
            (".content",          "class"),
            # 中文财经媒体专用
            (".article__content", "class"),   # 财新
            (".article-text",     "class"),   # 界面/第一财经
            (".text",             "class"),   # 21世纪经济
            (".newsContent",      "class"),   # 证券时报
            (".am-article-bd",    "class"),   # 财联社
            (".detailContent",    "class"),   # 东方财富
            (".Body",             "class"),   # 新华社英文
        ]

        candidates = []
        for selector, sel_type in ARTICLE_SELECTORS:
            if sel_type == "tag":
                elements = soup.find_all(selector)
            elif sel_type == "class":
                elements = soup.find_all(class_=selector.lstrip("."))
            else:  # id
                el = soup.find(id=selector.lstrip("#"))
                elements = [el] if el else []

            for el in elements:
                if el is None:
                    continue
                text = el.get_text(separator=' ', strip=True)
                if len(text) > 150:
                    score = _score_text_quality(text)
                    candidates.append((score, text))

        # 取质量最高的候选
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best_score, text_content = candidates[0]
            _log(f"      ✓ 正文候选 {len(candidates)} 个，最优质量分: {best_score:.2f}", "debug")
        else:
            # Fallback：整个 body
            body = soup.find('body')
            text_content = body.get_text(separator=' ', strip=True) if body else ""
            best_score = _score_text_quality(text_content)
            _log(f"      ⚠ 未命中正文选择器，使用 body（质量分: {best_score:.2f}）", "debug")

        # ── 第三步：文本后处理 ────────────────────────────────────
        # 合并多余空白
        import re as _re
        text_content = _re.sub(r'\s{3,}', '  ', text_content)
        text_content = ' '.join(text_content.split())

        # 截断
        MAX_LENGTH = 50_000
        if len(text_content) > MAX_LENGTH:
            text_content = text_content[:MAX_LENGTH]

        # 质量过低时返回空（让系统降级用 snippet）
        if best_score < 0.15 and len(text_content) < 300:
            _log(f"      ⚠ 正文质量过低 ({best_score:.2f})，丢弃", "debug")
            return ""

        return text_content

    except requests.exceptions.Timeout:
        _log(f"    ⏱ 抓取超时: {url[:60]}", "debug")
        return ""
    except requests.exceptions.RequestException as e:
        _log(f"    ✗ 抓取失败: {str(e)[:50]}", "debug")
        return ""
    except Exception as e:
        _log(f"    ✗ 解析失败: {str(e)[:50]}", "debug")
        return ""

# === 搜索策略 ===

def _parse_article_date(date_str: str) -> Optional[datetime]:
    """将日期字符串解析为 datetime（UTC），支持多种格式"""
    if not date_str:
        return None
    # 优先用 email.utils 解析 RFC 2822（Mon, 23 Feb 2026 10:30:00 +0000）
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # ISO 格式变体
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _extract_date_from_url(url: str) -> str:
    """
    从 URL 路径中提取发布日期（YYYY-MM-DD），适用于政府网站。
    示例：
      /202207/t20220726_1331315.html → 2022-07-26
      /szyw/202209/t20220923_1336230.html → 2022-09-23
      /2022/07/content_123.html → 2022-07-01
    """
    # 最精确：tYYYYMMDD_ 模式（政府网站正文链接）
    m = re.search(r't(\d{4})(\d{2})(\d{2})[_/]', url)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        if 2000 <= int(y) <= 2035 and 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            return f"{y}-{mo}-{d}"
    # /YYYYMM/ 模式
    m = re.search(r'/(\d{4})(\d{2})/', url)
    if m:
        y, mo = m.group(1), m.group(2)
        if 2000 <= int(y) <= 2035 and 1 <= int(mo) <= 12:
            return f"{y}-{mo}-01"
    # /YYYY/MM/ 模式
    m = re.search(r'/(\d{4})/(\d{2})/', url)
    if m:
        y, mo = m.group(1), m.group(2)
        if 2000 <= int(y) <= 2035 and 1 <= int(mo) <= 12:
            return f"{y}-{mo}-01"
    return ""

def _extract_date_from_text(text: str) -> str:
    """
    从文本中提取日期（优先返回最新日期，格式 YYYY-MM-DD）。
    支持：
      - 3 days ago / 5 hours ago / 2 weeks ago
      - 2026-02-20 / 2026/02/20 / 2026.02.20
      - 2026年2月20日
    """
    if not text:
        return ""

    now_utc = datetime.now(timezone.utc)
    candidates: List[datetime] = []

    # 相对时间（英文）
    for n, unit in re.findall(r'(\d+)\s*(hour|hours|day|days|week|weeks|month|months)\s+ago', text, flags=re.IGNORECASE):
        val = int(n)
        unit = unit.lower()
        if "hour" in unit:
            dt = now_utc - timedelta(hours=val)
        elif "day" in unit:
            dt = now_utc - timedelta(days=val)
        elif "week" in unit:
            dt = now_utc - timedelta(weeks=val)
        else:
            # month 按 30 天近似
            dt = now_utc - timedelta(days=val * 30)
        candidates.append(dt)

    # 相对时间（中文）
    for n in re.findall(r'(\d+)\s*天前', text):
        candidates.append(now_utc - timedelta(days=int(n)))

    # 绝对时间（YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD）
    for y, mo, d in re.findall(r'(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})', text):
        try:
            dt = datetime(int(y), int(mo), int(d), tzinfo=timezone.utc)
            candidates.append(dt)
        except ValueError:
            continue

    # 绝对时间（YYYY年M月D日）
    for y, mo, d in re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', text):
        try:
            dt = datetime(int(y), int(mo), int(d), tzinfo=timezone.utc)
            candidates.append(dt)
        except ValueError:
            continue

    if not candidates:
        return ""

    # 取最新日期，减少列表页中旧日期误命中的概率
    best = max(candidates)
    return best.strftime("%Y-%m-%d")


def _is_within_days(date_str: str, days: int, allow_undated: bool = True) -> bool:
    """判断文章日期是否在 days 天以内；可配置是否放行无日期/不可解析日期"""
    if not date_str:
        return allow_undated
    dt = _parse_article_date(date_str)
    if dt is None:
        return allow_undated
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return dt >= cutoff


def _search_ddgs_news(query: str, timelimit: Optional[str] = None, fetch_count: int = 30) -> List[Dict]:
    """
    使用 ddgs.news() 搜索，返回带 date 字段的结果。
    字段统一为 {href, title, body, date}（与 text() 格式对齐）
    """
    try:
        ddgs = DDGS()
        kwargs = {"max_results": fetch_count}
        if timelimit:
            kwargs["timelimit"] = timelimit
        results = ddgs.news(query, **kwargs)
        if results is None:
            return []
        # news() 返回字段: url / title / body / date / source
        # 统一映射为 href / title / body / date
        normalized = []
        for r in results:
            normalized.append({
                "href":  r.get("url", ""),
                "title": r.get("title", ""),
                "body":  r.get("body", ""),
                "date":  r.get("date", ""),
            })
        return normalized
    except Exception as e:
        _log(f"新闻搜索异常: {str(e)[:100]}", "error")
        return []


def _search_ddgs_text(query: str, region: str = 'wt-wt', timelimit: Optional[str] = None,
                      fetch_count: int = 30) -> List[Dict]:
    """底层 DuckDuckGo text 搜索（无 date 字段）"""
    try:
        ddgs = DDGS()
        if timelimit:
            results = ddgs.text(query, region=region, timelimit=timelimit, max_results=fetch_count)
        else:
            results = ddgs.text(query, region=region, max_results=fetch_count)
        if results is None:
            return []
        return [{"href": r.get("href",""), "title": r.get("title",""), "body": r.get("body",""), "date": ""}
                for r in results]
    except Exception as e:
        _log(f"搜索异常: {str(e)[:100]}", "error")
        return []


def _multi_strategy_search(query: str, days: int = 7, fetch_count: int = 30) -> tuple[List[Dict], str]:
    """
    多策略搜索（带重试和回退）
    策略A: ddgs.news()（有日期，时效最好）
    策略B: ddgs.text() + timelimit
    策略C: ddgs.text() 无限制（最后兜底）

    Returns:
        (results, strategy_path)
    """
    # 根据天数确定粗粒度时间限制
    if days <= 1:
        timelimit = 'd'
    elif days <= 7:
        timelimit = 'w'
    elif days <= 30:
        timelimit = 'm'
    else:
        timelimit = None

    strategy_path = []

    # site: 限域查询（如 site:pbc.gov.cn）在 DDG 新闻索引中无收录，直接跳到策略B
    is_site_query = "site:" in query.lower()

    # 策略A: ddgs.news()（返回日期，精度最高）——仅对非 site: 查询尝试
    if not is_site_query:
        strategy_path.append(f"A-news(时限:{timelimit or '无'})")
        for attempt in range(2):
            results = _search_ddgs_news(query, timelimit=timelimit, fetch_count=fetch_count)
            if results:
                return results, "→".join(strategy_path)
            if attempt < 1:
                time.sleep(1 + random.random())

    # 策略B: ddgs.text() + timelimit
    if timelimit:
        strategy_path.append(f"B-text(时限:{timelimit})")
        results = _search_ddgs_text(query, timelimit=timelimit, fetch_count=fetch_count)
        if results:
            return results, "→".join(strategy_path)

    # 策略C: ddgs.text() 无限制（兜底）
    strategy_path.append("C-text(无时限)")
    results = _search_ddgs_text(query, fetch_count=fetch_count)
    if results:
        return results, "→".join(strategy_path)

    return [], "→".join(strategy_path) + "(失败)"

# === 主采集函数（对外接口） ===
def gather(queries: List[str], days: int = 3, max_results: int = 5,
          save_json: bool = False, output_path: str = "gathered_results.json",
          extract_full_text: bool = True,  # 新增参数
          allow_undated_articles: bool = True,  # 新增参数：是否允许无日期文章
          max_time_filter_records: int = 500,  # 新增参数：时间过滤数组最大保留条数
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
        extract_full_text: 是否抓取网页完整内容（默认True，建议开启以支持验证）
        allow_undated_articles: 是否放行缺少日期或日期不可解析的文章（默认 True 保持兼容）
        max_time_filter_records: 时间过滤数组最大保留条数（避免内存增长）
        **kwargs: 预留扩展参数（如 proxy 等）

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
        "strategy_paths": {},
        "time_filtered_items": []
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
            pub_date = item.get("date", "")

            if not url or not title:
                continue

            # URL 质量过滤：剔除首页/搜索页/污染链接
            is_valid, reject_reason = _is_valid_article_url(url, title, snippet)
            if not is_valid:
                filtered += 1
                _log(f"    - URL质量过滤: {reject_reason}", "debug")
                continue

            # 如果 search API 没有返回日期，尝试从 URL 路径中提取
            if not pub_date:
                pub_date = _extract_date_from_url(url)
            # 仍无日期时，尝试从标题/摘要中提取（如 "3 days ago", "2026-02-20"）
            if not pub_date:
                pub_date = _extract_date_from_text(f"{title} {snippet}")

            # 日期过滤：可配置是否放行无日期文章
            if not _is_within_days(pub_date, days, allow_undated=allow_undated_articles):
                filtered += 1
                date_label = pub_date[:10] if pub_date else "NO_DATE"
                _log(f"    - 日期过滤({date_label}): {title[:40]}", "debug")
                if len(stats["time_filtered_items"]) < max_time_filter_records:
                    stats["time_filtered_items"].append({
                        "query": query,
                        "title": title,
                        "url": url,
                        "publish_date": date_label,
                        "reason": "NO_DATE" if date_label == "NO_DATE" else "OUT_OF_RANGE",
                        "days_limit": str(days)
                    })
                continue

            source = resolve_source(url)

            # 白名单过滤
            if not source.whitelisted:
                filtered += 1
                if filtered <= 3:
                    _log(f"    - 过滤: {source.domain}", "debug")
                continue

            # URL 精确去重
            if any(a.url == url for a in articles):
                continue

            # 标题相似度去重（拦截不同媒体的转载）
            is_dup, dup_reason = _is_near_duplicate(title, articles)
            if is_dup:
                filtered += 1
                _log(f"    - 转载去重: {dup_reason}", "debug")
                continue

            _log(f"    ✓ 命中: {source.tier} - {source.domain} {('(' + pub_date[:10] + ')') if pub_date else ''}", "success")
            _log(f"      {title[:60]}...", "debug")

            # 抓取完整网页内容（如果启用）
            full_text = ""
            if extract_full_text:
                _log(f"      🌐 正在抓取全文...", "debug")
                full_text = fetch_full_text(url, timeout=10)
                if full_text:
                    _log(f"      ✓ 全文已获取 ({len(full_text)} 字符)", "debug")
                else:
                    _log(f"      ⚠ 全文抓取失败，使用 snippet", "debug")

            # 构造 RawArticle
            article = RawArticle(
                article_id=hashlib.md5(url.encode()).hexdigest(),
                url=url,
                title=title,
                snippet=snippet,
                full_text=full_text,
                source=source,
                eligible_for_event=True,
                publish_date=pub_date[:10] if pub_date else ""  # 存 YYYY-MM-DD
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
    _log(f"  时间过滤数组: {len(stats['time_filtered_items'])}", "info")
    _log(f"  命中白名单: {stats['total_hits']}", "info")
    _log(f"{'='*60}", "info")

    # 更新最近一次采集的时间过滤数组（供上层读取）
    global LAST_TIME_FILTERED_ITEMS
    LAST_TIME_FILTERED_ITEMS = list(stats["time_filtered_items"])
    
    # 可选：保存 JSON
    if save_json and articles:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump([art.model_dump() for art in articles], f, ensure_ascii=False, indent=2)
            _log(f"💾 已保存: {output_path}", "success")
        except Exception as e:
            _log(f"⚠ 保存失败: {e}", "warning")
    
    return articles

def get_last_time_filtered_items() -> List[Dict[str, str]]:
    """获取最近一次 gather() 产生的时间过滤数组"""
    return list(LAST_TIME_FILTERED_ITEMS)

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
