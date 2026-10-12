# Stat definitions

The single source of truth for what each stat means. Code in `stats/` must match
these definitions, and each stat gets unit tests built from hand-written event
logs. To change a definition: update this file, the tests and the code in one PR,
and get the other partner's approval.

Values marked **(proposal)** are starting points. Confirm them with real data
before freezing.

## Terms

| Term | Definition |
|---|---|
| Rally | From the serve hit to the moment the ball is dead (fault, second bounce, out, net, or hit by a player out of turn) |
| Shot | One hit event by one player. The serve is shot 1 of the rally |
| Return | Shot 2. It must be hit after the ball bounces |
| Third shot | Shot 3, by the serving team. It must also be hit after a bounce (two-bounce rule) |
| Volley | A shot hit before the ball bounces on the hitter's side |
| Groundstroke | A shot hit after one bounce |
| Rally winner | The team that did not cause the rally to end |
| Point | Scored only by the serving team when it wins a rally (side-out scoring) |
| Side out | The receiving team wins a rally while the opponents are on their second server (or the first server of the game) and takes the serve |

Doubles score is called as serving team score, receiving team score, server
number (for example `4-3-2`). The first server of the game serves as server 2 (`0-0-2`).

## Events each stat needs

Every stat is computed from `events.json` (schema: `contracts/events.schema.json`).

| Signal | Fields used |
|---|---|
| Rally | `start_frame`, `end_frame`, `server`, `server_number`, `score_before`, `winner_team`, `end_reason` |
| Hit | `t`, `player`, `shot`, `volley`, `conf` |
| Bounce | `t`, `court_xy`, `in`, `close_call`, `conf` |
| Player position | foot point in court feet per frame (`players.parquet`) |

## Phase 1 stats (high confidence)

### Rallies played and rally length
- **Rallies played:** rallies in which the player was on court.
- **Rally length:** number of shots, and duration in seconds (`(end_frame - start_frame) / fps`).
- **Reported as:** average and longest, per game.

### Rallies won and points scored
- **Rallies won (team):** rallies with `winner_team` = the player's team. Credited to both partners.
- **Points scored (team):** rallies won while serving.
- **Points scored on own serve (player):** rallies won while that player was serving.
- **Note:** do not report "points won" for an individual. Credit individuals
  through winners and errors below.

### Serve
- **Serves:** hits with `shot = serve`.
- **Serve in %:** serves whose first bounce is inside the correct service court ÷ serves.
  A bounce on the kitchen line is a fault. Close calls go to review.
- **Serve depth:** distance in ft from the first bounce to the receiver's baseline.
  Buckets **(proposal)**: deep ≤ 5 ft, medium 5-10 ft, short > 10 ft.

### Return
- **Return in %:** returns whose first bounce is in court ÷ returns.
- **Return depth:** distance from the bounce to the serving team's baseline. Same buckets as serve depth.

### Court coverage
- **Heatmap:** foot-point positions over the game, in court feet.
- **Distance moved:** sum of foot-point movement in ft, after smoothing (filter `FILL-IN`).

## Phase 2 stats (medium confidence)

### Shots
- **Shots hit:** hit events attributed to the player.
- **Share of team shots:** player's shots ÷ team's shots, excluding serves.
- **Volley %:** volleys ÷ shots, excluding serves and returns (they can't be volleys).

### Errors
Only counted on the shot that ended the rally, by the player who hit it.

- **Net error:** the ball didn't cross the net (y = 22) after the hit.
- **Out error:** the ball's first bounce after the hit was outside the court (or the service court, for a serve).
- **Serve fault:** a serve that is a net or out error. Report separately from rally errors.
- **Not computed:** forced vs unforced. Report errors as net or out only.

### Winners
- **Winner:** the last shot of a rally the player's team won, where no opponent touched the ball after it.

### Third shot
Classified for every third shot by the serving team:

| Type | Rule (proposal) |
|---|---|
| Drop | First bounce in the opponents' kitchen, or a soft arc the opponents must hit upward |
| Drive | Fast and flat: speed above `FILL-IN`, low apex |
| Lob | High apex, first bounce within `FILL-IN` ft of the opponents' baseline |

- **Third-shot drop %:** drops ÷ third shots (how often the player chooses a drop).
- **Drop success % (proposal):** drops that land in the opponents' kitchen, or that the opponents
  answer without attacking (no drive or speed-up on the next shot), and that don't lose the
  rally on the next shot ÷ drops.

### Kitchen arrival
- **Returning team (proposal):** returner's foot point is at the kitchen line before the
  opponents hit the third shot.
- **Serving team (proposal):** both players at the kitchen line before the opponents hit the
  shot after a successful third-shot drop.
- **Kitchen arrival %:** times arrived ÷ chances.
- "At the kitchen line" is defined in `docs/COURT.md` › Zones.

### Dinks
- **Dink:** a soft shot hit from the kitchen line (hitter at the kitchen line) whose first
  bounce is in the opponents' kitchen.
- **Dinks hit, dink errors** (a dink that is a net or out error), **longest dink rally**
  (most consecutive dinks).

## Phase 3 stats (lower confidence, label as such)

- **Speed-ups attempted and won:** in a dink exchange, a shot whose speed jumps
  above `FILL-IN` × the average of the previous dinks. Won = the speed-up hitter's team wins the rally.
- **Forehand vs backhand:** from pose, which side of the body the paddle is on at contact.
- **Ball speed (mph):** from a 3D arc fitted between hit and bounce. Always shown as approximate.

## Not computed

Forced vs unforced errors, spin, automatic calls on balls touching a line, and
kitchen (foot) faults during volleys until feet tracking is reliable near the line.

## Open questions

- [ ] Confirm or change every **(proposal)** value with the first labelled games.
- [ ] Which 3 stats do the first beta players care about most?
- [ ] Should stats exclude rallies with low-confidence events, or include them with a flag?
