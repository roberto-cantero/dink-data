"""Events mode: exact-frame marks on top of rally gold, turned into a gold `events.json`.

Rally gold (`labels/gold-rallies/`) owns the rallies: their ids, games, serves and replays.
Events mode owns each rally's exact start and end frames, its hits, bounces and net events,
its end reason and the confirmed winner (DESIGN 6.13 and 9). The page sends frame indexes
only. Every `t` here comes from the video's frame times, so a `t` can't drift from its frame.

A rally's start, end and winner start as suggestions from rally gold. The labeller accepts or
replaces each one, and a rally is reviewed once all three are settled and it has an end reason.
No camera is calibrated yet, so a bounce keeps the pixel the labeller clicked, and `court_xy`
and `in` stay null until a calibration maps them.
"""

import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from dinkdata.contracts.common import Frame, PlayerId, RallyId, StrictModel, Team, team_of
from dinkdata.contracts.events import EndReason
from dinkdata.contracts.game_log import EventLog, Rally
from dinkdata.contracts.rallies import LabelRally, RallyLabels

Finite = Annotated[float, Field(allow_inf_nan=False)]
Settled = Literal["start", "end", "winner"]
Uncertain = Literal["start", "end", "winner", "end_reason", "hitter"]
Boundary = Literal["start", "end"]

_PLAYERS: tuple[PlayerId, ...] = ("p1", "p2", "p3", "p4")


@dataclass(frozen=True)
class Footage:
    """What events mode needs to know about the video."""

    video_id: str
    times: Sequence[float]
    """Seconds from the first frame, for every frame index, from the video reader."""
    fps_nominal: float
    dropped_frames: int
    width: int
    height: int

    def nearest(self, t: float) -> int:
        """The frame whose time is nearest `t`. A tie goes to the earlier frame."""
        i = bisect.bisect_left(self.times, t)
        if i == 0:
            return 0
        if i == len(self.times):
            return len(self.times) - 1
        return i - 1 if t - self.times[i - 1] <= self.times[i] - t else i


class EventMark(StrictModel):
    """One hit, bounce or net the labeller marked. `id` is the page's own, until a save."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)
    type: Literal["hit", "bounce", "net"]
    frame: Frame
    player: PlayerId | None = Field(default=None, description="A hit's hitter, from H then 1-4.")
    image_xy: tuple[Finite, Finite] | None = Field(
        default=None, description="A bounce's click in video pixels. null for X, out of view."
    )


class RallyMarks(StrictModel):
    id: RallyId
    start_frame: Frame | None = None
    end_frame: Frame | None = None
    winner: Team | None = None
    end_reason: EndReason | None = None
    confirmed: list[Settled] = Field(
        default_factory=list, description="The suggestions the labeller accepted or replaced."
    )
    events: list[EventMark] = Field(default_factory=list)


class Marks(StrictModel):
    """Everything the labeller has marked in one recording."""

    rallies: list[RallyMarks] = Field(default_factory=list)
    orphans: list[RallyMarks] = Field(
        default_factory=list,
        description="Saved rallies that rally gold no longer has. A save waits until they go.",
    )


class Item(BaseModel):
    """Something J stops at: a suggestion not yet accepted, or a hit with no hitter."""

    rally: str
    frame: int
    what: Uncertain
    event: str | None = None


class EventView(BaseModel):
    id: str
    shot_index: int | None = None
    volley: bool | None = None


class RallyView(BaseModel):
    """What the page shows for one rally, in the order of `Marks.rallies`."""

    id: str
    game: str
    server: PlayerId
    side: str
    replay: bool
    gold_winner: Team | None
    suggested_start: int
    suggested_end: int
    proposed_end_reason: EndReason | None = None
    events: list[EventView] = Field(default_factory=list, description="In frame order.")
    uncertain: list[Item] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="Worth a look. A save works.")
    problems: list[str] = Field(default_factory=list, description="A save waits for these.")
    reviewed: bool = False


class Review(BaseModel):
    rallies: list[RallyView]
    orphans: list[str] = Field(default_factory=list)
    uncertain: list[Item] = Field(default_factory=list, description="Every item, by frame.")


class IncompleteMarks(ValueError):
    """The marks can't become a label file yet."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class _GoldRally:
    game: str
    label: LabelRally
    start: int
    end: int


