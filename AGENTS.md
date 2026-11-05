# LitAudit — Agent Instructions

## 项目简介

LitAudit 是一个可核验的文献调研智能体，支持 arXiv / OpenAlex 在线检索、摘要筛选、证据核验与反证据报告。

## 快速启动

```bash
# 安装依赖
pip install -e ".[dev,map]"
python -m src.cli download-model

# 跑测试
python -m pytest -q

# 启动 UI（在线模式）
python -m src.cli ui --run-id phase2-real
```

## Cursor Cloud specific instructions

> Cloud Agent 必读：以下内容描述云端运行时的特殊要求。

### 环境变量（Secrets）

以下变量必须在 Cursor Dashboard → Cloud Agents → Secrets 中配置，
**不要**写进代码或提交到 git：

| 变量名 | 说明 |
|--------|------|
| `LITAUDIT_LLM_API_KEY` | LLM 密钥（DeepSeek 或 OpenAI 兼容） |
| `LITAUDIT_LLM_BASE_URL` | 如 `https://api.deepseek.com/v1` |
| `LITAUDIT_LLM_MODEL` | 如 `deepseek-chat` |
| `OPENALEX_MAILTO` | 可选，联系邮箱 |
| `OPENALEX_API_KEY` | 可选，使用 OpenAlex 账户的检索额度 |

### 验证 Secrets 已注入

```bash
python -c "from src.config import load_settings; s=load_settings(); print('LLM key:', 'ok' if s.llm_api_key else 'MISSING')"
```

### 运行测试

```bash
python -m pytest -q
```

所有测试应通过。若有失败，检查 `runs/` 目录是否缺少 `phase2-real` 数据，并运行 `python -m src.cli download-model` 确认 SPECTER2 已缓存。

### 在线检索说明

- arXiv 可公开检索。OpenAlex 支持匿名检索，也可配置 API Key 使用账户额度
- 检索结果写入 `runs/live_*/`，不覆盖 `runs/phase2-real/`

### 不要做的事

- 不要把 `.env` 或任何密钥提交到 git
- 不要修改 `runs/phase2-real/` 下的金标数据
- 不要删除 `data/` 目录下的金标数据集
