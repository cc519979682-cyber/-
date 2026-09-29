# 变更记录

## 2026-09-29

- 针对 Shadowrocket 开启时 Apple Watch / watchOS 与 iPhone 软件更新极慢：在 `personal/rules.conf` 的 router-sync 标记外新增手写 DIRECT 规则，覆盖 Apple HT210060 软件更新目录与下载 CDN，以及上游白名单里被标成 PROXY、且无法被 `DOMAIN-SUFFIX,apple.com` 命中的 Akamai/EdgeSuite CNAME（如 `mesu-cdn.apple.com.akadns.net`）。
- 不扩大到整个 `akadns.net`；不提交节点、凭据或私有 IP。合并后需在小火箭重新从配置 URL 拉取；手表更新仍建议充电并连 Wi‑Fi。

## 2026-09-27

- 针对小火箭内置 Tailscale 访问家庭 HA 白屏：生成小火箭成品时从 TUN 旁路列表移除 `100.64.0.0/10`，把它加入 `skip-proxy`，并在 `[Rule]` 开头加入该网段 `DIRECT,no-resolve`。不公开 NAS 的具体 Tailscale IP。
- 只影响小火箭成品，不改变 v2rayN 规则、节点、软路由或 NAS；增加离线回归测试。手机在外网访问 HA 的实际验收仍待完成，更新前的配置可作为回退。

## 2026-09-22

- 按 OpenBox/sing-box 当前生效配置核对公开分流；10 条 AI 域名规则前置，新增 `aistudio.google.com`，原有 9 条移至前部并去重。个人规则从 449 条增加到 450 条。
- 其余原规则及相对顺序保持；保留国内直连、富途 32 条代理、家庭访问例外、既有公开 IP 规则和客户端 DNS 设置。
- 代理出口统一映射为 `PROXY`，不导出住宅账号、节点信息、链式连接、私有规则源或家庭设备来源规则；客户端仍使用自己的节点。
- 两份客户端成品沿用原自动构建及订阅地址。本次只同步 GitHub 公开配置，不修改或重启家庭网络设备。

## 2026-09-10

- 从软路由当前生效规则增量同步 4 条公开安全直连域名：`spdbccc.cn`、`spdbccc.com.cn`、`bing.com`、`babybus.com`；个人规则从 445 条增加到 449 条。
- 保留已有富途 32 条代理规则、家庭 DDNS 例外及客户端 DNS 设置；不上传完整路由器配置、节点信息、凭据、设备来源规则或新 IP 规则。
- 修正 v2rayN 导出时全局按策略分桶导致的优先级丢失，仅合并相邻同出口、同字段规则，保留精确域名例外和 GeoIP 顺序。
- 新增 9 项离线回归测试，并加入自动构建流程。此更新不更改或重启家庭软路由。

## 2026-07-01

- 新增家庭网络恢复文档。
- 新增 Shadowrocket 规则说明。
- 新增 OpenClash 维护笔记。
- 新增 DNS 泄露排查说明。
- 增强 `.gitignore`，避免误把节点、订阅、密码、token、env 文件提交到 GitHub。
- 明确敏感资料放在 NAS 私人目录，不进入 GitHub。

