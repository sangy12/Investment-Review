# 免费补充源复核（2026-11-10）

后续：用户已采纳并完成接入，见 [接入与验收](FREE_SOURCE_INTEGRATION.md)。以下为接入前的候选小样本记录。

本次只读查询没有调用妙想付费工具、真实模型、账户或交易接口。原始安全元数据：[source-options-2026-11-10.json](source-options-2026-11-10.json)。下列为候选能力及小样本，不代表已经进入报告生产链。

| 缺口 | 已有渠道与本次实测 | 推荐方向 |
|---|---|---|
| 美国宏观 | 妙想工具清单有 mx_macro_data，尚未实测美国指标。已安装 AKShare 有美国宏观方法，部分上游为金十，尚未逐项验收。FRED 官方公开 CSV 不带 key 请求成功，ZIP 内 monthly.csv 含 CPIAUCSL、UNRATE，daily.csv 含 DGS10，均有数值 | 当前快照优先官方 FRED 下载；有需要再注册免费 API key，用于规范接口和历史 vintage |
| 富途社区 | 官方 futu-comment-sentiment 文档描述实时社区检索。本次 stock_feed 腾讯关键词公开 GET 返回 HTTP 200、code=0、3 条结果，没有账户授权 | 可补充港股社区样本，与新闻分开；先验标的、时间、正文、去重，再分类情绪 |
| 美股盈利预测 | 当前 yfinance 的 NVDA get_earnings_estimate 返回 4 行，期间 0q/+1q/0y/+1y，字段含 avg/low/high/numberOfAnalysts/currency/methodology | 扩展当前 Yahoo 适配器；营收预测另有 get_revenue_estimate，不能把 forwardPE 当盈利预测分布 |
| A 股盈利预测 | 当前 AKShare stock_profit_forecast_ths 对 600519 返回 3 行，字段年度、预测机构数、最小值、均值、最大值、行业平均数 | 同花顺作为免费入口；东方财富 stock_profit_forecast_em 另有预测接口，未在本次重复拉全市场 |
| 港股盈利预测 | 当前 AKShare stock_hk_profit_forecast_et 对 00700 的综合盈利预测返回 3 行，含财政年度、纯利/亏损、每股盈利、派息、资产净值、最高最低 | 经济通作为免费入口；币种、机构覆盖和更新时间仍须逐字段核验 |

注意：FRED 下载返回的是当前修订序列，观察期不等于发布日期，不能回填成历史当时已知值；服务器还返回了比请求窗口更宽的历史，适配器必须自行筛选。富途的看多/看空分类为后续处理，不是本次接口已经返回的可信百分比；长期免费政策、限额和历史档案未验收。盈利预测快照的抓取时间也不等于预测形成时间，需保留财年、币种、GAAP/调整口径、机构数与形成/更新日期的 UNKNOWN；不冒称专业数据库的历史一致预期。

其他免费官方宏观渠道：BLS API v1 无需注册，可取 CPI、就业；Fed H.15 发布利率下载；BEA 公开表格可下载 GDP/PCE，API 可免费注册 key。

来源：

- [FRED 官方导出说明](https://fred.stlouisfed.org/help/data/downloading/using-the-download-data-link/)
- [BLS 开发者说明](https://www.bls.gov/developers/home.htm)
- [Fed H.15 下载](https://www.federalreserve.gov/datadownload/Choose.aspx?rel=H15)
- [BEA 开发者说明](https://www.bea.gov/resources/for-developers)
- [富途官方社区情绪说明](https://github.com/FutunnOpen/futu-agent-hub/blob/main/skills/search-skills/futu-comment-sentiment/SKILL.md)
- [yfinance 预测接口](https://ranaroussi.github.io/yfinance/reference/yfinance.analysis.html)
- [AKShare 官方研报预测入口](https://akshare.akfamily.xyz/data/stock/stock.html)
