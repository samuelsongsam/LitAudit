# LitAudit 演示脚本（约 8–10 分钟）

目标：让评委看到可核验漏斗、研究地图、论断–证据卡和反证据，而不是一篇无法点回原文的综述。全程使用离线快照 `phase2-real`。

## 准备

```powershell
cd LitAudit
python -m src.cli doctor
python -m src.cli run --offline --run-id phase2-real
python -m src.cli evaluate
python -m src.cli ui --run-id phase2-real
```

浏览器打开 `http://127.0.0.1:8787/?run=phase2-real`。数字键 1–5 切换五个视图。

## 口播结构

1. **问题（30 秒）**  
   现有文献智能体优化流畅度和引用数量。研究者真正需要的是：这句话原文说过没有、谁该留下谁该扔掉、哪两条路线在打架、有没有能打脸的论文。

2. **输入（1 分钟）**  
   主问题写在顶栏：检索增强大模型智能体是否提高科学文献问答的证据可追溯性。说明这是本地关键词检索，不会编造论文，也不会写长综述。

3. **筛选漏斗（2 分钟）**  
   7 篇候选：PaperQA、SciMON 为 include；STORM、WebGPT、Toolformer 以及两篇风险论文为 exclude。打开筛选日志，指出历史 pending 记录仍在。点 Semantic Scholar `rate_limited` / HTTP 429，强调失败不能写成零结果成功。exclude 没有从界面消失。

4. **研究地图（2 分钟）**  
   三条主线：科学文献问答、相邻自动科研、任务边界。打开矛盾对：`claim-008` 上 paper-001 与 paper-006/007 冲突。说明边来自证据冲突和反证据命中，不是引用图谱。点 `paper-001`，`parse_status=pdf_partial_verified`，并读 parse_error：指定页已核验，不是 20 页逐页读完。

5. **证据卡（2 分钟）**  
   打开 `claim-001`（supported，verified 第 1 页）和 `claim-008`（pending，正反证据同时可见）。强调没有 Evidence 不能 supported；冲突必须 pending。

6. **证伪报告（1.5 分钟）**  
   `hit-001`、`hit-002` 来自 exclude 论文。威胁是 overlap 不是 fatal，因为任务是通用 RAG/QA。这就是「杀手论文」模块：系统强制保留能削弱强断言的证据。

7. **评测对照（1 分钟）**  
   打开评测页：相对无检索代理，locator / verified / 反证据覆盖率从 0 变成可计算差值。当场说清楚：这不是准确率，也不能当因果结论。

8. **收束（30 秒）**  
   产品输出是漏斗、地图、证据卡、反证据报告。主问题的普遍优越性主张保持 pending。

## 禁止口误

- 不要说「已经证明 RAG 全面更好」
- 不要把 `pdf_partial_verified` 说成全文审阅完毕
- 不要把 429 说成没检索到
- 不要把 fixture 算进真实统计
