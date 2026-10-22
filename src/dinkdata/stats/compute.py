"""The v1 stats as pure functions of the game log (docs/STATS.md).

`compute_stats` reads an `EventLog` and returns `Stats`: every v1 stat for every player in
every game. It reads no video and runs no model. Each stat collects items of evidence.

- A counted item adds to the stat. Its confidence is the lowest of the rally's `conf` and the
  confidences of the events it used.
- A left-out item might belong to the stat but couldn't be judged, such as a serve whose
  bounce the camera didn't see or an error by an unknown hitter. It carries a reason.

A stat's confidence is the mean confidence of its counted items times the share of its items
that were counted. A stat with no items at all takes the mean `conf` of the game's rallies,
because a count of 0 is only as sure as the rallies are. The stat ships if its confidence
reaches SHIP_THRESHOLD and, for a percentage, depth or landing map, it has something to show.
Otherwise its reason is the most common reason its items were left out, or `low_conf`.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from statistics import mean
from typing import get_args

from dinkdata.contracts.common import PlayerId, Team, team_of
from dinkdata.contracts.events import Hit
from dinkdata.contracts.game_log import EventLog, Game, Rally
from dinkdata.contracts.stats import (
    Depth,
    LandingMap,
    Reason,
    Stat,
    StatName,
    Stats,
    Value,
    check_stats,
)
from dinkdata.court.zones import (
    Point,
    depth_bucket,
    feet_to_baseline,
    half,
    in_court,
    in_service_court,
    other_half,
)
from dinkdata.stats.shots import (
    counted_rallies,
    first_bounce,
    hits,
    last_hit,
    next_hit,
    receivers_half,
    shot,
    team_half,
)

PLAYERS: tuple[PlayerId, ...] = get_args(PlayerId)
STAT_NAMES: tuple[StatName, ...] = get_args(StatName)

SHIP_THRESHOLD: dict[StatName, float] = dict.fromkeys(STAT_NAMES, 0.5)
"""Provisional. Beta-review corrections set the real values (docs/DESIGN.md 3.4)."""

NO_ATTRIBUTION: set[Reason] = {"low_attribution_conf", "winner_unknown", "events_missing"}
"""Reasons that mean the item isn't known to be this player's, so no landing map point."""


@dataclass(frozen=True)
class Item:
    """One piece of evidence for a stat.

    `players` is one player when the item is attributed, or every player it might belong to
    when it isn't. `left_out` is set when the item couldn't be judged.
    """

    players: tuple[PlayerId, ...]
    conf: float
    left_out: Reason | None = None
    landed_in: bool | None = None
    point: Point | None = None


def team(name: Team) -> tuple[PlayerId, ...]:
    return tuple(p for p in PLAYERS if team_of(p) == name)


def other_team(name: Team) -> Team:
    return "B" if name == "A" else "A"


def compute_stats(log: EventLog, run_id: str) -> Stats:
    """Every v1 stat for every player in every game of the log.

    Raises ValueError if the result breaks a rule between stats.json and events.json, which
    would be a bug here.
    """
    stats = Stats.model_validate(
        {
            "schema": "dinkdata.stats/v2",
            "video_id": log.video.id,
            "run_id": run_id,
            "stats": [s for game in log.games for s in game_stats(game)],
        }
    )
    problems = check_stats(stats, log)
    if problems:
        raise ValueError("; ".join(problems))
    return stats


def game_stats(game: Game) -> list[Stat]:
    """One game's stats, for each player in turn, in the order of `StatName`."""
    rallies = counted_rallies(game)
    if not rallies:
        return [_no_rallies(game.id, p, name) for p in PLAYERS for name in STAT_NAMES]
    fallback = mean(r.conf for r in rallies)
    serves = [i for r in rallies if (i := judge_serve(r)) is not None]
    returns = [i for r in rallies if (i := judge_return(r)) is not None]
    errors: dict[StatName, list[Item]] = {"net_errors": [], "out_errors": [], "serve_faults": []}
    for r in rallies:
        if (error := judge_error(r)) is not None:
            errors[error[0]].append(error[1])
    winners = [i for r in rallies if (i := judge_winner(r)) is not None]

    out: list[Stat] = []
    for p in PLAYERS:

        def mine(items: list[Item], player: PlayerId = p) -> list[Item]:
            return [i for i in items if player in i.players]

        out += [
            _ratio(game.id, p, "serve_in_pct", mine(serves), fallback, "no_serves"),
            _depth(game.id, p, "serve_depth", mine(serves), fallback, "no_serves"),
            _ratio(game.id, p, "return_in_pct", mine(returns), fallback, "no_returns"),
            _depth(game.id, p, "return_depth", mine(returns), fallback, "no_returns"),
            *(
                _count(game.id, p, name, mine(errors[name]), fallback)
                for name in ("net_errors", "out_errors", "serve_faults")
            ),
            _count(game.id, p, "winners", mine(winners), fallback),
            _landing_map(
                game.id,
                p,
                mine(serves),
                mine(returns),
                mine(errors["out_errors"]),
                fallback,
            ),
        ]
    return out


