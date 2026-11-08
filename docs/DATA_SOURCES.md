# A 股／港股候选源比较（2026-11-08）

优先顺序为“免费可持续 + 长期基本面独特信息 + 云端可维护”，而不是重复购买多路相同日线。建议方向是：Yahoo/EDGAR 维持美股；A/H 保留可替换适配器，先用免费基础数据，再挑一家能提供增量公告/行业数据的增强源；富途优先考察港股特有数据。**尚未定默认源、没有注册/购买或登录富途，也没有把下述 MCP 当作已接通的生产源。**

## 证据强度

目前执行容器只开放代码与软件包域名，最新 10 项探测全部被平台代理 CONNECT 403 拦截；用户尝试修改后确认必须创建新环境。网页检索与官方 GitHub 读取另有结果，不能当作运行容器已连通。现已核实富途新版 CLI/公开资讯接口，并找到妙想积分计量的产品发布资料；当前免费额度、账号权益和真实取数仍未通过验收。

| 候选 | 免费性 | 已观察到的接入证据 | 对本项目的潜在增量 | 云端与时点约束 | 建议 |
|---|---|---|---|---|---|
| AKShare | 开源包可免费安装；上游接口限流/变更仍可能发生 | 本环境安装 1.20.35，并检查了 A/H 财报、日线、新闻和宏观函数源码/签名；网络实数未验收 | 免费基础报表、国内快讯和宏观 | Python 可 headless；当前报表缺少可靠 as-filed 历史版本，历史请求须拒绝 | 作为可替换基础/兜底候选，代码已实现，待选择后启用 |
| 同花顺 iFinD MCP | 当前 MCP 免费额度、是否需终端权益：待账户验证；传统 API 免费版不能直接外推为 MCP 免费 | 官方入口确认行情、财务、公告、宏观服务；社区镜像另列行业 EDB/事件等工具，需认证后 tools/list 验证 | 行业/产品经营指标、股东/事件数据、公告检索是优先测试项 | 远程接口适合云端；历史“报告期”不证明当时可知，需披露时间与原始版本 | 先验证免费权益及茅台经营数据，再决定是否值得加入 |
| 东方财富妙想 MCP | 2026-06-29 产品发布账号说明 MCP/Skill 纳入积分计量，并提供套餐包；当前赠送额度/单次成本待账户验证，不算长期不限量免费 | 产品资料描述 A/H/美股等财务、估值、股东、事件和宏观；远程 HTTP MCP 端点已定位，实际工具待认证验证 | 可作公告、财务与行业证据增强，是否多出独特字段需同题比较 | 远程 HTTP 可 headless；自然语言答复须回溯原文，不能直接当财报库 | 预算受控的小样本测试，先看额度与原文证据，再决定是否加入 |
| 富途 SkillHub | 公开资讯接口的官方示例不要求 API key，但无已验证的长期免费承诺；行情看账户权限 | 官方 Hub 现指向 Linux/macOS CLI，支持 `auth login --no-browser`；新闻/公告/研报有独立公开 HTTP 契约 | 港股公告/新闻/研报与社区信息，比重复日线更值得先测 | 不再必须 OpenD；官方安装指南仍提示 Codex Cloud 网络受限。当前 CLI 默认 scopes 含交易写权限，尚未证实只读账户授权方式 | 优先测无需账户的公开资讯；默认账户 OAuth 暂不执行，不带入交易权限 |

AKShare 的多个接口本身使用东方财富，因此 AKShare + 妙想不能天然算“两家独立来源”；应比较上游原始来源、公告编号和时间，而非 SDK/MCP 品牌数量。富途情绪/资讯也需要核实其原始新闻来源，不能因为换了入口就计作独立证据。

当前实测状态与新环境接续见 [CLOUD_HANDOFF.md](CLOUD_HANDOFF.md)。新增 `bash scripts/cloud.sh probe` 可重复探测；网络不可达、鉴权失败、无数据、历史保护通过均分开记录。当前没有任何来源被记为实时数据验收通过。

## 用同一问题集实测，控制成本

