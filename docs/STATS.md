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
- Counts are per player per game unless the table says team.
- Values marked provisional are confirmed on real labelled games before they are frozen.

## v1 stats

| Stat | Who | Definition |
|---|---|---|
| Final score | Team | The score as played, game by game. Only the serving team scores. A game starts at `0-0-2` |
| Games won | Team | Games the team won. A game cut off at 45 minutes has no winner |
| Rallies won | Team | Rallies the team won. Both partners get credit |
| Points scored | Team | Rallies the team won while serving |
| Serve in % | Player | Serves whose first bounce lands in the diagonal service court, divided by serves |
| Serve depth | Player | Feet from the serve's first bounce to the receiver's baseline, bucketed as deep (5 ft or less), medium (over 5 to 10 ft) or short (over 10 ft). Provisional |
| Return in % | Player | Returns whose first bounce lands in the serving team's half, divided by returns |
| Return depth | Player | Feet from the return's first bounce to the serving team's baseline, with the same buckets |
| Net errors | Player | Rally-ending shots by the player that didn't cross the net |
| Out errors | Player | Rally-ending shots by the player whose first bounce was outside the court |
| Serve faults | Player | Serves that were net or out errors. Counted separately from net and out errors |
| Winners | Player | The last shot of a rally the player's team won, which no opponent touched after it |
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
- A rally with a rule deviation still counts. A team scores when it wins a rally on its own
  serve, whoever served.
- A replayed rally doesn't count toward any stat.

## Shipping rules

- For each stat, each player's count must be off by at most 1 in at least 90% of test
  player-games where it's shipped, and better than the median-count baseline.
- Coverage is reported overall and per camera setup. The provisional overall floor is 70% of
  player-games. Each camera setup gets its own floor after M1.

## Later stats

In this order unless the beta says otherwise: dink success rate (a dink that lands in the
opponents' kitchen and isn't an error), an all-shots heat map, unforced errors and forehand
versus backhand. Both owners approve any other stat first.