@dataclass(frozen=True)
class Basis:
    """Rally gold and the video it labels, which every function here builds on."""

    gold: RallyLabels
    footage: Footage
    _rallies: dict[str, _GoldRally] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        rallies = {}
        for game in self.gold.games:
            for r in game.rallies:
                start = self.footage.nearest(r.start_t)
                end = max(self.footage.nearest(r.end_t), min(start + 1, self.last))
                rallies[r.id] = _GoldRally(game.id, r, start, end)
        object.__setattr__(self, "_rallies", rallies)

    @property
    def last(self) -> int:
        return len(self.footage.times) - 1

    def rally_ids(self) -> list[str]:
        return list(self._rallies)

    def rally(self, rally_id: str) -> _GoldRally | None:
        return self._rallies.get(rally_id)

    def suggested(self) -> Marks:
        """Every rally gold rally at its nearest frames, with nothing accepted yet."""
        return Marks(
            rallies=[
                RallyMarks(
                    id=rally_id,
                    start_frame=g.start,
                    end_frame=g.end,
                    winner=g.label.winner_team,
                )
                for rally_id, g in self._rallies.items()
            ]
        )


def boundary_near(marks: Marks, basis: Basis, frame: int) -> tuple[int, Boundary]:
    """The rally and boundary that R moves: the start or end nearest `frame`. A boundary the
    labeller rejected counts at its suggestion."""
    best: tuple[int, int, Boundary] | None = None
    for i, r in enumerate(marks.rallies):
        g = basis.rally(r.id)
        candidates: tuple[tuple[Boundary, int | None, int | None], ...] = (
            ("start", r.start_frame, g.start if g else None),
            ("end", r.end_frame, g.end if g else None),
        )
        for name, value, fallback in candidates:
            at = value if value is not None else fallback
            if at is None:
                continue
            distance = abs(at - frame)
            if best is None or distance < best[0]:
                best = (distance, i, name)
    if best is None:
        raise ValueError("there are no rallies to move")
    return best[1], best[2]


def review(marks: Marks, basis: Basis) -> Review:
    """Say, rally by rally, what the marks give, what is uncertain and what blocks a save."""
    views = []
    previous_end: int | None = None
    for r in marks.rallies:
        view = _review_rally(r, basis, previous_end)
        views.append(view)
        if r.end_frame is not None:
            previous_end = r.end_frame
    orphans = [
        f"{o.id} has {len(o.events)} event(s) but isn't in rally gold any more. Fix rally gold "
        "in rally mode, or select it and press Delete."
        for o in marks.orphans
    ]
    uncertain = sorted((i for v in views for i in v.uncertain), key=lambda i: i.frame)
    return Review(rallies=views, orphans=orphans, uncertain=uncertain)


def to_log(marks: Marks, basis: Basis, crops: Mapping[str, str | None]) -> EventLog:
    """The gold `events.json` for the marks. Raises IncompleteMarks or ValidationError."""
    view = review(marks, basis)
    problems = [f"{v.id}: {p}" for v in view.rallies for p in v.problems] + view.orphans
    ids = [r.id for r in marks.rallies]
    missing = [g for g in basis.rally_ids() if g not in ids]
    if missing:
        problems.append(f"rally gold has {', '.join(missing)}, which the marks leave out")
    if problems:
        raise IncompleteMarks(problems)

    times = basis.footage.times
    by_id = {r.id: (r, v) for r, v in zip(marks.rallies, view.rallies, strict=True)}
    games, segments = [], []
    for game in basis.gold.games:
        rallies = [_rally_json(*by_id[r.id], times) for r in game.rallies]
        start = basis.footage.nearest(game.start_t)
        end = max(basis.footage.nearest(game.end_t), start + 1)
        if rallies:
            start = min(start, rallies[0]["start_frame"])
            end = max(end, rallies[-1]["end_frame"])
        end = min(end, basis.last)
        span = {
            "start_frame": start,
            "end_frame": end,
            "start_t": times[start],
            "end_t": times[end],
        }
        games.append({"id": game.id, **span, "rallies": rallies})
        segments.append({"type": "game", **span, "conf": 1.0})
    footage = basis.footage
    return EventLog.model_validate(
        {
            "schema": "dinkdata.events/v3",
            "video": {
                "id": footage.video_id,
                "fps_nominal": footage.fps_nominal,
                "frames": f"videos/{footage.video_id}.frames.parquet",
                "dropped_frames": footage.dropped_frames,
            },
            "camera": None,
            "players": [
                {"id": p, "team": team_of(p), "label": f"Player {p[1]}", "crop": crops.get(p)}
                for p in _PLAYERS
            ],
            "segments": segments,
            "games": games,
        }
    )


