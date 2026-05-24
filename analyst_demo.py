# analyst_demo.py
# Module B: The Analyst (Two-Phase Clustering Edition)
# 架构: TF-IDF预分组 + LLM精聚类
# 评分: 结构分(50%来源+25%覆盖+25%类别) 动态融合 LLM语义分

import os
import json
import math
import hashlib
from typing import List, Optional

try:
    from openai import OpenAI
    from rich.console import Console
    from rich.panel import Panel
    from rich.tree import Tree
    from rich import box
    console = Console()
except ImportError:
    print("❌ 缺少依赖，请 pip install openai rich")
    exit()

try:
    from models import RawArticle
except ImportError:
    exit()

# 从 models 统一导入 Event（避免重复定义）
try:
    from models import Event
except ImportError:
    from pydantic import BaseModel
    class Event(BaseModel):
        event_id: str
        main_title: str
        summary: str
        score: float
        articles: List[RawArticle]
        primary_category: str
        secondary_category: str = ""
        detail: dict = {}

# =======================
# 配置参数（顶部统一管理）
# =======================
TFIDF_SIM_THRESHOLD     = 0.22   # TF-IDF预分组相似度阈值（越低越容易合并）
TFIDF_MAX_FEATURES      = 800    # TF-IDF词汇表大小
MAX_GROUP_SIZE_FOR_LLM  = 12     # 单次LLM精聚类最大文章数
COVERAGE_LOG_SCALE      = 3.5    # 覆盖面对数归一化系数
ALPHA_WITH_TIER1        = (0.65, 0.35)  # 有tier1来源时（结构权重, LLM权重）
ALPHA_WITHOUT_TIER1     = (0.35, 0.65)  # 无tier1来源时（结构权重, LLM权重）
TIER1_BONUS_PER_ARTICLE = 0.3    # 每篇tier1文章加成分数，上限1.0

# =======================
# 一级分类体系（与 clustering taxonomy_0204.docx Table 1 对齐）
# =======================
TAXONOMY_DEFINITIONS = {
    "macro": {
        "name": "宏观经济 & 政策 (Macro)",
        "desc": "涉及国家级经济政策或宏观数据：GDP/CPI/PPI/PMI/LPR/MLF/降息/降准/财政预算/专项债/进出口/就业/稳增长/政治局会议/国务院常务会议等。",
        "keywords": "GDP, CPI, PPI, PMI, LPR, MLF, 降息, 降准, 财政, 专项债, 减税, 补贴, 社零, 进出口, 失业率, 稳增长, 政治局会议, 国务院, 财政赤字, 公开市场操作",
        "base_score": 10.0,
    },
    "regulation": {
        "name": "金融监管 (Regulation)",
        "desc": "金融监管部门（证监会/银保监/金监总局/交易所）发布的规则、公告、罚单、IPO审核、反垄断调查等。",
        "keywords": "证监会, 银保监, 金监总局, 国家金融监督管理总局, 交易所, 新规, 罚单, 问询函, IPO, 退市, 反垄断, TLAC, 银行监管, 支付牌照, 数字货币, CBDC, 并购审查",
        "base_score": 9.0,
    },
    "market": {
        "name": "资本市场 (Market)",
        "desc": "资本市场行情类事件：A股/港股指数涨跌、债市、汇率、北向资金、ETF、大宗商品期货价格等，不涉及单一公司。",
        "keywords": "A股, 上证指数, 沪深300, 港股, 恒生指数, 债市, 国债, 信用债, 汇率, 人民币, 北向资金, 南向资金, ETF, 国债收益率, 信用利差, 波动率, 融资融券, 原油, 铜, 铁矿石, 大宗商品, 期货, 期权",
        "base_score": 8.0,
    },
    "industry": {
        "name": "行业动态 (Industry)",
        "desc": "涉及某一行业的政策或整体趋势（非单一公司）：新能源/半导体/地产政策/消费升级/医保/碳市场等行业面事件。",
        "keywords": "新能源, 光伏, 风电, 半导体, 芯片, 地产, 限购, 限贷, 消费, 以旧换新, AI, 数字经济, 碳市场, 医保, 带量采购, 仿制药, 创新药, 开工率, 产能, REITs, 铁路, 民航, 物流",
        "base_score": 7.0,
    },
    "company": {
        "name": "公司事件 (Company)",
        "desc": "单一公司或少量公司的微观事件：财报/业绩预告/并购重组/高管变动/违规处罚/IPO申请等。",
        "keywords": "财报, 年报, 半年报, 季报, 业绩预告, 并购重组, 资产剥离, 控股权, 借壳, 回购, 定增, 违约, 诉讼, 财务造假, 内幕交易, 信息披露违规, 涨停, 人事变动, 董事长, CEO, IPO申请, 注册, 首发",
        "base_score": 5.0,
    },
    "other": {
        "name": "杂项 (Other)",
        "desc": "传闻、小作文、情绪化标题、无权威来源的低质信息，或以上五类均不适用的内容。",
        "keywords": "传闻, 小作文, 观点, 据悉, 消息人士",
        "base_score": 5.0,
    },
}

