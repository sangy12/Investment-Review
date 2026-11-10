# 新 Codex Cloud 环境交接

2026-11-10 币种独立复核见 [CURRENCY_DOUBLECHECK_20261110.md](CURRENCY_DOUBLECHECK_20261110.md)：以公司官方财报及央行汇率核验AKShare原始返回，MiniMax三表美元金额×6.8109、港交所公司港币归母净利×0.86855、腾讯人民币现金×1，共五项残差均为0。结论限定当前`stock_financial_hk_report_em`货币金额样本，不概括所有AKShare接口或发行人列报币种；该函数底层确实是东方财富，不能当成独立数据商。未更改渠道政策、未调用模型/妙想或交易接口。

2026-11-10 财报新鲜度/研究深度后续修复见 [SOURCE_QUALITY_AND_RESEARCH_DEPTH.md](SOURCE_QUALITY_AND_RESEARCH_DEPTH.md)：A/H 三表首源改为 AKShare/East Money、Yahoo 为备用，市场可独立配置；增加非空期间/过旧/官方已知期间校验和跨源期间比较。港股官方 HKEXnews 公告与完整定期报告发现已接入共享材料，MiniMax 实测保留五页财务原文含现金流续页。确认当前东方财富 HK F10 三表的金额为供应商换算 CNY，不能按港股默认 HKD，也不能与发行人 USD'000 混算。A 股改为先限最近四期再抓表，避免原函数遍历全历史。红队专用 analyst 职责已加强财务深度与重大事件筛选，但通用互联网 deep research 循环尚未实现；旧报告未重跑。主配置与两个私有活跃 profile 已同步，私有妙想预算仍为0，未调用模型/妙想或交易接口。

本轮验收：MiniMax/腾讯三表至2026-06-30、茅台三表至2026-09-30，共9项生产路由读取成功；茅台新抓取约12—15秒，三表均显式CNY。离线回归1533项及100个子测试通过，1项可选依赖跳过、1项deselected，Ruff通过。公开验收记录在 `docs/source-quality-validation-2026-11-10.json`，原始CSV/PDF仅放私有运行目录。

新对话迁移流程见 [NEW_CHAT_RESTORE.md](NEW_CHAT_RESTORE.md)。代码将保存到当前同名远端分支；私有资料为仓库外 AES-GCM 加密包，密钥单独保存，须由用户安全取走并在目标环境恢复，不能假定新任务自动继承。恢复工具默认不导入认证；认证只通过可信终端明确启用种子导入。

最新模型设置：用户在2026-11-10要求快速改为 `gpt-6.1-sol/high`、深度改为 `gpt-6.1-sol/max`，已更新主 profile 与 MiniMax 私有后续运行配置。已实现分层 reasoning_effort，未设置时沿用全局值；请求参数及报告元数据通过离线测试。此前 MiniMax 实际执行配置另存 `.runtime/minimax/redteam.executed-20261110.yaml`，原报告仍记录原 Sol/Terra/high 设置。本次没有重跑报告或发起模型调用。下文旧型号描述是历史验收记录。

2026-11-10 用户新增 MiniMax（0100.HK/港交所00100），已完成完整报告，入口 `reports/0100.HK/delivery-2026-11-10.md`。原生评级 Underweight，明确为2—4周策略窗口；另附针对用户2027年持有假设的独立核查与ARR情景表，不把两种期限混同。用户原始论点只保存在 `.runtime/minimax/watchlist.yaml` 和被Git忽略的报告中，公开watchlist仅新增标的、名称与空thesis。本次用 `.runtime/minimax/redteam.yaml`（妙想预算0）执行，Sol/Terra配置不变，45次模型成功、0次失败、515780 token。免费预测和社区在MiniMax样本失败，缺口原样保留；补读公司官网中期业绩及模型发布、官方公告和公开申报作为独立附件，未伪装成原生图输入。用户表示如有必要可充值妙想；当前未要求充值或追加付费调用，后续若确有已披露字段缺口须先说明字段及预计调用次数。

最新：用户已采纳免费方案，代码与红队 profile 已接入：[FREE_SOURCE_INTEGRATION.md](FREE_SOURCE_INTEGRATION.md)。FRED 公共宏观路由、三市场预测和港股社区共享材料均通过生产适配器实测，并在 CLI 缓存预览中出现；未调用模型或新增妙想查询。旧报告未重跑，后续新报告使用新配置。下文“尚未接入”的 2026-11-10 小样本记录现已被本段更新。

