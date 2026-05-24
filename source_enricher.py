import re
from typing import Dict, List

from models import Event, RawArticle
from source_policy import SourcePolicy


class WhitelistSourceEnricher:
    def __init__(
        self,
        min_sources_per_event: int = 3,
        max_sources_per_event: int = 6,
        days: int = 7,
        per_domain_results: int = 2,
        extract_full_text: bool = True,
    ):
        self.min_sources_per_event = min_sources_per_event
        self.max_sources_per_event = max_sources_per_event
        self.days = days
        self.per_domain_results = per_domain_results
        self.extract_full_text = extract_full_text
        self.policy = SourcePolicy()

    def enrich_events(self, events: List[Event]) -> List[Event]:
        return [self.enrich_event(event) for event in events]

    def enrich_event(self, event: Event) -> Event:
        existing_domains = {article.source.domain for article in event.articles}
        existing_urls = {article.url for article in event.articles}
        added: List[RawArticle] = []

        if len(existing_domains) >= self.min_sources_per_event:
            event.detail["added_source_count"] = 0
            event.detail["source_enrichment_queries"] = []
            return event

        queries = self._build_queries(event)
        for query in queries:
            if len({article.source.domain for article in event.articles + added}) >= self.min_sources_per_event:
                break
            if len(event.articles) + len(added) >= self.max_sources_per_event:
                break

            for article in self._gather_query(query):
                if article.url in existing_urls:
                    continue
                if not article.source.whitelisted:
                    continue
                if article.source.domain in existing_domains and len(existing_domains) > 1:
                    continue

                added.append(article)
                existing_urls.add(article.url)
                existing_domains.add(article.source.domain)

                if len(event.articles) + len(added) >= self.max_sources_per_event:
                    break

        event.articles = event.articles + added
        event.detail["added_source_count"] = len(added)
        event.detail["source_enrichment_queries"] = queries
        event.detail["source_domain_count"] = len({article.source.domain for article in event.articles})
        return event

    def _gather_query(self, query: str) -> List[RawArticle]:
        from gather_demo import gather

        return gather(
            [query],
            days=self.days,
            max_results=self.per_domain_results,
            save_json=False,
            extract_full_text=self.extract_full_text,
            allow_undated_articles=False,
        )

    def _build_queries(self, event: Event) -> List[str]:
        keywords = self._keywords(event)
        groups = self._groups_for_category(event.primary_category)
        domains = self.policy.domains_by_group(groups)
        current_domains = {article.source.domain for article in event.articles}

        queries = []
        for domain in domains:
            if domain in current_domains:
                continue
            queries.append(f"site:{domain} {keywords}")
        return queries

    @staticmethod
    def _groups_for_category(category: str) -> List[str]:
        mapping: Dict[str, List[str]] = {
            "macro": ["official", "media_depth", "media_official"],
            "regulation": ["official", "media_market", "media_official"],
            "market": ["media_market", "media_fast", "media_depth"],
            "industry": ["media_depth", "media_general", "media_fast"],
            "company": ["media_market", "media_depth", "media_general"],
        }
        return mapping.get(category, ["official", "media_depth", "media_market", "media_general"])

    @staticmethod
    def _keywords(event: Event) -> str:
        text = f"{event.main_title} {event.summary}"
        latin = re.findall(r"[A-Za-z0-9][A-Za-z0-9._%-]{1,}", text)
        cjk_terms = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        tokens = []
        for token in latin + cjk_terms:
            if token not in tokens:
                tokens.append(token)
        return " ".join(tokens[:8]) or event.main_title