# =======================
# 二级分类体系（与 clustering taxonomy_0204.docx Table 2 完整对齐）
# =======================
SECONDARY_CATEGORIES = {
    "macro":      ["monetary_policy", "fiscal_policy", "economic_data", "trade", "international"],
    "regulation": ["securities", "banking", "insurance", "fintech", "antitrust"],
    "market":     ["equity", "bond", "fx", "commodity", "derivative"],
    "industry":   ["energy", "tech", "consumer", "real_estate", "financial_sector", "healthcare", "transport"],
    "company":    ["earnings", "restructuring", "personnel", "violation", "ipo"],
    "other":      [],
}

# 二级分类说明（用于 LLM 提示词，帮助精准分类）
SECONDARY_CATEGORY_DESC = {
    "monetary_policy":  "央行政策利率调整、存准率变动、公开市场操作（MLF/OMO）、LPR变动",
    "fiscal_policy":    "财政赤字目标、地方政府专项债、减税降费、补贴政策",
    "economic_data":    "GDP/CPI/PPI/PMI/社会消费品零售/固定资产投资/外贸数据发布",
    "trade":            "进出口数据、贸易摩擦、关税政策、汇率干预",
    "international":    "美联储/ECB等境外央行政策、G7/G20峰会经济议题",
    "securities":       "证监会公告、上交所/深交所规则修订、IPO/再融资审批、退市政策",
    "banking":          "银行资本金要求、存款准备金、银行违规处罚、TLAC规则",
    "insurance":        "保险产品监管、偿付能力规则、险资投资比例调整",
    "fintech":          "支付牌照、互联网贷款、数字货币（CBDC）监管、数据合规",
    "antitrust":        "平台经济反垄断、并购审查、数据垄断调查",
    "equity":           "A股/港股指数涨跌、北向/南向资金、融资融券、大宗交易",
    "bond":             "国债/地方债/信用债发行与收益率变化、信用利差、违约事件",
    "fx":               "人民币汇率、中间价机制、外汇储备、跨境资本流动",
    "commodity":        "原油/铜/铁矿石/农产品期货价格、大宗商品供需",
    "derivative":       "股指期货/期权、利率互换、信用违约互换（CDS）",
    "energy":           "新能源政策、光伏/风电装机、煤炭保供、电价改革、碳市场",
    "tech":             "半导体/AI/数字经济政策、科技出口管制、芯片投资",
    "consumer":         "消费刺激政策、家电/汽车以旧换新、电商平台趋势",
    "real_estate":      "限购/限贷松绑、二手房指导价、开发商融资、REITs",
    "financial_sector": "银行息差、保险投资收益率、信托转型、券商业绩",
    "healthcare":       "医保政策、仿制药带量采购、创新药审批、医疗器械监管",
    "transport":        "铁路/民航/港口政策、物流基础设施投资",
    "earnings":         "上市公司年报/半年报/季报、业绩预告与修正",
    "restructuring":    "并购重组、资产剥离、控股权转让、借壳上市",
    "personnel":        "董事长/CEO等高管变动、实控人股权变化",
    "violation":        "财务造假、内幕交易、信息披露违规、监管处罚",
    "ipo":              "IPO申报、注册/终止进度、首发定价、上市首日表现",
}

