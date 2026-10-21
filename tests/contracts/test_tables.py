"""The Parquet contracts: catalog, frames, ball, candidates and ball labels."""

from datetime import datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from dinkdata.contracts.ball import BALL, BALL_LABELS
from dinkdata.contracts.candidates import CANDIDATES
from dinkdata.contracts.catalog import CATALOG
from dinkdata.contracts.frames import FRAMES
from dinkdata.contracts.tables import TableContract
from tests.contracts.examples import example

CONTRACTS: dict[str, TableContract] = {
    "catalog": CATALOG,
    "frames": FRAMES,
    "ball": BALL,
    "candidates": CANDIDATES,
    "ball_labels": BALL_LABELS,
}


def rows(name: str, change=None):
    data = example(name)
    if change:
        change(data)
    return [CONTRACTS[name].row.model_validate(r) for r in data]


def table(name: str, change=None) -> pa.Table:
    """A table built straight from rows, skipping the row model, as other code might write it."""
    data = example(name)
    if change:
        change(data)
    schema = CONTRACTS[name].schema
    times = [f.name for f in schema if pa.types.is_timestamp(f.type)]
    for row in data:
        for field in times:
            if row[field] is not None:
                row[field] = datetime.fromisoformat(row[field])
    return pa.Table.from_pylist(data, schema=schema)


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_example_round_trips_through_parquet(name, tmp_path):
    contract = CONTRACTS[name]
    path = tmp_path / f"{name}.parquet"
    contract.write(contract.table(rows(name)), path)
    back = contract.rows(contract.read(path))
    # float32 columns lose precision, so compare as tables, which hold the same float32 values.
    assert contract.table(back).equals(contract.table(rows(name)))


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_schema_name_is_in_the_metadata(name):
    assert CONTRACTS[name].name == f"dinkdata.{name}/v1"


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_example_table_has_no_errors(name):
    assert CONTRACTS[name].errors(table(name)) == []


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_missing_metadata_is_an_error(name):
    bad = table(name).replace_schema_metadata(None)
    assert any("schema" in e for e in CONTRACTS[name].errors(bad))


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_read_refuses_a_bad_file(name, tmp_path):
    path = tmp_path / f"{name}.parquet"
    pq.write_table(table(name, lambda d: d.append(dict(d[0]))), path)
    with pytest.raises(ValueError, match="invalid"):
        CONTRACTS[name].read(path)


def first(field, value):
    return lambda d: d[0].update({field: value})


@pytest.mark.parametrize(
    ("name", "change", "message"),
    [
        pytest.param("catalog", first("video_id", "v_5eed00000000e002"), "unique", id="dup video"),
        pytest.param("catalog", first("video_id", "session-123"), "video_id", id="raw id"),
        pytest.param("catalog", first("split", "val"), "split", id="unknown split"),
        pytest.param("catalog", first("setup", "overhead"), "setup", id="unknown setup"),
        pytest.param("catalog", first("size_bytes", 0), "size_bytes", id="empty file"),
        pytest.param(
            "catalog",
            lambda d: d[1].update(facility_id=d[0]["facility_id"]),
            "one split",
            id="facility in two splits",
        ),
        pytest.param("frames", lambda d: d.pop(2), "gaps", id="frame missing"),
        pytest.param("frames", first("t", 0.01), "first frame", id="first t not 0"),
        pytest.param("frames", lambda d: d[3].update(t=0.05), "rise", id="t goes back"),
        pytest.param("frames", first("dropped_before", 2), "first frame", id="drops before 0"),
        pytest.param("ball", lambda d: d[2].update(x=1.0), "x and y", id="x without y"),
        pytest.param("ball", first("visible", False), "visible", id="hidden with a position"),
        pytest.param(
            "ball", lambda d: d[2].update(interpolated=True), "interpolated", id="interp hidden"
        ),
        pytest.param("ball", first("conf", 1.2), "conf", id="conf above 1"),
        pytest.param("ball", lambda d: d[0]["peaks"].extend([[1, 1, 0.1]] * 2), "peaks", id="4"),
        pytest.param("ball", first("peaks", [[1.0, 1.0, 2.0]]), "peak", id="peak score"),
        pytest.param("candidates", first("hitter", [0.5, 0.5, 0.5, 0.0]), "sum", id="sum > 1"),
        pytest.param("candidates", first("p_net", -0.1), "p_net", id="negative p"),
        pytest.param("candidates", lambda d: d.reverse(), "sorted", id="unsorted"),
        pytest.param("ball_labels", first("split", "test"), "split", id="mixed splits"),
        pytest.param("ball_labels", first("visible", False), "visible", id="hidden click"),
    ],
)
def test_table_rules(name, change, message):
    errors = CONTRACTS[name].errors(table(name, change))
    assert any(message in e for e in errors), errors


@pytest.mark.parametrize(
    ("name", "change"),
    [
        pytest.param("catalog", first("facility_id", "facility-1"), id="raw facility"),
        pytest.param("catalog", first("uploaded_at", "2026-10-18T19:42:00"), id="naive time"),
        pytest.param("catalog", first("notes", "x" * 501), id="long notes"),
        pytest.param("frames", first("dropped_before", -1), id="negative drops"),
        pytest.param("ball", lambda d: d[2].update(x=1.0, y=2.0), id="hidden with position"),
        pytest.param("ball", lambda d: d[1].update(x=None, y=None, visible=False), id="interp"),
        pytest.param("candidates", first("hitter", [0.5, 0.2, 0.2, 0.0]), id="hitter sum"),
        pytest.param("candidates", first("hitter", [1.0, 0.0, 0.0]), id="three hitters"),
        pytest.param("ball_labels", first("split", "val"), id="unknown split"),
        pytest.param("ball_labels", first("conf", 1.0), id="unknown column"),
    ],
)
def test_row_rejects(name, change):
    with pytest.raises(ValidationError):
        rows(name, change)


def test_wrong_column_type_is_an_error():
    good = table("frames")
    bad = good.set_column(0, "frame", good.column("frame").cast(pa.int32()))
    assert any("schema" in e for e in FRAMES.errors(bad))
