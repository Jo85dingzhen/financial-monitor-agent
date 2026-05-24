# Financial Monitor Agent

Automated financial monitoring and report generation system.

## Entry Points

The default entry point now runs the V2 verified pipeline:

```bash
python main.py
```

V2 flow:

```text
Gather -> Analyst -> Journalist V2 -> Verifier -> Publisher V2
```

The legacy V1 pipeline is preserved as:

```bash
python main_legacy.py
```

## V2 Focus

- Atomic claims extracted from generated reports.
- TF-IDF evidence retrieval over source article chunks.
- Deterministic alignment for numbers, entities, dates, and key phrases.
- Optional adversarial audit check using the configured LLM API key.
- Auditable publishing with claim-level verification details.
- Optional representation-layer clustering via `clustering_mode = "embedding"`.

Development notes and historical fix documents have been moved into `docs/`.
