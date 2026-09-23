# Security

ContextMesh processes untrusted enterprise files. Production deployments should isolate parsers, validate MIME/content signatures, enforce upload quotas, scan uploaded objects, keep provider credentials server-side, and use tenant-scoped object/catalog access controls.

Do not place API keys in the static `site/` build or commit them to the repository.
