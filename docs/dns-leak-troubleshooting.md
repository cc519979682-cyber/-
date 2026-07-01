# DNS 泄露排查

DNS 泄露不是单纯看出口 IP。出口 IP 可能是代理美国，但 DNS 查询可能还跑到中国电信、运营商或系统 DNS。

## 家里 Wi-Fi

家里正常目标：

- 设备 DNS 指向软路由。
- 软路由统一处理 DNS。
- 国内直连解析走国内友好链路。
- 国外代理解析走代理侧。

如果同一个 Wi-Fi 下电脑没泄露、手机泄露，通常不是软路由整体坏了，优先查手机自身：

- Shadowrocket 是否关闭或配置没刷新。
- iPhone 是否开了连接助手。
- 是否开了 iCloud 私有中继。
- 是否有其他 VPN、描述文件、加速器。
- Safari 或 App 是否缓存了旧 DNS。

## 出门用 5G

出门时不经过家里软路由，主要靠 Shadowrocket。

推荐处理：

1. 更新 Shadowrocket 订阅。
2. 重启 Shadowrocket。
3. 开关飞行模式。
4. 再打开 DNS Leak Test。

如果 DNS 结果里有中国电信：

- 先确认 Shadowrocket 是否真的连接。
- 再确认测试网站规则是否 `PROXY,force-remote-dns`。
- 再确认 App 里没有系统 DNS 回落。

## 检测网站结果怎么理解

只出现代理所在地的 Cloudflare / Google：

- 通常可以接受。

同时出现 China Telecom：

- 说明有一部分 DNS 查询没有通过代理侧。
- 需要查 Shadowrocket、手机系统、浏览器缓存或其他工具。

DNS 检测网站偶尔也会有缓存或重复结果，所以修改后要重启 App 再测。

## 已知踩坑

连接助手：

- 曾经导致手机在 Wi-Fi 下出现 DNS 泄露。
- 关闭后恢复正常。

全部使用海外 DNS：

- 能减少国外 DNS 泄露，但可能导致国内直连网站打不开。
- 后来改成直连流量用国内友好 DoH，代理流量用远程 DNS。
