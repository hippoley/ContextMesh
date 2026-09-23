# Contributing

ContextMesh keeps three invariants:

1. Retrieval may schedule reading order; it must not silently remove required coverage units.
2. A final score must stay locked until ingest, semantic-readiness and execution gates pass.
3. Raw provenance must remain recoverable from every derived ContextBlock/evidence item.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,rich]'
pytest -q
contextmesh serve --host 127.0.0.1 --port 8765
```

Submit changes with tests that exercise the affected coverage/fidelity contract.
