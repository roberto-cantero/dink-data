"""Turn a hand-written rally pick list into `highlights.json` (DESIGN 3.3, 6.12).

In M0 there is no selector: a person names the rallies to put in each player's reel and why.
`RallyList` stands in for what the automatic selector (M2+) will produce from the scoring
rules in DESIGN 3.3, so it is a plain pydantic model here, not a versioned file format in
`dinkdata.contracts`. `build_highlights` turns picks plus the rally boundaries from
`rallies.json` or `events.json` into a validated `Highlights`, computing each clip's padded,
clamped start and end time (DESIGN 6.12 point 2: a clip never cuts into the next serve).
"""

from pydantic import Field

from dinkdata.contracts.common import GameId, PlayerId, RallyId, StrictModel, VideoId
from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.games import RallyBase
from dinkdata.contracts.highlights import Clip, ClipReason, Highlights, Reel, check_highlights
from dinkdata.contracts.rallies import RallyLabels

Timeline = EventLog | RallyLabels

START_PAD = 1.0
"""Seconds of padding before the serve (DESIGN 3.3)."""
END_PAD = 1.5
"""Seconds of padding after the rally ends (DESIGN 3.3)."""
NEXT_SERVE_MARGIN = 0.01
"""A clip's end must be strictly before the next serve; this keeps it from landing exactly on it."""


class RallyPick(StrictModel):
    """One rally, hand-picked for one player's reel, with why and how good."""

    game_id: GameId
    player_id: PlayerId
    rally_id: RallyId
    reasons: list[ClipReason] = Field(min_length=1)
    score: float = Field(ge=0, allow_inf_nan=False)


class RallyList(StrictModel):
    """A hand-written rally list: every pick for every reel of one video."""

    video_id: VideoId
    picks: list[RallyPick]


def _flat_rallies(timeline: Timeline) -> list[tuple[GameId, RallyBase]]:
    return [(g.id, r) for g in timeline.games for r in g.rallies]


def clip_span(
    rally: RallyBase, next_start: float | None, start_pad: float, end_pad: float
) -> tuple[float, float]:
    """A clip's padded start and end, clamped so it never cuts into the next serve.

    `next_start` is the next rally's `start_t`, flattened across every game, or null for the
    recording's last rally. Raises ValueError if the padding and clamp would leave an empty or
    backwards clip, which only happens for a rally shorter than the clamp's margin with no gap
    before the next one.
    """
    start_t = max(rally.start_t - start_pad, 0.0)
    end_t = rally.end_t + end_pad
    if next_start is not None:
        end_t = min(end_t, next_start - NEXT_SERVE_MARGIN)
    if end_t <= start_t:
        raise ValueError(
            f"{rally.id}: padding would make an empty or backwards clip "
            "(the next rally starts too soon)"
        )
    return start_t, end_t


def build_highlights(
    picks: RallyList,
    timeline: Timeline,
    *,
    start_pad: float = START_PAD,
    end_pad: float = END_PAD,
) -> Highlights:
    """Build and validate `highlights.json` from hand-picked rallies and their boundaries.

    Raises ValueError if a pick names a rally that isn't in `timeline`, if padding would make
    a clip empty or backwards, or if the result breaks a cross-file rule from `check_highlights`.
    """
    if picks.video_id != timeline.video_id:
        raise ValueError(
            f"video_id {picks.video_id} doesn't match the timeline's {timeline.video_id}"
        )
    rallies = _flat_rallies(timeline)
    index = {rally.id: i for i, (_, rally) in enumerate(rallies)}

    by_reel: dict[tuple[GameId, PlayerId], list[RallyPick]] = {}
    for pick in picks.picks:
        i = index.get(pick.rally_id)
        if i is None or rallies[i][0] != pick.game_id:
            raise ValueError(f"{pick.rally_id} is not a rally of game {pick.game_id} in timeline")
        by_reel.setdefault((pick.game_id, pick.player_id), []).append(pick)

    reels = []
    for (game_id, player_id), reel_picks in by_reel.items():
        ordered = sorted(reel_picks, key=lambda p: rallies[index[p.rally_id]][1].start_t)
        clips = []
        for n, pick in enumerate(ordered, start=1):
            i = index[pick.rally_id]
            rally = rallies[i][1]
            next_start = rallies[i + 1][1].start_t if i + 1 < len(rallies) else None
            start_t, end_t = clip_span(rally, next_start, start_pad, end_pad)
            clips.append(
                Clip(
                    id=f"{game_id}_{player_id}_c{n}",
                    rally_id=pick.rally_id,
                    start_t=start_t,
                    end_t=end_t,
                    reasons=pick.reasons,
                    score=pick.score,
                )
            )
        reels.append(Reel(game_id=game_id, player_id=player_id, clips=clips, mp4=None))

    highlights = Highlights(schema="dinkdata.highlights/v2", video_id=picks.video_id, reels=reels)
    errors = check_highlights(highlights, timeline)
    if errors:
        raise ValueError("; ".join(errors))
    return highlights
