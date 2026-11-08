# TradingAgents 基本面长期投资红队

本项目在 v0.7.1 上增加独立的消费层。四分析师、多空辩论、研究经理、交易员、风控三辩手与组合经理的节点、提示词和决策顺序保持原样；仅宏观工具说明补充了中国指标名称。完整正文保留，评级沿用五档。模型的不稳定性、数据缺口和证据不足都应在阅读时保留；收益回测不作为本项目验收标准。

基线工作区 HEAD 为 `9fa1196fffbcfd9de5146d2dd2869df84ab99838`；已核对它与上游 v0.7.1 (`c4544913a14ed3df5f1ed7b9e8483270ce20682a`) 在 `tradingagents/`、`cli/` 和 `pyproject.toml` 上没有代码差异。

## 安装与运行

Python 3.11+；云端镜像使用 3.13，当前开发环境为 3.12。在仓库根目录：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,china]'
export TZ=Asia/Shanghai
tradingagents login chatgpt
ta-watchlist models
ta-watchlist run --only NVDA
ta-watchlist run --date 2026-11-08
ta-watchlist run --skip-unchanged
ta-watchlist compare NVDA
```

清单在 `watchlist.yaml`，配置在 `config/redteam.yaml`，均可用 `--watchlist` / `--config` 覆盖；`run` 和 `compare` 均支持 `--reports`。`market` 支持 `US`、`A_SHARE`、`HK`；香港四、五位数字代码会转换成数据源要求的五位格式。清单不包含数量、成本或现金，不应将它当作真实组合仓位。个人 `thesis` 只进入报告结束后的对照层，不进入代理决策图。

`--skip-unchanged` 的定义为：该标的最近一次不晚于分析日的成功运行具有相同分析日、标的配置、个人论点、模型和运行配置。它是重复任务去重，**不会检查远端行情、公告或新闻是否更新**；需要刷新数据时去掉该选项。不同日期仍会重跑。单个标的失败后继续其他标的，进程最终返回非零退出码。

## 模型与登录

两层 provider 均固定为 `chatgpt`，不自动降级到 API 付费方式。深度层仅用于原有两个经理，快速层供其余原有角色；消费层额外使用快速层模型做一次结构化摘要与逐条核对。

默认请求：深度 `gpt-6-sol`、快速 `gpt-6.1-terra`、推理 `high`、辩论各两轮、工具上限 20、中文输出，内部辩论仍为英文。注意：v0.7.1 官方快速默认实际为 `gpt-6-luna`，本项目的 Terra 是用户指定值。

登录后以 `ta-watchlist models` 返回的实际套餐清单为准。运行会先核对两个型号是否可用；若不可用，先从清单中选定推理能力最强的深度型号、较快且能力强的快速型号，修改 YAML 并在相邻注释记录替换原因。尚无凭据时无法知道套餐可用型号，不能声称已替换或已测试。当前实现不会推测陌生型号的性能排行并静默替换。

环境变量覆盖 YAML，遵循 `TRADINGAGENTS_*`：例如 `TRADINGAGENTS_DEEP_THINK_LLM`、`TRADINGAGENTS_OPENAI_REASONING_EFFORT`、`TRADINGAGENTS_MAX_RISK_DISCUSS_ROUNDS`。原有 `TRADINGAGENTS_MAX_RISK_ROUNDS` 仍兼容，规范全名优先。订阅 profile 不含 `temperature` / `max_tokens`；如果环境变量或 YAML 配置了它们，会明确拒绝启动。

`SEC_EDGAR_USER_AGENT` 需设置为真实的应用名和联系邮箱。Yahoo 免 key；FRED key 可选，缺失时宏观工具明确返回不可用。

## 报告与对照

```text
reports/
  index.md
  last_batch.json
  NVDA/
    2026-11-08.md
    2026-11-08/
      complete_report.html
      snapshot.json
    runs/<运行ID>/
      complete_report.md       # 摘要 + 完整原文
      complete_report.html
      original_report.md       # 原生合并 Markdown，不含新增摘要
      snapshot.json
      1_analysts/ ... 5_portfolio/
    failed/<运行ID>/            # 图已完成但链校验/摘要失败时，保留原始报告
```

日期路径指向该日最新成功运行，同日重复运行保存在不同的 `runs/` 目录。失败不会覆盖上次成功报告；索引状态会提醒已有报告可能较旧。删除清单标的会移除索引行，历史研究文件保留。一次只能有一个批处理写同一报告根目录。

每份合并报告先显示评级、Investment Thesis 支撑证据、风险清单、与上次运行的变化，再显示完整原文。摘要有原文逐字引文和来源文件；不匹配原文的引用会被剔除。模型引用正确不等于推论必然正确，仍须核对原始公告/财报。

`compare` 不再次调用模型，读取最近一次成功分析日及该次保存的前次基准。评级轨迹包含每个运行 ID。历史日期补跑不读取其分析日之后的报告。失效条件仅提取自原报告 PM 的 Investment Thesis 中明确给出的条件，缺失时显示“无核对基准”。逐条状态为：触发、未触发、证据不足；后两者不会混为一谈。证据引用缺失/不合法时强制改为证据不足。

变量以名称匹配并保留期间、币种和单位，不自动计算不可比口径的增减。新增风险按原文字符串比较，措辞改写可能被列为新增，摘要会注明这一限制。首份报告没有上次基准。

## A 股／港股数据

候选源比较见 [DATA_SOURCES.md](DATA_SOURCES.md)。AKShare 是已实现但默认不启用的候选适配器。选择它时，取消 `config/redteam.yaml` 中 `china_data_vendors` 的注释。仅 A/H 标的会使用该配置，美股继续原链：

```yaml
china_data_vendors:
  core_stock_apis: yfinance,akshare
  fundamental_data: sec_edgar,yfinance,akshare
  news_data: akshare,yfinance
  macro_data: akshare