2026-11-10 补充复核：[免费渠道与小样本](SOURCE_OPTIONS_20261110.md)。FRED 官方公开 CSV（无 key）已取到 CPI/失业率/10年美债数值；富途社区返回 3 条结果；现有 yfinance / AKShare 对 NVDA、茅台、腾讯盈利预测分别返回 4/3/3 行。此前的 FRED 缺 key 仅描述 API 适配器，不代表没有免费数据入口。上述新能力尚未接入生产报告；未新增妙想、模型或账户/交易调用。

最新缺口修复见 [GAP_REPAIRS_20261109.md](GAP_REPAIRS_20261109.md)：红队已修复跨日新闻检查、经理直接读取四份分析师原文、A 股新闻回退及中国宏观路由，并补估值时间戳与逐摘要 PDF 原文。免费实测 CPI/LPR/茅台新闻可读，新增妙想和真实模型调用均为 0。旧报告没有重跑或替换；美国宏观 key、社区覆盖及未公开经营指标仍有明确外部依赖，不声称全部缺口已消除。

用户已采纳数据渠道分工并完成接入：[SOURCE_INTEGRATION.md](SOURCE_INTEGRATION.md)。红队 profile 对 A/H 三表启用 AKShare 兜底；妙想公告/经营结构与富途资讯进入一次准备、各代理共用的来源材料，按报告期缓存付费结果。已有实测已导入缓存，未重新消耗积分。全套离线测试通过。

2026-11-08 用户已在正确账号完成官方订阅登录，`bash scripts/cloud.sh models` 实际返回模型清单，包括 `gpt-6.1-sol` 和 `gpt-6.1-terra`。深度模型已按用户纠正改为 `gpt-6.1-sol`，快速模型仍为 `gpt-6.1-terra`。凭据文件权限 0600，未显示或提交内容。三市场真实报告验证使用私有临时 profile 将妙想付费预算设为 0，复用缓存。

三市场完整报告现已生成：NVDA 分析日 2026-11-08，茅台和腾讯分析日 2026-11-09（上海跨日后启动）。主索引为 `reports/index.md`，正文和 HTML 均已核对归档。三份报告实际模型均为 `gpt-6.1-sol` / `gpt-6.1-terra`，补充材料的 `mcp_calls` 均为 0。完整报告生成不等于所有财务数值、口径和原始披露已核验。

用户要求统计单份报告 ChatGPT usage 后，已接入只保存计数的实时记录器，覆盖 graph 和最终 review，包含在成功报告及快照内。A/H 初次执行被 OpenAI 明确以 Subscription Sharing usage limit 中止；随后已从匹配断点第 6 步续跑完成，未重跑分析师和多空辩论。茅台原执行加续跑累计返回 739,890 token（输入 705,389，输出 34,501）；腾讯为 686,903（输入 651,652，输出 35,251），每份均有 42 次成功、2 次未返回 token 的失败调用。汇总在 `reports/chatgpt-usage-summary-2026-11-09.md` / `.json`，包含按模型拆分和原始计数文件校验和；单次成功报告内的 `usage.json` 只计本次续跑，不可单独当累计值。NVDA 记录器启用前仅保留分析师 28 次调用的 283,101 token 下限，完整总量不可追溯。接口 token 不能换算订阅额度百分比。

额度错误现会立即停止批次，不做自由文本备用调用，不切换 API key。`run --resume-only` 优先恢复原断点内的来源材料和缺口说明，严格核对标的、日期及完整配置签名；不匹配时不调用模型。本轮实际 profile 是 `.runtime/config/redteam-validation.yaml`（妙想预算 0），后续恢复须沿用同一配置并指定原分析日期。全套离线测试 1499 项、100 个子测试通过，1 项可选依赖跳过、1 项 deselected；Ruff 和 diff 格式检查通过。

登录排查曾复现 POSIX 终端 canonical 输入超过 4095 字符被截断的问题（虚构 6000 字符仅读到 4095）。已改为不回显、非 canonical 的可信终端输入，并以 7200 字符及 EOF 退出验证完整接收和终端恢复；OpenAI JWKS 可达。用户随后报告 `invalid_grant`，并确认该次登录选错账号；改用正确账号后登录和模型清单读取均成功。不能把终端截断单独归为这次真实错误的已证实原因。

