# Data, storage and privacy

Where data lives, how we get it, and the rules that keep personal data out. `docs/DESIGN.md`
sections 8 and 11 have the reasoning, and ADRs 0006, 0007, 0017 and 0018 record the decisions.

## Storage

All files live in one Cloudflare R2 bucket named `dinkdata`. R2 has no object versioning, so
labels, calibrations and patches are written once to versioned paths and never overwritten. A
nightly scheduled job copies `labels/` and `cameras/` to a second bucket as a backup.

```
catalog/catalog.parquet                              list of known videos, no personal data
catalog/id_map.parquet                               our ids to PickleCam session ids, private
videos/{video_id}.mp4                                sample and gold videos, no audio
videos/{video_id}.frames.parquet                     frame timestamps
cameras/{camera_id}/v{n}/camera.json                 calibrations
labels/gold-events/{video_id}/{labeller}/v{n}.json   full-event gold
labels/gold-rallies/{video_id}/{labeller}/v{n}.json  rally-level gold
labels/ball/{video_id}/{labeller}/v{n}.parquet       ball clicks
labels/feet/{video_id}/{labeller}/v{n}.parquet       foot clicks
labels/silver/{video_id}/{run_id}/                   patch.json and the patched events.json
runs/{run_id}/{video_id}/                            pipeline outputs
models/{name}/{version}/                             checkpoint, config, eval results
eval/{run_id}.csv                                    metric history
```

During M0 to M3, R2 is the shared development store for the games, labels, calibrations and
models. The prototype's `dink run` never reads R2: it reads models from a local folder. After
the prototype, R2 holds results, not videos. Workers read each video from Bunny, process
it and keep the JSON outputs and report, about 0.5 MB a video. Per-frame tracks and rendered
reel MP4s are deleted after 30 days.

## Setting up R2

Both buckets, `dinkdata` and `dinkdata-backup`, are on Robby's Cloudflare account. Each has
Standard storage, automatic location and no public access. There are three R2 account API
tokens, each with Object Read & Write.

| Token | Buckets | Where the key lives |
|---|---|---|
| `dinkdata-robby` | `dinkdata` | Robby's `.env` |
| `dinkdata-marti` | `dinkdata` | Marti's `.env` |
| `dinkdata-ci-backup` | `dinkdata`, `dinkdata-backup` | GitHub secrets `R2_BACKUP_ACCESS_KEY_ID` and `R2_BACKUP_SECRET_ACCESS_KEY` |

The account's S3 endpoint is in each `.env` and in the GitHub secret `R2_ENDPOINT`. No key can
read `dinkdata-backup` except the CI key. To restore from the backup, Robby creates a
short-lived token on that bucket in the dashboard.

To set up a Mac, install Homebrew and run the wizard from the repo root:

```bash
scripts/r2-setup.sh
```

The wizard asks first whether you are creating the buckets and keys. Robby answers yes once. It
then walks him through the dashboard, writes his key to `.env` and sets the three GitHub
secrets. It never saves Marti's key. Robby sends that in a password manager share or a
disappearing Signal message, never by email, Slack or GitHub. Everyone else answers no and
pastes the endpoint and key they were sent. Both runs install rclone with Homebrew, write,
read and delete a test file in `dinkdata`, and offer to upload the local `labels/` folder.

rclone has no config file here. The `r2` remote comes from six `RCLONE_CONFIG_R2_*` variables
in `.env`, so pass the file to every rclone command:

```bash
uv run --env-file .env rclone lsf r2:dinkdata
```

```bash
uv run --env-file .env rclone copy labels r2:dinkdata/labels --immutable --exclude '.*'
```

The second command uploads new studio labels. Run it after each labelling session until the
studio writes to R2 itself. `--immutable` never overwrites a file and stops if a file in R2
differs from yours.

The `Backup` workflow (`.github/workflows/backup.yml`) runs every day at 04:17 UTC and can be
started by hand from the Actions tab. It copies `labels/` and `cameras/` from `dinkdata` to
`dinkdata-backup` inside R2 with `--immutable`. It never deletes, and it fails if a file it
already backed up has changed. The repo is public, so its log shows only totals. Videos,
runs and models aren't backed up.

## Ids

- `video_id`, `camera_id` and `facility_id` are HMAC-SHA256 hashes of PickleCam's ids, keyed
  with a secret in `.env`. Nobody without the key can recompute or reverse them.
- The map back to PickleCam session ids lives only in `catalog/id_map.parquet` in R2.
- An id is a prefix (`v_`, `c_` or `f_`) and the first 16 hex characters of the HMAC. The key
  is `DINKDATA_ID_KEY` in `.env`. For a game downloaded by hand, run
  `uv run --env-file .env dink id video` and paste the session id at the hidden prompt. It
  prints only the id, and `dink catalog sync` gives the same id later (ADR 0016).

## Getting videos for the prototype

The prototype needs about 150 games, not a live feed (ADR 0018). We download them from the
PickleCam facility dashboard, which costs PickleCam about $1.50 in Bunny bandwidth.

1. Both owners pick the held-out test facilities first, at least one per camera setup, and
   write them into the catalog notes. Nobody downloads, labels or trains on those facilities
   except for test labels.
2. Robby picks the games from training facilities, spread across facilities, cameras, court
   colours and game lengths, and skips recordings under 5 minutes. He downloads each one's
   1080p MP4 from its watch page within 14 days of upload, before PickleCam deletes it. We
   asked PickleCam whether a script may download from the dashboard's links instead.
