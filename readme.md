# Financial Monitor Agent

Automated financial monitoring and report generation system.

## Entry Point

The default entry point runs the V2 verified pipeline:

```bash
python main.py
```

V2 flow:

```text
Gather -> Analyst -> Whitelist Source Enrichment -> Event Representation
-> Journalist V2 -> Verifier -> Alignment Evaluation
-> Citation Diversity Evaluation -> Publisher V2 -> Event Memory
```

## V2 Focus

- Atomic claims extracted from generated reports.
- TF-IDF evidence retrieval over source article chunks.
- Deterministic alignment for numbers, entities, dates, and key phrases.
- Optional adversarial audit check using the configured LLM API key.
- Auditable publishing with claim-level verification details.
- Optional representation-layer clustering via `clustering_mode = "embedding"`.

## spEMO-inspired Design

This project adapts spEMO's representation-driven workflow from spatial biology to financial monitoring.

- spEMO builds spot-level representations from pathology image embeddings and biological text embeddings.
- This project builds event-level representations from financial news, policy sources, source-tier features, and verification signals.
- spEMO evaluates multi-modal alignment.
- This project evaluates claim-to-evidence alignment and citation diversity.

## Hallucination Reduction Strategy

The system reduces hallucination through:

1. Whitelist-only source collection.
2. Whitelist-only source enrichment before report generation.
3. Citation-required report generation.
4. Atomic claim extraction.
5. Evidence retrieval from original source chunks.
6. Deterministic alignment for numbers, dates, entities, and key phrases.
7. Citation diversity evaluation.
8. Publication gate based on verified rate, conflict rate, and not-found rate.

## Source Diversity

To avoid thin single-source reports, each event is enriched with additional whitelist-only sources before report generation. The Journalist module receives a diversified evidence pool and is instructed to cite multiple sources when available. Citation diversity is measured for each generated report.

Development notes and historical fix documents have been moved into `docs/`.
