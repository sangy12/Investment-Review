# 新 Codex Cloud 环境交接

当前实例仅允许软件包和代码站点，不能扩大网络访问；用户实际修改时收到环境级限制，要求新配置并开启新对话。2026-11-08 对 OpenAI、Yahoo 三标的、东方财富 A/H 财报来源、富途资讯、iFinD 和妙想共 10 个公开接口的探测均为代理 CONNECT 403。记录见 [validation-2026-11-08.json](validation-2026-11-08.json)。这不是账号密码错误，也不能据此判断数据源是否有数据。

## 创建环境

1. 设置 → Codex Cloud → Environments → **创建新的环境**，选择仓库 `sangy12/Investment-Review`，隐私保持 Only me。
2. 允许软件包站点，在 Additional allowed domains 中加入 [cloud-allowed-domains.txt](../config/cloud-allowed-domains.txt) 的域名（不包括注释）。如组织策略仍拒绝，需要有权限的管理员配置；不要在旧实例继续重试。
3. 安装依赖：在仓库根目录执行 `python3 -m venv .venv`，再执行 `.venv/bin/python -m pip install -e '.[dev,china]'`。解释器须为 Python 3.11+。
4. 发布新环境，用该环境创建新对话，并检出分支 `codex/fundamental-redteam-cloud-20261108`。不要仅检出 `main`，当前改造尚未合并主分支。

## 新环境第一步：验证网络

```bash
bash scripts/cloud.sh probe
```

脚本把凭据路径、缓存和研究记忆放在私有的 `.runtime/`，不用改系统 HOME，也不依赖只读的 `/home/agent`。`.runtime/` 同时排除在 Git 和 Docker build context 外。探测记录保存在 `reports/validation/`，只含状态/公开元数据，不保存认证头。

网络可达、认证成功、取到真实数据是三个不同状态。`probe` 只有在来源可达时才执行 Yahoo 价格、AKShare 当前利润表和富途公开新闻的读取，并用子进程限制单项时长为 45 秒。`safety_guard_passed` 仅说明历史日期被拒绝，不能算实时财报验收通过。退出码 1 表示存在网络策略阻断，2 表示公开数据检查未通过；即使公开数据通过，iFinD/妙想的认证工具与字段仍需单独验证。

## 登录 ChatGPT 订阅

当前 Codex 对话使用的登录身份不会自动变成 TradingAgents 的 OAuth 凭据。需要为这个开源应用单独授权 ChatGPT plan usage，不能读取/复用 Codex 的内部认证文件。

新环境网络可用后执行：

```bash
bash scripts/cloud.sh login
bash scripts/cloud.sh models
bash scripts/cloud.sh run --only NVDA
```

`login` 先连接 OpenAI JWKS 验证网络，然后复用上游的 PKCE、state、nonce、签名校验和 token 刷新实现。用户自己在浏览器完成登录及授权。若用户浏览器与执行环境不在同一机器，127.0.0.1 回调指向用户机器；将回调地址粘贴到运行登录命令的可信终端，而非聊天中。也可以依照 OpenAI VM 指南，安全导入同工具生成的受保护凭据，之后只让目标云端实例刷新。

支持三种接入：原生登录；`TRADINGAGENTS_CHATGPT_AUTH_SOURCE` 指向 secret 文件；或在 **Personal vault 的 Environment variable** 中配置 `TRADINGAGENTS_CHATGPT_AUTH_JSON`（官方完整登录 JSON）。后者需要原始内容，不应配置为只在网络代理替换的 HTTP secret。勿把 JSON、refresh token 或回调码写到聊天或 Git。

导入时为本云主机生成/保留独立稳定 host ID，不覆盖成来源机器的 ID；令牌文件 0600。已有可写存储中的轮换凭据优先于初始导入值。不要把同一 refresh token 同时交给多个新聊天实例刷新；新任务从发布镜像起步，不能假定会继承本聊天的运行时凭据。优先在一个专用聊天中继续执行并让它拥有会话。

OpenAI 官方支持符合条件的开源应用使用 ChatGPT 订阅，VM 指南要求独立主机标识和受保护的凭据转移。是否对本账号/工作区开放、可用模型和额度，仍须实际授权后确认：

- [开源应用授权](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [VM 凭据转移](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [云环境状态与网络设置](https://learn.chatgpt.com/docs/environments/cloud-environments)

## 数据源下一步

1. 先测无需账户的富途公开资讯：腾讯新闻/公告/研报必须含发布时间与原文链接；接口失败/空数据不算通过。
2. 测 AKShare 当前 A/H 三表，确认币种、单位和累计/单季口径；历史时点仍一律拒绝当前版本倒填。
3. iFinD、妙想先用各自账户只读权限 `tools/list` 验证工具和扣费口径，再对茅台/腾讯使用统一问题集。当前尚未接通两家 MCP。
4. 富途默认账户 OAuth 暂不执行：所检查官方 CLI 的默认 scopes 含 `trade:read trade:write`。需先验证官方能否授予仅行情/资讯的权限。只读取行情不等于默认授权也只读。
5. 真正取得 ChatGPT 模型权限后，检查/替换两个型号并在配置注释原因；再运行 NVDA、600519.SS、0700.HK 完整报告链。

## 可粘贴到新对话的交接指令

> 继续 `sangy12/Investment-Review` 的基本面长期投资红队项目。先检出 `codex/fundamental-redteam-cloud-20261108` 并阅读 `docs/CLOUD_HANDOFF.md`、`docs/REDTEAM.md` 和 `docs/DATA_SOURCES.md`。先验证新云环境网络与 `bash scripts/cloud.sh probe`，然后协助我通过官方 ChatGPT 订阅 OAuth 登录，凭据不要进入聊天/Git。保留代理决策核心和完整报告，不接券商/交易权限。按文档继续实测 A/H 财报、富途公开资讯、iFinD 与妙想，不把网络可达或历史保护测试当作数据成功。不要默认执行富途 CLI 的宽权限 OAuth。