3. `dink ingest` prepares each downloaded MP4 (section "Ingesting a game" below).
4. The prepared games live in R2 and in each owner's local `data/videos/`, never in the repo.

A new recording's MP4 appears a few minutes after its original upload and HLS stream, because
Bunny encodes it last. Download a game only once its watch page plays.

### Ingesting a game

Install ffmpeg once with `brew install ffmpeg`. If the browser named the download after its
title, rename it first, such as to `game.mp4`, because the title holds the session id. Then
run:

```bash
uv run --env-file .env dink ingest game.mp4 --split train
```

Ingest asks for the session id twice, then the facility as the dashboard names it and the
court number, all at a hidden prompt. It then:

- copies the video without its audio, metadata or chapters, using `-map 0:v:0 -c copy`, to
  `data/videos/<video_id>.mp4`
- reads every frame's timestamp with ffprobe and an MD5 of every decoded picture with
  ffmpeg, and writes `videos/<video_id>.frames.parquet`. A gap of about n usual frame lengths
  marks n - 1 dropped frames, and a picture equal to the one before is a duplicate
- gives the game its `video_id`, `facility_id` and `camera_id` with the same HMAC as `dink id`.
  A camera is one court at one facility, so `camera_id` hashes `<facility>/court<N>`
- uploads the video and its frames, then adds a row to `catalog/id_map.parquet` and to
  `catalog/catalog.parquet`, with `fetched` true and `uploaded_at` and `setup` null

`--split` is needed only for the first game of a facility. Later games of that facility take
its split, and a different `--split` is an error. Ingest prints "new facility" or "known
facility", so a typo in the facility name shows up before it splits one facility in two.

Running ingest again on the same game uploads only the files missing from R2, and does nothing
once the game is complete. It prints only opaque ids and frame counts, and removes the session
id, facility and file path from any error.

## After the prototype: the read-only endpoint

Every Bunny Stream library key can also delete videos, so no Bunny key leaves PickleCam. Once
the prototype is approved, the PickleCam backend developer exposes one read-only call,
protected by a token kept in `.env` (ADR 0017), built around what PickleCam already runs.

| Call | Returns |
|---|---|
| `GET /dinkdata/recordings?since=&page=` | A paged list across facilities: `session_id`, `facility_id`, `camera_id`, `started_at`, `stopped_at`, `uploaded_at`, `expires_at`, `library_id`, `video_id` and `mp4_url`, the download link for the 1080p MP4 |

The call returns no personal data. PickleCam builds `mp4_url`, so a change to its link format
or pull zone needs no change on our side. `dink catalog sync` reads it, and `dink fetch`
downloads each new game's MP4, then the original upload, then the HLS stream, which it remuxes
with `ffmpeg -c copy`.

## PickleCam's answers

We sent the spec and four questions on 20 October 2026, and the backend developer answered the
same day.

| Question | Answer |
|---|---|
| Can you add the read-only call? | Not now. The priority is a working prototype, and automatic intake waits until after it |
| Which camera models are installed? | Hard to find out. Training on several lenses makes the models more robust, and we calibrate each camera from its own video anyway (ADR 0004) |
| Can you turn on MP4 fallback for one library? | Our report was wrong. That video's MP4 wasn't encoded yet when we checked. All six libraries have MP4 fallback on |
| Who pays our download bandwidth? | PickleCam. Even the whole library would cost about $150, so cost work waits until the prototype is good |

## What the dashboard showed

On 20 October 2026 we answered the other backend questions ourselves from the PickleCam
facility dashboard and Bunny's file headers, across six facilities. We read headers and each
MP4's index only, never a whole video.

| Question | Finding |
|---|---|
| Are original uploads kept? | At 1 of 6 libraries. The original there is about 4 times the size of the MP4 |
| Is MP4 download on, and at what resolution? | On at all 6 libraries, at 1080p only. No library has a 720p version |
| Is the title format the same everywhere? | Yes. Every title is `court<N>_<sessionId>` |
| Do dropped frames survive Bunny's encoding? | Yes. Bunny rounds each frame time to a 1/30 s grid but keeps the gaps. One MP4 had 7 double-length gaps, and one original had 7 drops in 25 minutes |
| How long do videos stay? | 14 days after upload, at every facility |
| When are the courts busiest? | From about 10 AM to 10 PM local time, most of all from 6 to 10 PM |
| What size is a game? | 0.14 to 0.43 GB for 10 to 15 minutes of 1080p MP4 |
| Which camera models are installed? | Not visible. The dashboard shows only `court1`, `court2` and so on, and the files name only the recording software |

PickleCam also has a small highlights feature. A highlight is a fixed 30-second clip that a
command at the court creates, and 3 of 250 recordings we checked had one. Nothing picks
highlights automatically, so DinkData's reels are new.

## Keys

- Each person or service has its own R2 key in `.env` or a CI secret, limited to the buckets
  it needs ("Setting up R2" above).
- After the prototype, only the fetch workflow holds the endpoint token.
- Claude Code may not read `.env`.

## Privacy rules

1. No emails, facility names, session ids or Bunny ids go into the repo, issues, PRs, logs or labels.
2. No footage or frames go into the repo. Test fixtures are synthetic.
3. No audio is stored.
4. Player photos and reels stay in `runs/` and go only to the players in that game. The rally
   labeller's reference crops, one photo per player per game, are the one exception. They stay
   next to their labels in the private `labels/` folder in R2 and its backup, and never go into
   the repo.
5. DinkData stores no contact details.
6. Agents work only from issues the two owners wrote.
7. Robby confirmed for PickleCam on 17 October 2026 that all games may be used for this project.
