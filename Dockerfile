# syntax=docker/dockerfile:1
# The Linux image for all GPU work, in development and production (docs/OPERATIONS.md, #44).
# GitHub Actions builds it and pushes it to ghcr.io/roberto-cantero/dink-data
# (.github/workflows/image.yml). Keys never go in the image: pods get them from RunPod secrets.

# The base only sets up the NVIDIA runtime. PyTorch's cu126 wheels bring their own CUDA libraries.
FROM nvidia/cuda:12.6.3-base-ubuntu24.04@sha256:c87e78933f4c16e3272123bf2f75537306596d0fbaa395a29696a22786e5ee0e

ARG RUNPODCTL_VERSION=v3.0.1
ARG RUNPODCTL_SHA256=b66d11eca8cacbf18a2de6943c6e18a79ffbdc8a3c30aa13a49dc6cfc15d4239
# The same rclone as the backup workflow, for R2 (docs/DATA.md).
ARG RCLONE_VERSION=v1.75.2
ARG RCLONE_SHA256=349ac8fba6ff65d6247043f1750cdcb518ec5d500ef91463a10d37c0ccdf3702

ENV DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    PATH=/opt/dinkdata/.venv/bin:$PATH

# git and make run `make check`, and pyright's Node needs libatomic1. tzdata lets pyarrow read
# UTC timestamps. ffmpeg runs `dink ingest` and its tests. openssh-server lets people SSH in.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl ffmpeg git libatomic1 make openssh-server tzdata unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/

# The start script's stop timer calls runpodctl with the pod's own key, which RunPod provides.
RUN curl -fsSL -o /usr/local/bin/runpodctl \
      "https://github.com/runpod/runpodctl/releases/download/${RUNPODCTL_VERSION}/runpodctl-linux-amd64" \
    && echo "${RUNPODCTL_SHA256}  /usr/local/bin/runpodctl" | sha256sum --check --strict \
    && chmod 755 /usr/local/bin/runpodctl

# Pods reach R2 with rclone. Its `r2` remote comes from RCLONE_CONFIG_R2_* variables, which a
# pod gets from RunPod secrets (docs/OPERATIONS.md).
RUN curl -fsSL -o /tmp/rclone.zip \
      "https://downloads.rclone.org/${RCLONE_VERSION}/rclone-${RCLONE_VERSION}-linux-amd64.zip" \
    && echo "${RCLONE_SHA256}  /tmp/rclone.zip" | sha256sum --check --strict \
    && unzip -q -j /tmp/rclone.zip "*/rclone" -d /usr/local/bin \
    && rm /tmp/rclone.zip

WORKDIR /opt/dinkdata

# Libraries first, from the lockfile, so a code change doesn't reinstall PyTorch.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --extra cv --extra cu126 --extra studio

# The repo, with its git history, so `make check` can run the pre-commit hooks.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --extra cv --extra cu126 --extra studio \
    && git config --global --add safe.directory /opt/dinkdata \
    && uv run pre-commit install-hooks \
    && uv run pyright --version

COPY docker/start.sh /usr/local/bin/dink-start

LABEL org.opencontainers.image.source="https://github.com/roberto-cantero/dink-data" \
      org.opencontainers.image.description="DinkData GPU image" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

EXPOSE 22
# An entrypoint, so a pod's start command becomes arguments and can't skip the stop timer.
ENTRYPOINT ["/usr/local/bin/dink-start"]
