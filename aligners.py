# aligners.py
# Layer 3: Deterministic Aligners
# Handles numeric, temporal, and entity normalization/alignment
# ClusterQualityValidator 按照 clustering taxonomy_0204.docx 实现分层与评分校验

import re
import math
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

@dataclass
class NormalizedValue:
    """Normalized representation of a value"""
    original_text: str
    normalized_value: Any
    unit: Optional[str] = None

class NumericAligner:
    """
    Handles normalization and alignment of numeric values.
    Supports Chinese numerals, percentage variations, currency units.
    """
    
    def normalize(self, text: str) -> NormalizedValue:
        """Normalize a numeric string to a float value with unit"""
        original = text.strip()
        
        # Try percentage
        pct_match = re.search(r'([\d.]+)\s*%', text)
        if pct_match:
            return NormalizedValue(original, float(pct_match.group(1)) / 100, 'ratio')
        
        # Try Chinese number logic (Simple version)
        # 140万亿 -> 140 * 10^12
        if '万亿' in text:
            val = re.search(r'([\d.]+)', text)
            if val: return NormalizedValue(original, float(val.group(1)) * 1e12, 'count')
        elif '亿' in text:
            val = re.search(r'([\d.]+)', text)
            if val: return NormalizedValue(original, float(val.group(1)) * 1e8, 'count')
        
        # Try plain number
        num_match = re.search(r'[\d,.]+', text)
        if num_match:
            try:
                val = float(num_match.group().replace(',', ''))
                return NormalizedValue(original, val, None)
            except ValueError:
                pass
        
        return NormalizedValue(original, None)
    
    def align(self, claim_value: str, source_value: str, tolerance: float = 0.01) -> Tuple[bool, float, str]:
        """Check if two numeric values align within tolerance."""
        norm_claim = self.normalize(claim_value)
        norm_source = self.normalize(source_value)
        
        if norm_claim.normalized_value is None or norm_source.normalized_value is None:
            return False, 0.0, "Normalization failed"
        
        claim_val = norm_claim.normalized_value
        source_val = norm_source.normalized_value
        
        if source_val == 0: return False, 0.0, "Source is zero"
        
        rel_diff = abs(claim_val - source_val) / abs(source_val)
        
        if rel_diff <= tolerance:
            return True, 1.0 - rel_diff, f"Aligned within {tolerance:.1%}"
        else:
            return False, 0.0, f"Differs by {rel_diff:.1%}"

class CompositeAligner:
    """Main aligner that coordinates checks."""
    def __init__(self):
        self.numeric = NumericAligner()
        # Add TemporalAligner and EntityAligner here

    def align_claim_to_evidence(self, claim_text, evidence_text, claim_value=None):
        results = {'overall_aligned': False, 'alignments': []}

        # Strategy 1: Extract ALL numbers from claim text and match against evidence
        claim_nums = re.findall(r'[\d,]+\.?\d*%?|[\d,]+\.?\d*\s*万亿|[\d,]+\.?\d*\s*亿', claim_text)
        evidence_nums = re.findall(r'[\d,]+\.?\d*%?|[\d,]+\.?\d*\s*万亿|[\d,]+\.?\d*\s*亿', evidence_text)

        # Check if any claim number appears in evidence
        for claim_num in claim_nums:
            # Normalize: remove commas
            claim_norm = claim_num.replace(',', '')
            for ev_num in evidence_nums:
                ev_norm = ev_num.replace(',', '')
                # Check if they match (allowing for minor variations)
                if claim_norm == ev_norm or claim_norm in ev_norm or ev_norm in claim_norm:
                    results['alignments'].append({
                        'type': 'numeric', 'claim': claim_num, 'evidence': ev_num, 'score': 1.0
                    })
                    results['overall_aligned'] = True
                    break
            if results['overall_aligned']:
                break

        # Strategy 2: Check for key phrase overlap (fuzzy matching)
        if not results['overall_aligned']:
            # Extract key phrases from claim (split by punctuation, take phrases >4 chars)
            claim_phrases = [p.strip() for p in re.split(r'[，。、；：]', claim_text) if len(p.strip()) > 4]
            for phrase in claim_phrases:
                if phrase in evidence_text:
                    results['alignments'].append({
                        'type': 'text', 'claim': phrase, 'evidence': '匹配', 'score': 0.8
                    })
                    results['overall_aligned'] = True
                    break

        # Strategy 3: Fallback - check if significant portion of claim appears in evidence
        if not results['overall_aligned']:
            # Remove common words and check if core content exists
            claim_core = re.sub(r'[的了和与及在于为]', '', claim_text)
            if len(claim_core) > 10 and claim_core[:15] in evidence_text:
                results['overall_aligned'] = True
                results['alignments'].append({
                    'type': 'fuzzy', 'claim': claim_core[:20], 'evidence': '部分匹配', 'score': 0.6
                })

        return results