def merge(basis: Basis, saved: EventLog | None) -> Marks:
    """The latest rally gold with the labeller's latest saved file on top.

    Rally ids are positions in rally gold, so a rally added in rally mode renumbers the ones
    after it. Saved rallies are matched to rally gold by how much their frames overlap. A
    saved rally that matches nothing becomes an orphan if it holds events or an end reason.
    """
    marks = basis.suggested()
    if saved is None:
        return marks
    saved_rallies = [r for g in saved.games for r in g.rallies]
    pairs = []
    for i, s in enumerate(saved_rallies):
        for j, r in enumerate(marks.rallies):
            g = basis.rally(r.id)
            assert g is not None
            overlap = min(s.end_frame, g.end) - max(s.start_frame, g.start)
            if overlap > 0:
                pairs.append((overlap, i, j))
    used_saved, used_gold = set(), set()
    for _, i, j in sorted(pairs, reverse=True):
        if i in used_saved or j in used_gold:
            continue
        used_saved.add(i)
        used_gold.add(j)
        marks.rallies[j] = _from_saved(saved_rallies[i], marks.rallies[j])
    for i, s in enumerate(saved_rallies):
        if i not in used_saved and (s.events or s.end_reason is not None):
            marks.orphans.append(_from_saved(s, RallyMarks(id=s.id)))
    return marks


# ---- one rally ----


def _review_rally(r: RallyMarks, basis: Basis, previous_end: int | None) -> RallyView:
    g = basis.rally(r.id)
    if g is None:
        return RallyView(
            id=r.id,
            game="",
            server="p1",
            side="",
            replay=False,
            gold_winner=None,
            suggested_start=0,
            suggested_end=0,
            problems=[f"rally gold has no rally {r.id}"],
        )
    view = RallyView(
        id=r.id,
        game=g.game,
        server=g.label.serve.server,
        side=g.label.serve.side,
        replay=g.label.replay,
        gold_winner=g.label.winner_team,
        suggested_start=g.start,
        suggested_end=g.end,
    )
    ordered = _ordered(r.events)
    view.events = _shots(ordered)
    view.proposed_end_reason = _propose_end_reason(ordered)
    _check_frames(r, basis, previous_end, view)
    _check_events(r, ordered, basis, view)
    _check_serve(g, ordered, view)
    if r.winner is not None and g.label.replay:
        view.problems.append("Rally gold marks this rally as a replay, so it has no winner.")
    if "winner" in r.confirmed and r.winner != g.label.winner_team:
        view.warnings.append(
            f"The winner differs from rally gold ({g.label.winner_team or 'none'}). Check the "
            "score in rally mode."
        )

    at_start = r.start_frame if r.start_frame is not None else g.start
    at_end = r.end_frame if r.end_frame is not None else g.end
    suggestions: tuple[tuple[Settled, int], ...] = (
        ("start", at_start),
        ("end", at_end),
        ("winner", at_end),
    )
    for what, frame in suggestions:
        if what not in r.confirmed:
            view.uncertain.append(Item(rally=r.id, frame=frame, what=what))
    if r.end_reason is None:
        view.uncertain.append(Item(rally=r.id, frame=at_end, what="end_reason"))
    for e in ordered:
        if e.type == "hit" and e.player is None:
            view.uncertain.append(Item(rally=r.id, frame=e.frame, what="hitter", event=e.id))
    view.uncertain.sort(key=lambda i: i.frame)
    settled = all(s in r.confirmed for s in ("start", "end", "winner"))
    view.reviewed = settled and r.end_reason is not None and not view.problems
    return view


def _check_frames(r: RallyMarks, basis: Basis, previous_end: int | None, view: RallyView) -> None:
    if r.start_frame is None:
        view.problems.append("The rally has no start. Press R at the serve.")
    if r.end_frame is None:
        view.problems.append("The rally has no end. Press R when the ball is dead.")
    for name, frame in (("start", r.start_frame), ("end", r.end_frame)):
        if frame is not None and frame > basis.last:
            view.problems.append(f"The {name} is past the video's last frame, {basis.last}.")
    if r.start_frame is None or r.end_frame is None:
        return
    if r.end_frame <= r.start_frame:
        view.problems.append("The end must come after the start. Press R again.")
    if previous_end is not None and r.start_frame <= previous_end:
        view.problems.append("The rally overlaps the one before it. Move its start or their end.")


def _check_events(r: RallyMarks, ordered: list[EventMark], basis: Basis, view: RallyView) -> None:
    ids = [e.id for e in ordered]
    if len(set(ids)) != len(ids):
        view.problems.append("Two events share an id.")
    for e in ordered:
        start = r.start_frame if r.start_frame is not None else -1
        end = r.end_frame if r.end_frame is not None else -1
        if not start <= e.frame <= end:
            view.problems.append(f"The {e.type} at frame {e.frame} is outside the rally.")
        if e.type != "hit" and e.player is not None:
            view.problems.append(f"The {e.type} at frame {e.frame} can't have a hitter.")
        if e.type != "bounce" and e.image_xy is not None:
            view.problems.append(f"The {e.type} at frame {e.frame} can't have a click.")
        if e.image_xy is not None:
            x, y = e.image_xy
            if not (0 <= x <= basis.footage.width and 0 <= y <= basis.footage.height):
                view.problems.append(f"The bounce at frame {e.frame} is off the picture.")