```

适配器支持 A/H 不复权日线、三张报表与公司资料，A 股新闻、国内财经快讯，以及 CPI/GDP/LPR。`china_cpi`、`china_gdp`、`china_lpr` 显式命名，不能将美联储利率悄悄替换为中国 LPR。AKShare 失败使用原有 vendor 异常体系，链顺序不变。历史财报/资料、修订宏观值在请求前返回 `DATA_UNAVAILABLE`，不把当前值倒填。报告期结束日不等于披露日，有披露日期也不等于具备原始历史版本。

已知边界：港股个股新闻不能复用 A 股数字搜索接口，以免串股，当前回退 Yahoo；港股“报告期”可能是中期/年度，不能当独立季度数据；保留源单位与币种字段。技术指标与 verified market snapshot 仍沿用上游 Yahoo 实现，Yahoo 不可用时不会伪造技术值。国内社区情绪和北向/融资融券增强尚未实现；原有 StockTwits/Reddit 缺口应如实披露。

## 云端，无浏览器执行

初次 OAuth 授权需要用户在浏览器登录；**分析容器自身不需要浏览器**。官方 `tradingagents login chatgpt` 支持在远程终端粘贴回调地址，也可在可信环境完成官方登录后，将其完整登录 JSON 通过云平台 secret file 注入。不要把凭据粘贴到聊天或提交 Git。

```bash
docker build -f Dockerfile.redteam -t tradingagents-redteam:dev .
# managed Cloud 构建加：--secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt
mkdir -p reports
export CHATGPT_AUTH_SOURCE=/secure/path/chatgpt-auth.json
export SEC_EDGAR_USER_AGENT='YourResearch your-real-email@example.com'
docker compose -f compose.redteam.yaml run --rm redteam run --only NVDA
docker compose -f compose.redteam.yaml run --rm redteam compare NVDA
```

镜像以非 root 用户运行。主机 `reports` 目录须允许容器 appuser UID 写入；用本机 UID/GID 或正确属主配置，勿将凭据目录开放给所有人。首次注入的只读 secret 通过 `TRADINGAGENTS_CHATGPT_AUTH_SOURCE` 引导到持久化可写 auth volume，文件权限 0600；之后以 volume 中已轮换的 refresh token 为准，不用旧 secret 覆盖。不要复制同一个 refresh token 给多个彼此不共享锁的运行实例；应在目标云端完成独立登录，并仅在这个实例持续刷新。清单和配置只读挂载；缓存、官方研究记忆和检查点在持久卷中。

managed Cloud 运行时另需挂载可信 CA bundle，并为 requests / OpenAI SDK / curl 客户端设置对应的信任变量（`REQUESTS_CA_BUNDLE`、`SSL_CERT_FILE`、`CURL_CA_BUNDLE`），保持平台代理变量；构建阶段的 CA 不保留在镜像。Compose 不绕过平台网络策略。

## 验收与当前阻塞

已提供隔离测试：清单增删/筛选/空表、重复去重、同日评级变化、逐条失效核对、证据校验、历史补跑不读未来快照、单标的失败继续、凭据轮换不覆盖、A/H 代码转换、历史财报请求前阻断、行情/新闻未来行过滤、EDGAR → Yahoo → AKShare 降级。

```bash
pytest -q
ruff check tradingagents/watchlist tradingagents/dataflows/vendors/akshare.py tests/test_watchlist_redteam.py tests/test_akshare_redteam.py
```

这些测试使用确定性图/数据替身，**不代表 NVDA、茅台、腾讯已经通过真实数据与真实订阅验收**。实网验收需完成：

1. 在云环境网络设置放行 OpenAI 登录与模型站点，以及选用的数据源站点。
2. 通过 secret file 注入官方登录文件；`ta-watchlist models` 验证实际套餐模型并按需注释替换。
3. 决定 A/H 数据源组合并开通相应只读数据权限；如选择 AKShare，启用上述配置。
4. 对 NVDA、600519.SS、0700.HK 当天各跑一次，确认数据来源和完整报告；再用历史日期核对不可用标记。

基础域名清单：`auth.openai.com`、`api.openai.com`、`query1.finance.yahoo.com`、`query2.finance.yahoo.com`、`fc.yahoo.com`、`www.sec.gov`、`data.sec.gov`；可选 `api.stlouisfed.org`、`api.stocktwits.com`、`www.reddit.com`。AKShare 当前函数涉及 `emweb.securities.eastmoney.com`、`datacenter.eastmoney.com`、`datacenter-web.eastmoney.com`、`push2his.eastmoney.com`、`push2.eastmoney.com`、`search-api-web.eastmoney.com`、`np-weblist.eastmoney.com`。实际重定向/供应商变更须按失败证据补充，不能保证清单永久完整。

本项目没有接入真实券商、下单或解锁交易接口。既有框架中的交易员输出仅作为完整研究报告保存。
