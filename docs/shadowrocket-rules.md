# Shadowrocket 规则说明

这个 GitHub 项目主要服务手机出门使用。它不负责提供节点，只负责提供 Shadowrocket 规则和 DNS 策略。

## 这个项目做什么

每天自动拉取上游广告规则底版，再叠加个人规则，生成：

```text
sr_personal_whitelist_ad.conf
```

手机 Shadowrocket 订阅这个文件后，可以得到一套更适合自己的规则。

## GitHub 在这里的作用

GitHub 只是存放和自动生成配置文件。

GitHub 本身不会屏蔽广告，也不会帮你代理。真正执行规则的是 Shadowrocket。

## Shadowrocket 怎么理解规则

可以简单理解成三种动作：

- `REJECT`：拦截，常用于广告域名。
- `DIRECT`：直连，常用于国内网站、银行、淘宝、拼多多、NAS。
- `PROXY`：走代理，常用于 OpenAI、YouTube、X、TikTok、Google。

规则从上往下匹配，越靠前优先级越高。

## 当前出门版 DNS 思路

### Melco Club（新濠皇會）出门注意

软路由侧对 Melco 使用 `dns-proxy`（`8.8.8.8` 经 Proxy）。出门版 Shadowrocket 对应做法是：

- 构建脚本把 Melco 相关 `DOMAIN` / `DOMAIN-SUFFIX` / `DOMAIN-KEYWORD,melco` **置顶**到 `[Rule]` 开头 → `PROXY,force-remote-dns`（必须早于上游 `DOMAIN-SUFFIX,cn,DIRECT` 与广告 `REJECT`）。
- `[General] always-real-ip` 钉上 Melco 域名，避免 fake-IP 与透明网关不一致。
- 软路由不会拦截 Melco 用的 APM：`heapanalytics.com` / `newrelic.com` 在出门版改为提前 `PROXY`（避免被上游广告规则 `REJECT`）。

#### 5G 仍失败时先看日志（不要先怪「缺域名」）

用户实测日志里出现过：

- `mcp-blue.melcoclub.cn` → **`DOMAIN-SUFFIX,cn,DIRECT`**（错误；正确应是 Melco 的 `PROXY`）
- 同屏 `heapanalytics.com` / `mobile-collector.newrelic.com` → `REJECT`

若仍看到 `cn,DIRECT` 命中 `*.melcoclub.cn`，说明手机**没有在用**当前 GitHub 成品（或未选中该配置），不是「再缺几个 azure/firebase 域名」的问题。当前 main 成品里 Melco 规则远在 `DOMAIN-SUFFIX,cn,DIRECT` 之前。

#### 小火箭侧请逐项确认

1. 订阅 URL 必须是：`https://raw.githubusercontent.com/cc519979682-cyber/-/main/sr_personal_whitelist_ad.conf`
2. 「配置」里**选中**刚更新的那份 `sr_personal_whitelist_ad.conf`（不是旧本地副本）
3. 首页连接方式为**规则 / 配置**，不是「直连」；节点要真正连上
4. 更新订阅后：断开 VPN → 再连接 → 强杀 Melco 再开
5. 「数据 → 代理」里打开日志后搜 `melco`：应看到 `PROXY`，**不应**再看到 `DOMAIN-SUFFIX,cn,DIRECT`
6. 未开 MITM / HTTPS 解密；未把 Melco 放进「不走代理」应用列表
7. `[General]` 里能看到 `always-real-ip` 含 `*.melcoclub.cn` / `*.melco-dxmobprod.com`

#### 给机务官

请确认家里软路由 **live** 是否仍只有 3 条 Melco `domain_suffix`、且 `dns.rules` 是否已带 `dns-proxy`（仓库里 `openbox-config-live` 快照曾无 dns-proxy，而 `melco-fix` 快照有）。软路由勿改的前提下，只需回告 live 的 Melco route + dns 片段，便于继续对齐出门版。


出门时既要避免国外网站 DNS 泄露，也要保证国内网站能打开。

所以当前策略是：

- 国内直连流量使用国内友好的 DoH。
- 国外代理流量使用远程 DNS。
- DNS 泄露检测网站强制走代理和远程解析。
- 不再把所有 DNS 都强行改成海外 DNS，因为这样可能导致国内直连网站打不开。

## 哪些规则适合加在这里

适合加入：

- 国内 App 直连规则。
- 国外网站代理规则。
- 广告域名拦截规则。
- DNS 泄露测试网站代理规则。

不适合加入：

- VPS 真实 IP。
- 节点链接。
- 订阅链接。
- UUID、密码、密钥。
- 只适合家里软路由的内网规则。

## 更新方式

这个项目通过 GitHub Actions 自动更新：

- 每天北京时间 08:20 自动构建。
- 修改 `personal/`、`scripts/` 或 workflow 后也会自动构建。
- 手动触发也可以构建。

如果外面手机用起来不对，常见处理顺序：

1. 更新 Shadowrocket 配置。
2. 断开再连接 Shadowrocket。
3. 重启 Shadowrocket。
4. 开关飞行模式刷新网络。
5. 再测 DNS 泄露和国内网站。
