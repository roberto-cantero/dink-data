"""`build_highlights`: a hand-written rally list plus rally boundaries, as highlights.json."""

import pytest
from pydantic import ValidationError

from dinkdata.contracts.games import RallyBase, Serve
from dinkdata.contracts.rallies import RallyLabels
from dinkdata.highlights.build import RallyList, build_highlights, clip_span
from tests.contracts.examples import example


def rally_base(rally_id: str, start_t: float, end_t: float) -> RallyBase:
    return RallyBase(
        id=rally_id,
        start_t=start_t,
        end_t=end_t,
        serve=Serve(server="p1", side="right", receiver="p3", conf=1.0),
        winner_team="A",
        replay=False,
    )


VIDEO_ID = "v_5eed00000000a001"


@pytest.fixture
def labels() -> RallyLabels:
    return RallyLabels.model_validate(example("rallies"))


def picks(*rows: dict) -> RallyList:
    return RallyList.model_validate({"video_id": VIDEO_ID, "picks": list(rows)})


def pick(rally_id: str, player_id: str = "p1", game_id: str = "g1", **extra) -> dict:
    row = {
        "game_id": game_id,
        "player_id": player_id,
        "rally_id": rally_id,
        "reasons": ["winner"],
        "score": 1.0,
    }
    row.update(extra)
    return row


def test_one_pick_becomes_one_padded_clip(labels):
    highlights = build_highlights(picks(pick("g1_r6")), labels)
    assert len(highlights.reels) == 1
    reel = highlights.reels[0]
    assert (reel.game_id, reel.player_id) == ("g1", "p1")
    rally = labels.games[0].rallies[5]
    assert rally.id == "g1_r6"
    clip = reel.clips[0]
    assert clip.id == "g1_p1_c1"
    assert clip.start_t == pytest.approx(rally.start_t - 1.0)
    assert clip.end_t == pytest.approx(rally.end_t + 1.5)
    assert clip.reasons == ["winner"]
    assert clip.score == 1.0


def test_clips_are_sorted_by_rally_time_not_pick_order(labels):
    highlights = build_highlights(picks(pick("g1_r9"), pick("g1_r3")), labels)
    clip_ids = [c.rally_id for c in highlights.reels[0].clips]
    assert clip_ids == ["g1_r3", "g1_r9"]


def test_picks_split_into_one_reel_per_game_and_player(labels):
    highlights = build_highlights(
        picks(pick("g1_r1", player_id="p1"), pick("g1_r2", player_id="p2")), labels
    )
    keys = {(r.game_id, r.player_id) for r in highlights.reels}
    assert keys == {("g1", "p1"), ("g1", "p2")}


def test_padding_never_runs_into_the_next_serve(labels):
    # g1_r1 ends at 135.57 and g1_r2 starts at 151.28: padding alone wouldn't clash, so pad
    # generously to prove the clamp, not just the arithmetic.
    highlights = build_highlights(picks(pick("g1_r1")), labels, end_pad=20.0)
    clip = highlights.reels[0].clips[0]
    next_start = labels.games[0].rallies[1].start_t
    assert clip.end_t < next_start


def test_start_padding_never_goes_negative(labels):
    # g1_r1 is this video's first rally; 1 second of padding would go below zero.
    highlights = build_highlights(picks(pick("g1_r1")), labels, start_pad=1000.0)
    assert highlights.reels[0].clips[0].start_t == 0.0


def test_clip_span_pads_and_clamps():
    rally = rally_base("g1_r1", start_t=10.0, end_t=20.0)
    start_t, end_t = clip_span(rally, next_start=30.0, start_pad=1.0, end_pad=1.5)
    assert (start_t, end_t) == pytest.approx((9.0, 21.5))


def test_clip_span_floors_start_at_zero():
    rally = rally_base("g1_r1", start_t=0.5, end_t=2.0)
    start_t, _ = clip_span(rally, next_start=10.0, start_pad=1.0, end_pad=0.0)
    assert start_t == 0.0


def test_clip_span_never_reaches_the_next_start():
    rally = rally_base("g1_r1", start_t=10.0, end_t=12.0)
    _, end_t = clip_span(rally, next_start=12.5, start_pad=0.0, end_pad=5.0)
    assert end_t < 12.5


def test_clip_span_rejects_a_rally_too_short_for_the_margin():
    # A 5 ms rally with no gap before the next one: padding can't produce a real clip.
    rally = rally_base("g1_r1", start_t=10.0, end_t=10.005)
    with pytest.raises(ValueError, match="empty or backwards"):
        clip_span(rally, next_start=10.005, start_pad=0.0, end_pad=1.5)


def test_unknown_rally_is_rejected(labels):
    with pytest.raises(ValueError, match="g1_r99"):
        build_highlights(picks(pick("g1_r99")), labels)


def test_rally_from_the_wrong_game_is_rejected(labels):
    with pytest.raises(ValueError, match="g1_r1"):
        build_highlights(picks(pick("g1_r1", game_id="g2")), labels)


def test_video_id_mismatch_is_rejected(labels):
    mismatched = RallyList.model_validate({"video_id": "v_5eed00000000ffff", "picks": []})
    with pytest.raises(ValueError, match="video_id"):
        build_highlights(mismatched, labels)


def test_result_is_a_valid_highlights_file(labels):
    highlights = build_highlights(picks(pick("g1_r1"), pick("g1_r5")), labels)
    assert highlights.schema_ == "dinkdata.highlights/v2"
    assert highlights.video_id == VIDEO_ID


@pytest.mark.parametrize(
    ("row", "match"),
    [
        pytest.param({"reasons": []}, "at least 1 item", id="no reason"),
        pytest.param({"reasons": ["cool"]}, "cool", id="unknown reason"),
        pytest.param({"score": -1}, "greater than or equal to 0", id="negative score"),
    ],
)
def test_rally_list_rejects_bad_picks(row, match):
    with pytest.raises(ValidationError, match=match):
        picks(pick("g1_r1", **row))
