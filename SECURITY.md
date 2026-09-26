# Security Policy

ContextMesh processes potentially sensitive corpora, model credentials, object-storage credentials, and evidence traces. The project is usable for local and controlled evaluation workflows, but **the current runtime is not a production-hardened multi-tenant security boundary**.

## Supported code

Security fixes target:

- the latest release line;
- current `main` when a fix has not yet been released.

Older snapshots and archived Reality Probe environments are preserved for reproducibility and may intentionally contain upstream behavior that has since changed.

## Current security boundary

### Safe default assumption

Treat ContextMesh as a **single-operator / trusted-environment runtime** unless you add your own perimeter controls.

The project currently does **not** claim production-grade:

- authentication;
- RBAC;
- tenant isolation;
- internet-facing admin access;
- untrusted multi-user execution isolation.

Do not expose `contextmesh serve`, the Admin UI, or worker/control endpoints directly to an untrusted network without an authenticated reverse proxy or equivalent access boundary.

## Corpus and model privacy

ContextMesh can be configured with local or remote model routes.

If a route points to a remote provider, the content sent to that route is subject to that provider's transport, retention, and data-processing terms. **ContextMesh does not make a remote model private merely because the corpus was ingested locally.**

Before evaluating sensitive evidence:

1. inspect the configured model route;
2. confirm which blocks/reduced state can leave the host;
3. prefer a local route when policy requires data to remain local;
4. avoid putting secrets directly in prompts, traces, fixtures, or public Reality Probes.

Reality Probe fixtures should be synthetic or already-public data.

## Credentials

Keep provider keys, S3/MinIO credentials, tokens, and connection secrets outside the repository.

Use environment variables or your deployment secret store. Never include live credentials in:

- `.env` files committed to Git;
- benchmark result JSON;
- GitHub issues or PRs;
- Reality Probe logs;
- screenshots or public traces.

The Reality Lab and machine-readable public manifest are intended to contain **public evidence only**.

## Object storage

The S3/MinIO path is designed for controlled storage backends. Bucket policy, encryption, network exposure, retention, and credential rotation remain deployment responsibilities.

The included MinIO CI path is a test environment, not a reference production security configuration.

## File ingestion

Treat uploaded files as untrusted input.

Even when a parser is memory-safe, documents can contain adversarial text or instructions intended to influence downstream language models. Parsing success is not evidence that document content is trustworthy.

ContextMesh's evidence lifecycle helps track visibility and authority; it is **not** a malware sandbox or a complete prompt-injection defense.

## Reality Probe disclosure

A public Reality Probe should never require publishing:

- customer data;
- private repositories;
- proprietary prompts;
- access tokens;
- personal information;
- exploit details for an unpatched security vulnerability.

If a failure can be reproduced with a synthetic fixture, use that fixture.

## Reporting a vulnerability

Please **do not publish exploitable security details in a normal GitHub issue**.

Use GitHub's private vulnerability reporting / Security advisory flow for this repository when available:

```text
Repository -> Security -> Advisories / Report a vulnerability
```

If private reporting is unavailable, open a minimal public issue stating that you need a private security contact **without including exploit details, credentials, or sensitive payloads**.

Useful reports include:

- affected version or commit;
- attack preconditions;
- impact;
- minimal non-sensitive reproduction;
- whether credentials or private corpus data may be exposed;
- a suggested mitigation, if known.

## Reality failure vs security issue

Ordinary retrieval misses, model hallucinations, ranking errors, evidence truncation, and benchmark disagreements generally belong in the [Reality failure template](.github/ISSUE_TEMPLATE/reality-failure.md) unless they create a concrete confidentiality, integrity, authorization, or code-execution risk.

## Production hardening roadmap

Important remaining hardening work includes:

- authentication and authorization;
- explicit tenant isolation;
- secure-by-default internet deployment guidance;
- multi-node queue security;
- provider credential scoping;
- stronger untrusted-file isolation;
- formal threat modeling for remote model/tool routes.

Until those boundaries are implemented and reviewed, ContextMesh should not be represented as a turnkey secure multi-tenant service.
