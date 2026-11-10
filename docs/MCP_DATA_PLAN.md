# A/H 补充数据源：接入与验收

更新于 2026-11-08。用户确认目前只有东方财富妙想账户，因此先验证妙想，iFinD 保留为未来候选，不要求先注册或购买。基础层继续使用 Yahoo 行情、AKShare 财报和发行人/交易所原文核对，富途提供港股公开资讯。先将妙想与已有基础层及下文原文样本比较；尚未选择付费套餐或启用生产默认源。

**妙想最新状态：已认证并完成 4 次数据调用，11 个工具可列出。** 公告与经营结构补充有价值，港股汇总的原币/期间约束及 FCF/回购定义尚未通过。用户观察本轮减少 10.24 积分，不能视为固定单价。详情见 [本轮妙想验收](MIAOXIANG_VALIDATION_20261108.md)。下方匿名探测与缺 key 描述保留为前一阶段记录。

用户已采纳渠道分工；当前限定的来源材料接入、缓存和预览命令见 [SOURCE_INTEGRATION.md](SOURCE_INTEGRATION.md)。原始通用财务汇总不作为自动统一口径的数据来源。

## 候选能力与后续比较依据

- 已从官方页面发布的配置生成器确认独立 A 股、港美股、EDB、新闻公告服务。港股使用 `global-stock`，不套用 A 股接口。
- 官方港美股文档列出 `global_stock_financial`、`global_stock_events`，A 股列出 `get_stock_financials`、`get_stock_events`，EDB 列出 `search_edb`、`get_edb_data`。以上为公开文档能力，仍须认证后的 `tools/list` 与实际字段核验。
- 希望它补充的是经营/行业指标、股东与公司事件、公告证据；重复日线的增量有限。AKShare 财报当前来自东方财富，妙想也属于东方财富体系，二者不应仅按品牌数量计为两份独立证据。
- iFinD 官方已有个人套餐及 2026-09-23 调价说明；试用和付费权益需以当前账户为准。妙想 MCP 使用积分体系，2026-06 的赠送活动不是今天仍有效或永久免费承诺。

## 目前究竟卡在哪

本轮匿名 POST `tools/list`：iFinD A 股/港美股/EDB 真实 MCP 地址均返回 HTTP 401，妙想返回 HTTP 403。先前妙想响应正文明确要求密钥。记录在 `reports/validation/mcp-anonymous.json`，公开摘要另存于 [MCP 实测记录](mcp-discovery-2026-11-08.json)。这是待认证状态，不能据此判定没有相关数据。

新命令 `mcp-probe` 在缺密钥时返回 `missing_credential`，不会发认证请求。提供凭据后仅执行必要的协议初始化及 `tools/list`，不执行任何 `tools/call`，不把发现的工具自动暴露给研究代理，也不宣称这些元数据请求免费。支持 JSON/SSE、有限分页、超时和响应大小限制；报告不保存认证头、会话 ID 或原始错误正文。

## 安全录入与探测

用户在可信云端终端输入密钥，隐藏输入且不回显。不要在聊天或命令参数中提供真实值。

```bash
cd /workspace/Investment-Review
bash scripts/cloud.sh mcp-key --provider ifind
bash scripts/cloud.sh mcp-probe --provider ifind-stock
bash scripts/cloud.sh mcp-probe --provider ifind-global
bash scripts/cloud.sh mcp-probe --provider ifind-edb
bash scripts/cloud.sh mcp-probe --provider ifind-news
```

