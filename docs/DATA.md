# Data, storage and privacy

Where data lives, how we get it, and the rules that keep personal data out. `docs/DESIGN.md`
sections 8 and 11 have the reasoning, and ADRs 0006 and 0007 record the decisions.

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

In production, R2 holds results, not videos. Workers read each video from Bunny, process it and
keep the JSON outputs and report, about 0.5 MB a video. Per-frame tracks and rendered reel MP4s
are deleted after 30 days.

## Ids

- `video_id`, `camera_id` and `facility_id` are HMAC-SHA256 hashes of PickleCam's ids, keyed
  with a secret in `.env`. Nobody without the key can recompute or reverse them.
- The map back to PickleCam session ids lives only in `catalog/id_map.parquet` in R2.
- An id is a prefix (`v_`, `c_` or `f_`) and the first 16 hex characters of the HMAC. The key
  is `DINKDATA_ID_KEY` in `.env`. For a game downloaded by hand, run
  `uv run --env-file .env dink id video` and paste the session id at the hidden prompt. It
  prints only the id, and `dink catalog sync` gives the same id later (ADR 0016).

## Getting videos: the read-only endpoint

Every Bunny Stream library key can also delete videos, so no Bunny key leaves PickleCam. The
PickleCam backend developer exposes two read-only calls, protected by a token kept in `.env`.

| Call | Returns |
|---|---|
| `GET /dinkdata/videos?since=&page=` | A paged list across libraries: `session_id`, `facility_id`, `camera`, `uploaded_at`, `length_s`, `framerate`, `width`, `height`, `size_bytes`, `expires_at` |
| `GET /dinkdata/videos/{session_id}/links` | Short-lived `original_url`, `mp4_url` and `hls_url` |

The calls return no personal data. Until they exist, we develop against a recorded sample
response.

## Before the endpoint and R2 exist

1. Both owners pick the held-out test facilities first, at least one per camera setup, and
   write them into the catalog notes. Nobody downloads, labels or trains on those facilities
   except for test labels.
2. Robby downloads the first games by hand from the PickleCam dashboard, only from training
   facilities, and strips the audio with `ffmpeg -i in.mp4 -map 0:v -c copy out.mp4`.
3. Until the R2 bucket exists, these games live on the owners' machines and on the cloud GPU
   pod's disk, never in the repo. They move to R2 as soon as it exists.

Fetch prefers the original upload, then the MP4, then remuxes the HLS stream with
`ffmpeg -c copy`. It drops the audio track with `-map 0:v`, saves every frame's timestamp with
ffprobe, flags dropped and duplicated frames, and uploads to R2. PickleCam deletes videos 14
days after upload, so a scheduled workflow fetches selected games daily.

## Keys

- Each machine or service has its own R2 key in `.env` or a CI secret, limited to the bucket.
- Only the fetch workflow holds the endpoint token.
- Claude Code may not read `.env`.

## Privacy rules

1. No emails, facility names, session ids or Bunny ids go into the repo, issues, PRs, logs or labels.
2. No footage or frames go into the repo. Test fixtures are synthetic.
3. No audio is stored.
4. Player photos and reels stay in `runs/` and go only to the players in that game.
5. DinkData stores no contact details.
6. Agents work only from issues the two owners wrote.
7. Robby confirmed for PickleCam on 17 October 2026 that all games may be used for this project.
