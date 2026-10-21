"""`candidates.parquet`: the event spotter's candidates. Owner: Robby (DESIGN 6.7).

One row per candidate frame, sorted by frame. `conf` is the probability that any event happens
at this frame, and `p_hit`, `p_bounce` and `p_net` split it by type. `hitter` gives the
probability that each of p1 to p4 hit the ball, and is null when the candidate can't be a hit.
The rally grammar reads this table and writes the events in events.json.
"""

import numpy as np
import pyarrow as pa
from pydantic import Field, model_validator

from dinkdata.contracts.common import Conf, Frame, Seconds, StrictModel
from dinkdata.contracts.tables import TableContract, check_frame_order, check_unit, fixed_list

SCHEMA_NAME = "dinkdata.candidates/v1"
SUM_TOLERANCE = 1e-3

CANDIDATES_SCHEMA = pa.schema(
    [
        pa.field("frame", pa.int64(), nullable=False),
        pa.field("t", pa.float64(), nullable=False),
        pa.field("conf", pa.float32(), nullable=False),
        pa.field("p_hit", pa.float32(), nullable=False),
        pa.field("p_bounce", pa.float32(), nullable=False),
        pa.field("p_net", pa.float32(), nullable=False),
        pa.field("hitter", fixed_list(pa.float32(), 4)),
    ],
    metadata={"schema": SCHEMA_NAME},
)


class CandidateRow(StrictModel):
    """One row of candidates.parquet."""

    frame: Frame
    t: Seconds
    conf: Conf = Field(description="Probability that any event happens at this frame.")
    p_hit: Conf
    p_bounce: Conf
    p_net: Conf
    hitter: tuple[Conf, Conf, Conf, Conf] | None = Field(
        description="Probability that p1, p2, p3 or p4 hit it. Sums to 1. null if not a hit."
    )

    @model_validator(mode="after")
    def _hitter_sums_to_one(self) -> "CandidateRow":
        if self.hitter is not None and abs(sum(self.hitter) - 1) > SUM_TOLERANCE:
            raise ValueError(f"hitter probabilities must sum to 1, not {sum(self.hitter)}")
        return self


def _rules(table: pa.Table) -> list[str]:
    errors = check_frame_order(table)
    errors += check_unit(table, "conf", "p_hit", "p_bounce", "p_net", "hitter")
    hitter = table.column("hitter").drop_null().combine_chunks()
    if len(hitter):
        sums = hitter.flatten().to_numpy(zero_copy_only=False).reshape(-1, 4).sum(axis=1)
        if np.any(np.abs(sums - 1) > SUM_TOLERANCE):
            errors.append("hitter probabilities must sum to 1")
    return errors


CANDIDATES = TableContract(CANDIDATES_SCHEMA, CandidateRow, _rules)
