# Validation v0.8

## Automated test suite

```text
55 / 55 tests passed
```

The suite now covers the original runtime/control-plane tests plus the v0.8 multimodal fidelity gates, route preflight, cross-modal co-location and explicit source-reference following.

### Runtime/control plane

- full execution-coverage gate
- reader ordering and neighbors
- hierarchy
- resume/checkpoints
- deterministic parallel execution
- retry/failure semantics
- score-preservation benchmark
- RLM bridge
- Workspace/Admin routes
- Context Explorer APIs
- EventBus / SSE control-plane plumbing
- Prometheus telemetry parser
- model-route persistence and capability metadata
- async ingest + async evaluation jobs

### Real format fixtures

- TXT / Markdown / HTML / JSON / XML / YAML
- CSV
- text PDF
- **scanned PDF**
- text PPTX
- **image-only PPTX**
- XLSX values
- **XLSX formula without cached result**
- **XLSX chart + workbook visual channel**
- DOCX text/table + visual/layout channel accounting
- direct PNG image
- WAV audio
- MP4 video timeline

See [`FIDELITY_MATRIX.md`](FIDELITY_MATRIX.md).

## Real HTTP smoke test

A v0.8 FastAPI process was started and exercised over HTTP.

```text
GET /health    200  version=0.8.0
GET /          200  Workspace
GET /admin     200  Admin
```

A real synchronous upload contained:

```text
scanned PDF
formula XLSX
PNG image
```

Result:

```text
required blocks:       3
ingest coverage:       100%
semantic coverage:     100%
unresolved units:      0
modalities:            image=2, table=1
coverage_ready:        true
```

The offline text-only judge was then intentionally used on the same corpus. v0.8 now performs route preflight before any expensive block inspection:

```text
preflight ready:       false
unsupported:           vision
execution coverage:    0%
model requests:        0
final score:           null
complete:              false
```

This is the intended safety behavior. **Addressable source data is not equivalent to a model having the capability to read that modality.**

## Three independent coverage contracts

A final score is only valid when all three conditions hold:

```text
Ingest coverage   = 100%   files parsed / accounted for
Semantic coverage = 100%   known source channels addressable
Execution coverage= 100%   selected judge actually inspected every required block
```

A failure in any layer locks the final score.

## Important interpretation

These tests establish the runtime's fidelity and gating behavior. They do not prove that progressive reduction is mathematically identical to a hypothetical unlimited full-attention model. Production model/judge combinations should retain a direct-vs-progressive calibration set and score-drift tolerance.


## Mixed-format fidelity smoke

`examples/fidelity_smoke.py` builds a real mixed corpus containing TXT, PNG, scanned PDF, PPTX, XLSX with formula/chart, DOCX, WAV and MP4, then ingests all files through the production path. On the validation host:

```text
assets:                8
required blocks:       14
ingest coverage:       100%
semantic coverage:     100%
unresolved units:      0
modalities:            text=3 image=7 table=2 audio=1 video=1
required capabilities: audio, video, vision
```

This verifies addressability and fidelity accounting. It does not claim that a text-only model can consume those modalities; route preflight blocks such a run before the first model call.

## Cross-block / cross-modal validation

- same PDF page text and rendered visual are co-located during inspection;
- same PPT slide text and rendered visual are co-located during inspection;
- explicit `page N`, `slide N`, and `sheet X` references are resolved into bounded context;
- related context never increments coverage on behalf of the referenced block: each required block still has to be visited itself.
