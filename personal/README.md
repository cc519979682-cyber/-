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

## 一次性保留手机广告例外

家庭软路由关闭广告拦截，不代表手机公开配置也要删除原有广告规则。需要同步这种差异时，先用专用迁移器复制**既有已公开的39条 REJECT**到 auto 块之前的 `mobile-ad-keep` 手写保留段，再运行原来的路由同步器：

```sh
python scripts/preserve_mobile_ad_rules.py --dry-run
python scripts/preserve_mobile_ad_rules.py --write
# 然后按 scripts/nas/README.md 的既有转换流程处理只读导出。
```

迁移器默认只检查；只有 `--write` 才写入。它不改原 `router-sync` 块的字节，也不引入新广告列表；原块仍由 `sync_router_rules.py` 正常替换。计数、公开源指纹、标记或策略冲突不符时拒绝，重复运行不重复复制。迁移后原删除保护仍生效：保留段的规则不算删除，其余真实大删仍会阻止同步。

这不是绕过10%/最少条数门禁的开关，不会展开第三方规则集、解除 NAS `PAUSE` 或自动上传。规则源、两份生成文件与测试仍须按正常分支/PR流程审核。
