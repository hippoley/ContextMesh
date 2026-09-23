# Multimodal fidelity matrix — v0.8

ContextMesh distinguishes **addressable ingest** from **model capability**. A format can be fully ingested while a selected judge route is still unable to inspect one of its modalities. In that case the evaluation is blocked instead of silently marking the block visited.

| Input | Ingest path tested | Addressing | Fidelity gate | v0.8 validation |
| --- | --- | --- | --- | --- |
| TXT | native text | char range | full | tested |
| Markdown | native text + headings | section + char range | full | tested |
| HTML | native text | char range | full for raw markup/text | tested |
| JSON | native text | char range | full for raw source | tested |
| XML | native text | char range | full for raw source | tested |
| YAML | native text | char range | full for raw source | tested |
| CSV | native table | row range | full | tested |
| PDF with text | pypdf + rendered page | page + text/visual channel | text + page visual both required | tested |
| Scanned PDF | rendered page | page visual | vision route required | tested |
| PPTX text/table | python-pptx + rendered slide | slide + text/visual channel | whole-slide visual protects layout | tested |
| PPTX image-only | rendered slide | slide visual | no placeholder may count as coverage | tested |
| XLSX values | openpyxl | sheet + row range | full cell representation | tested |
| XLSX formulas | openpyxl formula + cached-value dual read | sheet + row range | formula is preserved even when cached value is absent | tested |
| XLSX charts | chart references + rendered workbook visual | sheet/chart + workbook page | visual fallback required for chart appearance | tested |
| DOCX | python-docx text/tables + rendered pages | char/table/page | visual/layout loss blocks final score | tested |
| PNG/JPEG/etc. | native image block | image | vision route required | PNG tested; same adapter covers listed raster types |
| WAV/MP3/etc. | native/ffmpeg audio block | timeline | audio-capable route or transcript required | WAV tested |
| MP4/MOV/etc. | ffmpeg segment materialization | timeline | generic OpenAI-compatible adapter currently blocks raw video | MP4 tested |

## What “tested” means

The repository test suite creates real fixture files and runs them through the same ingest/runtime code used by the application. The suite verifies that:

- scanned PDF pages become real image coverage blocks rather than zero-block “100% coverage”;
- image-only PPTX files do not use placeholder text as semantic completion;
- Excel formulas survive even when no cached calculation result exists;
- a text-only judge cannot mark vision/audio/video blocks as visited;
- a partial ingest can reach 100% **execution** coverage over available blocks but still cannot produce a final score;
- actual media timeline blocks are materialized and addressable.

This matrix does **not** assert that every cloud/local model can consume every modality. Model-route capability is a separate execution gate.


## Route and relation validation

The format matrix is now paired with a model-route preflight. A corpus may have 100% ingest and semantic addressability but still be blocked if the selected route cannot inspect `vision`, `audio`, or `video` blocks. The runtime reports unsupported block IDs/capabilities before issuing model calls.

For compound documents, ContextMesh additionally co-locates same-page/same-slide text and visual blocks and follows explicit page/slide/sheet references. These are context aids only; they never replace the requirement that every required block be visited independently.


## Integrity and live-model gates

`contextmesh audit` validates that the addressable corpus is internally consistent after ingest. It does not claim model understanding. For model understanding, `contextmesh fidelity-live` performs exact needle recovery using a configured real model route and reports unsupported modality blocks explicitly. This distinction prevents parser success from being confused with end-to-end semantic success.

Every asset report records the SHA-256 of the uploaded source file so a fidelity run is auditable against the exact bytes that were ingested.
