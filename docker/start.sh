#!/usr/bin/env bash
# Start script for the DinkData image (docs/OPERATIONS.md, #44).
#
# On a RunPod pod it starts a stop timer, so a forgotten pod stops itself, and starts SSH when
# RunPod passes a public key. Then it runs the given command, or waits so people can SSH in.
#
#   DINK_STOP_AFTER_S  seconds before the pod stops itself. Default 14400 (4 hours). 0 turns
#                      the timer off, which needs both owners' agreement (docs/OPERATIONS.md).
#   RUNPOD_POD_ID      set by RunPod. Without it there is no pod to stop, so no timer runs.
#   PUBLIC_KEY         set by RunPod from the account's SSH keys. SSH_PUBLIC_KEY overrides it.
set -euo pipefail

stop_after="${DINK_STOP_AFTER_S:-14400}"
if [[ ! "$stop_after" =~ ^[0-9]+$ ]]; then
  echo "start.sh: DINK_STOP_AFTER_S must be whole seconds, not '$stop_after'" >&2
  exit 1
fi

if [[ -z "${RUNPOD_POD_ID:-}" ]]; then
  echo "start.sh: not on a RunPod pod, so no stop timer" >&2
elif [[ "$stop_after" == 0 ]]; then
  echo "start.sh: DINK_STOP_AFTER_S is 0, so no stop timer" >&2
else
  echo "start.sh: this pod stops itself in ${stop_after} s" >&2
  # The timer writes to its own log, so it doesn't hold the container's output open.
  (
    sleep "$stop_after"
    runpodctl pod stop "$RUNPOD_POD_ID" || echo "start.sh: the stop timer failed to stop the pod" >&2
  ) >>"${DINK_TIMER_LOG:-/tmp/dink-stop-timer.log}" 2>&1 &
fi

key="${SSH_PUBLIC_KEY:-${PUBLIC_KEY:-}}"
if [[ -n "$key" ]] && command -v sshd >/dev/null; then
  mkdir -p ~/.ssh /run/sshd
  chmod 700 ~/.ssh
  echo "$key" >>~/.ssh/authorized_keys
  chmod 600 ~/.ssh/authorized_keys
  # Host keys are made per pod, never baked into the public image.
  ssh-keygen -A >/dev/null
  # SSH sessions don't inherit the container's environment, so login shells read it from here.
  # It holds the pod's secrets, and lives only on the pod's scratch disk.
  export -p | grep -v -E '^declare -x (HOME|HOSTNAME|OLDPWD|PWD|SHLVL|_)=' \
    >/etc/profile.d/10-pod-env.sh
  chmod 600 /etc/profile.d/10-pod-env.sh
  /usr/sbin/sshd
  echo "start.sh: SSH is up" >&2
fi

if [[ $# -eq 0 ]]; then
  exec sleep infinity
fi
exec "$@"
