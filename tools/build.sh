#!/usr/bin/env bash
# Thin wrapper so `tools/build.sh <target>` works from anywhere.
#
# It delegates to the Makefile rather than reimplementing the steps: the whole
# defect this repo was audited for (PIPE-02) is two places describing the build and
# disagreeing, so there is exactly ONE description of it, and it lives in ./Makefile.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v make >/dev/null 2>&1; then
  echo "make is not installed. The build is defined in $REPO/Makefile; run its" >&2
  echo "commands directly, e.g.: python3 tools/stages/run_stages.py && python3 build_index.py" >&2
  exit 127
fi
exec make -C "$REPO" "${@:-help}"
