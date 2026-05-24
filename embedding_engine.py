# embedding_engine.py
# Lightweight representation layer for article and event clustering.

import hashlib
import math
import re
from typing import Dict, List

from pydantic import BaseModel, Field

from models import RawArticle


class ArticleEmbedding(BaseModel):
    article_id: str
    text_embedding: List[float]
    source_tier_score: float
    category_hint: str = ""
    publish_date: str = ""


class EventRepresentation(BaseModel):
    event_id: str = ""
    text_embedding: List[float]
    source_score: float = 0.0
    coverage_score: float = 0.0
    category_score: float = 0.0
    llm_score: float = 0.0
    final_score: float = 0.0
    primary_category: str = ""
    secondary_category: str = ""
    region: str = ""
    article_ids: List[str] = Field(default_factory=list)


class EmbeddingEngine:
    """Deterministic local embedding baseline.

    This gives the pipeline a stable representation layer now. It can be
    replaced later by OpenAI/DeepSeek embeddings without changing Analyst's
    clustering contract.
    """

    def __init__(self, dimensions: int = 128):
        self.dimensions = dimensions

    def embed_article(self, article: RawArticle) -> ArticleEmbedding:
        text = f"{article.title} {article.full_text or article.snippet}"
        return ArticleEmbedding(
            article_id=article.article_id,
            text_embedding=self.embed_text(text),
            source_tier_score=self.source_tier_score(article.source.tier),
            category_hint="",
            publish_date=article.publish_date,
        )

    def embed_text(self, text: str) -> List[float]:
        vector = [0.0] * self.dimensions
        for token in self._tokenize(text):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % self.dimensions
            sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
            vector[idx] += sign

        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def cosine_similarity(self, left: List[float], right: List[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return sum(a * b for a, b in zip(left, right))

    def cluster_articles(
        self,
        articles: List[RawArticle],
        similarity_threshold: float = 0.42,
    ) -> List[List[RawArticle]]:
        embeddings = [self.embed_article(article) for article in articles]
        assigned = [False] * len(articles)
        groups: List[List[RawArticle]] = []

        for i, emb in enumerate(embeddings):
            if assigned[i]:
                continue

            group = [articles[i]]
            assigned[i] = True
            for j in range(i + 1, len(articles)):
                if assigned[j]:
                    continue
                sim = self.cosine_similarity(emb.text_embedding, embeddings[j].text_embedding)
                tier_bonus = 0.03 if embeddings[j].source_tier_score >= 0.8 else 0.0
                if sim + tier_bonus >= similarity_threshold:
                    group.append(articles[j])
                    assigned[j] = True
            groups.append(group)

        return groups

    @staticmethod
    def source_tier_score(tier: str) -> float:
        scores: Dict[str, float] = {
            "tier1": 1.0,
            "tier2": 0.75,
            "other": 0.35,
        }
        return scores.get((tier or "").lower(), 0.35)

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        lowered = text.lower()
        latin_tokens = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)?", lowered)
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", lowered)
        cjk_bigrams = [
            "".join(cjk_chars[i : i + 2])
            for i in range(max(0, len(cjk_chars) - 1))
        ]
        return latin_tokens + cjk_bigrams