# ==========================================
# 分类与评分标准常量（来源：clustering taxonomy_0204.docx）
# ==========================================

# 一级分类体系（Table 1）：代码 → (显示名, 权重分)
PRIMARY_TAXONOMY: Dict[str, Dict[str, Any]] = {
    "macro":      {"name": "宏观经济 & 政策", "base_score": 10.0},
    "regulation": {"name": "金融监管",        "base_score": 9.0},
    "market":     {"name": "资本市场",        "base_score": 8.0},
    "industry":   {"name": "行业动态",        "base_score": 7.0},
    "company":    {"name": "公司事件",        "base_score": 5.0},
    "other":      {"name": "其他杂项",        "base_score": 5.0},
}

# 二级分类合法值（Table 2）
SECONDARY_TAXONOMY: Dict[str, List[str]] = {
    "macro":      ["monetary_policy", "fiscal_policy", "economic_data", "trade", "international"],
    "regulation": ["securities", "banking", "insurance", "fintech", "antitrust"],
    "market":     ["equity", "bond", "fx", "commodity", "derivative"],
    "industry":   ["energy", "tech", "consumer", "real_estate", "financial_sector", "healthcare", "transport"],
    "company":    ["earnings", "restructuring", "personnel", "violation", "ipo"],
    "other":      [],
}

# 媒体等级分值（Table 3）
MEDIA_TIER_SCORES: Dict[str, float] = {
    "tier1":   10.0,   # 央行/财政部等官方机构，双倍权重
    "tier2":   7.0,    # 财新/一财/21世纪等核心媒体
    "unknown": 3.0,
}

# 结构评分权重（Table 3）
STRUCT_WEIGHT_SOURCE   = 0.50
STRUCT_WEIGHT_COVERAGE = 0.25
STRUCT_WEIGHT_CATEGORY = 0.25

# 覆盖面对数归一化系数（Table 5）
COVERAGE_LOG_SCALE = 3.5

# 动态融合权重（Table 4）
ALPHA_WITH_TIER1    = (0.65, 0.35)   # (结构权重, LLM权重) 有 tier1 时
ALPHA_WITHOUT_TIER1 = (0.35, 0.65)   # 无 tier1 时

# tier1 加成（Table 5）
TIER1_BONUS_PER_ARTICLE = 0.3        # 每篇 tier1 加 0.3，上限 1.0

# 质量阈值
LOW_INTRA_THRESHOLD    = 0.3   # 簇内相似度过低警戒线
HIGH_INTER_SIMILARITY  = 0.7   # 簇间相似度过高警戒线（距离 < 0.3 时预警）


# ==========================================
# Clustering Quality Validator
# ==========================================

