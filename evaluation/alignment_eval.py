from typing import Dict, List

from models import ClaimBasedReport, ClaimType, VerificationStatus


def evaluate_claim_evidence_alignment(report: ClaimBasedReport) -> Dict[str, float]:
    factual_claims = [claim for claim in report.claims if claim.claim_type == ClaimType.FACTUAL]
    total = len(factual_claims)
    if total == 0:
        return {
            "citation_coverage": 0.0,
            "evidence_hit_rate": 0.0,
            "verified_rate": 0.0,
            "conflict_rate": 0.0,
            "not_found_rate": 0.0,
        }

    cited = sum(1 for claim in factual_claims if claim.source_ids or claim.source_urls)
    evidence_hits = sum(
        1
        for claim in factual_claims
        if claim.supporting_evidence
        or claim.verification_status in {VerificationStatus.VERIFIED, VerificationStatus.CONFLICT}
    )
    verified = sum(1 for claim in factual_claims if claim.verification_status == VerificationStatus.VERIFIED)
    conflicts = sum(1 for claim in factual_claims if claim.verification_status == VerificationStatus.CONFLICT)
    not_found = sum(1 for claim in factual_claims if claim.verification_status == VerificationStatus.NOT_FOUND)

    return {
        "citation_coverage": cited / total,
        "evidence_hit_rate": evidence_hits / total,
        "verified_rate": verified / total,
        "conflict_rate": conflicts / total,
        "not_found_rate": not_found / total,
    }


def evaluate_reports_alignment(reports: List[ClaimBasedReport]) -> Dict[str, float]:
    if not reports:
        return {}
    metrics = [evaluate_claim_evidence_alignment(report) for report in reports]
    keys = metrics[0].keys()
    return {key: sum(item[key] for item in metrics) / len(metrics) for key in keys}
