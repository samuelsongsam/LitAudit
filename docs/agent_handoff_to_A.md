# B -> A 交接：工程骨架与离线流水线

- 交接方向：B -> A
- 本轮负责角色：B 产品与工程负责人
- 日期：2026-08-25
- 分支：`feat/b-eng-skeleton`

## 1. 本轮完成

1. 建立 `src/`、`tests/`、`data/fixtures/`、CLI 入口和依赖文件。
2. 按 `docs/data_contract.md` 实现 JSON/JSONL 读取与校验：缺字段、重复 ID、错误枚举、孤立外键、无证据的 `supported` 都会报错。
3. 实现离线 pipeline：读取数据 -> 生成 `run_id` -> 把校验后的对象和 `map.json` 写入 `runs/<run_id>/output/`。
4. 实现回放、文件缓存目录，以及漏斗 / 地图 / 证据卡 / 证伪报告四屏。
5. `null` 的 `authors` / `abstract` 原样保留；`exclude` 与 `pending` 及 `reason` / `reason_code` 都在漏斗页展示。

## 2. 对 A 三个问题的确认

1. **读取器是否接受 null 元数据并保留 pending？** 是。不会填充默认作者或摘要；没有核验过的论文保持 `pending`。
2. **能否同时展示 exclude 与 pending 及 reason/reason_code？** 是。漏斗表包含这三列，排除论文不会从输出里删掉。
3. **locator 是否支持 page/section/paragraph/url_anchor？** 是。另外按契约支持 `char_range`；至少要有其中一个，否则校验失败。

## 3. A 可以立即执行的命令

在仓库根目录、已安装 `requirements.txt` 的环境中：

```powershell
python -m src.cli doctor
python -m src.cli validate
python -m src.cli run --offline
python -m src.cli replay --list
python -m pytest -q
python -m src.cli ui
```

预期：`validate` 对 `data/` 报 0 个 error；离线 run 的 `stats.decision_counts` 为 include=0、exclude=2、pending=3；fixture 论文不计入 `paper_count`。

## 4. 输出位置

- 代码：`src/schema.py`、`src/pipeline.py`、`src/replay.py`、`src/ui/`
- 样例：`data/fixtures/`
- 一次 fixture 回放：`python -m src.cli run --fixture --run-id demo` 后查看 `runs/demo/`
- 本交接：`docs/agent_handoff_to_A.md`
- 演示步骤：`docs/demo_script.md`

## 5. B 没有改动的内容

- `docs/research_scope.md` 的主问题和纳排标准
- `data/papers.jsonl` / `data/screening_log.jsonl` 的判决
- 字段名称与枚举含义

## 6. 已知限制

- 未接入真实 arXiv / OpenAlex / Semantic Scholar。
- 没有 `paper_cards.jsonl`，地图没有主线和矛盾对。
- 真实数据还没有 Claim / Evidence / Falsification；对应页面显示空状态，而不是编造综述。
- 当前只允许离线模式；若传入在线开关会直接报错。

## 7. 请 A 下一步做的事

1. 补核验 `paper-001` 到 `paper-003` 的摘要/作者，决定 include 或继续 pending。
2. 产出 `data/paper_cards.jsonl`、`data/claims.jsonl`、`data/evidence.jsonl`。
3. 不要删除 `paper-004` / `paper-005` 的 exclude 记录。
4. 若要增加字段，先改 `docs/data_contract.md` 并告诉 B，不要只改 JSON。

## 8. 验收记录（B 自检）

- 真实 `data/` 可通过 schema 校验。
- fixture run 可回放，且 `paper_count=0`、`fixture_paper_count=1`。
- 无 `paper_id` 的引用、无 locator 的证据、无证据的 `supported` 会被拒绝。
