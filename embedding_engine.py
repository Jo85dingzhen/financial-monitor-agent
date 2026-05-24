# embedding_engine.py
# Lightweight representation layer for article and event clustering.

import hashlib
import math
import re
from typing import Dict, List

from pydantic import BaseModel, Field

from models import Event, RawArticle


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

    def build_event_representation(self, event: Event) -> EventRepresentation:
        article_embeddings = [self.embed_article(article) for article in event.articles]
        if article_embeddings:
            text_embedding = [
                sum(embedding.text_embedding[i] for embedding in article_embeddings) / len(article_embeddings)
                for i in range(self.dimensions)
            ]
            norm = math.sqrt(sum(value * value for value in text_embedding)) or 1.0
            text_embedding = [value / norm for value in text_embedding]
        else:
            text_embedding = [0.0] * self.dimensions

        domains = {article.source.domain for article in event.articles}
        source_scores = [self.source_tier_score(article.source.tier) for article in event.articles]
        source_score = sum(source_scores) / len(source_scores) if source_scores else 0.0
        coverage_score = min(1.0, math.log(1 + len(domains)) / math.log(6))
        category_score = 1.0 if event.primary_category and event.primary_category != "other" else 0.5
        llm_score = max(0.0, min(1.0, event.score / 10.0))
        final_score = (0.35 * source_score) + (0.25 * coverage_score) + (0.15 * category_score) + (0.25 * llm_score)

        return EventRepresentation(
            event_id=event.event_id,
            text_embedding=text_embedding,
            source_score=round(source_score, 4),
            coverage_score=round(coverage_score, 4),
            category_score=round(category_score, 4),
            llm_score=round(llm_score, 4),
            final_score=round(final_score, 4),
            primary_category=event.primary_category,
            secondary_category=event.secondary_category,
            region=event.detail.get("region", "") if event.detail else "",
            article_ids=[article.article_id for article in event.articles],
        )

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
