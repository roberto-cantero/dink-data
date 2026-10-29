"""Events mode: marks on top of rally gold, the fields it derives, and the gold events.json."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from dinkdata.contracts.game_log import EventLog
from dinkdata.contracts.rallies import RallyLabels
from dinkdata.studio import events, rally
from dinkdata.studio.events import Basis, EventMark, Footage, IncompleteMarks, Marks

VIDEO_ID = "v_5eed00000000a051"
# 60 camera frames 1/30 s apart, with frame 10 and frames 30 to 32 dropped, so frame indexes
# and times don't line up after the first gap.
TIMES = [n * (512 / 15360) for n in range(60) if n not in (10, 30, 31, 32)]
FOOTAGE = Footage(
    video_id=VIDEO_ID, times=TIMES, fps_nominal=30.0, dropped_frames=4, width=64, height=48
)
CROPS = {"p1": "labels/gold-rallies/x/marti/crops/p1/v1.png", "p2": None, "p3": None, "p4": None}


def gold() -> RallyLabels:
    """Two rallies in one game that the recording cuts off, as rally mode saves them."""
    marks = rally.Marks.model_validate(
        {
            "games": [{"start_t": 0.1, "end_t": 1.85, "finished": False, "target": 11}],
            "rallies": [
                {"t": 0.2, "end_t": 0.6, "server": "p1", "side": "right", "winner": "A"},
                {"t": 0.8, "end_t": 1.5, "server": "p1", "side": "left", "winner": "B"},
            ],
        }
    )
    return rally.to_labels(marks, VIDEO_ID, "marti")


@pytest.fixture
def basis() -> Basis:
    return Basis(gold(), FOOTAGE)


def nearest(t: float) -> int:
    return min(range(len(TIMES)), key=lambda i: abs(TIMES[i] - t))


def settled(basis: Basis) -> Marks:
    """The suggestions with every rally accepted and given an end reason."""
    marks = basis.suggested()
    for r in marks.rallies:
        r.confirmed = ["start", "end", "winner"]
        r.end_reason = "unexplained"
    return marks


def hit(id_: str, frame: int, player: str | None) -> EventMark:
    return EventMark.model_validate({"id": id_, "type": "hit", "frame": frame, "player": player})


def bounce(id_: str, frame: int, xy: tuple[float, float] | None = (10.0, 20.0)) -> EventMark:
    return EventMark.model_validate({"id": id_, "type": "bounce", "frame": frame, "image_xy": xy})


def net(id_: str, frame: int) -> EventMark:
    return EventMark.model_validate({"id": id_, "type": "net", "frame": frame})


# ---- suggestions from rally gold ----


def test_rally_gold_becomes_suggestions_at_the_nearest_frames(basis):
    marks = basis.suggested()
    assert [r.id for r in marks.rallies] == ["g1_r1", "g1_r2"]
    first, second = marks.rallies
    assert (first.start_frame, first.end_frame) == (nearest(0.2), nearest(0.6))
    assert (second.start_frame, second.end_frame) == (nearest(0.8), nearest(1.5))
    assert [first.winner, second.winner] == ["A", "B"]
    assert all(r.confirmed == [] and r.events == [] for r in marks.rallies)


def test_suggestions_are_uncertain_until_accepted(basis):
    view = events.review(basis.suggested(), basis)
    first = view.rallies[0]
    assert [i.what for i in first.uncertain] == ["start", "end", "winner", "end_reason"]
    assert not first.reviewed
    assert [i.frame for i in view.uncertain] == sorted(i.frame for i in view.uncertain)


def test_a_rally_is_reviewed_once_every_suggestion_is_settled(basis):
    view = events.review(settled(basis), basis)
    assert all(r.reviewed and r.uncertain == [] for r in view.rallies)


# ---- R moves the nearest start or end ----


@pytest.mark.parametrize(
    ("t", "expected"),
    [(0.15, (0, "start")), (0.65, (0, "end")), (0.75, (1, "start")), (1.8, (1, "end"))],
)
def test_r_moves_the_rally_boundary_nearest_the_playhead(basis, t, expected):
    assert events.boundary_near(basis.suggested(), basis, nearest(t)) == expected


def test_r_finds_a_rejected_boundary_at_its_suggestion(basis):
    marks = basis.suggested()
    marks.rallies[1].start_frame = None
    assert events.boundary_near(marks, basis, nearest(0.8)) == (1, "start")


# ---- derived fields ----


def test_shot_index_volley_and_receiver_come_from_the_marks(basis):
    marks = settled(basis)
    r = marks.rallies[1]
    s = r.start_frame
    assert s is not None
    # Serve, bounce, return, bounce, third shot, then a volley with no bounce before it.
    r.events = [
        hit("a", s + 1, "p1"),
        bounce("b", s + 3),
        hit("c", s + 5, "p4"),
        bounce("d", s + 7),
        hit("e", s + 9, "p2"),
        hit("f", s + 11, "p3"),
    ]
    view = events.review(marks, basis).rallies[1]
    shots = {e.id: (e.shot_index, e.volley) for e in view.events}
    assert shots == {
        "a": (1, False),
        "b": (None, None),
        "c": (2, False),
        "d": (None, None),
        "e": (3, False),
        "f": (4, True),
    }
    log = events.to_log(marks, basis, CROPS)
    assert log.games[0].rallies[1].serve.receiver == "p4"


def test_the_return_is_never_a_volley(basis):
    marks = settled(basis)
    r = marks.rallies[1]
    s = r.start_frame
    assert s is not None
    r.events = [hit("a", s + 1, "p1"), hit("b", s + 3, "p3")]
    shots = {e.id: e.volley for e in events.review(marks, basis).rallies[1].events}
    assert shots == {"a": False, "b": False}


def test_events_are_put_in_frame_order_whatever_order_they_were_marked(basis):
    marks = settled(basis)
    r = marks.rallies[1]
    s = r.start_frame
    assert s is not None
    r.events = [hit("late", s + 6, "p3"), hit("early", s + 2, "p1")]
    view = events.review(marks, basis).rallies[1]
    assert [(e.id, e.shot_index) for e in view.events] == [("early", 1), ("late", 2)]


@pytest.mark.parametrize(
    ("tail", "proposed"),
    [
        pytest.param([net("n", 6)], "net", id="ends in the net"),
        pytest.param([bounce("x", 5), bounce("y", 7)], "double_bounce", id="two bounces"),
        pytest.param([bounce("x", 5), hit("z", 7, "p3")], None, id="unknown"),
    ],
)
def test_an_end_reason_is_proposed_from_the_last_events(basis, tail, proposed):
    marks = basis.suggested()
    r = marks.rallies[1]
    s = r.start_frame
    assert s is not None
    for e in tail:
        e.frame += s
    r.events = [hit("a", s + 1, "p1"), *tail]
    view = events.review(marks, basis).rallies[1]
    assert view.proposed_end_reason == proposed
    assert "end_reason" in [i.what for i in view.uncertain]


def test_a_hit_without_a_hitter_is_uncertain(basis):
    marks = settled(basis)
    s = marks.rallies[0].start_frame
    assert s is not None
    marks.rallies[0].events = [hit("a", s + 1, None)]
    view = events.review(marks, basis).rallies[0]
    assert [(i.what, i.event) for i in view.uncertain] == [("hitter", "a")]
    saved = events.to_log(marks, basis, CROPS).games[0].rallies[0].events[0]
    assert saved.type == "hit" and saved.player is None


# ---- warnings and problems ----


def test_a_winner_that_differs_from_rally_gold_is_flagged_but_saves(basis):
    marks = settled(basis)
    marks.rallies[0].winner = "B"
    view = events.review(marks, basis).rallies[0]
    assert any("rally gold" in w for w in view.warnings)
    assert view.problems == []
    assert events.to_log(marks, basis, CROPS).games[0].rallies[0].winner_team == "B"


def test_a_first_hit_by_someone_other_than_the_server_is_flagged(basis):
    marks = settled(basis)
    s = marks.rallies[0].start_frame
    assert s is not None
    marks.rallies[0].events = [hit("a", s + 1, "p2")]
    assert any("server" in w for w in events.review(marks, basis).rallies[0].warnings)


def test_a_return_by_the_serving_team_is_flagged_and_has_no_receiver(basis):
    marks = settled(basis)
    s = marks.rallies[0].start_frame
    assert s is not None
    marks.rallies[0].events = [hit("a", s + 1, "p1"), hit("b", s + 3, "p2")]
    assert any("return" in w for w in events.review(marks, basis).rallies[0].warnings)
    assert events.to_log(marks, basis, CROPS).games[0].rallies[0].serve.receiver is None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(lambda m: setattr(m.rallies[0], "start_frame", None), "Press R", id="start"),
        pytest.param(lambda m: setattr(m.rallies[1], "end_frame", None), "Press R", id="end"),
        pytest.param(
            lambda m: setattr(m.rallies[0], "end_frame", m.rallies[0].start_frame),
            "after",
            id="end before start",
        ),
        pytest.param(
            lambda m: setattr(m.rallies[1], "start_frame", m.rallies[0].end_frame),
            "overlaps",
            id="overlap",
        ),
        pytest.param(
            lambda m: m.rallies[0].events.append(hit("a", 50, "p1")), "outside", id="event out"
        ),
        pytest.param(
            lambda m: m.rallies[0].events.append(bounce("a", 8, (65.0, 10.0))),
            "picture",
            id="click off the picture",
        ),
        pytest.param(lambda m: setattr(m.rallies[1], "end_frame", 56), "video", id="past end"),
    ],
)
def test_marks_that_cant_be_saved_are_problems(basis, change, message):
    marks = settled(basis)
    change(marks)
    view = events.review(marks, basis)
    assert any(message in p for r in view.rallies for p in r.problems)
    with pytest.raises(IncompleteMarks, match=message):
        events.to_log(marks, basis, CROPS)


def test_a_rally_rally_gold_doesnt_have_is_a_problem(basis):
    marks = settled(basis)
    marks.rallies[1].id = "g1_r9"
    with pytest.raises(IncompleteMarks, match="g1_r9"):
        events.to_log(marks, basis, CROPS)


def test_a_replay_has_no_winner():
    marks = rally.Marks.model_validate(
        {
            "games": [{"start_t": 0.1, "end_t": 1.85, "finished": False, "target": 11}],
            "rallies": [
                {"t": 0.2, "end_t": 0.6, "server": "p1", "side": "right", "replay": True},
                {"t": 0.8, "end_t": 1.5, "server": "p1", "side": "right", "winner": "B"},
            ],
        }
    )
    basis = Basis(rally.to_labels(marks, VIDEO_ID, "marti"), FOOTAGE)
    marks_ = settled(basis)
    assert marks_.rallies[0].winner is None
    events.to_log(marks_, basis, CROPS)
    marks_.rallies[0].winner = "A"
    with pytest.raises(IncompleteMarks, match="replay"):
        events.to_log(marks_, basis, CROPS)


# ---- the saved file ----


def test_the_saved_file_is_a_valid_game_log_with_times_from_frames(basis):
    marks = settled(basis)
    r = marks.rallies[1]
    s = r.start_frame
    assert s is not None
    r.events = [
        hit("a", s + 1, "p1"),
        bounce("b", s + 3),
        bounce("c", s + 4, None),
        net("d", s + 6),
    ]
    log = events.to_log(marks, basis, CROPS)
    EventLog.model_validate(log.model_dump(by_alias=True))
    assert log.schema_ == "dinkdata.events/v3"
    assert log.camera is None
    assert log.video.frames == f"videos/{VIDEO_ID}.frames.parquet"
    assert log.video.dropped_frames == 4
    assert [p.crop for p in log.players] == list(CROPS.values())
    game = log.games[0]
    assert [s.type for s in log.segments] == ["game"]
    assert (log.segments[0].start_frame, log.segments[0].end_frame) == (
        game.start_frame,
        game.end_frame,
    )
    saved = game.rallies[1]
    assert saved.serve.server == "p1" and saved.serve.side == "left"
    assert saved.winner_source == "label" and saved.reviewed and saved.conf == 1
    assert [e.id for e in saved.events] == ["g1_r2_e1", "g1_r2_e2", "g1_r2_e3", "g1_r2_e4"]
    assert (saved.start_t, saved.end_t) == (TIMES[saved.start_frame], TIMES[saved.end_frame])
    assert [e.t for e in saved.events] == [TIMES[e.frame] for e in saved.events]
    assert (game.start_t, game.end_t) == (TIMES[game.start_frame], TIMES[game.end_frame])
    first, unseen = saved.events[1], saved.events[2]
    assert first.type == "bounce" and first.image_xy == (10.0, 20.0)
    assert first.court_xy is None and first.in_ is None and not first.close_call
    assert unseen.type == "bounce" and unseen.image_xy is None


def test_a_half_done_game_saves_with_unreviewed_rallies(basis):
    log = events.to_log(basis.suggested(), basis, CROPS)
    first = log.games[0].rallies[0]
    assert not first.reviewed
    assert first.end_reason is None
    assert first.winner_team == "A" and first.winner_source == "label"


def test_a_rally_moved_outside_its_game_stretches_the_game(basis):
    marks = settled(basis)
    marks.rallies[0].start_frame = 0
    game = events.to_log(marks, basis, CROPS).games[0]
    assert game.start_frame == 0 and game.start_t == 0


def test_contract_errors_still_raise():
    basis = Basis(gold(), replace(FOOTAGE, fps_nominal=0))
    with pytest.raises(ValidationError):
        events.to_log(settled(basis), basis, CROPS)


# ---- merging a saved file with the latest rally gold ----


def test_a_saved_file_comes_back_with_its_edits(basis):
    marks = settled(basis)
    s = marks.rallies[0].start_frame
    assert s is not None
    marks.rallies[0].start_frame = s - 1
    marks.rallies[0].events = [hit("a", s, "p1")]
    marks.rallies[1].confirmed = []
    marks.rallies[1].end_reason = None
    saved = events.to_log(marks, basis, CROPS)
    back = events.merge(basis, saved)
    assert back.orphans == []
    first, second = back.rallies
    assert first.start_frame == s - 1
    assert sorted(first.confirmed) == ["end", "start", "winner"]
    assert first.end_reason == "unexplained"
    assert [(e.type, e.frame, e.player) for e in first.events] == [("hit", s, "p1")]
    assert second.confirmed == [] and second.end_reason is None


def test_merge_follows_rally_gold_when_it_gains_a_rally(basis):
    """Rally ids are positions, so a rally added in rally mode renumbers the ones after it.
    The merge matches rallies by where they are in the video, not by id."""
    marks = settled(basis)
    s = marks.rallies[1].start_frame
    assert s is not None
    marks.rallies[1].events = [hit("a", s + 1, "p1")]
    saved = events.to_log(marks, basis, CROPS)

    added = rally.Marks.model_validate(
        {
            "games": [{"start_t": 0.05, "end_t": 1.85, "finished": False, "target": 11}],
            "rallies": [
                {"t": 0.06, "end_t": 0.12, "server": "p1", "side": "right", "replay": True},
                {"t": 0.2, "end_t": 0.6, "server": "p1", "side": "right", "winner": "A"},
                {"t": 0.8, "end_t": 1.5, "server": "p1", "side": "left", "winner": "B"},
            ],
        }
    )
    newer = Basis(rally.to_labels(added, VIDEO_ID, "marti"), FOOTAGE)
    back = events.merge(newer, saved)
    assert [r.id for r in back.rallies] == ["g1_r1", "g1_r2", "g1_r3"]
    assert back.rallies[0].events == [] and back.rallies[0].confirmed == []
    assert [e.player for e in back.rallies[2].events] == ["p1"]
    assert back.orphans == []


def test_a_rally_gone_from_rally_gold_keeps_its_events_and_blocks_the_save(basis):
    marks = settled(basis)
    s = marks.rallies[1].start_frame
    assert s is not None
    marks.rallies[1].events = [hit("a", s + 1, "p1")]
    saved = events.to_log(marks, basis, CROPS)

    fewer = rally.Marks.model_validate(
        {
            "games": [{"start_t": 0.1, "end_t": 1.85, "finished": False, "target": 11}],
            "rallies": [{"t": 0.2, "end_t": 0.6, "server": "p1", "side": "right", "winner": "A"}],
        }
    )
    newer = Basis(rally.to_labels(fewer, VIDEO_ID, "marti"), FOOTAGE)
    back = events.merge(newer, saved)
    assert [r.id for r in back.rallies] == ["g1_r1"]
    assert [o.id for o in back.orphans] == ["g1_r2"]
    assert any("rally gold" in p for p in events.review(back, newer).orphans)
    with pytest.raises(IncompleteMarks, match="rally gold"):
        events.to_log(back, newer, CROPS)
    back.orphans = []
    events.to_log(back, newer, CROPS)


def test_a_rally_gone_from_rally_gold_with_nothing_on_it_is_dropped(basis):
    saved = events.to_log(basis.suggested(), basis, CROPS)
    fewer = rally.Marks.model_validate(
        {
            "games": [{"start_t": 0.1, "end_t": 1.85, "finished": False, "target": 11}],
            "rallies": [{"t": 0.2, "end_t": 0.6, "server": "p1", "side": "right", "winner": "A"}],
        }
    )
    back = events.merge(Basis(rally.to_labels(fewer, VIDEO_ID, "marti"), FOOTAGE), saved)
    assert back.orphans == []
