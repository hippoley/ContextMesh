import os
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from contextmesh.uploads import S3MultipartAdapter


pytestmark = pytest.mark.skipif(
    os.getenv("CONTEXTMESH_MINIO_E2E") != "1",
    reason="requires live MinIO test service",
)


def _put(url: str, payload: bytes) -> str:
    req = Request(url, data=payload, method="PUT")
    with urlopen(req, timeout=30) as response:
        assert 200 <= response.status < 300
        return response.headers["ETag"]


def test_real_minio_multipart_resume_complete_and_materialize(tmp_path: Path):
    bucket = os.environ["CONTEXTMESH_S3_BUCKET"]
    adapter = S3MultipartAdapter.from_env()
    adapter.client.create_bucket(Bucket=bucket)

    key, upload_id = adapter.begin("integration-session", "large.bin", "application/octet-stream")
    first = b"a" * (5 * 1024 * 1024)
    second = b"tail-of-object"

    etag1 = _put(adapter.presign_part(key=key, upload_id=upload_id, part_number=1), first)

    # This is the resume boundary: a fresh ListParts sees the already committed part.
    remote = adapter.list_parts(key=key, upload_id=upload_id)
    assert [p["part_number"] for p in remote] == [1]
    assert remote[0]["size_bytes"] == len(first)
    assert remote[0]["etag"] == etag1

    etag2 = _put(adapter.presign_part(key=key, upload_id=upload_id, part_number=2), second)
    remote = adapter.list_parts(key=key, upload_id=upload_id)
    assert [p["part_number"] for p in remote] == [1, 2]
    assert remote[1]["etag"] == etag2

    uri = adapter.complete(key=key, upload_id=upload_id, parts=remote)
    assert uri == f"s3://{bucket}/{key}"

    out = adapter.materialize(key=key, destination=tmp_path / "downloaded.bin")
    assert out.read_bytes() == first + second


def test_real_minio_abort_removes_incomplete_upload():
    adapter = S3MultipartAdapter.from_env()
    key, upload_id = adapter.begin("abort-session", "abort.bin")
    _put(adapter.presign_part(key=key, upload_id=upload_id, part_number=1), b"x" * (5 * 1024 * 1024))
    assert adapter.list_parts(key=key, upload_id=upload_id)
    adapter.abort(key=key, upload_id=upload_id)

    response = adapter.client.list_multipart_uploads(Bucket=adapter.bucket)
    uploads = response.get("Uploads", [])
    assert all(item.get("UploadId") != upload_id for item in uploads)
