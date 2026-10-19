# Operations

How we run GPU work and keep spending low. `docs/DESIGN.md` section 11 has the costs, and ADR
0010 records the decision. The M0 ticket for the Docker image and cloud accounts fills in the
exact commands.

## Where things run

| Job | Where |
|---|---|
| Coding, tests, studio, short clips without a GPU | Our MacBooks |
| Interactive GPU work and training | A RunPod pod with a community RTX 4090, or Vast.ai when cheaper |
| Batch and eval runs over many games | Modal first, using its free monthly credit, or RunPod serverless |
| Daily fetch and nightly label backup | Scheduled GitHub Actions workflows |
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

Robby's accounts and card pay for RunPod, Vast.ai, Modal and Cloudflare R2 for now, and Marti
pays Robby back for his share. Spending alerts go to Robby's email, and both owners look at the
month's spend together at the start of each month.

## Guardrails

- RunPod and Vast.ai use prepaid credit, topped up $25 at a time, so spending can't pass the
  balance.
- Modal has a workspace spending limit set to the monthly cap.
- Pods shut down after 30 minutes idle and have a maximum run time.
- The development budget is $50 a month, with an alert at $30. The owners agree any month
  that needs more first, such as a long training run.

## Secrets

- Each person keeps their own keys in `.env`, which is never committed and which Claude Code
  may not read.
- CI and scheduled workflows read keys from GitHub Actions secrets.
- Pods and serverless jobs get keys from the provider's secret store, never baked into the
  Docker image.

## Before a GPU session

1. Check the balance and this month's spend.
2. Start the pod or job from the Docker image.
3. Stop the pod when done, even if idle shutdown would catch it.
