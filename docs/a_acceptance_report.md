# [历史版本] A 对 B 第一轮工程骨架验收

> 本文件是之前的工程骨架验收。当前交付请以 `docs/current_delivery_report.md` 为准。

## 验收日期
2026-08-26

## 验收结论
通过基础验收。B 的离线数据契约、流水线、回放和四屏 UI 可以接续开发；真实检索和真实证据链尚未接入。

## 已验证项目
- pytest -q：10 passed。
- src.cli doctor：ok=true，error_count=0。
- src.cli validate：JSON/JSONL 读取成功，issues=[]。
- src.cli run --offline --run-id acceptance-data：成功生成真实数据离线 run。
- src.cli run --fixture --run-id demo 与 src.cli replay demo：成功，fixture 不计入真实论文统计。
- null authors/abstract 保留；pending/exclude 和理由保留。
- 修复后，坏行 schema_error 不会被覆盖；doctor 在错误时返回非零码。

## 未验收范围
- 在线 arXiv/OpenAlex/Semantic Scholar 检索。
- 真实 PaperCard、Claim、Evidence、FalsificationHit 内容。
- 研究地图主线、引用边和矛盾对。
- 真实端到端 UI 研究结论。
