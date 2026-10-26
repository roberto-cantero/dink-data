"""Read one rally of the game log: its serve, return, last shot and where each shot landed.

A shot's first bounce is the first bounce after it and before the next hit. Net events in
between are skipped, so a net-cord serve is judged by where it lands (docs/STATS.md).
"""

from dinkdata.contracts.common import Team, team_of
from dinkdata.contracts.events import Bounce, Hit
from dinkdata.contracts.game_log import Game, Rally
from dinkdata.court.zones import Half, half, in_court, other_half


def counted_rallies(game: Game) -> list[Rally]:
    """The rallies stats read. A replayed rally counts toward no stat."""
    return [r for r in game.rallies if not r.replay]


def hits(rally: Rally) -> list[Hit]:
    return [e for e in rally.events if isinstance(e, Hit)]


def shot(rally: Rally, index: int) -> Hit | None:
    """The hit with this `shot_index`: 1 is the serve, 2 the return."""
    return next((h for h in hits(rally) if h.shot_index == index), None)


def last_hit(rally: Rally) -> Hit | None:
    rally_hits = hits(rally)
    return rally_hits[-1] if rally_hits else None


def next_hit(rally: Rally, after: Hit) -> Hit | None:
    rally_hits = hits(rally)
    i = rally_hits.index(after)
    return rally_hits[i + 1] if i + 1 < len(rally_hits) else None


def first_bounce(rally: Rally, after: Hit) -> Bounce | None:
    """The first bounce after a hit and before the next hit. None if there is none."""
    started = False
    for event in rally.events:
        if event is after:
            started = True
        elif started and isinstance(event, Hit):
            return None
        elif started and isinstance(event, Bounce):
            return event
    return None


def _visible_half(rally: Rally, hit: Hit | None) -> Half | None:
    if hit is None:
        return None
    landing = first_bounce(rally, hit)
    if landing is None or landing.court_xy is None or not in_court(landing.court_xy):
        return None
    return half(landing.court_xy)


def receivers_half(rally: Rally) -> Half | None:
    """The receiving team's half, from where the serve bounced. None if that wasn't seen."""
    return _visible_half(rally, shot(rally, 1))


def team_half(rally: Rally, team: Team) -> Half | None:
    """The half a team stood on in this rally, from the serve's bounce or else the return's.

    The serve lands on the receivers' half and the return on the servers' half. None if
    neither bounce was seen in the court.
    """
    receivers = receivers_half(rally)
    if receivers is None:
        servers = _visible_half(rally, shot(rally, 2))
        if servers is None:
            return None
        receivers = other_half(servers)
    serving_team = team_of(rally.serve.server)
    return other_half(receivers) if team == serving_team else receivers
