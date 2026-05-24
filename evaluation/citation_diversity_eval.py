import re
from typing import Dict

from models import ClaimBasedReport, Event


def evaluate_citation_diversity(report: ClaimBasedReport, event: Event | None = None) -> Dict[str, float | int]:
    available_domains = set()
    if event:
        available_domains = {article.source.domain for article in event.articles}
    if not available_domains:
        available_domains = {
            meta.split("|")[0]
            for meta in report.source_mapping.values()
            if "|" in meta and meta.split("|")[0]
        }

    cited_ids = set()
    report_text = "\n".join(
        [report.summary_text, report.background_text, report.analysis_text, report.outlook_text]
    )
    cited_ids.update(re.findall(r"\[cite:\s*(\d+)\]", report_text))
    for claim in report.claims:
        cited_ids.update(claim.source_ids or [])

    cited_domains = set()
    for cite_id in cited_ids:
        meta = report.source_mapping.get(str(cite_id), "")
        if "|" in meta:
            cited_domains.add(meta.split("|")[0])

    total_sources_available = len(available_domains)
    cited_source_count = len(cited_ids)
    cited_domain_count = len(cited_domains)
    denominator = total_sources_available or len(report.source_mapping) or 1

    return {
        "total_sources_available": total_sources_available,
        "cited_sources": cited_source_count,
        "cited_domains": cited_domain_count,
        "citation_diversity_rate": cited_domain_count / denominator,
    }
