#!/usr/bin/env bash
# Mentor Pro scheduled replenishment wrapper (T066). Run by the user crontab line in
# deploy/mentorpro-replenish.cron. Appends one classified line per run to the log and
# exits with the real status, so cron and operators can tell outcomes apart:
#   RESULT=OK | RESULT=SKIPPED (tick ran; disabled, paused or busy)       exit 0
#   RESULT=TICK_FAILED      replenish tick exited 5 (error in generation.replenish_tick)  exit 5
#   RESULT=ERROR            replenish tick exited with any other non-zero status  exit <rc>
#   RESULT=CONTAINER_MISSING the app container does not exist or is not running  exit 20
#   RESULT=DOCKER_ERROR     docker itself failed (daemon, permissions, exec)     exit 21
#   RESULT=LOG_ERROR        the log directory cannot be created or written       exit 22
# Output is redacted (key=value secrets, bearer tokens, URL credentials) and bounded
# before it is logged. `--check` only verifies the log directory and the container.
set -u
umask 077

CONTAINER="${MENTOR_PRO_CONTAINER:-mentor-pro-app-1}"
LOG_DIR="${MENTOR_PRO_REPLENISH_LOG_DIR:-$HOME/mentor-pro-review/runs}"
LOG="$LOG_DIR/replenish-tick.log"
MAX_LINES=20

ts() { date -u +%FT%TZ; }

redact() {
  sed -E \
    -e 's#(Bearer|Token)[[:space:]]+[A-Za-z0-9._~+/=-]+#\1 [REDACTED]#Ig' \
    -e 's#([A-Za-z0-9_]*(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|KEY|AUTH)[A-Za-z0-9_]*)(["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?)[^[:space:]"'"'"',}]+#\1\3[REDACTED]#Ig' \
    -e 's#(://[^:/@[:space:]]+):[^@[:space:]]+@#\1:[REDACTED]@#g' \
    -e 's#sk-[A-Za-z0-9_-]{8,}#[REDACTED]#g'
}

if ! mkdir -p "$LOG_DIR" 2>/dev/null || ! chmod 700 "$LOG_DIR" 2>/dev/null \
   || ! touch "$LOG" 2>/dev/null || [ ! -w "$LOG" ]; then
  echo "$(ts) RESULT=LOG_ERROR rc=22 cannot create or write $LOG" >&2
  exit 22
fi
chmod 600 "$LOG" 2>/dev/null

log() { printf '%s %s\n' "$(ts)" "$*" >> "$LOG"; }

state=$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>&1)
irc=$?
if [ $irc -ne 0 ]; then
  if printf '%s' "$state" | grep -qi 'no such'; then
    log "RESULT=CONTAINER_MISSING rc=20 container=$CONTAINER"
    exit 20
  fi
  log "RESULT=DOCKER_ERROR rc=21 step=inspect docker_rc=$irc $(printf '%s' "$state" | head -1 | redact)"
  exit 21
fi
if [ "$state" != "true" ]; then
  log "RESULT=CONTAINER_MISSING rc=20 container=$CONTAINER running=$state"
  exit 20
fi

if [ "${1:-}" = "--check" ]; then
  log "RESULT=CHECK_OK rc=0 log_dir=$LOG_DIR container=$CONTAINER"
  echo "CHECK_OK $LOG"
  exit 0
fi

out=$(docker exec "$CONTAINER" python -m app.practice.replenish tick 2>&1)
rc=$?
first=$(printf '%s\n' "$out" | head -1 | redact)

case $rc in
  0)
    case "$first" in
      "TICK SKIPPED"*) log "RESULT=SKIPPED rc=0 $first" ;;
      *) log "RESULT=OK rc=0 $first" ;;
    esac
    ;;
  5)
    log "RESULT=TICK_FAILED rc=5 $first"
    printf '%s\n' "$out" | tail -n "$MAX_LINES" | redact | sed 's/^/    /' >> "$LOG"
    ;;
  125|126|127)
    # docker exec: 125 daemon/exec error, 126 not executable, 127 not found
    log "RESULT=DOCKER_ERROR rc=21 step=exec docker_rc=$rc $first"
    printf '%s\n' "$out" | tail -n "$MAX_LINES" | redact | sed 's/^/    /' >> "$LOG"
    exit 21
    ;;
  *)
    log "RESULT=ERROR rc=$rc $first"
    printf '%s\n' "$out" | tail -n "$MAX_LINES" | redact | sed 's/^/    /' >> "$LOG"
    ;;
esac
exit $rc
