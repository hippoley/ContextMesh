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

Implemented:

- `CreateMultipartUpload`;
- persisted remote upload ID/object key;
- presigned `UploadPart` URLs;
- remote `ListParts` reconciliation for resume;
- ordered `PartNumber + ETag` completion;
- abort;
- materialization into the existing parser pipeline.

Not yet validated in this repository environment:

- a live AWS S3 bucket;
- a live MinIO deployment;
- browser interruption/reconnect against a real remote object store;
- multipart retry behavior under injected packet loss;
- IAM/bucket policy variants;
- very large 1–5 GB remote upload stress.

Therefore the S3/MinIO transport should be described as **implemented, not yet live-E2E verified**.

## Compatibility

The original multipart-form ingest endpoint remains available for API compatibility. The v0.14 Workspace uses the resumable session path.

## Next validation gates

Before calling remote multipart storage production-ready:

1. run a MinIO integration job in CI or a disposable test environment;
2. test interrupted upload/resume with missing-part reconciliation;
3. test duplicate/retried part writes;
4. test final object checksum and parser input identity;
5. stress at multi-GB size;
6. validate cleanup/abort of stale incomplete uploads.
