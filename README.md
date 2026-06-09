# Personal Shadowrocket Rules

This repository builds a public-safe Shadowrocket config from a soft-router rule overlay.

## Output

- `sr_personal_whitelist_ad.conf`: final Shadowrocket subscription file.
- `personal/rules.conf`: public-safe personal overlay rules.

Use this URL after GitHub Pages is enabled:

```text
https://<your-github-username>.github.io/<repo-name>/sr_personal_whitelist_ad.conf
```

## What Is Published

The generated config uses Johnshall's `sr_top500_whitelist_ad.conf` as the base and inserts your public-safe rules at the top of `[Rule]`.

The public version deliberately does not publish:

- node names
- node links
- VPS IP rules
- proxy groups
- subscription URLs
- passwords, UUIDs, or server fields

## Refresh Rules From A Local Export

Run this locally after exporting a new Shadowrocket/OpenClash-derived config:

```powershell
python scripts/build_personal_shadowrocket.py --refresh-from "C:\path\to\shadowrocket-soft-router-rules.conf" --drop-ip "x.x.x.x"
```

You can also put private IPs in `.private/drop_ips.txt` or set `PRIVATE_DROP_IPS` as a comma-separated list. `.private/` is ignored by Git.

Review `personal/rules.conf`, then commit it. GitHub Actions will rebuild the final config daily at 08:20 Beijing time.