def _check_serve(g: _GoldRally, ordered: list[EventMark], view: RallyView) -> None:
    hits = [e for e in ordered if e.type == "hit"]
    server = g.label.serve.server
    if hits and hits[0].player is not None and hits[0].player != server:
        view.warnings.append(
            f"The first hit is by {hits[0].player}, but rally gold says the server is {server}."
        )
    if len(hits) > 1 and _receiver(server, hits) is None and hits[1].player is not None:
        view.warnings.append("The return is by the serving team, so the rally has no receiver.")


def _ordered(events: list[EventMark]) -> list[EventMark]:
    """Events by frame. Events at one frame keep the order they were marked in."""
    return sorted(events, key=lambda e: e.frame)


def _shots(ordered: list[EventMark]) -> list[EventView]:
    """shot_index counts hits from the serve. A volley is a hit with no bounce since the shot
    before it. The serve and the return are never volleys, because both must bounce first."""
    views = []
    shot = 0
    bounced = False
    for e in ordered:
        if e.type == "bounce":
            bounced = True
        if e.type != "hit":
            views.append(EventView(id=e.id))
            continue
        shot += 1
        views.append(EventView(id=e.id, shot_index=shot, volley=shot >= 3 and not bounced))
        bounced = False
    return views


def _propose_end_reason(ordered: list[EventMark]) -> EndReason | None:
    """`net` when the rally's last event is the net, `double_bounce` when it ends with two
    bounces in a row. Anything else needs the labeller."""
    if ordered and ordered[-1].type == "net":
        return "net"
    if len(ordered) >= 2 and ordered[-1].type == ordered[-2].type == "bounce":
        return "double_bounce"
    return None


def _receiver(server: PlayerId, hits: list[EventMark]) -> PlayerId | None:
    """The hitter of the return, when the other team hit it."""
    if len(hits) < 2 or hits[1].player is None:
        return None
    player = hits[1].player
    return None if team_of(player) == team_of(server) else player


def _rally_json(r: RallyMarks, view: RallyView, times: Sequence[float]) -> dict:
    assert r.start_frame is not None and r.end_frame is not None
    ordered = _ordered(r.events)
    shots = {s.id: s for s in view.events}
    events = []
    for k, e in enumerate(ordered, 1):
        common = {"id": f"{r.id}_e{k}", "type": e.type, "frame": e.frame, "t": times[e.frame]}
        if e.type == "hit":
            shot = shots[e.id]
            events.append(
                common
                | {
                    "player": e.player,
                    "shot_index": shot.shot_index,
                    "volley": shot.volley,
                    "conf": 1.0,
                }
            )
        elif e.type == "bounce":
            events.append(
                common
                | {
                    "image_xy": e.image_xy,
                    "court_xy": None,
                    "in": None,
                    "close_call": False,
                    "conf": 1.0,
                }
            )
        else:
            events.append(common | {"conf": 1.0})
    hits = [e for e in ordered if e.type == "hit"]
    server: PlayerId = view.server
    return {
        "id": r.id,
        "start_frame": r.start_frame,
        "end_frame": r.end_frame,
        "start_t": times[r.start_frame],
        "end_t": times[r.end_frame],
        "serve": {
            "server": server,
            "side": view.side,
            "receiver": _receiver(server, hits),
            "conf": 1.0,
        },
        "winner_team": r.winner,
        "winner_source": None if r.winner is None else "label",
        "replay": view.replay,
        "end_reason": r.end_reason,
        "reviewed": view.reviewed,
        "conf": 1.0,
        "events": events,
    }


def _from_saved(saved: Rally, suggestion: RallyMarks) -> RallyMarks:
    """Marks for one saved rally. The file keeps only `reviewed`, so a field counts as
    confirmed when the rally was reviewed or when it differs from its suggestion."""
    confirmed: list[Settled] = []
    fields: tuple[tuple[Settled, object, object], ...] = (
        ("start", saved.start_frame, suggestion.start_frame),
        ("end", saved.end_frame, suggestion.end_frame),
        ("winner", saved.winner_team, suggestion.winner),
    )
    for name, value, suggested in fields:
        if saved.reviewed or value != suggested:
            confirmed.append(name)
    events = []
    for e in saved.events:
        mark = {"id": e.id, "type": e.type, "frame": e.frame}
        if e.type == "hit":
            mark["player"] = e.player
        elif e.type == "bounce":
            mark["image_xy"] = e.image_xy
        events.append(EventMark.model_validate(mark))
    return RallyMarks(
        id=suggestion.id,
        start_frame=saved.start_frame,
        end_frame=saved.end_frame,
        winner=saved.winner_team,
        end_reason=saved.end_reason,
        confirmed=confirmed,
        events=events,
    )