# =======================
# 媒体等级分值
# =======================
MEDIA_TIER_SCORE = {
    "tier1":   10.0,  # 央行、财政部、证监会等官方机构
    "tier2":   7.0,   # 财新、一财、21世纪经济报道等核心媒体
    "unknown": 3.0,
}

# =======================
# 工具函数
# =======================

def make_event_id(main_title: str, articles: List[RawArticle]) -> str:
    """基于内容哈希生成稳定的事件ID（修复Auditor跨批次匹配问题）"""
    urls_str = "".join(sorted(art.url for art in articles))
    content = main_title + urls_str
    return "evt_" + hashlib.md5(content.encode("utf-8")).hexdigest()[:12]


def calculate_struct_score(articles: List[RawArticle], category_key: str) -> tuple:
    """
    结构评分：struct_score = 0.50×source + 0.25×coverage + 0.25×category
    返回 (struct_score, tier1_count, detail_dict)
    """
    # 1. 来源权威性（tier1双倍权重）
    weights = [2.0 if a.source.tier == "tier1" else 1.0 for a in articles]
    scores  = [MEDIA_TIER_SCORE.get(a.source.tier, 3.0) for a in articles]
    total_weight = sum(weights)
    source_score = sum(w * s for w, s in zip(weights, scores)) / total_weight if total_weight > 0 else 0.0

    # 2. 覆盖面（对数归一化）
    coverage_score = min(10.0, math.log(1 + len(articles)) * COVERAGE_LOG_SCALE)

    # 3. 事件类别基础分
    cat_def = TAXONOMY_DEFINITIONS.get(category_key, TAXONOMY_DEFINITIONS["other"])
    category_score = cat_def["base_score"]

    # 4. tier1文章数量（用于加成）
    tier1_count = sum(1 for a in articles if a.source.tier == "tier1")

    struct_score = 0.50 * source_score + 0.25 * coverage_score + 0.25 * category_score

    detail = {
        "source_score":   round(source_score, 2),
        "coverage_score": round(coverage_score, 2),
        "category_score": category_score,
        "struct_score":   round(struct_score, 2),
        "tier1_count":    tier1_count,
    }
    return struct_score, tier1_count, detail


def fuse_scores(struct_score: float, llm_score: float, tier1_count: int) -> float:
    """
    动态权重融合最终分
    - 有tier1来源：结构65% + LLM35%
    - 无tier1来源：结构35% + LLM65%
    - tier1加成：每篇+0.3，上限1.0
    """
    alpha_s, alpha_l = ALPHA_WITH_TIER1 if tier1_count > 0 else ALPHA_WITHOUT_TIER1
    tier1_bonus = min(1.0, tier1_count * TIER1_BONUS_PER_ARTICLE)
    final = alpha_s * struct_score + alpha_l * llm_score + tier1_bonus
    return min(10.0, round(final, 2))


