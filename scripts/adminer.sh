#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-up}"
NERDCTL_BIN="${NERDCTL_BIN:-nerdctl}"
CLI=()  # populated by select_runtime as an array to support multi-word commands
ADMINER_CONTAINER="${ADMINER_CONTAINER:-pf-rates-adminer}"
ADMINER_PORT="${ADMINER_PORT:-8090}"

log() {
  printf '[adminer] %s\n' "$1"
}

runtime_available() {
  # Accepts a single binary name or a multi-word command string.
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

container_exists() {
  "${CLI[@]}" container inspect "$ADMINER_CONTAINER" >/dev/null 2>&1
}

container_is_running() {
  [[ "$("${CLI[@]}" inspect --format '{{.State.Status}}' "$ADMINER_CONTAINER" 2>/dev/null)" == "running" ]]
}

configured_port() {
  "${CLI[@]}" inspect --format '{{with index .HostConfig.PortBindings "8080/tcp"}}{{(index . 0).HostPort}}{{end}}' "$ADMINER_CONTAINER" 2>/dev/null || true
}

published_port() {
  "${CLI[@]}" port "$ADMINER_CONTAINER" 8080/tcp 2>/dev/null | awk -F: 'NR==1 {print $NF}'
}

port_is_free() {
  python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        raise SystemExit(1)
raise SystemExit(0)
PY
}

find_free_port() {
  python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
for candidate in range(port, port + 200):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", candidate))
        except OSError:
            continue
        print(candidate)
        raise SystemExit(0)

raise SystemExit(1)
PY
}

create_container() {
  local port
  port="$(find_free_port "$ADMINER_PORT")" || {
    echo "Could not find a free port for Adminer starting at $ADMINER_PORT." >&2
    exit 1
  }

  log "Creating Adminer container $ADMINER_CONTAINER on port $port"
  "${CLI[@]}" run -d \
    --name "$ADMINER_CONTAINER" \
    --restart unless-stopped \
    -p "$port:8080" \
    -e ADMINER_DEFAULT_SERVER=host.docker.internal \
    adminer >/dev/null

  printf 'http://localhost:%s\n' "$port"
}

recreate_container() {
  log "Recreating Adminer container $ADMINER_CONTAINER with a free port"
  "${CLI[@]}" rm -f "$ADMINER_CONTAINER" >/dev/null
  create_container
}

ensure_container() {
  if container_exists; then
    if container_is_running; then
      local port
      port="$(published_port)"
      if [[ -z "$port" ]]; then
        recreate_container
        return
      fi
      log "Using existing running container $ADMINER_CONTAINER"
      printf 'http://localhost:%s\n' "$port"
      return
    fi

    local port
    port="$(configured_port)"
    if [[ -n "$port" ]] && port_is_free "$port"; then
      log "Starting existing container $ADMINER_CONTAINER on port $port"
      "${CLI[@]}" start "$ADMINER_CONTAINER" >/dev/null
      printf 'http://localhost:%s\n' "$port"
      return
    fi

    recreate_container
    return
  fi

  create_container
}

stop_container() {
  if container_exists && container_is_running; then
    log "Stopping container $ADMINER_CONTAINER"
    "${CLI[@]}" stop "$ADMINER_CONTAINER" >/dev/null
  else
    log "Container $ADMINER_CONTAINER is not running"
  fi
}

select_runtime

case "$ACTION" in
  up)
    ensure_container
    ;;
  down)
    stop_container
    ;;
  *)
    echo "Usage: $0 {up|down}" >&2
    exit 1
    ;;
esac
