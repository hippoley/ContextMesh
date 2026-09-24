# ContextMesh v0.14 Validation

## Automated regression

GitHub Actions runs the suite on Python 3.11 and 3.12.

Validated HEAD after the resumable-upload integration:

```text
82 passed, 3 skipped
```

The suite covers the existing full-coverage runtime plus the v0.13/v0.14 additions.

## v0.13 durable execution plane

Verified in automated tests:

- queue state persists across a new `SQLiteJobQueue` instance;
- one worker atomically leases a queued job;
- expired worker leases are reclaimable by another worker;
- queued cancellation prevents later leasing;
- retry attempts persist and become terminal at `max_attempts`;
- worker heartbeats expose worker identity and active queue item;
- existing asynchronous ingest/evaluation tests still complete through the queue;
- checkpoint cancel/resume behavior remains intact.

The SQLite WAL queue is intentionally scoped to workers on the same host. It is not presented as a multi-node queue backend.

## v0.14 resumable uploads

Verified locally/in CI:

- upload-session metadata survives construction of a new store instance;
- already-received parts are reported so a resumed client can skip them;
- local parts can be validated with SHA-256;
- a bad part checksum is rejected;
- completion is blocked when parts are missing;
- final local assembly preserves the original bytes;
- the HTTP flow works end to end for:
  - create session;
  - upload part;
  - inspect status/missing parts;
  - complete upload.

The Workspace now stores upload-session IDs in browser local storage and asks the server for missing parts before sending data again.

## S3 / MinIO status

A dedicated GitHub Actions integration job now starts a real MinIO server and exercises the S3-compatible multipart transport end to end.

Verified against live MinIO in CI:

- `CreateMultipartUpload`;
- SigV4 path-style presigned `UploadPart`;
- upload of a multipart object with a >=5 MiB non-final part;
- remote `ListParts` reconciliation after the first part (resume boundary);
- ordered `PartNumber + ETag` completion;
- materialization/download with byte-for-byte payload verification;
- abort of an incomplete multipart upload.

The live test discovered a real compatibility issue during development: boto3 initially emitted a legacy SigV2 presigned URL for the custom MinIO endpoint and MinIO returned `SignatureDoesNotMatch`. The adapter now explicitly uses SigV4 with path-style S3 addressing, and the MinIO integration passes.

Still not validated in this repository environment:

- a live AWS S3 account with IAM policies;
- browser interruption/reconnect over a real WAN;
- multipart retry behavior under injected packet loss;
- multi-GB 1–5 GB upload stress;
- lifecycle cleanup of abandoned remote multipart uploads at scale.

Therefore the MinIO-compatible transport is now **live-E2E verified in CI**. AWS S3 compatibility follows the same S3 multipart protocol but should still receive a separate IAM/policy integration pass before being called production-verified.

## Compatibility

The original multipart-form ingest endpoint remains available for API compatibility. The v0.14 Workspace uses the resumable session path.

## Next validation gates

Before calling remote multipart storage production-ready:

1. test browser interruption/reconnect across a real network boundary;
2. inject failed/retried part uploads;
3. test duplicate/retried part writes;
4. verify final object checksum and parser input identity for remote ingest;
5. stress at multi-GB size;
6. validate lifecycle cleanup of stale incomplete uploads;
7. run the same integration against AWS S3 with least-privilege IAM.
