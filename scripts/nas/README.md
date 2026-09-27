# 路由器规则自动同步（NAS 端）

## 这是做什么的

家里路由器（ImmortalWrt + OpenBox / sing-box）里的分流规则会经常调整。
这个小工具放在 NAS（绿联 DXP4800）上，**每天晚上 21:00 自动**做一次：

1. 通过 SSH **只读**登录路由器，只取出“分流规则”部分：
   - `route` 段（在路由器上提取；有 `jq` 就用 `jq`，没有就用系统自带的 `ucode`，**路由器上不需要安装任何软件**）
   - 被引用的本地规则集（在路由器上用 `/opt/open-box/bin/sing-box rule-set decompile` 转成文本；
     默认不会用到，只有打开 `INCLUDE_RULE_SETS=1` 时才会展开，见下文）
   - 节点服务器地址的 **sha256 指纹**（在路由器上计算，只用来过滤，地址本身不出路由器）

   **节点、密码、UUID、订阅等敏感信息永远不会离开路由器**，完整的 `config.json` 不会被复制到 NAS；
   如果路由器上既没有 `jq` 也没有 `ucode`，脚本会直接报错停止，而不是退而复制整个配置。
2. 把规则转换成公开安全的 Shadowrocket 规则（`DIRECT` / `PROXY` / `REJECT`），
   只替换 `personal/rules.conf` 里下面两行之间的内容：
   ```
   // BEGIN router-sync (auto-generated, do not edit by hand)
   // END router-sync
   ```
   **以路由器为准**：路由器里有的规则全部放进这两行之间，并采用路由器的策略；
   如果标记块外面（“手写保留区”）有同一条规则（类型 + 域名/IP 相同，不区分大小写，不看策略），
   就把它从保留区**移走**，不会两边重复。路由器里没有的规则（只存在于仓库里的，大约 90 条）
   **原样留在原位、顺序不变**。注释、空行、两行标记、`GEOIP,CN,DIRECT` 永远不会被动。
   想恢复旧做法（手写规则优先，重复的从路由器那边去掉），在 `sync.env` 里设 `HAND_RULES_WIN=1`。
3. 只有内容真的变了，才通过 GitHub 网页接口更新文件，提交信息为 `Sync router rules (auto)`。
   GitHub Actions 随后会自动重新生成 Shadowrocket / v2rayN 配置。

**默认只同步你自己写的规则**：只取路由器 `route.rules` 里直接写出的 `domain` / `domain_suffix` /
`domain_keyword` / `ip_cidr`（一般几十到一百来条）。路由规则里引用的规则集（`rule_set`，例如 geosite、
各类第三方分流列表，共 96 个）**默认不展开**，因为那会多出几千行（日志里 `expanded_rule_set_refs=0`，
`skipped_rule_set_refs=<跳过的引用数>`，只引用规则集、没有自己写匹配项的规则计为 `skipped_rule_set_only_rules`）。
同一条路由规则里如果既有自己写的域名又引用了规则集，自己写的部分照常同步。
如确实想把规则集也展开发布，在 `sync.env` 里设置 `INCLUDE_RULE_SETS=1`（手机上的 Shadowrocket
本来就有底版规则，一般不需要）。

不会被公开的规则：按设备（源 IP、端口、进程、用户、入站）的规则、走住宅出口
（`Webshare-US-Residential`、`AI-Residential`）的规则、内网 IP 段、指向节点地址的规则、
以及无法准确表达的规则（取反、AND 组合、正则、限定端口/协议）。
另外：
- **单个主机 IP 一律不公开**：IPv4 前缀 ≥ /29、IPv6 前缀 ≥ /120 的 IP 规则（很可能是自家或自有服务器的公网 IP），
  不管走哪个出站都跳过（日志计数 `skipped_host_ip`）。手写在标记块外的 IP 规则不受影响。
- （仅在 `INCLUDE_RULE_SETS=1` 时相关）**规则集里的“直连 IP 段”默认不公开**：这些几乎都是中国 IP 段，生成的配置里已有 `GEOIP,CN,DIRECT` 覆盖，
  全部写出会多出约一万行（计数 `skipped_ip_direct_ruleset`）。直接写在路由规则里的直连 IP、以及走代理的 IP 段
  （例如 Telegram）照常保留。如确实需要，在 `sync.env` 里设置 `INCLUDE_RULESET_IP_DIRECT=1`。

