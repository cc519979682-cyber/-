#!/bin/sh
# Hourly NAS job: read router route rules (read-only, over SSH), convert them into
# public-safe rules and update personal/rules.conf on GitHub only when it changed.
# No git needed on the NAS. See scripts/nas/README.md.
set -eu

BASE_DIR="${ROUTER_SYNC_HOME:-$HOME/router-sync}"
ENV_FILE="${SYNC_ENV:-$BASE_DIR/sync.env}"
LOG_DIR="$BASE_DIR/logs"
LOG_FILE="$LOG_DIR/sync.log"
LOCK_DIR="$BASE_DIR/run.lock"
PAUSE_FILE="$BASE_DIR/PAUSE"

mkdir -p "$LOG_DIR"
umask 077
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt 1048576 ]; then
  mv -f "$LOG_FILE" "$LOG_FILE.1"
fi
if [ "${SYNC_LOG_STDOUT:-0}" != "1" ]; then
  exec >>"$LOG_FILE" 2>&1
fi

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { log "FAILED: $*"; exit 1; }

if [ -e "$PAUSE_FILE" ]; then
  log "paused ($PAUSE_FILE exists), skipping"
  exit 0
fi

# ---- lock (mkdir is atomic); clear a stale lock left by a dead process
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  old_pid=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    log "another run (pid $old_pid) is still active, skipping"
    exit 0
  fi
  log "removing stale lock"
  rm -rf "$LOCK_DIR"
  mkdir "$LOCK_DIR" || fail "cannot take lock $LOCK_DIR"
fi
echo $$ > "$LOCK_DIR/pid"
WORK=$(mktemp -d "$BASE_DIR/work.XXXXXX")
cleanup() { rm -rf "$WORK" "$LOCK_DIR"; }
trap cleanup EXIT
trap 'exit 1' INT TERM HUP

# ---- config
[ -r "$ENV_FILE" ] || fail "missing $ENV_FILE (copy sync.env.example)"
# shellcheck disable=SC1090
. "$ENV_FILE"
# ROUTER_HOST may be an ssh alias from ~/.ssh/config (e.g. openbox-router); then leave
# ROUTER_USER / ROUTER_PORT / ROUTER_SSH_KEY empty and ssh uses the alias settings.
: "${ROUTER_HOST:?set ROUTER_HOST in sync.env}"
ROUTER_PORT="${ROUTER_PORT:-}"
ROUTER_USER="${ROUTER_USER:-}"
ROUTER_SSH_KEY="${ROUTER_SSH_KEY:-}"
ROUTER_CONFIG="${ROUTER_CONFIG:-/opt/open-box/etc/config.json}"
ROUTER_SINGBOX="${ROUTER_SINGBOX:-}"
GITHUB_REPO="${GITHUB_REPO:-cc519979682-cyber/-}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
GITHUB_TOKEN_FILE="${GITHUB_TOKEN_FILE:-$HOME/.config/router-sync/github_pat}"
# Code is fetched through api.github.com (raw.githubusercontent.com resets connections from the NAS).
CODE_URL="${CODE_URL:-https://api.github.com/repos/$GITHUB_REPO/tarball/$GITHUB_BRANCH}"
GITHUB_RETRY_DELAY="${GITHUB_RETRY_DELAY:-30}"
export GITHUB_RETRY_DELAY

case "$ROUTER_CONFIG$ROUTER_SINGBOX" in
  *[!A-Za-z0-9._/-]*) fail "ROUTER_CONFIG / ROUTER_SINGBOX may only contain A-Z a-z 0-9 . _ / -" ;;
esac
case "$ROUTER_HOST$ROUTER_USER$ROUTER_PORT" in
  *[!A-Za-z0-9._:@-]*) fail "ROUTER_HOST / ROUTER_USER / ROUTER_PORT contain unexpected characters" ;;
esac
if [ -n "$ROUTER_SSH_KEY" ] && [ ! -r "$ROUTER_SSH_KEY" ]; then
  fail "SSH key $ROUTER_SSH_KEY not found"
fi
USE_TOKEN=1
if [ ! -r "$GITHUB_TOKEN_FILE" ]; then
  if [ "${DRY_RUN:-0}" = "1" ]; then
    USE_TOKEN=0   # dry run reads the public repo anonymously; nothing is pushed
  else
    fail "token file $GITHUB_TOKEN_FILE not found"
  fi
fi

log "start"

