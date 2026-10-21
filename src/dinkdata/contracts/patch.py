"""`patch.json`: human corrections to one pipeline run. Owner: Robby (DESIGN 6.13, 9).

Corrections never overwrite model output. A patch lists add, change and delete operations on
the games, rallies and events of the run's events.json, by id, in the order they were made.
A change and a delete keep the old values, so a patch that no longer matches its events.json
fails instead of applying silently. `apply_patch` gives the patched events.json, which is saved
next to the patch in `labels/silver/{video_id}/{run_id}/`.
"""

from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from dinkdata.contracts.common import Handle, RunId, StrictModel, VideoId
from dinkdata.contracts.game_log import EventLog

Target = Literal["game", "rally", "event"]
CHILDREN = {"game": "rallies", "rally": "events"}
PARENT: dict[str, Target] = {"rally": "game", "event": "rally"}


class _Op(StrictModel):
    target: Target
    id: str = Field(min_length=1)
    author: Handle
    at: AwareDatetime


class Add(_Op):
    op: Literal["add"]
    parent: str | None = Field(description="The game of a new rally, the rally of a new event.")
    value: dict[str, Any] = Field(description="The new object, as in events.json.")

    @model_validator(mode="after")
    def _add_rules(self) -> "Add":
        if (self.parent is None) != (self.target == "game"):
            raise ValueError(f"add {self.id}: a game has no parent, a rally or event has one")
        if self.value.get("id") != self.id:
            raise ValueError(f"add {self.id}: value.id must be {self.id}")
        return self


class Change(_Op):
    op: Literal["change"]
    set: dict[str, Any] = Field(min_length=1, description="The new values of changed fields.")
    old: dict[str, Any] = Field(description="The values they replace.")

    @model_validator(mode="after")
    def _change_rules(self) -> "Change":
        if self.set.keys() != self.old.keys():
            raise ValueError(f"change {self.id}: set and old must name the same fields")
        if "id" in self.set or CHILDREN.get(self.target, "") in self.set:
            raise ValueError(f"change {self.id}: change ids and children with their own ops")
        return self


class Delete(_Op):
    op: Literal["delete"]
    old: dict[str, Any] = Field(description="The deleted object, as in events.json.")


Op = Annotated[Add | Change | Delete, Field(discriminator="op")]


class Patch(StrictModel):
    """The corrections to one run's events.json."""

    schema_: Literal["dinkdata.patch/v1"] = Field(alias="schema")
    run_id: RunId
    video_id: VideoId
    ops: list[Op]

    @model_validator(mode="after")
    def _in_time_order(self) -> "Patch":
        times = [op.at for op in self.ops]
        if times != sorted(times):
            raise ValueError("ops must be in the order they were made")
        return self


def _find(log: dict[str, Any], target: Target, id_: str) -> tuple[list[Any], int] | None:
    """The list holding the object and its index, or None."""
    lists = {"game": [log["games"]]}
    lists["rally"] = [g["rallies"] for g in log["games"]]
    lists["event"] = [r["events"] for g in log["games"] for r in g["rallies"]]
    for items in lists[target]:
        for i, item in enumerate(items):
            if item["id"] == id_:
                return items, i
    return None


def apply_patch(log: EventLog, patch: Patch) -> EventLog:
    """The patched events.json. Raises ValueError if the patch doesn't fit this log."""
    if patch.video_id != log.video.id:
        raise ValueError(f"patch is for {patch.video_id}, events.json for {log.video.id}")
    data = log.model_dump(mode="json", by_alias=True)
    for op in patch.ops:
        found = _find(data, op.target, op.id)
        if isinstance(op, Add):
            if found is not None:
                raise ValueError(f"add {op.id}: it already exists")
            if op.parent is None:
                items = data["games"]
            else:
                kind = PARENT[op.target]
                parent = _find(data, kind, op.parent)
                if parent is None:
                    raise ValueError(f"add {op.id}: no {kind} {op.parent}")
                items = parent[0][parent[1]][CHILDREN[kind]]
            items.append(deepcopy(op.value))
            items.sort(key=lambda item: item.get("start_t", item.get("t", 0)))
            continue
        if found is None:
            raise ValueError(f"{op.op} {op.id}: no such {op.target}")
        items, i = found
        if isinstance(op, Delete):
            if items[i] != op.old:
                raise ValueError(f"delete {op.id}: it changed since the patch was made")
            del items[i]
            continue
        for field, old in op.old.items():
            if items[i].get(field) != old:
                raise ValueError(f"change {op.id}: {field} is no longer {old!r}")
        items[i].update(deepcopy(op.set))
    return EventLog.model_validate(data)
