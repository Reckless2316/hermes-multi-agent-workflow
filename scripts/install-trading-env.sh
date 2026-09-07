#!/usr/bin/env bash
# Idempotent install for a workspace that checks out this repo and (optionally)
# the sibling model-trader repo. Safe to re-run.
set -euo pipefail

python3 -m pip install --upgrade pip

find_repo() {
  local name="$1"
  local candidates=(
    "$PWD/$name"
    "$PWD/repos/$name"
    "$(dirname "$PWD")/$name"
    "/workspace/$name"
    "/agent/repos/$name"
  )
  local p
  for p in "${candidates[@]}"; do
    if [[ -d "$p" ]]; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}

HERMES_ROOT="$(find_repo hermes-multi-agent-workflow || true)"
if [[ -z "${HERMES_ROOT}" && -f "$PWD/triage.yaml" && -d "$PWD/engine" ]]; then
  HERMES_ROOT="$PWD"
fi
TRADER_ROOT="$(find_repo model-trader || true)"

if [[ -n "${HERMES_ROOT}" && -f "${HERMES_ROOT}/requirements.txt" ]]; then
  python3 -m pip install -r "${HERMES_ROOT}/requirements.txt"
fi

if [[ -n "${TRADER_ROOT}" && -f "${TRADER_ROOT}/pyproject.toml" ]]; then
  python3 -m pip install -e "${TRADER_ROOT}"
fi

if [[ -n "${HERMES_ROOT}" ]]; then
  ( cd "${HERMES_ROOT}" && python3 -m cli.triage validate )
fi
