# aligners.py
# Layer 3: Deterministic Aligners
# Handles numeric, temporal, and entity normalization/alignment

import re
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
# Clustering Quality Validator
# ==========================================

class ClusterQualityValidator:
    """
    聚类质量验证器
    实现 Speaker 1 提出的质量检查需求：
    1. 簇内相似度 (Intra-cluster similarity)
    2. 簇间距离 (Inter-cluster distance)
    3. 质量评分报告 (Quality score report)
    """

    def __init__(self):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            self.TfidfVectorizer = TfidfVectorizer
            self.cosine_similarity = cosine_similarity
            self.vectorizer = None
        except ImportError:
            raise ImportError("需要安装 scikit-learn: pip install scikit-learn")

    def validate_clustering(self, events: List, verbose: bool = True) -> Dict[str, Any]:
        """
        验证聚类质量

        Args:
            events: Event 对象列表
            verbose: 是否打印详细信息

        Returns:
            质量报告字典，包含：
            - overall_score: 总体质量分数 (0-100)
            - intra_cluster_scores: 各簇内相似度
            - inter_cluster_distances: 簇间距离矩阵
            - quality_issues: 质量问题列表
        """
        if not events:
            return {"overall_score": 0, "error": "No events to validate"}

        # 1. 计算簇内相似度
        intra_scores = self._calculate_intra_cluster_similarity(events)

        # 2. 计算簇间距离
        inter_distances = self._calculate_inter_cluster_distance(events)

        # 3. 检测质量问题
        issues = self._detect_quality_issues(events, intra_scores, inter_distances)

        # 4. 计算总体质量分数
        overall_score = self._calculate_overall_score(intra_scores, inter_distances, issues)

        report = {
            "overall_score": overall_score,
            "intra_cluster_scores": intra_scores,
            "inter_cluster_distances": inter_distances,
            "quality_issues": issues,
            "num_events": len(events),
            "total_articles": sum(len(e.articles) for e in events)
        }

        if verbose:
            self._print_quality_report(report)

        return report

    def _calculate_intra_cluster_similarity(self, events: List) -> Dict[str, float]:
        """计算每个簇内的平均相似度"""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        scores = {}

        for event in events:
            if len(event.articles) < 2:
                scores[event.event_id] = 1.0  # 单篇文章默认满分
                continue

            # 提取文章文本
            texts = []
            for article in event.articles:
                # 优先使用 full_text，否则使用 title + snippet
                text = getattr(article, 'full_text', '') or article.snippet
                if not text:
                    text = article.title
                texts.append(text)

            # 计算 TF-IDF 相似度
            try:
                vectorizer = TfidfVectorizer(max_features=100)
                tfidf_matrix = vectorizer.fit_transform(texts)
                similarity_matrix = cosine_similarity(tfidf_matrix)

                # 计算平均相似度（排除对角线）
                n = len(texts)
                if n > 1:
                    total_sim = similarity_matrix.sum() - n  # 减去对角线
                    avg_sim = total_sim / (n * (n - 1))
                    scores[event.event_id] = round(avg_sim, 3)
                else:
                    scores[event.event_id] = 1.0
            except Exception:
                scores[event.event_id] = 0.0

        return scores

    def _calculate_inter_cluster_distance(self, events: List) -> Dict[str, float]:
        """计算簇间距离（使用簇中心向量）"""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        if len(events) < 2:
            return {}

        # 为每个簇计算中心向量
        cluster_centers = {}
        all_texts = []

        for event in events:
            texts = []
            for article in event.articles:
                text = getattr(article, 'full_text', '') or article.snippet or article.title
                texts.append(text)
            all_texts.extend(texts)
            cluster_centers[event.event_id] = texts

        # 使用所有文本训练 vectorizer
        try:
            vectorizer = TfidfVectorizer(max_features=200)
            vectorizer.fit(all_texts)

            # 计算每个簇的中心向量（平均）
            centers = {}
            for event_id, texts in cluster_centers.items():
                tfidf = vectorizer.transform(texts)
                center = tfidf.mean(axis=0)  # 平均向量作为簇中心
                centers[event_id] = center

            # 计算簇间距离
            distances = {}
            event_ids = list(centers.keys())
            for i in range(len(event_ids)):
                for j in range(i + 1, len(event_ids)):
                    id1, id2 = event_ids[i], event_ids[j]
                    sim = cosine_similarity(centers[id1], centers[id2])[0][0]
                    distance = 1 - sim  # 距离 = 1 - 相似度
                    distances[f"{id1}_{id2}"] = round(distance, 3)

            return distances
        except Exception:
            return {}

    def _detect_quality_issues(self, events: List, intra_scores: Dict, inter_distances: Dict) -> List[str]:
        """检测聚类质量问题"""
        issues = []

        # 阈值定义
        LOW_INTRA_THRESHOLD = 0.3  # 簇内相似度过低
        HIGH_INTER_SIMILARITY = 0.7  # 簇间相似度过高（距离过小）

        # 检查簇内相似度过低的簇
        for event_id, score in intra_scores.items():
            if score < LOW_INTRA_THRESHOLD:
                issues.append(f"Event {event_id}: 簇内相似度过低 ({score:.2f}), 可能需要拆分")

        # 检查簇间距离过小的簇对（可能需要合并）
        for pair, distance in inter_distances.items():
            if distance < (1 - HIGH_INTER_SIMILARITY):
                issues.append(f"Event pair {pair}: 簇间距离过小 ({distance:.2f}), 可能需要合并")

        # 检查单文章簇过多
        single_article_events = sum(1 for e in events if len(e.articles) == 1)
        if single_article_events > len(events) * 0.5:
            issues.append(f"单文章簇过多 ({single_article_events}/{len(events)}), 聚类可能过细")

        return issues

    def _calculate_overall_score(self, intra_scores: Dict, inter_distances: Dict, issues: List) -> float:
        """计算总体质量分数 (0-100)"""
        score = 100.0

        # 簇内相似度贡献 (50分)
        if intra_scores:
            avg_intra = sum(intra_scores.values()) / len(intra_scores)
            score = avg_intra * 50

        # 簇间距离贡献 (30分)
        if inter_distances:
            avg_distance = sum(inter_distances.values()) / len(inter_distances)
            score += avg_distance * 30

        # 质量问题惩罚 (20分)
        issue_penalty = min(len(issues) * 5, 20)
        score += (20 - issue_penalty)

        return round(max(0, min(100, score)), 1)

    def _print_quality_report(self, report: Dict):
        """打印质量报告"""
        try:
            from rich.console import Console
            from rich.table import Table
            console = Console()

            console.rule("[bold cyan]📊 聚类质量报告 (Clustering Quality Report)[/]")

            # 总体评分
            score = report["overall_score"]
            if score >= 80:
                color = "green"
                grade = "优秀"
            elif score >= 60:
                color = "yellow"
                grade = "良好"
            else:
                color = "red"
                grade = "需改进"

            console.print(f"\n[bold {color}]总体质量分数: {score}/100 ({grade})[/]\n")

            # 簇内相似度表格
            if report["intra_cluster_scores"]:
                table = Table(title="簇内相似度 (Intra-Cluster Similarity)", show_header=True)
                table.add_column("Event ID", style="cyan")
                table.add_column("相似度", justify="right")
                table.add_column("状态", justify="center")

                for event_id, score in report["intra_cluster_scores"].items():
                    status = "✅" if score >= 0.3 else "⚠️"
                    table.add_row(event_id[:20], f"{score:.3f}", status)

                console.print(table)

            # 质量问题
            if report["quality_issues"]:
                console.print("\n[yellow]⚠️ 发现的质量问题:[/]")
                for issue in report["quality_issues"]:
                    console.print(f"  • {issue}")
            else:
                console.print("\n[green]✅ 未发现质量问题[/]")

            console.print()

        except ImportError:
            print(f"\n聚类质量报告:")
            print(f"总体分数: {report['overall_score']}/100")
            print(f"事件数: {report['num_events']}")
            print(f"质量问题: {len(report['quality_issues'])}")