def detect_region(articles: List[RawArticle]) -> str:
    """
    检测事件地域属性，返回 domestic / mixed / international。

    判断优先级：
    1. 来源域名：tier1/tier2 白名单域名为中国机构 → 强国内信号
    2. 关键词计数：国内关键词 vs 国际关键词加权比较
    3. 默认兜底：无法判断时归为 domestic（本系统以中国金融为主）
    """
    # 强国内信号：来源域名属于中国机构
    DOMESTIC_DOMAINS = {
        "pbc.gov.cn", "mof.gov.cn", "gov.cn", "ndrc.gov.cn",
        "stats.gov.cn", "csrc.gov.cn", "nfra.gov.cn", "safe.gov.cn",
        "caixin.com", "cls.cn", "yicai.com", "21jingji.com",
        "sina.com.cn", "news.cn", "stcn.com", "cs.com.cn",
        "cnstock.com", "financialnews.com.cn", "ce.cn",
        "jiemian.com", "thepaper.cn", "eeo.com.cn", "nbd.com.cn",
    }

    # 国内关键词（权重 1）
    DOMESTIC_KW = [
        "中国", "国内", "大陆", "内地",
        "统计局", "发改委", "政治局", "国务院", "人大", "两会",
        "央行", "人民银行", "银保监", "证监会", "金监总局", "财政部",
        "A股", "深交所", "上交所", "北交所", "沪深", "创业板", "科创板",
        "人民币", "CNY", "LPR", "MLF", "OMO",
        "GDP", "CPI", "PPI", "PMI",  # 在中文语境下均指中国数据
        "专项债", "城投", "房地产", "限购", "保交楼",
    ]

    # 国际关键词（权重 1）
    INTL_KW = [
        "美国", "美联储", "Fed", "FOMC",
        "欧洲", "欧央行", "ECB", "欧元区",
        "日本", "日元", "日银", "BOJ",
        "英国", "英镑", "英央行", "BOE",
        "全球", "国际", "跨境", "离岸",
        "纳斯达克", "标普", "道琼斯", "NYSE",
        "港股", "恒生", "港元",
        "G7", "G20", "IMF", "世界银行", "WTO",
        "制裁", "关税", "贸易战",
    ]

    domestic_score = 0
    intl_score = 0

    for art in articles:
        domain = getattr(getattr(art, "source", None), "domain", "") or ""
        text = f"{art.title} {getattr(art, 'full_text', '') or art.snippet}"

        # 来源域名命中 → 强国内信号（等价于 3 个关键词）
        if any(d in domain for d in DOMESTIC_DOMAINS):
            domestic_score += 3

        domestic_score += sum(1 for kw in DOMESTIC_KW if kw in text)
        intl_score     += sum(1 for kw in INTL_KW     if kw in text)

    # 判断
    if intl_score == 0:
        return "domestic"                           # 无任何国际信号 → 国内
    if domestic_score == 0:
        return "international"                      # 无任何国内信号 → 国际
    ratio = domestic_score / (domestic_score + intl_score)
    if ratio >= 0.75:
        return "domestic"                           # 国内信号占比 ≥ 75%
    if ratio <= 0.25:
        return "international"                      # 国际信号占比 ≥ 75%
    return "mixed"                                  # 两者都有 → 混合


