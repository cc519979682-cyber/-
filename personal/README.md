# Personal Public Rules

`rules.conf` contains only public-safe Shadowrocket rules.

Keep this file free of:

- node names
- node links
- VPS IPs
- proxy provider URLs
- passwords or UUIDs

Policies in this file should only be `DIRECT`, `REJECT`, or `PROXY`.

Outdoor DNS policy:

- Direct/domestic traffic uses China-friendly DoH in `[General]`.
- Proxy traffic keeps `force-remote-dns` so foreign sites and DNS leak tests resolve through the proxy side.
- Do not change every DNS server to overseas-only DoH, or domestic direct sites can fail when outside the home router.

Router sync block:

- Lines between `// BEGIN router-sync (auto-generated, do not edit by hand)` and `// END router-sync` are rewritten by the NAS job (`scripts/sync_router_rules.py`). Do not edit them by hand.
- The router is the source of truth (default): every publishable router rule is written into the block with the router's policy, and a hand-kept line with the same type + value is removed from outside the block. Hand-kept rules the router does not have stay where they are. `HAND_RULES_WIN=1` restores the old behaviour (hand-kept lines stay and win; duplicates are left out of the block).
- The block sits just before the final `GEOIP,CN,DIRECT` line; comments, blank lines, the markers and GEOIP/FINAL lines are never moved.
