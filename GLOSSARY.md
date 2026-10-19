# DinkData

DinkData turns a PickleCam recording of a doubles pickleball game into per-player stats and
highlight reels. This glossary fixes the words we use for the game, the footage and our data.
`docs/DESIGN.md` explains how the system works.

## The game

**Rally**:
Play from the serve until the ball is dead.
_Avoid_: point (a point is scored only by the serving team), exchange

**Game**:
One game of side-out scoring inside a recording, from `0-0-2` until a team wins or the recording ends.
_Avoid_: match, set

**Side-out scoring**:
The scoring system in which only the serving team scores, each team has two servers per turn, and the first turn of a game has one server.
_Avoid_: traditional scoring

**Rally scoring**:
A scoring system in which either team can score on any rally. Not supported in v1.

**Score call**:
The score as serving team score, receiving team score and server number, such as `4-3-2`.
_Avoid_: score line

**Server number**:
Whether the serving player is the first or second server of their team's turn, 1 or 2.

**Side-out**:
The moment the serving team loses the serve to the other team.
_Avoid_: turnover, change of serve

**Starting positions**:
The sides of the court a team's players stand on at the start of a game. They stand there again whenever that team's score is even.

**Stacking**:
Partners lining up on non-standard sides, usually to keep a forehand in the middle.

**Two-bounce rule**:
The rule that the serve and the return must each bounce before being hit.

**Kitchen**:
The 7-foot zone on each side of the net where players may not volley.
_Avoid_: non-volley zone, NVZ

**Service court**:
The box diagonally opposite the server where the serve must land, beyond the kitchen line.
_Avoid_: service box

**Fault**:
A rule break that ends the rally, such as a serve out, a volleyed return, a kitchen volley, the ball hitting a player or a foot fault.

**Rule deviation**:
A rally where the players broke the serving rules, such as the wrong partner serving or a missed side-out.
_Avoid_: error (errors are shots)

**Net-cord serve**:
A serve that clips the net and lands in. It is live.
_Avoid_: let

**Volley**:
A shot hit before the ball bounces.

**Dink**:
A soft shot that lands in the opponents' kitchen.

**Lob**:
A high shot over the opponents.

**Winner**:
The last shot of a rally won by the hitter's team, which no opponent touched.

**Net error**:
A rally-ending shot that didn't cross the net.

**Out error**:
A rally-ending shot whose first bounce was outside the court, or outside the service court for a serve.

**Close call**:
A bounce near enough a line that we flag it for review instead of calling it in or out.
_Avoid_: line call

## Players and teams

**Player**:
One of the four people playing the game, named p1 to p4.
_Avoid_: athlete, user (a user is whoever receives the stats)

**p1, p2, p3, p4**:
p1 is the first server in the recording and p2 is p1's partner. p3 receives the first serve and p4 is p3's partner.

**Team A, team B**:
Team A is p1 and p2. Team B is p3 and p4.
_Avoid_: home and away, side

**Partner identity**:
Knowing which of a team's two players is which, especially at the serve.

**Serve state**:
What the cameras show at a serve: the serving team, the serving player, the side they serve from and who receives.

## Footage

**Recording**:
One PickleCam video of one camera session. It usually holds one game, and can hold warm-up, several games or a game cut off at 45 minutes.
_Avoid_: session (PickleCam's internal word), clip (a clip is part of a reel)

**Facility**:
A venue with PickleCam cameras.
_Avoid_: club, venue, site

**Camera**:
One fixed PickleCam camera filming one court.

**Camera setup**:
How a camera is mounted: down-the-line low (2 m or below), down-the-line high (above 2 m), or diagonal.
_Avoid_: angle, view

**Down-the-line**:
A camera behind one baseline, looking down the centre line.
_Avoid_: DTL in prose

**Game mode**:
Whether the players are in a game, warming up, drilling or idle.

**Segment**:
A stretch of a recording with one game mode.

**Court coordinates**:
Positions on the court in feet, with the origin at the far-left baseline corner as seen from the camera, x across and y toward the camera.

**Calibration**:
The fitted lens and position of one camera, which converts floor pixels to court coordinates.

**Visibility mask**:
The part of the court a camera can see.

**Background image**:
A picture of the empty court for a stretch of a recording.

## Events

**Event**:
A hit, a bounce or the ball going into the net, at one moment of a rally.

**Candidate**:
A moment the system proposes as a possible event, before the rally grammar accepts or rejects it.

**Rally grammar**:
The rules of what can follow what inside a rally.

**End reason**:
Why a rally ended: net, out, double bounce, unreturned, fault or unexplained.

**Game log**:
The structured record of a recording's games, rallies and events.
_Avoid_: event log, match log

## Outputs

**Stat**:
A number for one player or team in one game, such as serve in %.

**Shipped**:
A stat that passed its confidence checks and appears in the report.
_Avoid_: published

**Coverage**:
The share of stats shipped.

**Landing map**:
A top-down court showing where a player's serves, returns and out-errors bounced.
_Avoid_: heat map (the all-shots heat map is a later feature)

**Report**:
The one-page summary of a game for its players.

**Reel**:
A short highlight video for one player, made of clips from one game.
_Avoid_: highlight video, montage

**Clip**:
One rally's stretch of video inside a reel.

## Labels and evaluation

**Gold set**:
Hand-made labels used only to measure accuracy, never to train. It has a full-event tier and a rally-level tier.
_Avoid_: ground truth, test data

**Full-event gold**:
Gold labels with every hit, bounce, hitter and rally outcome of a game.

**Rally-level gold**:
Gold labels with only each rally's server, side and winner.

**Silver labels**:
Model output corrected by a person, used for training.

**Agreement game**:
A game both owners label separately, to measure how well two people agree.

**Held-out facility**:
A facility whose recordings are used only for testing.

**Baseline**:
The trivial prediction a stat must beat, such as every player's median count.

**Patch**:
A human correction stored on top of a pipeline run's output.
_Avoid_: edit, fix

**Run**:
One execution of the pipeline over a set of recordings.
