#!/usr/bin/env bash
# Shared container-runtime helpers sourced by db.sh and adminer.sh.
# Requires: NERDCTL_BIN and CLI to be declared in the calling script.
# Requires: log() to be defined in the calling script before select_runtime is called.

runtime_available() {
  # Accepts a single binary name or a multi-word command string.
  # Uses eval so "nerdctl --address /path" is treated as one command invocation.
  eval "$* info" >/dev/null 2>&1
}

select_runtime() {
  if [[ "$NERDCTL_BIN" != "auto" ]] && runtime_available "$NERDCTL_BIN"; then
    read -ra CLI <<< "$NERDCTL_BIN"
  elif runtime_available nerdctl; then
    CLI=(nerdctl)
  elif runtime_available docker; then
    CLI=(docker)
  else
    echo "No working container CLI found. Start Rancher Desktop and ensure nerdctl or docker is available." >&2
    exit 1
  fi
  log "Using container runtime: ${CLI[*]}"
}
