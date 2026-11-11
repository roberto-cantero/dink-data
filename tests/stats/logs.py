"""Hand-written game logs for the stat tests.

Each rally reads like the story of one point: `rally(hit("p1", 1), bounce(5, 8), ...)`. The
builder fills in ids, frames and times so the log is a valid `events.json`. Frames and times
are made up independently, as in a real video with dropped frames.

Court reminder (docs/COURT.md): y = 0 is the far baseline, 22 the net, 44 the near baseline.
In these tests team A (p1, p2) stands at the near end and team B (p3, p4) at the far end, so
p1 serving from the right lands in the far box left of x = 10.
"""

from typing import Any

from dinkdata.contracts.common import Team
from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.stats import Stat, Stats

VIDEO_ID = "v_5eed000000005001"
RALLY_SECONDS = 10.0
RALLY_FRAMES = 300


def hit(player: str | None, shot: int, *, volley: bool = False, conf: float = 0.9) -> dict:
    return {"type": "hit", "player": player, "shot_index": shot, "volley": volley, "conf": conf}


def bounce(x: float, y: float, *, close_call: bool = False, conf: float = 0.9) -> dict:
    return {
        "type": "bounce",
        "image_xy": [100.0, 100.0],
        "court_xy": [x, y],
        "in": None,
        "close_call": close_call,
        "conf": conf,
    }


def unseen_bounce(*, conf: float = 0.9) -> dict:
    """A bounce the camera couldn't see: no position and no in or out."""
    return {
        "type": "bounce",
        "image_xy": None,
        "court_xy": None,
        "in": None,
        "close_call": False,
        "conf": conf,
    }


def net(*, conf: float = 0.9) -> dict:
    return {"type": "net", "conf": conf}


def rally(
    *events: dict,
    server: str = "p1",
    side: str = "right",
    receiver: str | None = "p3",
    winner: Team | None = "A",
    end: str | None = None,
    replay: bool = False,
    reviewed: bool = False,
    conf: float = 0.9,
) -> dict:
    """One rally. A replay gets no winner, as the contract requires."""
    if replay:
        winner = None
    return {
        "serve": {"server": server, "side": side, "receiver": receiver, "conf": 0.95},
        "winner_team": winner,
        "winner_source": None if winner is None else "ball",
        "replay": replay,
        "end_reason": end,
        "reviewed": reviewed,
        "conf": conf,
        "events": list(events),
    }


def game_log(*games: list[dict]) -> EventLog:
    """A log of the given games, each a list of rallies, played one after another."""
    out: list[dict[str, Any]] = []
    n_rally = 0
    n_event = 0
    for g, rallies in enumerate(games, start=1):
        game_start = n_rally
        game_rallies = []
        for r, spec in enumerate(rallies, start=1):
            start_t = n_rally * RALLY_SECONDS + 1.0
            start_frame = n_rally * RALLY_FRAMES + 20
            events = []
            for k, event in enumerate(spec["events"], start=1):
                n_event += 1
                events.append(
                    {"id": f"e{n_event}", "frame": start_frame + 10 * k, "t": start_t + 0.5 * k}
                    | event
                )
            game_rallies.append(
                {
                    "id": f"g{g}_r{r}",
                    "start_t": start_t,
                    "end_t": start_t + RALLY_SECONDS - 2.0,
                    "start_frame": start_frame,
                    "end_frame": start_frame + RALLY_FRAMES - 60,
                }
                | {k: v for k, v in spec.items() if k != "events"}
                | {"events": events}
            )
            n_rally += 1
        out.append(
            {
                "id": f"g{g}",
                "start_t": game_start * RALLY_SECONDS,
                "end_t": max(n_rally, game_start + 1) * RALLY_SECONDS,
                "start_frame": game_start * RALLY_FRAMES,
                "end_frame": max(n_rally, game_start + 1) * RALLY_FRAMES,
                "rallies": game_rallies,
            }
        )
        n_rally = max(n_rally, game_start + 1)
    return EventLog.model_validate(
        {
            "schema": "dinkdata.events/v3",
            "video": {
                "id": VIDEO_ID,
                "fps_nominal": 30,
                "frames": f"videos/{VIDEO_ID}.frames.parquet",
                "dropped_frames": 0,
            },
            "camera": {"id": "c_5eed000000005001", "version": 1},
            "players": [
                {"id": p, "team": t, "label": f"Player {p[1]}", "crop": None}
                for p, t in [("p1", "A"), ("p2", "A"), ("p3", "B"), ("p4", "B")]
            ],
            "segments": [],
            "games": out,
        }
    )


def stat(stats: Stats, name: str, player: str, game: str = "g1") -> Stat:
    return next(s for s in stats.stats if s.stat == name and s.subject == player and s.game == game)
