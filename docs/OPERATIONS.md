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

## Starting a pod

Install the CLI once with `brew install runpod/runpodctl/runpodctl`, then run
`runpodctl doctor` and paste your own API key when it asks. The key stays in `~/.runpod/`.

```bash
runpodctl pod create --name dinkdata-<handle> --cloud-type COMMUNITY \
  --gpu-id "NVIDIA GeForce RTX 4090" \
  --image runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404 --container-disk-in-gb 20 \
  --docker-args 'bash -c "sleep 14400; runpodctl stop pod \$RUNPOD_POD_ID"'
```

- `--cloud-type COMMUNITY` matters, because `runpodctl` picks Secure Cloud by default. Use
  `SECURE` when no community GPU is free.
- The start command stops the pod after 4 hours. Every pod has `RUNPOD_POD_ID` and a
  `runpodctl` that can only control that pod.
- A start command replaces the image's default one. Add your own commands before `sleep`, or
  put the timer in the background with `&`.
- Stop and remove a pod with `runpodctl pod stop <id>` and `runpodctl pod delete <id>`.
- The Docker image from #44 replaces the standard image, through a saved template.