# Judging one rally


def judge_serve(rally: Rally) -> Item | None:
    """Whether the serve's first bounce was in the diagonal service court.

    None when the receiver hit the serve before it bounced, so there was nothing to judge.
    """
    server = rally.serve.server
    serve = shot(rally, 1)
    if serve is None:
        return Item((server,), rally.conf, left_out="events_missing")
    conf = min(rally.conf, rally.serve.conf, serve.conf)
    item = _judge_landing(
        rally, serve, (server,), conf, lambda p: in_service_court(p, rally.serve.side)
    )
    if _ended_in_net(rally, serve):
        return replace(item or Item((server,), conf), left_out=None, landed_in=False)
    return item


def judge_return(rally: Rally) -> Item | None:
    """Whether the return's first bounce was in the servers' half.

    A return hit before the serve bounced is a fault, so it counts as not in. None when the
    rally has no return, or the servers hit the return before it bounced.
    """
    receiving = team(other_team(team_of(rally.serve.server)))
    ret = shot(rally, 2)
    if ret is None:
        return None if hits(rally) else Item(receiving, rally.conf, left_out="events_missing")
    returner = ret.player or rally.serve.receiver
    players = (returner,) if returner is not None else receiving
    conf = min(rally.conf, ret.conf)
    receivers = receivers_half(rally)
    servers = None if receivers is None else other_half(receivers)

    def landed_in(p: Point) -> bool:
        return in_court(p) and (servers is None or half(p) == servers)

    item = _judge_landing(rally, ret, players, conf, landed_in)
    if ret.volley or _ended_in_net(rally, ret):
        item = replace(item or Item(players, conf), left_out=None, landed_in=False)
    if item is not None and returner is None:
        item = replace(item, left_out="low_attribution_conf")
    return item


def judge_error(rally: Rally) -> tuple[StatName, Item] | None:
    """The net error, out error or serve fault that ended the rally, if it ended in one.

    An error belongs only to the shot that ended the rally. When the hitter is unknown, the
    item is left out for every player who might have hit it.
    """
    end = rally.end_reason
    if end not in ("net", "out"):
        return None
    losers = PLAYERS if rally.winner_team is None else team(other_team(rally.winner_team))
    name: StatName = "net_errors" if end == "net" else "out_errors"
    final = last_hit(rally)
    if final is None:
        return name, Item(losers, rally.conf, left_out="events_missing")
    is_serve = final.shot_index == 1
    if is_serve:
        name = "serve_faults"
    hitter = rally.serve.server if is_serve else final.player
    conf = min(rally.conf, final.conf)
    left_out: Reason | None = None
    point: Point | None = None
    landing = first_bounce(rally, final) if end == "out" else None
    if landing is not None:
        conf = min(conf, landing.conf)
        point = landing.court_xy
        if landing.close_call and not rally.reviewed:
            left_out = "close_call_review"
    if hitter is None:
        return name, Item(losers, conf, left_out="low_attribution_conf", point=point)
    return name, Item((hitter,), conf, left_out=left_out, point=point)


def judge_winner(rally: Rally) -> Item | None:
    """The winner the rally's last shot was, if it was one.

    The last shot is a winner when the hitter's team won and no opponent returned it: the ball
    bounced twice on the opponents' side, it hit an opponent (a fault with no opponent hit
    after the shot), or the end is unknown but the ball bounced in on the opponents' half and
    nothing came after it, as when the second bounce leaves the picture.
    """
    end = rally.end_reason
    if end in ("net", "out", "unreturned"):
        return None
    winning = rally.winner_team
    final = last_hit(rally)
    if final is None:
        if winning is None:
            return None
        return Item(team(winning), rally.conf, left_out="events_missing")
    conf = min(rally.conf, final.conf)
    if winning is None:
        players = (final.player,) if final.player is not None else PLAYERS
        return Item(players, conf, left_out="winner_unknown")
    if final.player is None:
        return Item(team(winning), conf, left_out="low_attribution_conf")
    if team_of(final.player) != winning:
        return None
    hitter = (final.player,)
    if end in ("double_bounce", "fault"):
        return Item(hitter, conf)
    landing = first_bounce(rally, final)
    if landing is None or landing.court_xy is None:
        return Item(hitter, conf, left_out="bounces_not_visible")
    conf = min(conf, landing.conf)
    if landing.close_call and not rally.reviewed:
        return Item(hitter, conf, left_out="close_call_review")
    opponents = team_half(rally, other_team(winning))
    if opponents is None:
        return Item(hitter, conf, left_out="bounces_not_visible")
    if in_court(landing.court_xy) and half(landing.court_xy) == opponents:
        return Item(hitter, conf)
    return None


def _ended_in_net(rally: Rally, hit: Hit) -> bool:
    return rally.end_reason == "net" and last_hit(rally) is hit