安全保护（任一条触发都会**停止、不上传**，在日志里写明原因，退出码非 0）：
- 路由器这次一条可发布的规则都没有（例如读取失败）；
- 这次的路由器规则数**不到上次标记块的一半**；
- 标记块比上次**少了 10% 以上**（上次至少 20 条时）。

这些都是为了防止路由器临时出错把规则清空。确认是你有意大幅删减后，可以用
`ALLOW_LARGE_DELETION=1` 手动放行一次（“一条都没有”这一条不能放行）。

NAS 上**不需要 git**（装了也不用），只用到自带的 `python3`、`curl`、`ssh`。

## 第一次设置（只做一次）

以下命令都在 NAS 上、用 `cc40045309` 这个用户执行。

### 1. 放脚本

```sh
mkdir -p ~/router-sync
curl -fsSL https://raw.githubusercontent.com/cc519979682-cyber/-/main/scripts/nas/sync_router_rules.sh -o ~/router-sync/sync_router_rules.sh
curl -fsSL https://raw.githubusercontent.com/cc519979682-cyber/-/main/scripts/nas/sync.env.example -o ~/router-sync/sync.env
chmod 700 ~/router-sync/sync_router_rules.sh
chmod 600 ~/router-sync/sync.env
```

之后每次运行，脚本会自动从 GitHub 下载最新的转换程序，不用手动更新
（如果想固定版本，可以在 `sync.env` 里设置 `CODE_DIR` 指向一份本地拷贝）。

`sync.env` 默认已经写好 `ROUTER_HOST=openbox-router`，直接使用 NAS 上 `~/.ssh/config` 里的
`Host openbox-router` 设置（地址、root 用户、钥匙都在那里），`ROUTER_USER` / `ROUTER_PORT` / `ROUTER_SSH_KEY`
留空即可。如果不用别名，也可以把 `ROUTER_HOST` 写成 IP，并填上这三项。这个文件只在 NAS 上，不会上传。

### 2. 创建 GitHub 令牌（只能改这个仓库）

> 只做第 4 步“试跑”的话可以先跳过这一步；正式自动上传前再做。

1. 打开 GitHub → 右上角头像 → **Settings** → 左下 **Developer settings**
   → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**。
2. Token name 随便填，例如 `nas-router-sync`；Expiration 选一个到期时间（到期后重新生成一次即可）。
3. **Repository access** 选 **Only select repositories**，只勾选 `cc519979682-cyber/-`。
4. **Permissions → Repository permissions → Contents** 选 **Read and write**，其它都保持 No access。
5. 点 **Generate token**，复制那一串 `github_pat_...`（只显示一次）。

保存到 NAS（把 `粘贴令牌` 换成刚才复制的内容）：

```sh
mkdir -p ~/.config/router-sync
umask 077
printf '%s\n' '粘贴令牌' > ~/.config/router-sync/github_pat
chmod 600 ~/.config/router-sync/github_pat
```

脚本会检查这个文件的权限，别人可读时会拒绝运行；令牌不会出现在日志里。

> 备选方案（部署密钥）：GitHub 仓库的 Deploy key 只能配合 git 使用。NAS 现在装有 git 2.39.5，但本脚本
> 刻意不依赖 git，默认用上面的令牌。若想改用部署密钥，可在仓库 Settings → Deploy keys 添加一把“允许写入”的
> SSH 公钥，再自行把脚本的上传步骤换成 git clone/commit/push；那样就不需要令牌了。

### 3. NAS 登录路由器的钥匙

路由器用 dropbear SSH，登录用户是 `root`，钥匙是 `~/.ssh/router_sync_ed25519`。
如果 `~/.ssh/config` 里已经有下面这段、并且路由器指纹已在 `known_hosts` 里，这一步就已完成：

```
Host openbox-router
  HostName 192.168.1.1
  User root
  IdentityFile ~/.ssh/router_sync_ed25519
  IdentitiesOnly yes
```

检查一下（应当打印出 sing-box 版本，且不需要输入密码）。路由器的 busybox `command -v` 遇到第一个找不到的程序就会停下，
所以每个程序分开查，每行都会显示“有”或“没有”：

