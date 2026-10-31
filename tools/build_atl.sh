#!/usr/bin/env bash
# Builds ATL from the source in ./atl (plus its dependencies) for arm64 / Ubuntu 24.04 and puts the
# result in ./usr, where the store (and clickable) pick it up.  Replaces tools/fetch_sdk.sh.
#
# Needs Docker. On an x86 PC the arm64 container runs through qemu (slow, the first build can take an hour):
#     sudo apt install docker.io qemu-user-static binfmt-support
# Usage:  ./tools/build_atl.sh          (PLATFORM=linux/amd64 for a build that can only be tested on the PC)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PLATFORM="${PLATFORM:-linux/arm64}"
IMAGE="droidstore-atl-builder"

# dependency versions (tools/versions.env); exported so that docker run -e passes them on
set -a
# shellcheck disable=SC1091
. "$HERE/tools/versions.env"
set +a

docker build --platform "$PLATFORM" -t "$IMAGE" -f "$HERE/tools/Dockerfile.atl" "$HERE/tools"
docker run --rm --platform "$PLATFORM" -v "$HERE":/src -w /src \
    -e WOLFSSL_REF -e BIONIC_REF -e ART_REF -e OPENSLES_REF -e JOBS \
    "$IMAGE" bash /src/tools/build_atl_inner.sh
