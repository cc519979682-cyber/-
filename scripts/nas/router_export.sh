#!/bin/sh
# Runs ON THE ROUTER (ImmortalWrt + OpenBox), fed via: ssh <router> 'sh -s -- CONFIG SINGBOX' < router_export.sh
# Writes a tar stream to stdout containing ONLY:
#   route.json            {"route": ...} (no outbounds / inbounds / dns / secrets)
#   drop_hashes.txt       sha256 of each outbound server / endpoint peer address (addresses never leave)
#   rulesets/<name>.json  local rule-sets referenced by route.rule_set, as sing-box source JSON
# JSON is read with jq when installed, otherwise with ucode (built into OpenWrt/ImmortalWrt).
# Nothing is installed on the router and config.json is only ever read, never copied off it.
set -eu

CFG="${1:-/opt/open-box/etc/config.json}"
SB="${2:-}"
JSON_TOOL="${ROUTER_EXPORT_JSON_TOOL:-}"   # optional override for tests: jq | ucode

# ucode program: same three outputs as the jq filters below (see extract()).
#   route    -> {"route": <route or null>}
#   servers  -> unique, sorted string .server of outbounds/endpoints and .address of their peers, one per line
#   rulesets -> "<format>\t<path>" for every route.rule_set entry whose type is "local" (or missing);
#               a missing value is printed as "-" (tab is IFS whitespace, so empty fields would collapse)
UC_PROG='
import { readfile } from "fs";
let cfg = json(readfile(ARGV[0]));
let mode = ARGV[1];
function arr(v) { return type(v) == "array" ? v : []; }
function obj(v) { return type(v) == "object" ? v : {}; }
function str(v) { return (v == null || v === false || v === "") ? "-" : "" + v; }
if (mode == "route") {
	printf("%J\n", { route: obj(cfg).route });
}
else if (mode == "servers") {
	let seen = {}, out = [];
	for (let o in [ ...arr(obj(cfg).outbounds), ...arr(obj(cfg).endpoints) ]) {
		if (type(o) != "object")
			continue;
		let cands = [ o.server ];
		for (let p in arr(o.peers))
			if (type(p) == "object")
				push(cands, p.address);
		for (let s in cands)
			if (type(s) == "string" && !exists(seen, s)) {
				seen[s] = true;
				push(out, s);
			}
	}
	for (let s in sort(out))
		print(s, "\n");
}
else if (mode == "rulesets") {
	for (let r in arr(obj(obj(cfg).route).rule_set)) {
		if (type(r) != "object")
			continue;
		let t = (r.type == null || r.type === false) ? "local" : r.type;
		if (t != "local")
			continue;
		print(str(r.format), "\t", str(r.path), "\n");
	}
}
else {
	die("unknown mode");
}
'

if [ -z "$JSON_TOOL" ]; then
  if command -v jq >/dev/null 2>&1; then
    JSON_TOOL=jq
  elif command -v ucode >/dev/null 2>&1; then
    JSON_TOOL=ucode
  else
    echo "router-export: neither jq nor ucode found on the router; cannot read $CFG safely (the full config is never copied off the router)" >&2
    exit 3
  fi
fi

extract() {
  case "$JSON_TOOL" in
    jq)
      case "$1" in
        route) jq -c '{route: .route}' "$CFG" ;;
        servers) jq -r '[(.outbounds // [])[], (.endpoints // [])[] | objects | (.server?, ((.peers // [])[] | objects | .address?)) | strings] | unique | .[]' "$CFG" ;;
        rulesets) jq -r '(.route.rule_set // [])[] | objects | select((.type // "local") == "local") | [(.format // "-" | tostring | if . == "" then "-" else . end), (.path // "-" | tostring | if . == "" then "-" else . end)] | join("\t")' "$CFG" ;;
      esac ;;
    ucode) ucode -S -e "$UC_PROG" "$CFG" "$1" ;;
    *) echo "router-export: unsupported JSON tool $JSON_TOOL" >&2; return 3 ;;
  esac
}

if command -v sha256sum >/dev/null 2>&1; then
  hash_line() { printf '%s' "$1" | tr 'A-Z' 'a-z' | sha256sum | cut -d' ' -f1; }
elif command -v openssl >/dev/null 2>&1; then
  hash_line() { printf '%s' "$1" | tr 'A-Z' 'a-z' | openssl dgst -sha256 -r | cut -d' ' -f1; }
else
  echo "router-export: need sha256sum (busybox) or openssl to fingerprint node addresses" >&2
  exit 6
fi

if [ -z "$SB" ]; then
  for c in /opt/open-box/bin/sing-box /usr/bin/sing-box /opt/open-box/sing-box; do
    if [ -x "$c" ]; then SB="$c"; break; fi
  done
  [ -n "$SB" ] || SB=$(command -v sing-box 2>/dev/null || true)
fi
[ -r "$CFG" ] || { echo "router-export: cannot read $CFG" >&2; exit 4; }

umask 077
T=$(mktemp -d /tmp/router-sync.XXXXXX)
trap 'rm -rf "$T"' EXIT INT TERM
mkdir "$T/out" "$T/out/rulesets"

# Each step writes a file first, so a failing extractor aborts the export (no pipefail in POSIX sh).
extract route > "$T/out/route.json"
extract servers > "$T/servers.txt"
extract rulesets > "$T/rulesets.tsv"

: > "$T/out/drop_hashes.txt"
while IFS= read -r addr; do
  [ -n "$addr" ] && hash_line "$addr" >> "$T/out/drop_hashes.txt"
done < "$T/servers.txt"
rm -f "$T/servers.txt"   # plaintext addresses never leave the router

TAB=$(printf '\t')
while IFS="$TAB" read -r fmt path; do
  case "$path" in
    /*) ;;
    *) echo "router-export: skipping rule_set with non-absolute path" >&2; continue ;;
  esac
  name=$(basename "$path")
  stem=${name%.*}
  if [ -z "$fmt" ] || [ "$fmt" = "-" ]; then
    case "$name" in *.srs) fmt=binary ;; *) fmt=source ;; esac
  fi
  if [ "$fmt" = "binary" ]; then
    [ -n "$SB" ] || { echo "router-export: sing-box binary not found (set ROUTER_SINGBOX)" >&2; exit 5; }
    "$SB" rule-set decompile --output "$T/out/rulesets/$stem.json" "$path" >/dev/null
  else
    cp "$path" "$T/out/rulesets/$stem.json"
  fi
done < "$T/rulesets.tsv"

tar -C "$T/out" -cf - route.json drop_hashes.txt rulesets
