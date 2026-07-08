# 自用 Shadowrocket 去广告与分流规则

这个仓库用于生成一份给 Shadowrocket / 小火箭使用的自用配置文件。

它的目标很简单：

- 广告、追踪域名尽量拦截。
- 国内网站、银行、购物、常用国产 App 尽量直连。
- OpenAI、Google、YouTube、X、TikTok 等国外服务走代理。
- 手机离开家里软路由后，也尽量减少 DNS 泄露。
- 不公开节点、密码、UUID、订阅链接等敏感信息。

## 直接使用

### Shadowrocket / 小火箭

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