| 用例 | 需要返回 | 可以接受 | 不足以通过 |
|---|---|---|---|
| 贵州茅台最近两期收入/经营现金流/合同负债及销售结构 | 数值、币种/单位、期间、披露时间、公告链接 | 明确说明未覆盖某字段 | 只给自然语言结论或“最新值”，没有原文出处 |
| 腾讯最近两期收入/分部、自由现金流、资本开支、回购 | 统一期间口径、原始报表/公告链接，A/H 正确代码 | 字段不支持时明确不可用 | 将半年累计当独立季度、混合人民币与港币 |
| “什么情况会推翻投资逻辑”证据检索 | 检索到的原文片段、公开时间、URL | 不完整覆盖有明确提示 | 无结果就宣称没有风险 |
| 历史日期早于某次财报公布日 | 仅当时已公开的原始版本或 DATA_UNAVAILABLE | 无历史能力而诚实拒绝 | 用今天查到的重述值冒充历史原始值 |
| 云容器重启与会话续期 | headless 凭据注入、刷新机制、错误码/限流语义 | 首次用户 OAuth，此后无人值守 | 必须一直依赖用户本地主机或每次手工浏览器操作 |

免费权益测试仅列出工具/查少量样例，不自动购买。记录每工具单次消耗、每日/月额度、到期时间、港股权限、可否持久缓存原文、数据延迟。组合上限先控制为一个免费基础源 + 一家增量源 + 富途港股只读增强，避免重复维护三个完整数据栈。

## 接入决策的边界

现有 `dataflows` 以工具方法映射到 vendor。确定源后应新增独立 vendor，原有 EDGAR → Yahoo 顺序保留；对新闻/行业数据可用按市场的显式工具链。MCP 只允许固定的只读工具名，并保存来源、公开时间和原文链接。不能直接将任意第三方 agent/Skills 指令整体放入决策图，也不能暴露交易、资金、账户持仓或订单工具。

现在没有足够证据认定 iFinD、妙想或富途满足免费的长期使用及历史时点要求，所以没有写入猜测出来的生产认证、未核实字段映射或收费结论。也没有因为有富途账户而连接账户/交易接口。

## 来源

用户指定的官方入口（当前权益待核实）：

- [同花顺 iFinD MCP](https://mcp.51ifind.com/)
- [富途 SkillHub](https://www.futunn.com/skillhub)
- [东方财富妙想 MCP](https://choice.eastmoney.com/mcp/)

已读取的公开材料：

- [富途官方 SDK README](https://github.com/FutunnOpen/py-futu-api/blob/master/README.md)：可核实行情/交易 API 区分，不代表 SkillHub 权益。
- [iFinD skill 社区镜像](https://github.com/LeoYeAI/agent-master-skills/blob/8f88f9a0dd5a1075d4f0c7626f9d960844d57575/skills/ifind-finance-data/SKILL.md)：列出的财务、行业 EDB、新闻公告工具，仅作候选能力线索。
- [Chatbox 妙想 MCP 配置源码](https://github.com/chatboxai/chatbox/blob/d17455c5ca8fd3ff44385c6d4d2118599e4c970f/src/renderer/components/settings/mcp/CustomServersSection.tsx)：可观察 HTTP endpoint 与认证 header，不能证明免费额度。
- [富途 Skills 社区集成说明](https://github.com/BSTester/dsh-trading-agents/blob/7544cad1ab69d3cbbb9d7b522509c7351e3adb8a/skills/futu-skills/README.md)：仅作云端依赖和资讯局限的测试线索，其自述不能代替富途官方保证。
- AKShare 1.20.35 包源码：`stock/finance/stock_finance_hk_em.py`、`stock/finance/stock_three_report_em.py`、`stock/quote/stock_hist_em.py`、`stock/research/stock_news_stock.py`、`macro/macro_china.py`。
- [富途官方 Hub 安装指南](https://github.com/FutunnOpen/futu-agent-hub/blob/e9e0445e8c29bcd1375ed51db3e75a463c380fd4/docs/futu-install.md)：新版 CLI、Linux、headless OAuth 和 Codex Cloud 限制说明。
- [富途官方资讯接口](https://github.com/FutunnOpen/futu-agent-hub/blob/e9e0445e8c29bcd1375ed51db3e75a463c380fd4/skills/search-skills/futu-news-search/SKILL.md)：公开 GET 新闻/公告/研报契约，不代表已验证免费额度。
- [富途 CLI OAuth 默认 scopes](https://github.com/FutunnOpen/futu-cli/blob/58af97ce1e49565fa6c5989117fd4f5da3584588/internal/auth/oauth.go)：包含 `quote:read quote:write trade:read trade:write accid:*`，因此默认授权暂不执行。
- [妙想产品发布资料，2026-06-29](https://caifuhao.eastmoney.com/news/20260629073004808426910)：积分计量与套餐说明；历史活动不能代表今天的赠送额度。
- [同花顺传统 API 免费版权限说明](https://quantapi.51ifind.com/gwstatic/static/ds_web/quantapi-web/help-center/permission.html)：仅适用其对应产品，不能外推 MCP 当前权益。
