"""players.parquet: one row per frame per track, as a pyarrow schema."""

from collections.abc import Iterator
from typing import Any

import pyarrow as pa
import pytest
from pydantic import ValidationError

from dinkdata.contracts.players import (
    PLAYERS_SCHEMA,
    PlayerRow,
    players_errors,
    players_table,
    read_players,
    table_rows,
    write_players,
)
from tests.contracts.examples import example


def rows(change=None) -> list[PlayerRow]:
    data = example("players")
    if change:
        change(data)
    return [PlayerRow.model_validate(row) for row in data]


def numbers(value: Any) -> Iterator[float]:
    if isinstance(value, dict):
        for v in value.values():
            yield from numbers(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from numbers(v)
    elif isinstance(value, int | float) and not isinstance(value, bool):
        yield value


def test_example_round_trips_through_parquet(tmp_path):
    original = rows()
    write_players(players_table(original), tmp_path / "players.parquet")
    table = read_players(tmp_path / "players.parquet")
    assert table.schema.equals(PLAYERS_SCHEMA, check_metadata=True)
    back = table_rows(table)
    # Boxes and keypoints are float32, so compare numbers to float32 precision.
    for a, b in zip(original, back, strict=True):
        assert (a.player_id, a.team, a.estimated_foot) == (b.player_id, b.team, b.estimated_foot)
        assert (a.foot_court is None) == (b.foot_court is None)
        assert list(numbers(b.model_dump())) == pytest.approx(
            list(numbers(a.model_dump())), rel=1e-6
        )


def test_schema_name_is_in_the_metadata():
    assert PLAYERS_SCHEMA.metadata == {b"schema": b"dinkdata.players/v1"}


def test_valid_table_has_no_errors():
    assert players_errors(players_table(rows())) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(lambda d: d.reverse(), "sorted", id="not sorted by frame"),
        pytest.param(lambda d: d[1].update(track_id=3), "duplicate", id="duplicate frame track"),
        pytest.param(lambda d: d[2].update(t=184.0), "t", id="t goes backwards"),
    ],
)
def test_table_rules(change, message):
    errors = players_errors(players_table(rows(change)))
    assert any(message in e for e in errors), errors


def test_wrong_column_type_is_an_error():
    table = players_table(rows())
    table = table.set_column(
        table.schema.get_field_index("conf"), "conf", table.column("conf").cast(pa.float64())
    )
    assert any("schema" in e for e in players_errors(table))


def test_missing_metadata_is_an_error():
    table = players_table(rows()).replace_schema_metadata(None)
    assert any("schema" in e for e in players_errors(table))


def test_values_are_checked_even_when_written_by_other_code():
    table = players_table(rows())
    bad = pa.array([1.5, 0.91, 0.62], pa.float32())
    table = table.set_column(table.schema.get_field_index("conf"), "conf", bad)
    table = table.replace_schema_metadata(PLAYERS_SCHEMA.metadata)
    assert players_errors(table)


def test_read_players_refuses_a_bad_file(tmp_path):
    table = players_table(rows(lambda d: d.reverse()))
    path = tmp_path / "players.parquet"
    import pyarrow.parquet as pq

    pq.write_table(table, path)
    with pytest.raises(ValueError, match="sorted"):
        read_players(path)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d[0].update(player_id="p7"), id="unknown player"),
        pytest.param(lambda d: d[0].update(team="B"), id="p1 on team B"),
        pytest.param(lambda d: d[2].update(team="A"), id="team without player"),
        pytest.param(lambda d: d[0].update(box=[671.0, 288.0, 612.5, 455.5]), id="box inverted"),
        pytest.param(lambda d: d[0]["keypoints"].pop(), id="16 keypoints"),
        pytest.param(lambda d: d[0].update(foot_conf=None), id="foot without foot_conf"),
        pytest.param(lambda d: d[2].update(foot_conf=0.4), id="foot_conf without foot"),
        pytest.param(lambda d: d[0].update(conf=1.01), id="conf above 1"),
        pytest.param(lambda d: d[0].update(frame=-1), id="negative frame"),
        pytest.param(lambda d: d[0].update(name="x"), id="unknown column"),
    ],
)
def test_row_rejects(change):
    with pytest.raises(ValidationError):
        rows(change)
