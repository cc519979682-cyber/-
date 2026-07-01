# Personal Shadowrocket Rules

This repository builds a public-safe Shadowrocket config from a soft-router rule overlay.

## Output

- `sr_personal_whitelist_ad.conf`: final Shadowrocket subscription file.
- `personal/rules.conf`: public-safe personal overlay rules.

## Recovery Docs

This repo also keeps public-safe recovery notes under `docs/`.

- `docs/README-小白恢复指南.md`: plain-language recovery checklist.
- `docs/network-topology.md`: home network topology and device roles.
- `docs/shadowrocket-rules.md`: Shadowrocket rule and DNS policy notes.
- `docs/openclash-notes.md`: OpenClash maintenance notes without secrets.
- `docs/dns-leak-troubleshooting.md`: DNS leak troubleshooting notes.

Sensitive node material is not stored in GitHub. Keep it in the private NAS folder:

```text
\\192.168.1.186\personal_folder\同步工作\VPS
```

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
