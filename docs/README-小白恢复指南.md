# 小白恢复指南

这份文档是给未来的自己、另一台电脑上的 Codex、或者临时接手的人看的。它只记录恢复思路和安全操作顺序，不保存节点链接、UUID、密码、订阅地址、Reality 参数等敏感信息。

## 最重要的原则

1. GitHub 里只放公开安全内容。
2. 节点、密码、订阅、SSH 信息放在 NAS 私人目录。
3. 修改软路由前先备份，再做小范围修改。
4. 不确定时先不要重启 OpenClash，因为重启可能让 Codex 或远程会话断线。
5. 国内网站慢，先查是否误走代理；国外网站慢，先查代理节点和 OpenClash 分组；DNS 泄露，先查 Shadowrocket 或软路由 DNS 链路。

## 敏感资料在哪里

敏感资料不要提交到 GitHub。

当前约定的私人资料目录：

```text
\\192.168.1.186\personal_folder\同步工作\VPS
```

这里可以放 VPS 节点信息、二维码、订阅链接、SSH 信息、API 信息、软路由完整备份等。GitHub 文档只能写“去这里找”，不能把里面的内容复制出来。

## 新机器恢复顺序

1. 先确认本机能访问软路由：`http://192.168.1.1`。
2. 确认能访问 NAS 私人目录。
3. 从 NAS 找到当前 VPS/节点资料。
4. 登录软路由，检查 OpenClash 是否运行。
5. 检查 OpenClash 当前配置文件和备份文件是否存在。
6. 只恢复必要内容：节点、分组、直连名单、DNS 设置。
7. 验证国内网站、国外网站、ChatGPT/Codex、YouTube、X/Twitter、NAS、银行证券 App。
8. 最后再更新 Shadowrocket GitHub 规则。

## 哪些东西不能公开

不要上传这些内容：

- 节点链接，例如 vless、ss、trojan、vmess。
- UUID、Reality public key、short-id。
- VPS 登录密码、root 密码、API token。
- 机场订阅链接。
- 完整 OpenClash 配置文件。
- 手机二维码截图。
可以公开这些内容：

- 分流思路。
- 故障排查步骤。
- 哪些 App 应该直连，哪些 App 应该代理。
- Shadowrocket 规则模板。
- 不含真实节点参数的配置说明。

## 快速判断问题在哪里

国内网站打不开：

- 优先怀疑被错误代理、DNS 对国内解析不友好、Shadowrocket 出门配置过度保护。

国外网站打不开：

- 优先怀疑节点失效、OpenClash 分组选择错误、机场订阅失效、VPS 自身不可用。

ChatGPT/Codex 重连：

- 优先怀疑当前节点不稳定、Reality 参数不兼容、连接复用或频繁切换影响长连接。

DNS 泄露：

- 家里 Wi-Fi 先查软路由 DNS 链路。
- 出门用手机流量先查 Shadowrocket DNS 设置。
- iPhone 还要检查是否有连接助手、私有中继、描述文件或其他 VPN 类工具干扰。
