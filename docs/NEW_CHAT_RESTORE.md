# 新对话接续与私有备份

代码保存到 Git 分支 `codex/fundamental-redteam-cloud-20261108`。新对话选择同一仓库及已发布云环境，先检出该分支并阅读 `docs/CLOUD_HANDOFF.md`。新任务可能从发布快照启动，不保证继承本对话实例的 `.runtime/` 或 `reports/`。

本轮迁移备份放在仓库之外的 `/workspace/investment-review-backups/`；解密密钥单独放在 `/workspace/.investment-review-backup-keys/`，均只允许当前用户访问。文件名和校验信息以该目录中本次 `README.md` / `SHA256SUMS` 为准。代码 Git bundle 可以离线克隆；私有备份使用 AES-256-GCM 认证加密，覆盖报告、MiniMax 原始投资逻辑、运行配置、缓存、研究记忆及受保护登录文件，带逐文件 SHA-256 清单。

必须将加密备份与密钥分别安全下载保存。只在当前实例创建文件，不等于新对话已能访问它们。不要把解密密钥、OAuth JSON、回调地址或妙想 key 贴入聊天、Git 或公开文件；密钥不要和加密包一起公开分发。未备份虚拟环境，可按项目安装步骤重建；私有包中保留软件包版本清单。

## 恢复研究资料

先克隆代码并安装依赖，再把加密包和密钥通过可信文件通道放到目标机器，运行（路径替换成本机实际位置）：

```bash
.venv/bin/python scripts/restore_private_backup.py /secure/private-state.aesgcm \
  --key-file /secure/private-state.key --destination /workspace/Investment-Review
```

工具先验证加密与逐文件校验和，再恢复到受 Git 忽略的 `.runtime/` 和 `reports/`。默认跳过认证目录、不覆盖已有文件；只有用户明确添加 `--overwrite` 才覆盖。可先加 `--verify-only` 验证而不写入。

## 单独迁移认证

优先在新实例独立登录。确需迁移同一订阅登录时，先停止旧实例的登录刷新和研究任务，再在可信终端加 `--with-auth` 恢复凭据种子。ChatGPT JSON 会保存为 `.runtime/auth/imported-chatgpt-auth.json`，不直接复活旧主机身份。使用官方项目引导导入：

```bash
TRADINGAGENTS_CHATGPT_AUTH_SOURCE=/workspace/Investment-Review/.runtime/auth/imported-chatgpt-auth.json \
  bash scripts/cloud.sh models
```

引导会保留目标机器自身稳定 host ID 和已轮换凭据优先级。备份是时间点副本，后续源端若刷新了令牌，旧副本可能失效；不要让不共享锁的多个云实例同时刷新同一个 refresh token。妙想 key 作为私有文件恢复，不进入代码。

## MiniMax 接续

个人持有逻辑在 `.runtime/minimax/watchlist.yaml`；当前后续运行配置在 `.runtime/minimax/redteam.yaml`，模型为快速 `gpt-6.1-sol/high`、深度 `gpt-6.1-sol/max`，妙想预算为0。此前实际执行配置另存 `redteam.executed-20261110.yaml`。保留报告中原执行设置，不把新模型配置改写为旧报告的运行记录。

可给新对话的指令：

> 继续 Investment-Review 基本面红队项目。检出 codex/fundamental-redteam-cloud-20261108，先读 docs/CLOUD_HANDOFF.md 与 docs/NEW_CHAT_RESTORE.md。核对备份是否已恢复；凭据只走可信文件/终端，不进入聊天或 Git，不接交易接口。沿用快速 Sol 6.1/high、深度 Sol 6.1/max。MiniMax 的个人逻辑从私有 watchlist 读取，先看已完成报告和专项核查，不重复消耗模型或妙想用量。
