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

- Lines between `// BEGIN router-sync (auto-generated, do not edit by hand)` and `// END router-sync` are rewritten by the NAS job (`scripts/sync_router_rules.py`). Do not edit them by hand; add hand-kept rules outside the block instead.
- Hand-kept rules outside the block win: duplicates are removed from the block, and the block sits just before the final `GEOIP,CN,DIRECT` line so every hand-kept rule matches first.