# =======================
# Analyst Agent（两阶段聚类）
# =======================
class AnalystAgent:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Missing API Key")
        self.client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com")

    def cluster_articles(
        self,
        articles: List[RawArticle],
        verbose: bool = True,
        use_rule_based: bool = False,
        enable_quality_check: bool = True,
        clustering_mode: str = "tfidf_llm",
    ) -> List[Event]:
        if not articles:
            return []

        if use_rule_based:
            clustering_mode = "llm"

        if clustering_mode == "llm":
            console.rule("[bold purple]🟣 Phase 2: 规则驱动聚类 (Rule-Based Clustering)[/]")
            clusterer = RuleBasedClusterer(similarity_threshold=0.4)
            events = clusterer.cluster_articles_rule_based(articles, verbose=verbose)
        elif clustering_mode == "embedding":
            console.rule("[bold purple]Phase 2: Embedding + LLM Clustering[/]")
            events = self._embedding_phase_cluster(articles, verbose=verbose)
        else:
            console.rule("[bold purple]🟣 Phase 2: 两阶段聚类 (TF-IDF + LLM)[/]")
            events = self._two_phase_cluster(articles, verbose=verbose)

        # 质量验证
        if enable_quality_check and verbose and events:
            try:
                from aligners import ClusterQualityValidator
                validator = ClusterQualityValidator()
                quality_report = validator.validate_clustering(events, verbose=True)
                for evt in events:
                    evt.detail["quality_score"] = quality_report.get("overall_score", 0)
            except Exception as e:
                console.print(f"[yellow]质量验证失败: {e}[/]")

        if verbose:
            self._print_dashboard(events)

        return events

    # --------------------------------------------------
    # 两阶段聚类主逻辑
    # --------------------------------------------------

    def _two_phase_cluster(self, articles: List[RawArticle], verbose: bool = True) -> List[Event]:
        """TF-IDF预分组 → LLM精聚类"""
        # 阶段一
        console.print(f"[cyan]📊 Phase 2.1: TF-IDF 预分组（{len(articles)} 篇文章）...[/]")
        groups = self._tfidf_pregroup(articles)
        console.print(f"[green]✓ 预分组完成，生成 {len(groups)} 个组[/]")

        # 阶段二
        console.print(f"[cyan]🤖 Phase 2.2: LLM 精聚类（{len(groups)} 个预分组）...[/]")
        all_events = []
        for i, group in enumerate(groups, 1):
            if verbose:
                console.print(f"[dim]  处理预分组 {i}/{len(groups)}（{len(group)} 篇）[/]")
            try:
                sub_events = self._llm_refine_group(group)
                all_events.extend(sub_events)
            except Exception as e:
                console.print(f"[yellow]  ⚠️ 预分组 {i} LLM处理失败: {e}，使用fallback[/]")
                fallback = self._fallback_single_event(group)
                if fallback:
                    all_events.append(fallback)

        all_events.sort(key=lambda x: x.score, reverse=True)
        return all_events

    def _embedding_phase_cluster(self, articles: List[RawArticle], verbose: bool = True) -> List[Event]:
        """Representation layer pregrouping -> LLM refinement."""
        try:
            from embedding_engine import EmbeddingEngine
        except Exception as e:
            console.print(f"[yellow]Embedding engine unavailable: {e}. Falling back to TF-IDF.[/]")
            return self._two_phase_cluster(articles, verbose=verbose)

        engine = EmbeddingEngine()
        groups = engine.cluster_articles(articles)
        console.print(f"[green]Embedding pregrouping complete: {len(groups)} groups[/]")

        all_events = []
        for i, group in enumerate(groups, 1):
            if verbose:
                console.print(f"[dim]  Embedding group {i}/{len(groups)} ({len(group)} articles)[/]")
            try:
                sub_events = self._llm_refine_group(group)
                for evt in sub_events:
                    representation = engine.build_event_representation(evt)
                    evt.detail["event_representation"] = {
                        "representation_layer": "hash_embedding",
                        "article_ids": representation.article_ids,
                        "source_score": representation.source_score,
                        "coverage_score": representation.coverage_score,
                        "category_score": representation.category_score,
                        "llm_score": representation.llm_score,
                        "final_score": representation.final_score,
                        "primary_category": representation.primary_category,
                        "secondary_category": representation.secondary_category,
                        "region": representation.region,
                        "embedding_dimension": len(representation.text_embedding),
                    }
                all_events.extend(sub_events)
            except Exception as e:
                console.print(f"[yellow]  Embedding group {i} LLM refine failed: {e}. Using fallback.[/]")
                fallback = self._fallback_single_event(group)
                if fallback:
                    representation = engine.build_event_representation(fallback)
                    fallback.detail["event_representation"] = {
                        "representation_layer": "hash_embedding",
                        "article_ids": representation.article_ids,
                        "source_score": representation.source_score,
                        "coverage_score": representation.coverage_score,
                        "category_score": representation.category_score,
                        "llm_score": representation.llm_score,
                        "final_score": representation.final_score,
                        "primary_category": representation.primary_category,
                        "secondary_category": representation.secondary_category,
                        "region": representation.region,
                        "embedding_dimension": len(representation.text_embedding),
                    }
                    all_events.append(fallback)

        all_events.sort(key=lambda x: x.score, reverse=True)
        return all_events

    def _tfidf_pregroup(self, articles: List[RawArticle]) -> List[List[RawArticle]]:
        """阶段一：TF-IDF + 余弦相似度贪心分组"""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            console.print("[yellow]⚠️ 未安装 scikit-learn，所有文章作为一组[/]")
            return [articles]

        texts = [
            f"{art.title} {(getattr(art, 'full_text', '') or art.snippet or '')[:300]}"
            for art in articles
        ]
        try:
            vectorizer = TfidfVectorizer(
                max_features=TFIDF_MAX_FEATURES,
                analyzer="char_wb",
                ngram_range=(2, 4),
            )
            tfidf_matrix = vectorizer.fit_transform(texts)
        except Exception as e:
            console.print(f"[yellow]⚠️ TF-IDF向量化失败: {e}[/]")
            return [articles]

        sim_matrix = cosine_similarity(tfidf_matrix)

        # 贪心分组：已分配的文章不重复分配
        n = len(articles)
        assigned = [False] * n
        groups = []
        for i in range(n):
            if assigned[i]:
                continue
            group = [i]
            assigned[i] = True
            for j in range(i + 1, n):
                if not assigned[j] and sim_matrix[i][j] >= TFIDF_SIM_THRESHOLD:
                    group.append(j)
                    assigned[j] = True
            groups.append([articles[idx] for idx in group])

        return groups

    def _llm_refine_group(self, articles: List[RawArticle]) -> List[Event]:
        """阶段二：LLM精聚类，判断是否拆分并进行语义评分"""
        # 超大组分批处理
        if len(articles) > MAX_GROUP_SIZE_FOR_LLM:
            all_events = []
            for i in range(0, len(articles), MAX_GROUP_SIZE_FOR_LLM):
                batch = articles[i:i + MAX_GROUP_SIZE_FOR_LLM]
                all_events.extend(self._llm_refine_group(batch))
            return all_events

        input_lines = "\n".join(
            f"[{i}] 【{a.source.outlet_name} | {a.source.tier}】{a.title}\n  摘要: {a.snippet[:150]}"
            for i, a in enumerate(articles)
        )

        sec_desc_str = "\n".join(
            f"  {k}: {v}" for k, v in SECONDARY_CATEGORY_DESC.items()
        )
        system_prompt = f"""你是一名严格遵循分类框架的金融情报分析师。请对以下文章进行聚类、分类并打分。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【一】聚类规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. 同一政策批次 / 同一数据发布 / 同一会议 → 合并为 1 个事件
2. 同一公司一周内两件逻辑独立的重大事件 → 必须拆分
3. 不同月份的宏观数据 → 必须拆分
4. 不同层级政府的会议（国务院 vs 省级 vs 县级）→ 必须拆分，不可合并

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【二】一级分类决策树（category 字段必须严格使用以下代码之一）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Q1: 是否涉及国家级经济政策或宏观数据？
  ├── YES → category = "macro"
  │         secondary: monetary_policy / fiscal_policy / economic_data / trade / international
  └── NO  → Q2

Q2: 是否涉及金融监管部门（证监会/银保监/金监总局/交易所）发布的规则/公告/处罚？
  ├── YES → category = "regulation"
  │         secondary: securities / banking / insurance / fintech / antitrust
  └── NO  → Q3

Q3: 是否为资本市场行情类（指数/债市/汇率/大宗商品价格），且不针对单一公司？
  ├── YES → category = "market"
  │         secondary: equity / bond / fx / commodity / derivative
  └── NO  → Q4

Q4: 是否涉及某一行业的政策或整体趋势（非单一公司）？
  ├── YES → category = "industry"
  │         secondary: energy / tech / consumer / real_estate / financial_sector / healthcare / transport
  └── NO  → Q5

Q5: 是否主要描述单一公司或少量公司的微观事件？
  ├── YES → category = "company"
  │         secondary: earnings / restructuring / personnel / violation / ipo
  └── NO  → category = "other"；secondary = ""

一级分类对应权重分（影响结构评分）：
{json.dumps({k: v['base_score'] for k, v in TAXONOMY_DEFINITIONS.items()}, ensure_ascii=False)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【三】二级分类说明（secondary_category 字段参考）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sec_desc_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【四】评分维度（均为 0-10 整数）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- macro_impact:  对宏观经济的潜在影响深度
- market_impact: 对股/债/汇/商品市场的波动驱动力
- urgency:       时效紧迫程度（10=需立即关注）
- long_term:     中长期结构性影响程度
- llm_score:     综合以上四维度的最终语义重要性（0-10整数）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【五】输出格式（严格输出 JSON，不含注释）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "events": [
    {{
      "main_title": "事件标准标题（不超过30字）",
      "summary": "关键事实摘要（100字内，只含可核查事实，不含分析推断）",
      "article_indices": [0, 2],
      "category": "macro",
      "secondary_category": "monetary_policy",
      "macro_impact": 8,
      "market_impact": 7,
      "urgency": 9,
      "long_term": 6,
      "llm_score": 8
    }}
  ]
}}"""

        resp = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": input_lines},
            ],
            response_format={"type": "json_object"},
            temperature=0.05,
            timeout=120.0,
        )
        data = json.loads(resp.choices[0].message.content)

        events = []
        for item in data.get("events", []):
            indices = item.get("article_indices", [])
            rel_arts = [articles[i] for i in indices if 0 <= i < len(articles)]
            if not rel_arts:
                continue

            cat_key = item.get("category", "other")
            if cat_key not in TAXONOMY_DEFINITIONS:
                cat_key = "other"

            secondary  = item.get("secondary_category", "")
            llm_score  = float(item.get("llm_score", 5))

            struct_score, tier1_count, detail = calculate_struct_score(rel_arts, cat_key)
            final_score = fuse_scores(struct_score, llm_score, tier1_count)

            detail.update({
                "llm_score":     llm_score,
                "macro_impact":  item.get("macro_impact", 0),
                "market_impact": item.get("market_impact", 0),
                "urgency":       item.get("urgency", 0),
                "long_term":     item.get("long_term", 0),
                "region":        detect_region(rel_arts),
            })

            events.append(Event(
                event_id=make_event_id(item.get("main_title", ""), rel_arts),
                main_title=item.get("main_title", "未命名"),
                summary=item.get("summary", ""),
                score=final_score,
                articles=rel_arts,
                primary_category=cat_key,
                secondary_category=secondary,
                detail=detail,
            ))

        return events

    def _fallback_single_event(self, articles: List[RawArticle]) -> Optional[Event]:
        """LLM失败时的fallback：整组视为一个事件"""
        if not articles:
            return None
        cat_key = self._keyword_match_category(articles)
        struct_score, tier1_count, detail = calculate_struct_score(articles, cat_key)
        detail["region"] = detect_region(articles)
        return Event(
            event_id=make_event_id(articles[0].title, articles),
            main_title=articles[0].title[:60],
            summary=articles[0].snippet[:200],
            score=fuse_scores(struct_score, 5.0, tier1_count),
            articles=articles,
            primary_category=cat_key,
            secondary_category="",
            detail=detail,
        )

    def _keyword_match_category(self, articles: List[RawArticle]) -> str:
        combined = " ".join(f"{a.title} {a.snippet}" for a in articles)
        scores = {
            k: sum(1 for kw in v.get("keywords", "").split(", ") if kw and kw in combined)
            for k, v in TAXONOMY_DEFINITIONS.items()
        }
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "other"

    def _print_dashboard(self, events: List[Event]):
        for evt in events:
            score = evt.score
            color = "red" if score >= 8.5 else "yellow" if score >= 6.5 else "blue"

            cat_info = TAXONOMY_DEFINITIONS.get(evt.primary_category, {})
            cat_name = cat_info.get("name", evt.primary_category)
            cat_label = cat_name + (f" / {evt.secondary_category}" if evt.secondary_category else "")

            d = evt.detail
            region = d.get("region", "unknown")
            region_icon = {"domestic": "🇨🇳", "international": "🌍", "mixed": "🌐", "unknown": "❓"}.get(region, "❓")
            region_text = {"domestic": "国内", "international": "国际", "mixed": "混合", "unknown": "未知"}.get(region, "未知")

            tree = Tree(f"[bold {color}]{evt.main_title}[/] (Score: {score})")
            tree.add(f"[cyan]分类:[/cyan] {cat_label}")
            tree.add(
                f"[dim]结构分:{d.get('struct_score','?')} "
                f"(来源:{d.get('source_score','?')} 覆盖:{d.get('coverage_score','?')} 类别:{d.get('category_score','?')}) "
                f"| LLM分:{d.get('llm_score','?')} | tier1:{d.get('tier1_count',0)}篇 "
                f"| 地域:{region_icon} {region_text}[/dim]"
            )
            if d.get("urgency"):
                tree.add(
                    f"[dim]紧迫性:{d['urgency']} | "
                    f"宏观影响:{d.get('macro_impact','?')} | "
                    f"市场影响:{d.get('market_impact','?')} | "
                    f"长期性:{d.get('long_term','?')}[/dim]"
                )
            tree.add(f"[italic]{evt.summary}[/italic]")
            console.print(Panel(tree, border_style=color, box=box.ROUNDED))