iFinD：在 [官方门户](https://mcp.51ifind.com/) 登录，进入“个人中心 → 密钥/MCP”。录入官方生成配置中 **Authorization 对应的值**，不要粘贴整份 JSON。按官方原值发送，不自行添加 `Bearer`。

妙想：在 [官方门户](https://choice.eastmoney.com/mcp/) 获取本人 API key，然后运行：

```bash
bash scripts/cloud.sh mcp-key --provider miaoxiang
bash scripts/cloud.sh mcp-probe --provider miaoxiang
```

文件分别是 `.runtime/auth/ifind-mcp.key`、`.runtime/auth/miaoxiang.key`，权限 0600，目录 0700，Git/Docker 均排除。也可使用安全环境变量 `IFIND_MCP_AUTHORIZATION` / `EM_API_KEY`，或对应的 `_FILE` 变量指定 secret file。优先级：环境值 → 显式 secret file → 本地私有文件。已有错误环境值会优先于新录入文件，应在安全设置中修正。未申请/读取 Codex 内部凭据。

所有探测只访问固定官方地址：

| 服务 | 地址 | 认证头 |
|---|---|---|
| iFinD A 股 | `https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp` | `Authorization` |
| iFinD 港美股 | `https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-global-stock-mcp` | `Authorization` |
| iFinD 行业经济 | `https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-edb-mcp` | `Authorization` |
| iFinD 新闻公告 | `https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-news-mcp` | `Authorization` |
| 妙想 | `https://mxapi.eastmoney.com/mxds/mcp` | `em_api_key` |

## 拿到工具清单后的统一小样本

先核对账户可用额度、到期日、单工具扣费及港股权限，再选择确切只读工具名和参数；不能将未知收费工具自动加入整条代理链。输出必须有期间、币种、单位、披露时间、原文链接，缺失项明确列为未知。

| 样本 | iFinD/妙想均需回答 | 与免费基础源的增量 |
|---|---|---|
| 茅台最新两期 | 收入、经营现金流、合同负债、直销/批发及产品结构，附原文 | 是否能直接补齐经营拆分和行业信息，而非重复三表 |
| 腾讯最新两期 | 分部收入、FCF、资本开支、回购，附定义和原文 | FCF/资本开支定义、港币交易对价与人民币现金流、注销回购与员工激励购股分别核对 |
| 风险证据 | 指定原文风险片段、公开时间、URL | 原始证据可追溯性，不用“无结果”代替“无风险” |
| 历史时点 | 披露前不可用、原始版本与重述值区分 | 没有 as-filed 能力时须诚实拒绝 |

## 原文核对已发现的边界

[字段样本记录](financial-samples-2026-11-08.json) 包含 17 项比对：16 项数值/单位/期间对应，1 项映射不一致。它是定日期样本，不是对所有公司、期间和字段的通用认证。

- 茅台最近两期的营业收入、营业总收入、现金流、资产、合同负债共 10 项与原文数值一致，三表货币单位为人民币元；利润与现金流为年初至期末累计，资产负债表为时点。经营结构另表使用万元，不可沿用三表单位。
- 腾讯 2026 中期部分金额与发行人人民币百万元表格相差 1,000,000 倍，而每股盈利按元/股，不能对所有 `AMOUNT` 统一缩放。
- 腾讯中期原文总收入为 401,243 百万元，与源表“营运收入”对应。“营业额”396,431 百万元不含 4,812 百万元 Others，不能直接改名总收入。
- 源表“回购股份”为 24,194 百万元，原文回购现金支付为 22,257 百万元，员工激励购股另列 1,937 百万元，两项合计恰好为 24,194。这个源字段不能直接当作仅针对注销回购的现金支付；回购交易对价中的港币金额也不能直接混入人民币现金流。

这些问题说明补充源需要验证字段语义及原文来源。返回更多字段或更流畅的自然语言，不足以通过验收。生产适配器保留原字段，并提示累计期间及字段标签差异，未自动填入本轮样本推导出的通用币种/单位。

## ChatGPT 登录并行接续

`127.0.0.1` 回调需粘回运行同一登录流程的云终端。此前的通用失败提示无法判别原因；现已补上固定安全诊断码、HTTP 状态和标准 OAuth 错误，回调输入改为隐藏。重新运行 `bash scripts/cloud.sh login` 后如仍失败，只反馈诊断码即可，不发送回调、密码或 token。真实失败原因须由新流程的诊断确定，当前不能宣称订阅登录修复成功。

## 官方材料

- [iFinD 官方门户与文档](https://mcp.51ifind.com/)；本轮其公开 JS 配置生成器和文档模块均已从官方 CDN 实际读取，保存于 Git 排除的 `reports/validation/provider-docs/`。
- [妙想官方接入文档](https://mxapi.eastmoney.com/mxds/doc/mcp-install.md)：核实 URL、Streamable HTTP 及认证头，未照其中示例输出任何真实凭据。
- [茅台三季报原文](https://static.cninfo.com.cn/finalpage/2026-10-31/1225649896.PDF)、[半年报原文](https://static.cninfo.com.cn/finalpage/2026-08-15/1225475868.PDF)。
- [腾讯中期报告原文](https://www.tencent.com/wp-content/uploads/2026/08/E700_IR.pdf)、[第二季业绩公告](https://www.tencent.com/wp-content/uploads/2026/08/Tencent-Announces-2026-Second-Quarter-Results.pdf)。已在本云端下载、提取文本并记录 SHA-256，不将网页检索可达代替云端可达。
