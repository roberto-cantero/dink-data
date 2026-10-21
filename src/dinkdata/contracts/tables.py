"""Shared machinery for the Parquet contracts: catalog, frames, ball, candidates, ball labels.

Each table is a pyarrow schema, which is the contract, plus a pydantic row model for the
generated JSON Schema and for code that builds rows. `TableContract` checks a whole table
with vectorised rules, so validating a game of 27,000 frames is cheap.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

R = TypeVar("R", bound=BaseModel)


def fixed_list(item: pa.DataType, size: int) -> pa.DataType:
    # Parquet names list items "element", so the schema uses that name to survive a round trip.
    return pa.list_(pa.field("element", item), size)


def column(table: pa.Table, name: str) -> np.ndarray:
    return table.column(name).to_numpy(zero_copy_only=False)


def is_null(table: pa.Table, name: str) -> np.ndarray:
    return np.asarray(table.column(name).is_null().to_pylist(), dtype=bool)


def check_frame_order(table: pa.Table) -> list[str]:
    """Rows sorted by frame with no repeats, and t rising with frame."""
    frame, t = column(table, "frame"), column(table, "t")
    if np.any((frame < 0) | ~np.isfinite(t) | (t < 0)):
        return ["frame and t must be non-negative"]
    if np.any(np.diff(frame) <= 0):
        return ["rows must be sorted by frame, one row per frame"]
    if np.any(np.diff(t) <= 0):
        return ["t must rise with frame"]
    return []


def check_unit(table: pa.Table, *names: str) -> list[str]:
    """Each named column, ignoring nulls, lies between 0 and 1."""
    errors = []
    for name in names:
        array = table.column(name).combine_chunks()
        while pa.types.is_list(array.type) or pa.types.is_fixed_size_list(array.type):
            array = array.flatten()
        values = array.drop_null().to_numpy(zero_copy_only=False)
        if np.any(~((values >= 0) & (values <= 1))):
            errors.append(f"{name} must be between 0 and 1")
    return errors


def check_position(table: pa.Table) -> list[str]:
    """x and y are set exactly when the ball is visible."""
    visible = column(table, "visible")
    if np.any(is_null(table, "x") != is_null(table, "y")):
        return ["x and y must both be set or both null"]
    if np.any(is_null(table, "x") == visible):
        return ["x and y are set exactly when visible is true"]
    return []


@dataclass(frozen=True)
class TableContract(Generic[R]):
    """A Parquet file format: its schema, its row model and its whole-table rules."""

    schema: pa.Schema
    row: type[R]
    rules: Callable[[pa.Table], list[str]]

    @property
    def name(self) -> str:
        return (self.schema.metadata or {})[b"schema"].decode()

    def table(self, rows: list[R]) -> pa.Table:
        return pa.Table.from_pylist([r.model_dump() for r in rows], schema=self.schema)

    def rows(self, table: pa.Table) -> list[R]:
        return [self.row.model_validate(r) for r in table.to_pylist()]

    def errors(self, table: pa.Table) -> list[str]:
        """Everything wrong with a table: its schema, its nulls, then its rules."""
        if not table.schema.equals(self.schema, check_metadata=True):
            return [f"schema doesn't match {self.name}:\n{table.schema}"]
        nulls = [
            f"{f.name} has nulls"
            for f in self.schema
            if not f.nullable and table.column(f.name).null_count
        ]
        if nulls or len(table) == 0:
            return nulls
        return self.rules(table)

    def read(self, path: Path) -> pa.Table:
        """Read the file and validate it. Raises ValueError if it is invalid."""
        table = pq.read_table(path)
        errors = self.errors(table)
        if errors:
            raise ValueError(f"{path.name} is invalid: " + "; ".join(errors))
        return table

    def write(self, table: pa.Table, path: Path) -> None:
        errors = self.errors(table)
        if errors:
            raise ValueError(f"{self.name} table is invalid: " + "; ".join(errors))
        pq.write_table(table, path)
