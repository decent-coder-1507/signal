#!/bin/sh
# SIGNAL autostart for the Windows logon task (ADR-028). Runs as root inside the Alpine WSL distro:
# starts dockerd if it isn't answering, brings the SIGNAL stack up (no rebuild), then holds the WSL VM open
# with `sleep` so Windows doesn't idle it away. Signing out of Windows ends this process and lets WSL stop.
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG=/var/log/signal-autostart.log
exec >>"$LOG" 2>&1
echo "$(date -Iseconds) autostart: begin ($REPO)"

if ! docker info >/dev/null 2>&1; then
  rm -f /var/run/docker.pid
  setsid nohup dockerd >/var/log/dockerd-manual.log 2>&1 </dev/null &
  i=0
  until docker info >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -ge 60 ] && { echo "dockerd did not start"; exit 1; }
    sleep 2
  done
fi

cd "$REPO" && docker compose --profile full up -d && echo "$(date -Iseconds) autostart: stack up"

# Keep the VM alive for as long as this logon session lasts.
exec sleep infinity
