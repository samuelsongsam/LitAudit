# LitAudit

可核验的文献调研智能体。输入一个科研问题或 idea，输出筛选漏斗、研究地图、论断-证据卡和反证据报告，而不是一篇无法回溯的长综述。

当前仓库处于 **A 摘要级证据 + B 第二轮接入**：pipeline 读取 papers 主索引、paper_cards、claim_decisions 和 retrieval_runs；四屏展示漏斗、摘要级主线、论断-证据卡和反证据。在线 API 不由 B pipeline 自动调用，摘要级证据不会伪装成全文核验。

## 快速开始

Python ≥ 3.10。在仓库根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.cli doctor
python -m src.cli validate
python -m src.cli run --offline
python -m src.cli replay --list
python -m src.cli ui
```

离线样例（不混入真实论文统计）：

```powershell
python -m src.cli run --fixture --run-id demo
python -m src.cli replay demo
python -m src.cli ui --run-id demo
```

测试：

```powershell
python -m pytest -q
```

## 角色边界

| 角色 | 负责 |
|---|---|
| A 研究与可信度 | 研究范围、检索/筛选、论断、证据、反证据规则、指标 |
| B 产品与工程 | 数据契约落地、流水线、缓存/回放、四屏 UI、README |

B 不改变 `decision` / `status` 语义，不填充 `null` 作者或摘要，不把缺失证据写成确定结论。

## 目录

```text
data/                 A 的真实候选与筛选日志
data/cache/           实际检索来源的原始响应缓存
data/paper_cards.jsonl A 的摘要级论文卡片
data/claims.jsonl     A 的 Claim
data/evidence.jsonl   A 的摘要级 Evidence
data/falsification.jsonl A 的反证据命中
data/fixtures/        虚构 schema 样例，不计入真实统计
src/schema.py         字段校验
src/pipeline.py       离线读取 -> run_id -> JSON 落盘
src/replay.py         回放已有 run
src/ui/               漏斗 / 地图 / 证据卡 / 证伪报告
runs/<run_id>/        一次可回放运行
docs/                 范围、契约、交接
```

## 当前数据状态（A 摘要级核验）

- 主问题见 `docs/research_scope.md`
- 7 篇候选：2 include，5 exclude，0 pending
- 8 条 Claim、10 条摘要级 Evidence、2 条 FalsificationHit
- paper_cards.jsonl 已有 7 张摘要级卡片；全文页码级证据尚未完成
- claim-008 因正反摘要证据冲突保持 pending

## 已知限制

- B pipeline 只支持 --offline / --fixture；在线检索结果需先由 A 保存为缓存和结构化数据。
- 研究地图已接入 paper_cards.jsonl 的 task/method 主线候选；关系边仍为空，不推断引用。
- Evidence 目前全部为 abstract_only；不能当作全文页码级证据。
- Semantic Scholar 批量请求曾返回 HTTP 429；OpenAlex 部分 external ID 查询仍需修正。