新云环境已于 2026-11-08 完成公开数据实测，详情见 [本轮验收记录](CLOUD_VALIDATION_20261108.md) 和 [公开元数据 JSON](validation-2026-11-08-cloud.json)。三市场行情、A/H 三表和富途三类资讯读取通过；部分字段已核对原文，妙想已认证并完成下述小样本。ChatGPT 官方订阅登录及模型清单读取已成功；完整财务口径、iFinD 认证和长期数据权益仍未验收。

后续已增加 [补充源接入与验收计划](MCP_DATA_PLAN.md)：匿名探测时 iFinD 官方 A 股/港美股/EDB 地址到达 401 认证层，妙想到达 403 认证层；妙想现已在用户配置密钥后通过认证。`mcp-key` 支持可信终端隐藏录入，`mcp-probe` 仅列工具。字段原文核对见 [17 项样本](financial-samples-2026-11-08.json)，不能将腾讯汇总“回购股份”直接当作仅注销回购现金支付。ChatGPT 登录失败已有固定安全诊断。

用户已确认只有妙想账户，密钥已通过 `mcp-key --provider miaoxiang` 安全录入；`mcp-probe` 已取得 11 个工具，另完成 4 次只读数据调用。公告 PDF 和经营构成有增量，港股汇总仍忽略定向 CNY/期间要求，FCF/回购出现口径替换，因此未启用生产默认源。用户观察整轮减少 10.24 积分，本轮已停止扩量。详见 [妙想验收](MIAOXIANG_VALIDATION_20261108.md)。iFinD 保留候选，不要求用户先开新账户。

以下创建步骤保留用于以后重建环境。旧实例仅允许软件包和代码站点，不能扩大网络访问；用户实际修改时收到环境级限制。旧实例 10 个接口全部为代理 CONNECT 403，历史记录见 [validation-2026-11-08.json](validation-2026-11-08.json)，不要将它当成本轮环境的当前状态。

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

网络可达、认证成功、取到真实数据是三个不同状态。`probe` 只有在来源可达时才执行正式 yfinance 客户端价格、AKShare 当前三表和富途公开新闻/公告/研报的读取，并用子进程限制单项时长为 45 秒。普通 HTTP Yahoo 探测返回 429 不代表正式 yfinance 客户端也失败。`safety_guard_passed` 仅说明历史日期被拒绝，不能算实时财报验收通过。退出码 1 表示存在网络策略阻断，2 表示公开数据检查未通过；即使公开数据通过，币种/单位/期间口径、原始披露和 iFinD/妙想的认证工具与字段仍需单独验证。

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
3. 妙想已完成工具清单和 4 次统一小样本，结果见上方验收报告；接续时不要重复付费跑同一批。iFinD 未认证，待以后有账户时先列工具。费用需另与账户用量核对，`tools/list` 本身不证明扣费口径。
4. 富途默认账户 OAuth 暂不执行：所检查官方 CLI 的默认 scopes 含 `trade:read trade:write`。需先验证官方能否授予仅行情/资讯的权限。只读取行情不等于默认授权也只读。
5. ChatGPT 真实模型及三市场完整报告链已验证。后续先阅读累计用量和报告原文，继续核对财报口径与披露；不要为重新统计用量重复全图或妙想查询。额度中断可沿用原配置、原分析日加 `--resume-only` 恢复。

## 可粘贴到新对话的交接指令

> 继续 `sangy12/Investment-Review` 的基本面长期投资红队项目。先检出 `codex/fundamental-redteam-cloud-20261108` 并阅读 `docs/CLOUD_HANDOFF.md`、`docs/REDTEAM.md` 和 `docs/DATA_SOURCES.md`。先验证新云环境网络与 `bash scripts/cloud.sh probe`，然后协助我通过官方 ChatGPT 订阅 OAuth 登录，凭据不要进入聊天/Git。保留代理决策核心和完整报告，不接券商/交易权限。按文档继续实测 A/H 财报、富途公开资讯、iFinD 与妙想，不把网络可达或历史保护测试当作数据成功。不要默认执行富途 CLI 的宽权限 OAuth。
