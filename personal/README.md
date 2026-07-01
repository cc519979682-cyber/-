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
