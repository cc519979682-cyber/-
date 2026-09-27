# 路由器规则自动同步（NAS 端）

## 这是做什么的

家里路由器（ImmortalWrt + OpenBox / sing-box）里的分流规则会经常调整。
这个小工具放在 NAS（绿联 DXP4800）上，**每小时自动**做一次：

1. 通过 SSH **只读**登录路由器，只取出“分流规则”部分：
   - `route` 段（用 `jq '{route: .route}'` 在路由器上提取）
   - 被引用的本地规则集（在路由器上用 `sing-box rule-set decompile` 转成文本）
   - 节点服务器地址的 **sha256 指纹**（只是用来过滤，地址本身不出路由器）
   
   **节点、密码、UUID、订阅等敏感信息永远不会离开路由器**，完整的 `config.json` 不会被复制到 NAS。
2. 把规则转换成公开安全的 Shadowrocket 规则（`DIRECT` / `PROXY` / `REJECT`），
   只替换 `personal/rules.conf` 里下面两行之间的内容：
   ```
   // BEGIN router-sync (auto-generated, do not edit by hand)
   // END router-sync
   ```
   这两行之外你手写的规则（Tailscale、家里 NAS 直连、泄漏测试、富途、广告、国内直连等）**一个字都不会动**，
   而且手写规则优先（写在前面，重复的会自动去掉）。
3. 只有内容真的变了，才通过 GitHub 网页接口更新文件，提交信息为 `Sync router rules (auto)`。
   GitHub Actions 随后会自动重新生成 Shadowrocket / v2rayN 配置。

不会被公开的规则：按设备（源 IP、端口、进程、用户、入站）的规则、走住宅出口
（`Webshare-US-Residential`、`AI-Residential`）的规则、内网 IP 段、指向节点地址的规则、
以及无法准确表达的规则（取反、AND 组合、正则、限定端口/协议）。

安全保护：如果这次生成的规则比上次**少了 10% 以上**（上次至少 20 条时），会**停止、不上传**，
并在日志里说明原因（防止路由器临时出错把规则清空）。

NAS 上**不需要安装 git**，只用到自带的 `python3`、`curl`、`ssh`。

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

用文本编辑器打开 `~/router-sync/sync.env`，把 `ROUTER_HOST` 改成路由器的内网地址，其它一般不用改。
这个文件只在 NAS 上，不会上传。

### 2. 创建 GitHub 令牌（只能改这个仓库）

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

> 备选方案（部署密钥）：GitHub 仓库的 Deploy key 只能配合 git 使用，而这台 NAS 没装 git，
> 所以默认用上面的令牌。如果以后装了 git，也可以改成仓库 Settings → Deploy keys 添加一把“允许写入”的
> SSH 公钥，用 git 推送；那样就不需要令牌了（需要自行改脚本的上传步骤）。

### 3. NAS 登录路由器的钥匙（需要另行确认后再做）

路由器用 dropbear SSH，登录用户是 `root`。钥匙约定放在 `~/.ssh/router_sync_ed25519`：

```sh
ssh-keygen -t ed25519 -N '' -f ~/.ssh/router_sync_ed25519 -C nas-router-sync
```

然后把 `~/.ssh/router_sync_ed25519.pub` 的内容加到路由器的 `/etc/dropbear/authorized_keys`
（LuCI：系统 → 管理权 → SSH 密钥），并在 NAS 上手动连一次 `ssh -i ~/.ssh/router_sync_ed25519 root@路由器地址`
确认指纹（脚本要求主机指纹已知）。

路由器需要有 `jq`：`opkg update && opkg install jq`。`sing-box` 会自动寻找，找不到时在 `sync.env`
里写 `ROUTER_SINGBOX=/实际/路径/sing-box`。

### 4. 先试一次（不上传）

```sh
DRY_RUN=1 SYNC_LOG_STDOUT=1 sh ~/router-sync/sync_router_rules.sh
```

会打印将要做的改动和统计（例如跳过了多少设备规则、有没有不认识的出站名）。

### 5. 设置每小时自动运行

```sh
crontab -e
```

加一行（每小时第 17 分钟运行）：

```
17 * * * * /bin/sh $HOME/router-sync/sync_router_rules.sh
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
  - `FAILED: deletion guard tripped`：规则一下子少了很多，已停止。确认是你有意删减后，
    手动放行一次：`ALLOW_LARGE_DELETION=1 SYNC_LOG_STDOUT=1 sh ~/router-sync/sync_router_rules.sh`。
- 暂停：`touch ~/router-sync/PAUSE`；恢复：`rm ~/router-sync/PAUSE`。
- 彻底停用：`crontab -e` 删掉那一行。
- 同一时间只会有一个在跑（`~/router-sync/run.lock`），上一次没跑完时这次会自动跳过。
- 失败时脚本退出码非 0，日志里有 `FAILED:` 开头的原因。