def _judge_landing(
    rally: Rally,
    hit: Hit,
    players: tuple[PlayerId, ...],
    conf: float,
    landed_in: Callable[[Point], bool],
) -> Item | None:
    """Judge a shot by its first bounce. None when the next shot was hit before it bounced."""
    landing = first_bounce(rally, hit)
    if landing is None:
        after = next_hit(rally, hit)
        if after is not None and after.volley:
            return None
        return Item(players, conf, left_out="bounces_not_visible")
    conf = min(conf, landing.conf)
    point = landing.court_xy
    if point is None:
        return Item(players, conf, left_out="bounces_not_visible")
    if landing.close_call and not rally.reviewed:
        return Item(players, conf, left_out="close_call_review", point=point)
    return Item(players, conf, landed_in=landed_in(point), point=point)


# Turning items into stats


def _confidence(counted: list[Item], left: list[Item], fallback: float) -> float:
    if not counted and not left:
        return round(fallback, 3)
    if not counted:
        return 0.0
    share = len(counted) / (len(counted) + len(left))
    return round(mean(i.conf for i in counted) * share, 3)


def _most_common(left: list[Item], otherwise: Reason) -> Reason:
    reasons = [i.left_out for i in left if i.left_out is not None]
    return Counter(reasons).most_common(1)[0][0] if reasons else otherwise


def _split(items: list[Item]) -> tuple[list[Item], list[Item]]:
    return [i for i in items if i.left_out is None], [i for i in items if i.left_out is not None]


def _stat(
    game: str,
    player: PlayerId,
    name: StatName,
    value: Value | None,
    conf: float,
    left: list[Item],
    blocked: Reason | None = None,
    num: int | None = None,
    den: int | None = None,
) -> Stat:
    """One stat entry. `blocked` is why it can't ship whatever its confidence.

    Otherwise it ships if its confidence reaches the threshold. If not, its reason is the most
    common reason items were left out, or `low_conf`.
    """
    reason = blocked
    if reason is None and conf < SHIP_THRESHOLD[name]:
        reason = _most_common(left, "low_conf")
    return Stat(
        game=game,
        subject=player,
        stat=name,
        value=value,
        num=num,
        den=den,
        conf=conf,
        shipped=reason is None,
        reason=reason,
    )


def _ratio(
    game: str,
    player: PlayerId,
    name: StatName,
    items: list[Item],
    fallback: float,
    no_items: Reason,
) -> Stat:
    judged, left = _split(items)
    num = sum(1 for i in judged if i.landed_in)
    den = len(judged)
    conf = _confidence(judged, left, fallback)
    if not den:
        return _stat(game, player, name, None, conf, left, _most_common(left, no_items), 0, 0)
    return _stat(game, player, name, num / den, conf, left, None, num, den)


def _depth(
    game: str,
    player: PlayerId,
    name: StatName,
    items: list[Item],
    fallback: float,
    no_items: Reason,
) -> Stat:
    """Bucket counts of the shots that landed in, by feet to the baseline they landed toward."""
    judged, left = _split(items)
    landed = [i.point for i in judged if i.landed_in and i.point is not None]
    conf = _confidence(judged, left, fallback)
    if not landed:
        blocked = f"{no_items}_in" if judged else _most_common(left, no_items)
        return _stat(game, player, name, None, conf, left, blocked)
    buckets = Counter(depth_bucket(feet_to_baseline(p)) for p in landed)
    value = Depth(deep=buckets["deep"], medium=buckets["medium"], short=buckets["short"])
    return _stat(game, player, name, value, conf, left)


def _count(game: str, player: PlayerId, name: StatName, items: list[Item], fallback: float) -> Stat:
    counted, left = _split(items)
    return _stat(game, player, name, len(counted), _confidence(counted, left, fallback), left)


def _landing_map(
    game: str,
    player: PlayerId,
    serves: list[Item],
    returns: list[Item],
    out_errors: list[Item],
    fallback: float,
) -> Stat:
    """Where the player's serves, returns and out errors bounced, when the camera saw it.

    A serve or return into the net has no bounce, so it adds no point and isn't left out.
    """
    points: dict[str, list[Point]] = {"serve": [], "return": [], "out_error": []}
    counted: list[Item] = []
    left: list[Item] = []
    for kind, items in (("serve", serves), ("return", returns), ("out_error", out_errors)):
        for i in items:
            if i.left_out in NO_ATTRIBUTION:
                left.append(i)
            elif i.point is not None:
                points[kind].append(i.point)
                counted.append(i)
            elif i.left_out is not None or kind == "out_error":
                left.append(replace(i, left_out="bounces_not_visible"))
    value = LandingMap.model_validate(points)
    conf = _confidence(counted, left, fallback)
    blocked = None if counted else _most_common(left, "no_bounces")
    return _stat(game, player, "landing_map", value, conf, left, blocked)


def _no_rallies(game: str, player: PlayerId, name: StatName) -> Stat:
    ratio = 0 if name in ("serve_in_pct", "return_in_pct") else None
    return _stat(game, player, name, None, 0.0, [], "no_rallies", ratio, ratio)
