# Stat definitions

This file is the authority for stat code in `src/dinkdata/stats/`. A stat's code must match its
definition here, and each rule has a unit test built from a hand-written game log. Changing a
definition means updating this file, its tests and its code in one PR that both owners approve.
`docs/DESIGN.md` section 3 explains why these stats were chosen.

## Rules for every stat

- A stat is a pure function of `events.json`. It reads no video and runs no model.
- Every stat returns a value, a numerator and denominator where they apply, a confidence, a
  shipped flag and, when not shipped, a reason.
- A stat ships only if its confidence passes its threshold and the events it needs were
  visible. Otherwise it is left out with a reason such as `near_court_not_visible`.
- Counts are per player per game.
- No stat reports the score or a number players could check against it: no final score,
  games won, points scored or rallies won (ADR 0019). Many players lose track of side-out
  scoring, so a correct count would still look wrong to them.
- Values marked provisional are confirmed on real labelled games before they are frozen.

## v1 stats

| Stat | Who | Definition |
|---|---|---|
| Serve in % | Player | Serves whose first bounce lands in the diagonal service court, divided by serves |
| Serve depth | Player | Feet from the serve's first bounce to the receiver's baseline, bucketed as deep (5 ft or less), medium (over 5 to 10 ft) or short (over 10 ft). Provisional |
| Return in % | Player | Returns whose first bounce lands in the serving team's half, divided by returns |
| Return depth | Player | Feet from the return's first bounce to the serving team's baseline, with the same buckets |
| Net errors | Player | Rally-ending shots by the player that didn't cross the net |
| Out errors | Player | Rally-ending shots by the player whose first bounce was outside the court |
| Serve faults | Player | Serves that were net or out errors. Counted separately from net and out errors |
| Winners | Player | The last shot of a rally the player's team won, which no opponent returned. A ball that hits an opponent counts |
| Landing map | Player | The court positions of the player's serve bounces, return bounces and out-error bounces |

## Edge cases

- A serve that touches the kitchen line is a fault. A serve on any other line of its service
  court is in.
- A return or third shot hit before it bounced is a fault, under the two-bounce rule.
- A serve whose first bounce the camera can't see is left out of serve in % and depth. It
  is not counted as in or out.
- A net-cord serve that lands in is in.
- A close call is flagged for review and left out until reviewed.
- An error belongs only to the shot that ended the rally.
- A rally where the players broke the serving rules still counts. Its winner comes from what
  happened on court, never from the score.
- A replayed rally doesn't count toward any stat.

## How the code reads these rules

`src/dinkdata/stats/compute.py` follows these readings, and each has a unit test. Court
positions and zones follow `docs/COURT.md`, and `src/dinkdata/court/zones.py` holds the zones.

### Shots and bounces

- A shot's first bounce is the first bounce after it and before the next hit. Net events in
  between are skipped, so a net-cord serve is judged by where it lands.
- The code judges in or out from the bounce's `court_xy`, not from the bounce's `in` field.
- A serve's bounce is taken to be on the receivers' half. It is in if it lands in the service
  court diagonal from the server's side.
- A return is in if it lands in the court on the servers' half. That half is the one the
  serve didn't land on. When the serve's bounce wasn't seen, the return only has to land in
  the court.
- A serve or return that is the rally's last shot in a rally that ended `net` counts as not in.
- A return hit before the serve bounced counts as not in. The serve isn't judged.
- When the third shot is hit before the return bounced, the return isn't judged.

### Depth, errors and winners

- Depth counts only the serves and returns that landed in. It measures the distance to the
  baseline of the half where the ball landed.
- Net errors, out errors and serve faults come from the rally's `end_reason` and its last hit.
  A rally that ended `net` or `out` on the serve is a serve fault. It is not a net or out
  error.
- A shot is a winner when the hitter's team won the rally, the shot was the rally's last hit,
  and one of these holds:
  - The rally ended `double_bounce`.
  - The rally ended `fault`. No opponent hit came after the shot, so the fault is the ball
    hitting an opponent. The game log can't tell this from an opponent touching the net,
    which also counts.
  - The end is `null` or `unexplained`, and the shot's first bounce was seen in the court on
    the opponents' half. That is a hard shot whose second bounce left the picture.
- A rally that ended `unreturned` has no winner, because an opponent's paddle touched the
  ball.
- The landing map shows the seen first bounces of the player's serves and returns, and the
  bounces of their out errors. Serve faults appear with the serves.

### Confidence and shipping

A stat collects items. A counted item adds to the stat. Its confidence is the lowest of the
rally's `conf` and the `conf` of each event it used. A left-out item might belong to the stat
but couldn't be judged, and it has a reason. When the hitter is unknown, the item is left out
for every player who might have hit it.

A stat's confidence is the mean confidence of its counted items times the share of items that
were counted. A stat with no items takes the mean `conf` of the game's rallies. The stat ships
if its confidence is at least 0.5 (provisional) and it has something to show. A percentage
needs a denominator, a depth needs a serve or return that landed in, and a landing map needs
a point. Otherwise the reason is one of these.

| Reason | Meaning |
|---|---|
| `no_rallies` | The game has no rallies apart from replays |
| `no_serves`, `no_returns` | The player hit no serve or return that could be judged |
| `no_serves_in`, `no_returns_in` | No serve or return landed in, so there is no depth |
| `no_bounces` | The landing map has no points |
| `bounces_not_visible` | The camera didn't see the bounces the stat needs |
| `close_call_review` | A close call waits for a person's review |
| `low_attribution_conf` | The hitter is unknown |
| `winner_unknown` | The rally's winner is unknown |
| `events_missing` | The rally has no hits in the game log |
| `low_conf` | The confidence is below the threshold, and no item was left out |

When items were left out, the reason is the most common left-out reason.

## Shipping rules

- For each stat, each player's count must be off by at most 1 in at least 90% of test
  player-games where it's shipped, and better than the median-count baseline.
- Coverage is reported overall and per camera setup. The provisional overall floor is 70% of
  player-games. Each camera setup gets its own floor after M1.

## Later stats

In this order unless the beta says otherwise: dink success rate (a dink that lands in the
opponents' kitchen and isn't an error), an all-shots heat map, unforced errors and forehand
versus backhand. Both owners approve any other stat first.
