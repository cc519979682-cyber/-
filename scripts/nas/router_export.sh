#!/bin/sh
# Runs ON THE ROUTER (ImmortalWrt + OpenBox), fed via: ssh root@router 'sh -s -- CONFIG SINGBOX' < router_export.sh
# Writes a tar stream to stdout containing ONLY:
#   route.json         {"route": ...} extracted with jq (no outbounds / inbounds / dns / secrets)
#   drop_hashes.txt    sha256 of each outbound/endpoint server address (addresses themselves never leave)
#   rulesets/<name>.json  local rule-sets referenced by route.rule_set, decompiled to sing-box source JSON
# It reads config.json read-only and deletes its temp dir on exit.
set -eu

CFG="${1:-/opt/open-box/etc/config.json}"
SB="${2:-}"

if ! command -v jq >/dev/null 2>&1; then
  echo "router-export: jq not found on router. Install it once with: opkg update && opkg install jq" >&2
  exit 3
fi
if [ -z "$SB" ]; then
  SB=$(command -v sing-box 2>/dev/null || true)
  [ -n "$SB" ] || for c in /usr/bin/sing-box /opt/open-box/bin/sing-box /opt/open-box/sing-box; do
    [ -x "$c" ] && { SB="$c"; break; }
  done
fi
[ -r "$CFG" ] || { echo "router-export: cannot read $CFG" >&2; exit 4; }

T=$(mktemp -d /tmp/router-sync.XXXXXX)
trap 'rm -rf "$T"' EXIT INT TERM
umask 077
mkdir "$T/rulesets"

jq -c '{route: .route}' "$CFG" > "$T/route.json"

jq -r '[(.outbounds // [])[], (.endpoints // [])[] | (.server?, ((.peers // [])[] | .address?)) | strings] | unique | .[]' "$CFG" |
while IFS= read -r addr; do
  printf '%s' "$addr" | tr 'A-Z' 'a-z' | sha256sum | cut -d' ' -f1
done > "$T/drop_hashes.txt"

TAB=$(printf '\t')
jq -r '(.route.rule_set // [])[] | select((.type // "local") == "local") | [(.format // ""), (.path // "")] | @tsv' "$CFG" |
while IFS="$TAB" read -r fmt path; do
  case "$path" in
    /*) ;;
    *) echo "router-export: skipping rule_set with non-absolute path" >&2; continue ;;
  esac
  name=$(basename "$path")
  stem=${name%.*}
  if [ -z "$fmt" ]; then
    case "$name" in *.srs) fmt=binary ;; *) fmt=source ;; esac
  fi
  if [ "$fmt" = "binary" ]; then
    [ -n "$SB" ] || { echo "router-export: sing-box binary not found (pass it as 2nd arg)" >&2; exit 5; }
    "$SB" rule-set decompile --output "$T/rulesets/$stem.json" "$path" >/dev/null
  else
    cp "$path" "$T/rulesets/$stem.json"
  fi
done

tar -C "$T" -cf - route.json drop_hashes.txt rulesets
