"""The rclone store: commands it runs and how it reads rclone's exit codes."""

import subprocess
from pathlib import Path

import pytest

from dinkdata.data import r2


class FakeRclone:
    """Records each rclone call and answers with a fixed exit code and output."""

    def __init__(self, code: int = 0, stdout: str = "") -> None:
        self.calls: list[list[str]] = []
        self.code, self.stdout = code, stdout

    def __call__(self, args, **_kwargs):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(args, self.code, self.stdout, "rclone said no")


@pytest.fixture
def fake(monkeypatch):
    def install(code: int = 0, stdout: str = "") -> FakeRclone:
        rclone = FakeRclone(code, stdout)
        monkeypatch.setattr(r2.subprocess, "run", rclone)
        return rclone

    return install


def test_exists_lists_the_folder_and_matches_the_exact_name(fake):
    rclone = fake(stdout="v_1.mp4\nv_10.mp4\n")
    store = r2.RcloneStore()
    assert store.exists("videos/v_1.mp4")
    assert not store.exists("videos/v_2.mp4")
    assert rclone.calls[0] == ["rclone", "lsf", "--files-only", "r2:dinkdata/videos"]


def test_a_missing_folder_means_the_file_is_missing(fake):
    fake(code=3)
    assert not r2.RcloneStore().exists("catalog/catalog.parquet")


def test_other_rclone_failures_raise(fake):
    fake(code=1)
    with pytest.raises(r2.RcloneError, match="rclone said no"):
        r2.RcloneStore().exists("videos/v_1.mp4")


def test_put_never_overwrites_unless_asked(fake):
    rclone = fake()
    store = r2.RcloneStore()
    store.put(Path("local.mp4"), "videos/v_1.mp4")
    store.put(Path("catalog.parquet"), "catalog/catalog.parquet", overwrite=True)
    assert rclone.calls == [
        ["rclone", "copyto", "--immutable", "local.mp4", "r2:dinkdata/videos/v_1.mp4"],
        ["rclone", "copyto", "catalog.parquet", "r2:dinkdata/catalog/catalog.parquet"],
    ]


def test_get_copies_to_the_local_path(fake):
    rclone = fake()
    r2.RcloneStore().get("catalog/id_map.parquet", Path("here.parquet"))
    assert rclone.calls == [
        ["rclone", "copyto", "r2:dinkdata/catalog/id_map.parquet", "here.parquet"]
    ]


@pytest.fixture
def s3():
    """A stubbed S3 client: each test lists the calls R2 should get and what it answers."""
    import boto3
    from botocore.stub import Stubber

    client = boto3.client(
        "s3",
        endpoint_url="https://r2.example",
        region_name="auto",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


def test_put_if_sends_if_match_with_the_etag_it_read(s3, tmp_path):
    from botocore.stub import ANY

    client, stub = s3
    local = tmp_path / "catalog.parquet"
    local.write_bytes(b"rows")
    expected = {"Bucket": "dinkdata", "Key": "catalog/catalog.parquet", "Body": ANY}
    stub.add_response("put_object", {"ETag": '"new"'}, expected | {"IfMatch": '"old"'})
    assert r2.RcloneStore(s3=client).put_if(local, "catalog/catalog.parquet", '"old"')


def test_put_if_creates_only_when_the_file_is_absent(s3, tmp_path):
    from botocore.stub import ANY

    client, stub = s3
    local = tmp_path / "id_map.parquet"
    local.write_bytes(b"rows")
    expected = {"Bucket": "dinkdata", "Key": "catalog/id_map.parquet", "Body": ANY}
    stub.add_response("put_object", {"ETag": '"new"'}, expected | {"IfNoneMatch": "*"})
    assert r2.RcloneStore(s3=client).put_if(local, "catalog/id_map.parquet", None)


@pytest.mark.parametrize(
    ("code", "status"), [("PreconditionFailed", 412), ("ConditionalRequestConflict", 409)]
)
def test_put_if_returns_false_when_someone_wrote_first(s3, tmp_path, code, status):
    client, stub = s3
    local = tmp_path / "catalog.parquet"
    local.write_bytes(b"rows")
    stub.add_client_error("put_object", code, http_status_code=status)
    assert not r2.RcloneStore(s3=client).put_if(local, "catalog/catalog.parquet", '"old"')


def test_put_if_raises_on_other_errors(s3, tmp_path):
    client, stub = s3
    local = tmp_path / "catalog.parquet"
    local.write_bytes(b"rows")
    stub.add_client_error("put_object", "AccessDenied", http_status_code=403)
    with pytest.raises(r2.RcloneError, match="AccessDenied"):
        r2.RcloneStore(s3=client).put_if(local, "catalog/catalog.parquet", '"old"')


def test_get_versioned_downloads_the_file_and_returns_its_etag(s3, tmp_path):
    import io

    from botocore.response import StreamingBody

    client, stub = s3
    body = StreamingBody(io.BytesIO(b"rows"), len(b"rows"))
    stub.add_response(
        "get_object",
        {"Body": body, "ETag": '"abc"'},
        {"Bucket": "dinkdata", "Key": "catalog/catalog.parquet"},
    )
    local = tmp_path / "catalog.parquet"
    assert r2.RcloneStore(s3=client).get_versioned("catalog/catalog.parquet", local) == '"abc"'
    assert local.read_bytes() == b"rows"


def test_get_versioned_returns_none_for_a_missing_file(s3, tmp_path):
    client, stub = s3
    stub.add_client_error("get_object", "NoSuchKey", http_status_code=404)
    local = tmp_path / "catalog.parquet"
    assert r2.RcloneStore(s3=client).get_versioned("catalog/catalog.parquet", local) is None
    assert not local.exists()


def test_the_s3_client_comes_from_the_rclone_variables(monkeypatch):
    monkeypatch.setenv("RCLONE_CONFIG_R2_ENDPOINT", "https://account.r2.example")
    monkeypatch.setenv("RCLONE_CONFIG_R2_ACCESS_KEY_ID", "id")
    monkeypatch.setenv("RCLONE_CONFIG_R2_SECRET_ACCESS_KEY", "secret")
    client = r2.RcloneStore().s3_client()
    assert client.meta.endpoint_url == "https://account.r2.example"
    assert client.meta.region_name == "auto"


def test_the_s3_client_needs_the_rclone_variables(monkeypatch):
    monkeypatch.delenv("RCLONE_CONFIG_R2_ENDPOINT", raising=False)
    with pytest.raises(r2.RcloneError, match="RCLONE_CONFIG_R2_ENDPOINT"):
        r2.RcloneStore().s3_client()