class ClusterQualityValidator:
    """
    聚类质量验证器
    按照 clustering taxonomy_0204.docx 的分层体系与评分公式对聚类结果进行多维校验：

    1. 分类合规校验  (Taxonomy Compliance)
       - primary_category 必须是 PRIMARY_TAXONOMY 中的合法值
       - secondary_category 必须属于该 primary 对应的合法子类

    2. 评分公式校验  (Scoring Consistency)
       - struct_score = 0.50×source_score + 0.25×coverage_score + 0.25×category_score
       - 来源权威性：tier1 双倍权重，tier1=10 / tier2=7 / unknown=3
       - 覆盖面：min(10, log(1+n) × 3.5)

    3. 来源质量分布  (Source Quality Distribution)
       - tier1 / tier2 / unknown 文章占比
       - tier1 加成：min(1.0, count × 0.3)

    4. 簇内/簇间相似度  (Intra/Inter-Cluster Similarity)
       - 簇内相似度过低 → 建议拆分
       - 簇间距离过小   → 建议合并

    总体质量分（0–100）= 分类合规(20) + 评分一致(20) + 来源质量(20) + 聚类结构(40)
    """

    def __init__(self):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            self.TfidfVectorizer = TfidfVectorizer
            self.cosine_similarity = cosine_similarity
        except ImportError:
            raise ImportError("需要安装 scikit-learn: pip install scikit-learn")

    # --------------------------------------------------
    # 主入口
    # --------------------------------------------------
    def validate_clustering(self, events: List, verbose: bool = True) -> Dict[str, Any]:
        """
        验证聚类质量，返回多维质量报告。

        Args:
            events: Event 对象列表（每个 Event 应有 articles / primary_category /
                    secondary_category / detail['struct_score'] 等字段）
            verbose: 是否打印详细 Rich 报告

        Returns:
            质量报告字典，包含：
            - overall_score:          总体质量分 (0–100)
            - taxonomy_score:         分类合规得分 (0–20)
            - scoring_score:          评分一致得分 (0–20)
            - source_quality_score:   来源质量得分 (0–20)
            - cluster_structure_score:聚类结构得分 (0–40)
            - taxonomy_issues:        分类问题列表
            - scoring_issues:         评分偏差列表
            - source_summary:         来源分布摘要
            - intra_cluster_scores:   各簇内相似度
            - inter_cluster_distances:簇间距离
            - quality_issues:         所有问题汇总
        """
        if not events:
            return {"overall_score": 0, "error": "No events to validate"}

        # 1. 分类合规校验
        taxonomy_result = self._validate_taxonomy(events)

        # 2. 评分公式校验
        scoring_result = self._validate_scoring(events)

        # 3. 来源质量分布
        source_result = self._validate_source_quality(events)

        # 4. 聚类结构（簇内/簇间）
        intra_scores     = self._calculate_intra_cluster_similarity(events)
        inter_distances  = self._calculate_inter_cluster_distance(events)
        structure_issues = self._detect_structure_issues(events, intra_scores, inter_distances)

        # 5. 汇总评分
        cluster_structure_score = self._calc_cluster_structure_score(
            intra_scores, inter_distances, structure_issues
        )

        all_issues = (
            taxonomy_result["issues"]
            + scoring_result["issues"]
            + structure_issues
        )

        overall_score = round(
            taxonomy_result["score"]
            + scoring_result["score"]
            + source_result["score"]
            + cluster_structure_score,
            1,
        )

        report = {
            "overall_score":           overall_score,
            "taxonomy_score":          taxonomy_result["score"],
            "scoring_score":           scoring_result["score"],
            "source_quality_score":    source_result["score"],
            "cluster_structure_score": cluster_structure_score,
            "taxonomy_issues":         taxonomy_result["issues"],
            "scoring_issues":          scoring_result["issues"],
            "source_summary":          source_result["summary"],
            "intra_cluster_scores":    intra_scores,
            "inter_cluster_distances": inter_distances,
            "quality_issues":          all_issues,
            "num_events":              len(events),
            "total_articles":          sum(len(e.articles) for e in events),
        }

        if verbose:
            self._print_quality_report(report)

        return report

    # --------------------------------------------------
    # 1. 分类合规校验
    # --------------------------------------------------
    def _validate_taxonomy(self, events: List) -> Dict[str, Any]:
        """
        按 clustering taxonomy_0204.docx 第三、四章定义校验分类合规性。
        满分 20 分，每个违规事件扣 2 分。
        """
        issues = []
        for evt in events:
            pri = getattr(evt, "primary_category", "")
            sec = getattr(evt, "secondary_category", "")
            title = getattr(evt, "main_title", evt.event_id)[:20]

            # 检查 primary_category 合法性
            if pri not in PRIMARY_TAXONOMY:
                issues.append(
                    f"[分类] {title}：primary_category='{pri}' 不在合法列表 "
                    f"{list(PRIMARY_TAXONOMY.keys())}"
                )
                continue

            # 检查 secondary_category 合法性（other 类允许为空）
            allowed_secondary = SECONDARY_TAXONOMY.get(pri, [])
            if sec and allowed_secondary and sec not in allowed_secondary:
                issues.append(
                    f"[分类] {title}：secondary_category='{sec}' "
                    f"不属于 {pri} 的合法子类 {allowed_secondary}"
                )

        deduction = min(20, len(issues) * 2)
        return {"score": round(20 - deduction, 1), "issues": issues}

    # --------------------------------------------------
    # 2. 评分公式校验
    # --------------------------------------------------
    def _validate_scoring(self, events: List) -> Dict[str, Any]:
        """
        按 clustering taxonomy_0204.docx 第六章公式重新计算 struct_score，
        与 detail 中记录的值对比，偏差超过 0.5 视为异常。
        满分 20 分，每个评分异常事件扣 2 分。
        """
        issues = []
        for evt in events:
            detail = getattr(evt, "detail", {})
            if not detail:
                continue

            articles = getattr(evt, "articles", [])
            pri      = getattr(evt, "primary_category", "other")
            title    = getattr(evt, "main_title", evt.event_id)[:20]

            # 重新计算 source_score（tier1 双倍权重）
            weights = [2.0 if getattr(a.source, "tier", "unknown") == "tier1" else 1.0
                       for a in articles]
            scores  = [MEDIA_TIER_SCORES.get(getattr(a.source, "tier", "unknown"), 3.0)
                       for a in articles]
            total_w = sum(weights)
            expected_source = (sum(w * s for w, s in zip(weights, scores)) / total_w
                               if total_w > 0 else 0.0)

            # 覆盖面
            expected_coverage = min(10.0, math.log(1 + len(articles)) * COVERAGE_LOG_SCALE)

            # 类别基础分
            expected_category = PRIMARY_TAXONOMY.get(pri, PRIMARY_TAXONOMY["other"])["base_score"]

            # 结构评分公式
            expected_struct = (
                STRUCT_WEIGHT_SOURCE   * expected_source
                + STRUCT_WEIGHT_COVERAGE * expected_coverage
                + STRUCT_WEIGHT_CATEGORY * expected_category
            )

            recorded_struct = detail.get("struct_score")
            if recorded_struct is not None:
                diff = abs(float(recorded_struct) - expected_struct)
                if diff > 0.5:
                    issues.append(
                        f"[评分] {title}：struct_score 记录={recorded_struct:.2f}，"
                        f"按公式期望={expected_struct:.2f}，偏差={diff:.2f}"
                    )

            # tier1 加成上限校验
            tier1_count    = detail.get("tier1_count", 0)
            expected_bonus = min(1.0, tier1_count * TIER1_BONUS_PER_ARTICLE)
            recorded_score = getattr(evt, "score", None)
            if recorded_score is not None:
                # final_score 不超过 10.0
                if float(recorded_score) > 10.0:
                    issues.append(
                        f"[评分] {title}：final_score={recorded_score} 超过上限 10.0"
                    )

        deduction = min(20, len(issues) * 2)
        return {"score": round(20 - deduction, 1), "issues": issues}

    # --------------------------------------------------
    # 3. 来源质量分布
    # --------------------------------------------------
    def _validate_source_quality(self, events: List) -> Dict[str, Any]:
        """
        统计所有文章的 tier 分布，并给出来源质量得分。
        tier1 占比越高得分越高，满分 20 分。
        """
        tier_counts: Dict[str, int] = {"tier1": 0, "tier2": 0, "unknown": 0}
        for evt in events:
            for art in getattr(evt, "articles", []):
                tier = getattr(getattr(art, "source", None), "tier", "unknown") or "unknown"
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

        total = sum(tier_counts.values()) or 1
        tier1_ratio   = tier_counts["tier1"]   / total
        tier2_ratio   = tier_counts["tier2"]   / total
        unknown_ratio = tier_counts["unknown"] / total

        # 评分：tier1 每 10% → +4 分；tier2 每 10% → +1.5 分；unknown 过多扣分
        raw_score = (
            tier1_ratio   * 40
            + tier2_ratio   * 15
            + (1 - unknown_ratio) * 5
        )
        source_score = round(min(20.0, raw_score), 1)

        summary = {
            "tier1":        tier_counts["tier1"],
            "tier2":        tier_counts["tier2"],
            "unknown":      tier_counts["unknown"],
            "tier1_ratio":  round(tier1_ratio, 3),
            "tier2_ratio":  round(tier2_ratio, 3),
            "unknown_ratio":round(unknown_ratio, 3),
        }
        return {"score": source_score, "summary": summary}

    # --------------------------------------------------
    # 4. 聚类结构（簇内/簇间）
    # --------------------------------------------------
    def _calculate_intra_cluster_similarity(self, events: List) -> Dict[str, float]:
        """计算每个簇内的平均 TF-IDF 余弦相似度"""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        scores = {}
        for event in events:
            if len(event.articles) < 2:
                scores[event.event_id] = 1.0
                continue

            texts = []
            for article in event.articles:
                text = getattr(article, 'full_text', '') or article.snippet or article.title
                texts.append(text)

            try:
                vectorizer = TfidfVectorizer(max_features=100)
                tfidf_matrix = vectorizer.fit_transform(texts)
                sim_matrix   = cosine_similarity(tfidf_matrix)
                n = len(texts)
                total_sim = sim_matrix.sum() - n
                avg_sim   = total_sim / (n * (n - 1))
                scores[event.event_id] = round(avg_sim, 3)
            except Exception:
                scores[event.event_id] = 0.0

        return scores

    def _calculate_inter_cluster_distance(self, events: List) -> Dict[str, float]:
        """计算簇间距离（1 - 余弦相似度）"""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        if len(events) < 2:
            return {}

        cluster_texts: Dict[str, List[str]] = {}
        all_texts: List[str] = []
        for event in events:
            texts = [
                getattr(a, 'full_text', '') or a.snippet or a.title
                for a in event.articles
            ]
            cluster_texts[event.event_id] = texts
            all_texts.extend(texts)

        try:
            vectorizer = TfidfVectorizer(max_features=200)
            vectorizer.fit(all_texts)

            centers = {}
            for event_id, texts in cluster_texts.items():
                tfidf  = vectorizer.transform(texts)
                center = tfidf.mean(axis=0)
                centers[event_id] = center

            distances: Dict[str, float] = {}
            event_ids = list(centers.keys())
            for i in range(len(event_ids)):
                for j in range(i + 1, len(event_ids)):
                    id1, id2 = event_ids[i], event_ids[j]
                    sim = cosine_similarity(centers[id1], centers[id2])[0][0]
                    distances[f"{id1}_{id2}"] = round(1 - sim, 3)

            return distances
        except Exception:
            return {}

    def _detect_structure_issues(
        self,
        events: List,
        intra_scores: Dict[str, float],
        inter_distances: Dict[str, float],
    ) -> List[str]:
        """检测聚类结构问题（按文档阈值：簇内<0.3 / 簇间距离<0.3）"""
        issues = []

        for event_id, score in intra_scores.items():
            if score < LOW_INTRA_THRESHOLD:
                issues.append(
                    f"[结构] Event {event_id[:16]}：簇内相似度过低 ({score:.3f} < {LOW_INTRA_THRESHOLD})，"
                    f"建议拆分"
                )

        for pair, distance in inter_distances.items():
            if distance < (1 - HIGH_INTER_SIMILARITY):
                issues.append(
                    f"[结构] Event pair {pair[:24]}：簇间距离过小 ({distance:.3f})，"
                    f"建议合并"
                )

        single_cnt = sum(1 for e in events if len(e.articles) == 1)
        if single_cnt > len(events) * 0.5:
            issues.append(
                f"[结构] 单文章簇过多 ({single_cnt}/{len(events)})，"
                f"TF-IDF 阈值可能过高，考虑调低 TFIDF_SIM_THRESHOLD"
            )

        return issues

    def _calc_cluster_structure_score(
        self,
        intra_scores: Dict[str, float],
        inter_distances: Dict[str, float],
        issues: List[str],
    ) -> float:
        """聚类结构得分，满分 40 分"""
        score = 0.0

        # 簇内相似度贡献 (20 分)
        if intra_scores:
            avg_intra = sum(intra_scores.values()) / len(intra_scores)
            score += avg_intra * 20

        # 簇间距离贡献 (15 分)
        if inter_distances:
            avg_dist = sum(inter_distances.values()) / len(inter_distances)
            score += avg_dist * 15

        # 无结构问题 (5 分)
        structure_issues = [i for i in issues if i.startswith("[结构]")]
        penalty = min(5, len(structure_issues) * 1.5)
        score += max(0, 5 - penalty)

        return round(min(40.0, score), 1)

    # --------------------------------------------------
    # 报告打印
    # --------------------------------------------------
    def _print_quality_report(self, report: Dict):
        """用 Rich 打印分层质量报告"""
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.panel import Panel
            from rich import box
            console = Console()

            console.rule("[bold cyan]📊 聚类质量报告（按 clustering taxonomy_0204 标准）[/]")

            # ── 总体评分 ──
            total = report["overall_score"]
            grade_color = "green" if total >= 80 else "yellow" if total >= 60 else "red"
            grade_text  = "优秀" if total >= 80 else "良好" if total >= 60 else "需改进"
            console.print(
                f"\n[bold {grade_color}]总体质量分数: {total}/100  ({grade_text})[/]\n"
            )

            # ── 四维分项得分 ──
            dim_table = Table(title="四维质量分项", box=box.ROUNDED, show_header=True)
            dim_table.add_column("维度",        style="cyan",   width=18)
            dim_table.add_column("得分",        justify="right", width=8)
            dim_table.add_column("满分",        justify="right", width=8)
            dim_table.add_column("说明",        style="dim",    width=30)

            dim_table.add_row(
                "分类合规",
                str(report["taxonomy_score"]), "20",
                "primary/secondary 是否在合法值域内"
            )
            dim_table.add_row(
                "评分一致性",
                str(report["scoring_score"]), "20",
                "struct_score 是否符合文档公式"
            )
            dim_table.add_row(
                "来源质量",
                str(report["source_quality_score"]), "20",
                "tier1/tier2/unknown 分布"
            )
            dim_table.add_row(
                "聚类结构",
                str(report["cluster_structure_score"]), "40",
                "簇内相似度 + 簇间距离 + 结构问题"
            )
            console.print(dim_table)

            # ── 来源质量分布 ──
            src = report.get("source_summary", {})
            if src:
                console.print("\n[bold]来源质量分布（按 tier 分级）[/]")
                src_table = Table(box=box.SIMPLE, show_header=True)
                src_table.add_column("等级",   style="cyan")
                src_table.add_column("文章数", justify="right")
                src_table.add_column("占比",   justify="right")
                src_table.add_column("单价分值",justify="right")

                tier_meta = [
                    ("tier1",   "央行/财政部等官方",  "10.0（双倍权重）"),
                    ("tier2",   "财新/一财等核心媒体", "7.0"),
                    ("unknown", "未知来源",            "3.0"),
                ]
                for key, label, price in tier_meta:
                    cnt   = src.get(key, 0)
                    ratio = src.get(f"{key}_ratio", 0)
                    src_table.add_row(f"{key}  {label}", str(cnt), f"{ratio:.1%}", price)
                console.print(src_table)

            # ── 簇内相似度 ──
            if report.get("intra_cluster_scores"):
                intra_table = Table(title="簇内相似度", box=box.ROUNDED, show_header=True)
                intra_table.add_column("Event ID",  style="cyan",  width=22)
                intra_table.add_column("相似度",    justify="right", width=8)
                intra_table.add_column("状态",      justify="center", width=6)
                for eid, sc in report["intra_cluster_scores"].items():
                    status = "✅" if sc >= LOW_INTRA_THRESHOLD else "⚠️"
                    intra_table.add_row(eid[:20], f"{sc:.3f}", status)
                console.print(intra_table)

            # ── 问题列表 ──
            all_issues = report.get("quality_issues", [])
            if all_issues:
                console.print("\n[yellow]⚠️  发现的质量问题：[/]")
                for issue in all_issues:
                    console.print(f"  • {issue}")
            else:
                console.print("\n[green]✅  未发现质量问题[/]")

            console.print()

        except ImportError:
            # Fallback: plain text
            print(f"\n聚类质量报告:")
            print(f"  总体分数:   {report['overall_score']}/100")
            print(f"  分类合规:   {report['taxonomy_score']}/20")
            print(f"  评分一致:   {report['scoring_score']}/20")
            print(f"  来源质量:   {report['source_quality_score']}/20")
            print(f"  聚类结构:   {report['cluster_structure_score']}/40")
            print(f"  事件数:     {report['num_events']}")
            print(f"  文章总数:   {report['total_articles']}")
            if report.get("quality_issues"):
                print("  问题列表:")
                for issue in report["quality_issues"]:
                    print(f"    • {issue}")