# =======================
# Rule-Based Clusterer（保留向后兼容）
# =======================
class RuleBasedClusterer:
    """规则驱动聚类器（向后兼容，use_rule_based=True 时使用）"""

    def __init__(self, similarity_threshold: float = 0.4):
        self.similarity_threshold = similarity_threshold
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            self.TfidfVectorizer  = TfidfVectorizer
            self.cosine_similarity = cosine_similarity
        except ImportError:
            raise ImportError("需要安装 scikit-learn: pip install scikit-learn")

    def cluster_articles_rule_based(self, articles: List[RawArticle], verbose: bool = True) -> List[Event]:
        if not articles:
            return []
        console.print(f"[cyan]开始规则驱动聚类（共 {len(articles)} 篇文章）...[/]")

        texts = [f"{art.title} {getattr(art, 'full_text', '') or art.snippet or ''}" for art in articles]
        vectorizer  = self.TfidfVectorizer(max_features=200)
        tfidf_matrix = vectorizer.fit_transform(texts)
        sim_matrix  = self.cosine_similarity(tfidf_matrix)

        clusters = self._greedy_cluster(articles, sim_matrix)
        events   = self._score_clusters(clusters)

        if verbose:
            console.print(f"\n[bold green]规则聚类结果:[/]")
            for evt in events:
                console.print(f"  • {evt.main_title} ({len(evt.articles)} 篇) - {evt.primary_category}")

        return events

    def _greedy_cluster(self, articles, sim_matrix) -> List[List[RawArticle]]:
        n = len(articles)
        clusters = [[i] for i in range(n)]
        while True:
            best_sim, merge_pair = -1, None
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    sim = sum(sim_matrix[a][b] for a in clusters[i] for b in clusters[j])
                    sim /= len(clusters[i]) * len(clusters[j])
                    if sim > best_sim and sim >= self.similarity_threshold:
                        best_sim, merge_pair = sim, (i, j)
            if merge_pair is None:
                break
            i, j = merge_pair
            clusters[i].extend(clusters[j])
            clusters.pop(j)
        return [[articles[idx] for idx in c] for c in clusters]

    def _score_clusters(self, clusters: List[List[RawArticle]]) -> List[Event]:
        events = []
        for arts in clusters:
            if not arts:
                continue
            cat_key = self._match_category(arts)
            struct_score, tier1_count, detail = calculate_struct_score(arts, cat_key)
            detail["region"] = detect_region(arts)
            events.append(Event(
                event_id=make_event_id(arts[0].title, arts),
                main_title=arts[0].title[:50],
                summary=arts[0].snippet[:200],
                score=fuse_scores(struct_score, 5.0, tier1_count),
                articles=arts,
                primary_category=cat_key,
                secondary_category="",
                detail=detail,
            ))
        events.sort(key=lambda x: x.score, reverse=True)
        return events

    def _match_category(self, articles: List[RawArticle]) -> str:
        combined = " ".join(f"{art.title} {getattr(art, 'full_text', '') or art.snippet}" for art in articles)
        scores = {
            k: sum(1 for kw in v.get("keywords", "").split(", ") if kw and kw in combined)
            for k, v in TAXONOMY_DEFINITIONS.items()
        }
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "other"


if __name__ == "__main__":
    pass