# download URL to FILE: 3 attempts, $GITHUB_RETRY_DELAY seconds apart, each retry logged.
# The token (if present) goes into a 600 header file in $WORK, never onto the command line.
fetch_with_retry() {
  _url="$1"; _out="$2"; _n=1
  set -- -fsSL --connect-timeout 20 --max-time 180 -H "Accept: application/vnd.github+json" -H "User-Agent: router-rule-sync"
  if [ "$USE_TOKEN" = "1" ]; then
    printf 'Authorization: Bearer %s\n' "$(cat "$GITHUB_TOKEN_FILE")" > "$WORK/auth.hdr"
    set -- "$@" -H "@$WORK/auth.hdr"
  fi
  while :; do
    if curl "$@" "$_url" -o "$_out"; then
      rm -f "$WORK/auth.hdr"
      return 0
    fi
    if [ "$_n" -ge 3 ]; then
      rm -f "$WORK/auth.hdr"
      return 1
    fi
    log "WARNING download failed (attempt $_n/3), retrying in ${GITHUB_RETRY_DELAY}s: ${_url%%\?*}"
    sleep "$GITHUB_RETRY_DELAY"
    _n=$((_n + 1))
  done
}

# ---- converter code: fresh copy of main each run (or a fixed local copy)
if [ -n "${CODE_DIR:-}" ]; then
  SRC="$CODE_DIR"
else
  SRC="$WORK/src"
  mkdir -p "$SRC"
  fetch_with_retry "$CODE_URL" "$WORK/src.tgz" || fail "download of converter code failed (3 attempts)"
  tar -xzf "$WORK/src.tgz" -C "$SRC" --strip-components=1 || fail "cannot unpack converter code"
fi
[ -f "$SRC/scripts/sync_router_rules.py" ] || fail "converter missing in $SRC"

# ---- router export (read-only; only route + decompiled rule-sets + address hashes leave the router)
mkdir -p "$WORK/bundle"
set -- -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes
[ -n "$ROUTER_SSH_KEY" ] && set -- "$@" -i "$ROUTER_SSH_KEY"
[ -n "$ROUTER_PORT" ] && set -- "$@" -p "$ROUTER_PORT"
[ -n "$ROUTER_USER" ] && set -- "$@" -l "$ROUTER_USER"
if ! ssh "$@" "$ROUTER_HOST" "sh -s -- '$ROUTER_CONFIG' '$ROUTER_SINGBOX'" \
    < "$SRC/scripts/nas/router_export.sh" > "$WORK/bundle.tar"; then
  fail "router export over SSH failed"
fi
tar -xf "$WORK/bundle.tar" -C "$WORK/bundle" || fail "bad bundle from router"
[ -s "$WORK/bundle/route.json" ] || fail "router returned no route.json"
# Canonical compact JSON, so the jq and ucode export paths give byte-identical bundles.
python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p,encoding="utf-8")); open(p,"w",encoding="utf-8").write(json.dumps(d,ensure_ascii=False,separators=(",",":"))+"\n")' \
  "$WORK/bundle/route.json" || fail "router returned invalid route.json"
log "bundle: $(ls "$WORK/bundle/rulesets" | wc -l) rule-set files"

# ---- self-test of the downloaded code
python3 -m unittest discover -s "$SRC/scripts" -p 'test_*.py' > "$WORK/unittest.log" 2>&1 || {
  cat "$WORK/unittest.log"; fail "unit tests failed"; }

# ---- convert + push via GitHub API (only when personal/rules.conf changes)
set -- --bundle "$WORK/bundle" --repo "$GITHUB_REPO" --branch "$GITHUB_BRANCH"
[ "$USE_TOKEN" = "1" ] && set -- "$@" --token-file "$GITHUB_TOKEN_FILE"
[ -n "${GITHUB_API:-}" ] && set -- "$@" --api "$GITHUB_API"
[ -n "${OUTBOUND_MAP_OVERRIDE:-}" ] && set -- "$@" --outbound-map-override "$OUTBOUND_MAP_OVERRIDE"
[ "${STRICT:-0}" = "1" ] && set -- "$@" --strict
[ "${DRY_RUN:-0}" = "1" ] && set -- "$@" --dry-run
[ "${ALLOW_LARGE_DELETION:-0}" = "1" ] && set -- "$@" --allow-large-deletion
[ "${INCLUDE_RULE_SETS:-0}" = "1" ] && set -- "$@" --include-rule-sets
[ "${HAND_RULES_WIN:-0}" = "1" ] && set -- "$@" --hand-rules-win
[ "${INCLUDE_RULESET_IP_DIRECT:-0}" = "1" ] && set -- "$@" --include-ruleset-ip-direct
if python3 "$SRC/scripts/nas/github_sync.py" "$@"; then
  log "done"
else
  rc=$?
  [ "$rc" = "2" ] && fail "safety guard tripped (router returned no/too few rules, or >10% of the block would be deleted); nothing pushed, see above"
  fail "converter/push exited with $rc"
fi