```sh
ssh -o BatchMode=yes openbox-router '/opt/open-box/bin/sing-box version | head -1
for p in jq ucode sha256sum; do if command -v "$p" >/dev/null 2>&1; then echo "$p: 有 ($(command -v "$p"))"; else echo "$p: 没有"; fi; done'
```

正常情况：`jq: 没有` 没关系；`ucode` 和 `sha256sum` 需要是“有”（二者任缺其一，jq 或 openssl 可替代）。

路由器上**不需要安装 jq**：没有 jq 时自动使用系统自带的 `ucode`。`sing-box` 默认先找
`/opt/open-box/bin/sing-box`，路径不同再在 `sync.env` 里写 `ROUTER_SINGBOX=/实际/路径/sing-box`。

### 4. 先试一次（不上传，不需要令牌）

```sh
DRY_RUN=1 SYNC_LOG_STDOUT=1 sh ~/router-sync/sync_router_rules.sh
```

会打印将要做的改动和统计（例如跳过了多少设备规则、有没有不认识的出站名），其中：

- `removed_from_hand_kept=N`：有 N 条保留区规则因为路由器也有，被移进了标记块；
- `policy_changed=N`：其中策略被路由器改掉的条数，每条会单独列出一行
  `POLICY CHANGED DOMAIN-SUFFIX,xxx: DIRECT -> PROXY (router wins)`；
- `hand_kept_remaining=N`，以及 `hand_kept_DIRECT` / `hand_kept_PROXY` / `hand_kept_REJECT`：留在保留区的规则数，
  后面 `HAND-KEPT rules remaining` 下面会逐条列出（就是“只在仓库里有”的那些）；
- `block_rules=N`：标记块里的路由器规则数；
- `shadowed_by_hand_kept=N`：保留区里有 N 条更宽的规则（写在标记块**上面**）会先匹配到某条路由器规则，
  而且策略不同，每条列成 `SHADOWED ...`。例如保留区的 `DOMAIN-SUFFIX,youtube.com,PROXY` 会抢在路由器的
  `DOMAIN-SUFFIX,ads.youtube.com,REJECT` 前面。看到这类提示，可以把那条保留区规则也加到路由器里，或者从仓库删掉。

最后一行是 `result=dry-run`
（没有变化时是 `result=unchanged`）。试跑只从公开地址读取 `personal/rules.conf`，**不需要 GitHub 令牌、也不会上传**；
正式运行（去掉 `DRY_RUN=1`）才需要第 2 步的令牌。

### 5. 设置每天自动运行

```sh
crontab -e
```

加一行（每天 21:00 运行一次）：

```
0 21 * * * /bin/sh $HOME/router-sync/sync_router_rules.sh
```

## 日常查看

- 日志：`~/router-sync/logs/sync.log`（超过 1MB 自动轮换成 `sync.log.1`）
  ```sh
  tail -n 50 ~/router-sync/logs/sync.log
  ```
  - `result=unchanged`：路由器规则没变，什么也没做。
  - `result=<一串字符>`：已更新 GitHub。
  - `WARNING unknown outbound tag skipped`：路由器里有个出站名还没登记，这条规则被跳过了。
    在仓库的 `scripts/router_outbound_map.json` 里把它加到 `DIRECT` / `PROXY` / `REJECT` / `DROP` 之一；
    或者只在 NAS 上写一个同格式的 `outbound_map.local.json`，并在 `sync.env` 里设置 `OUTBOUND_MAP_OVERRIDE`。
    **真实节点名不要写进仓库。**
  - `FAILED: safety guard tripped`：路由器没读到规则，或规则一下子少了很多，已停止、没有上传。
    先检查路由器；确认是你有意删减后，手动放行一次：
    `ALLOW_LARGE_DELETION=1 SYNC_LOG_STDOUT=1 sh ~/router-sync/sync_router_rules.sh`。
- 暂停：`touch ~/router-sync/PAUSE`；恢复：`rm ~/router-sync/PAUSE`。
- 彻底停用：`crontab -e` 删掉那一行。
- 同一时间只会有一个在跑（`~/router-sync/run.lock`），上一次没跑完时这次会自动跳过。
- 失败时脚本退出码非 0，日志里有 `FAILED:` 开头的原因。
