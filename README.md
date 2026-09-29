# 自用 Shadowrocket 去广告与分流规则

这个仓库结合上游广告规则与公开安全的个人分流规则，生成 Shadowrocket（小火箭）去广告配置和 v2rayN 路由规则。

它的目标很简单：

- 广告、追踪域名尽量拦截。
- 国内网站、银行、购物、常用国产 App 尽量直连。
- OpenAI、Google、YouTube、X、TikTok 等国外服务走代理。
- 手机离开家里软路由后，也尽量减少 DNS 泄露。
- 不公开节点、密码、UUID、订阅链接等敏感信息。

## 当前同步范围（2026-09-22）

已按当前 OpenBox/sing-box 生效规则更新公开分流：10 条 AI 域名规则前置，新增 `aistudio.google.com`，个人规则共 450 条。原有国内直连、广告拦截、富途代理与家庭访问例外继续保留。

公开配置把各代理出口统一为 `PROXY`，使用客户端自己选择的节点。它不包含住宅代理账号、链式出口或家庭设备专用规则；下载本配置不会自动获得家庭住宅出口，也不是整台路由器的恢复包。路由器的 DNS、AdGuard 例外和在线规则源另行维护。

## 直接使用

### Shadowrocket / 小火箭

如果在小火箭中启用了 Tailscale 隧道，本配置会让其 `100.64.0.0/10` 地址段留在 TUN 内并前置直连，不交给普通代理节点。请保留手机上原配置作回退；更新后需要在外网用实际 Tailscale 服务验收，仓库测试不能代替手机端连通性。

Shadowrocket 里可以通过 URL 下载这份配置：

```text
https://raw.githubusercontent.com/cc519979682-cyber/-/main/sr_personal_whitelist_ad.conf
```

建议在 Shadowrocket 里这样操作：

```text
配置 -> 右上角加号 -> 从 URL 下载配置 -> 粘贴上面的链接 -> 下载
```

下载后选择 `sr_personal_whitelist_ad.conf` 作为当前配置。

### v2rayN

v2rayN 和小火箭不太一样：

- 节点订阅：继续用你自己的机场/VPS订阅。
- 路由规则：可以用这个仓库生成的公开规则。

v2rayN 路由规则链接：

```text
https://raw.githubusercontent.com/cc519979682-cyber/-/main/v2rayn_personal_routing_rules.json
```

建议在 v2rayN 里这样操作：

```text
设置 -> 路由设置 -> 路由规则 -> 从订阅 URL 导入规则
```

粘贴上面的链接后导入。导入后选择这套路由规则，再配合你的节点订阅使用。

## 文件说明

- `sr_personal_whitelist_ad.conf`：最终生成的小火箭配置文件。
- `v2rayn_personal_routing_rules.json`：最终生成的 v2rayN 路由规则文件。
- `personal/rules.conf`：我自己的公开安全规则，只放域名分流和广告拦截补充。
- `scripts/build_personal_shadowrocket.py`：自动生成小火箭配置的脚本。
- `scripts/build_v2rayn_routing.py`：自动生成 v2rayN 路由规则的脚本。
- `docs/`：软路由、DNS、防泄露、恢复流程等说明文档。

## 自动更新

这个项目会通过 GitHub Actions 自动更新。

大致流程是：

1. 每天拉取上游广告规则底版。
2. 把 `personal/rules.conf` 里的自用规则合并进去。
3. 重新生成 `sr_personal_whitelist_ad.conf` 和 `v2rayn_personal_routing_rules.json`。
4. 自动提交到 GitHub。

所以平时你只需要订阅最终链接，不需要每天手动下载。

### 路由器规则自动同步

家里 NAS 每天 21:00 会从路由器（OpenBox / sing-box）只读取出分流规则，转换成公开安全的规则，
写进 `personal/rules.conf` 里 `// BEGIN router-sync` 和 `// END router-sync` 两行之间，
只有真的有变化才提交（`Sync router rules (auto)`），然后上面的流程自动重新生成配置。

- 以路由器为准：路由器里有的规则都放进标记块、用路由器的策略；标记块外面同样的规则会被移走（不重复）。
  路由器里没有、只在仓库里的规则留在标记块外原位不动。可用 `HAND_RULES_WIN=1` 恢复“手写优先”的旧做法。
- 节点、密码、UUID、订阅、按设备的规则、住宅出口规则、内网地址都不会被同步出来。
- 默认只同步路由器里直接手写的规则；引用的第三方规则集（rule_set）默认不展开（可用 `INCLUDE_RULE_SETS=1` 打开）。
- 单个主机 IP（IPv4 /29 及更小、IPv6 /120 及更小）不会被同步；展开规则集时，其中的直连 IP 段默认也不同步（已由 `GEOIP,CN,DIRECT` 覆盖）。
- 路由器一条规则都没读到、规则数不到上次一半、或一次少掉 10% 以上时会自动停止，避免路由器出错时把规则清空。

设置方法见 [`scripts/nas/README.md`](scripts/nas/README.md)。

## 安全边界

这个仓库只适合放“公开也没关系”的规则，例如：

- `DOMAIN-SUFFIX,example.com,DIRECT`
- `DOMAIN-SUFFIX,example.com,PROXY`
- `DOMAIN-SUFFIX,ads.example.com,REJECT`

不要把下面这些内容放进 GitHub：

- 节点链接
- 机场订阅链接
- VPS IP 专用规则
- UUID
- Reality public key / short-id
- 密码
- API key
- 完整 OpenClash 配置文件

敏感资料请继续放在私人 NAS 文件夹里，不要提交到这个公开仓库。

## 规则原则

这份配置采用“白名单直连 + 广告拦截 + 其余代理”的思路：

- 明确属于国内、银行、电商、生活服务的域名：`DIRECT`
- 明确属于广告、追踪、统计的域名：`REJECT`
- 明确属于国外服务的域名：`PROXY`
- 没有命中的流量：按最终规则处理

## 相关文档

- `docs/README-小白恢复指南.md`：故障后如何恢复配置。
- `docs/network-topology.md`：家庭网络拓扑和设备角色。
- `docs/shadowrocket-rules.md`：Shadowrocket 规则和 DNS 说明。
- `docs/openclash-notes.md`：OpenClash 维护笔记。
- `docs/dns-leak-troubleshooting.md`：DNS 泄露排查说明。

## 本地更新规则

如果以后软路由规则变了，可以先导出公开安全的规则，再在本地执行：

```powershell
python scripts/build_personal_shadowrocket.py --refresh-from "C:\path\to\shadowrocket-soft-router-rules.conf" --drop-ip "x.x.x.x"
```

也可以把不想公开的 IP 放到 `.private/drop_ips.txt`，这个目录不会被 Git 提交。

更新后请先检查：

- `personal/rules.conf` 里没有敏感信息。
- `sr_personal_whitelist_ad.conf` 能正常生成。
- Shadowrocket 下载配置后国内外网站都能正常打开。
