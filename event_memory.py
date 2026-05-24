import json
import os
from datetime import datetime
from typing import Dict, List

from embedding_engine import EmbeddingEngine
from models import Event, VerificationResult


class EventMemoryStore:
    def __init__(self, path: str = "memory/event_memory.jsonl"):
        self.path = path
        self.engine = EmbeddingEngine()
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def append_run(self, events: List[Event], verification_results: List[VerificationResult]) -> str:
        results_by_event: Dict[str, VerificationResult] = {
            result.event_id: result for result in verification_results
        }
        with open(self.path, "a", encoding="utf-8") as f:
            for event in events:
                result = results_by_event.get(event.event_id)
                representation = self.engine.build_event_representation(event)
                row = {
                    "event_id": event.event_id,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "title": event.main_title,
                    "summary": event.summary,
                    "primary_category": event.primary_category,
                    "secondary_category": event.secondary_category,
                    "region": representation.region,
                    "score": event.score,
                    "article_ids": representation.article_ids,
                    "source_domains": sorted({article.source.domain for article in event.articles}),
                    "representation": representation.text_embedding,
                    "verification_status": result.status if result else "UNVERIFIED",
                    "verified_claims": result.verified_claims if result else 0,
                    "failed_claims": result.failed_claims if result else 0,
                    "not_found_claims": result.not_found_claims if result else 0,
                    "publish_allowed": result.publish_allowed if result else False,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return self.path

    def retrieve_similar_events(self, title: str, summary: str = "", top_k: int = 5) -> List[dict]:
        query_vec = self.engine.embed_text(f"{title} {summary}")
        rows = []
        if not os.path.exists(self.path):
            return rows

        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                score = self.engine.cosine_similarity(query_vec, row.get("representation", []))
                row["similarity"] = score
                rows.append(row)

        rows.sort(key=lambda item: item.get("similarity", 0.0), reverse=True)
        return rows[:top_k]


def save_event_memory(events: List[Event], verification_results: List[VerificationResult]) -> str:
    return EventMemoryStore().append_run(events, verification_results)


def retrieve_similar_events(query_event: Event, top_k: int = 5) -> List[dict]:
    return EventMemoryStore().retrieve_similar_events(
        query_event.main_title,
        query_event.summary,
        top_k=top_k,
    )
