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
