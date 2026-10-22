# Operations

How we run GPU work and keep spending low. `docs/DESIGN.md` section 11 has the costs, and ADR
0010 records the decision. The M0 ticket for the Docker image and cloud accounts fills in the
exact commands.

## Where things run

| Job | Where |
|---|---|
| Coding, tests, studio, short clips without a GPU | Our MacBooks |
| Interactive GPU work and training | A RunPod pod with a community RTX 4090, or Secure Cloud when community GPUs are unavailable or keep getting interrupted |
| Batch and eval runs over many games | RunPod pods for now. The first ticket that runs batch eval decides whether to add Modal |
| Nightly label backup, and the daily fetch after the prototype | Scheduled GitHub Actions workflows |
| Production | The provider the M4 benchmark picks |

All GPU work uses one Linux Docker image, the same in development and production. The Windows
PCs aren't part of the plan.

## Spending rules

- Choose the cheapest GPU that gives the same result, and accept slower training.
- Never save money on input resolution, model size, labelled data or the accuracy gates.
- Training saves a checkpoint at least every 30 minutes and resumes after an interruption, so
  cheap interruptible GPUs are fine.
- Every eval run records its GPU cost, and accuracy PRs show it.

## Who pays

Robby's accounts and card pay for RunPod and Cloudflare R2 for now. Marti is a member of
Robby's RunPod team, so he can start and stop pods but can't change billing. Marti pays Robby
back half of each month's RunPod spend. Spending alerts go to Robby's email, and both owners look at the
month's spend together at the start of each month.

## Guardrails

- The prepaid balance is the cap. Auto-pay stays off, so spending can't pass the balance. When
  the balance reaches $0, RunPod stops every pod.
- Top-ups are $25 at a time, at most $50 a month. A second top-up in one month means both
  owners check the spend together.
- RunPod emails Robby when the balance drops below $5.
- RunPod can't stop a pod when it goes idle, so every pod starts with a 4-hour timer (below).
- No network volume in M0. Pod disks are scratch space and R2 is the lasting store, so a pod
  that stops at $0 loses nothing we need.
- The development budget is $50 a month. A training run that measurably
  improves accuracy can go over it if both owners agree first.

## Secrets

- Each person keeps their own keys in `.env`, which is never committed and which Claude Code
  may not read.
- CI and scheduled workflows read keys from GitHub Actions secrets.
- Pods and serverless jobs get keys from the provider's secret store, never baked into the
  Docker image.

## Before a GPU session

1. Check the balance and this month's spend.
2. Start the pod or job from the Docker image.
3. Terminate the pod when done. The timer is a safety net, and a stopped pod still bills for
   its disk.

## The Docker image

Every pod runs `ghcr.io/roberto-cantero/dink-data`. The `Image` workflow
(`.github/workflows/image.yml`) builds it on GitHub whenever a push to `main` changes the
`Dockerfile`, the code or the lockfile, and tags it `main` and `sha-<commit>`. A pull request that
changes the image gets the tag `pr-<number>`, so it can be tried on a pod before it merges.

The image holds the NVIDIA CUDA 12.6 base, Python 3.12, every library from `uv.lock` with the
`cv`, `cu126` and `studio` extras and the dev tools, the repo with its git history in
`/opt/dinkdata`, ffmpeg, rclone, runpodctl and an SSH server. It holds no keys.

Its start script, `docker/start.sh`, runs first on every pod:

- It stops the pod after `DINK_STOP_AFTER_S` seconds, 14400 (4 hours) by default. A pod's start
  command can't skip the timer, because the script is the image's entrypoint. Setting
  `DINK_STOP_AFTER_S=0` turns it off, and needs both owners' agreement first.
- It starts SSH with the public keys in your RunPod account settings.
- It then runs the pod's start command, or waits so you can SSH in.

## Keys on a pod

Pods read keys from RunPod secrets, never from the image. The template maps the secrets
`r2_endpoint`, `r2_access_key_id` and `r2_secret_access_key` to the six `RCLONE_CONFIG_R2_*`
variables, so `rclone` and `dink ingest` reach R2 the same way as on a Mac. SSH sessions see
those variables too.

## Starting a pod

Install the CLI once with `brew install runpod/runpodctl/runpodctl`, then run
`runpodctl doctor` and paste your own API key when it asks. The key stays in `~/.runpod/`.
Add your SSH public key in the RunPod console under Settings, SSH Public Keys.

Start a pod from the saved `dinkdata` template, id `w9rs32bv7m`:

```bash
runpodctl pod create --name dinkdata-<handle> --template-id w9rs32bv7m \
  --cloud-type COMMUNITY --gpu-id "NVIDIA GeForce RTX 4090"
```

- `--cloud-type COMMUNITY` matters, because `runpodctl` picks Secure Cloud by default. Use
  `SECURE` when no community GPU is free.
- `runpodctl ssh info <pod-id>` prints the SSH command once the pod is running.
- Check a new image on a pod with these commands. The first runs everything CI runs, and the
  second runs the GPU smoke test.

```bash
cd /opt/dinkdata && SKIP=no-commit-to-branch make check
```

```bash
cd /opt/dinkdata && uv run pytest -m gpu -v
```

- Terminate the pod when you're done with `runpodctl pod delete <pod-id>`. A stopped pod still
  bills for its disk.
- For a different timer on one pod, pass `--env` with `DINK_STOP_AFTER_S` and every variable
  from the template below, because a pod's `--env` may replace the template's.

The template was made once with this command. Change it with
`runpodctl template update w9rs32bv7m`, which takes the same flags.

```bash
runpodctl template create --name dinkdata --image ghcr.io/roberto-cantero/dink-data:main \
  --container-disk-in-gb 30 --ports "22/tcp" --port-labels "22=ssh" \
  --env '{"RCLONE_CONFIG_R2_TYPE":"s3","RCLONE_CONFIG_R2_PROVIDER":"Cloudflare","RCLONE_CONFIG_R2_NO_CHECK_BUCKET":"true","RCLONE_CONFIG_R2_ENDPOINT":"{{ RUNPOD_SECRET_r2_endpoint }}","RCLONE_CONFIG_R2_ACCESS_KEY_ID":"{{ RUNPOD_SECRET_r2_access_key_id }}","RCLONE_CONFIG_R2_SECRET_ACCESS_KEY":"{{ RUNPOD_SECRET_r2_secret_access_key }}"}'
```
