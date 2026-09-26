# ContextMesh web surfaces

This directory contains **two different web surfaces** that intentionally share visual language but have different deployment contracts.

## 1. Runtime Workspace

Files:

- `index.html`
- `admin.html`
- `api.html`
- `app.js`
- `app.css`

These pages are served by the ContextMesh FastAPI runtime and depend on live `/api/**`, `/health`, SSE, ingest, evaluation, and admin endpoints.

They are **not** published as the public GitHub Pages site.

Local/runtime entry points:

```text
/        Workspace
/admin   Admin
/docs    API docs
```

## 2. Public Reality Lab

File:

- `reality.html`

This is a self-contained static public surface for verified Reality Probes, evidence-stage failures, before/after results, and contributor entry points.

GitHub Pages publishes a staged artifact built by:

```text
.github/workflows/pages.yml
```

The workflow intentionally maps:

```text
site/reality.html -> Pages /index.html
site/reality.html -> Pages /reality.html
assets/contextmesh-social-preview.png -> Pages /assets/...
```

So the public Pages root is the Reality Lab rather than a backend-dependent Runtime Workspace.

Expected public URL after the one-time Pages enablement:

```text
https://hippoley.github.io/ContextMesh/
```

## Release gate

Every public-site change is checked by:

```bash
python scripts/check_reality_site.py
```

The check protects the public/runtime boundary and verifies:

- no Workspace/Admin/API-only navigation leaks into the static site;
- one canonical OpenGraph metadata set;
- unique Reality Case deep links;
- one share/run/evidence path per case;
- the 1280x640 PNG social preview.

## Editing rule

If a change needs a live ContextMesh API, it belongs to the **Runtime Workspace**.

If it must remain useful on a static host with no backend, it belongs to the **Public Reality Lab**.
