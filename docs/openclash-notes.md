# OpenClash 维护笔记

OpenClash 是家里软路由分流的核心。这个文件只记录维护原则，不保存完整 YAML。

## 核心目标

1. 国内和内网尽量直连。
2. 国外网站按用途分流。
3. ChatGPT/Codex 这种长连接要稳定，不要频繁切换。
4. YouTube、TikTok、X 等要兼顾速度和稳定。
5. NAS、银行、证券、淘宝、拼多多、OKX 等不应浪费 VPS 或机场流量。

## 重要分组

常见核心分组包括：

- `Proxy`
- `OpenAI`
- `AppleAI`
- `AI-Stable`
- `Stable-Daily`
- `Media-Auto`
- `Media-Stable`
- `Javday-Video`
- `YouTube`
- `TikTok-Stable`
- `Domestic`

这些名字可能被脚本或规则依赖，不要随便改名。

## 修改前检查

动 OpenClash 前先确认：

- 当前活动配置文件是哪一个。
- `BF.yaml` 或其他备份是否存在。
- 当前节点是否能用。
- Windows 本机是否开着 v2rayN，避免误判软路由状态。

## 修改原则

优先小改：

- 添加一个直连规则。
- 调整一个分组选择。
- 修复一个节点参数。
- 增加一个 fake-ip-filter。

避免大改：

- 不要大面积重排 YAML。
- 不要删除机场自带节点。
- 不要删除成熟规则组。
- 不要把完整敏感配置贴到聊天或 GitHub。

## 备份习惯

每次大改前至少备份：

- 主配置 YAML。
- `BF.yaml`。
- crontab。
- 关键脚本。

备份建议放在软路由本地和 NAS 私人目录两处。

## 常见故障

国外都慢：

- 先查当前代理节点。
- 再查是否全家流量都压到 VPS。
- 再查 OpenClash 是否频繁健康检查或频繁切换。

国内 App 慢：

- 先查是否被误判为代理。
- 再查 DNS 是否把国内域名解析到不合适地址。

Codex 无限重连：

- 先查当前节点长连接稳定性。
- Reality 节点要注意 SNI、fingerprint、flow、mux/smux。
- 不要让 AI 组频繁切换。

SSH 到 VPS 失败：

- 先确认 VPS IP 是否直连。
- OpenClash 不能把 VPS 自己的 IP 代理到自己。
