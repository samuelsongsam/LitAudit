# 提交清单

截止日期：2026-09-15 23:59  
提交邮箱：ai2026agent@163.com

## 材料

- [ ] 技术文档 PDF：由 `docs/contest_technical_report.md` 导出，文件名建议 `勘文-LitAudit-技术文档.pdf`
- [ ] 演示视频 ≤ 10 分钟：按 `docs/demo_script.md` 录制离线 UI，文件名建议 `勘文-LitAudit-演示.mp4`
- [ ] 代码 ZIP：仓库根目录打包，排除 `.venv/`、`.env`、`__pycache__/`、未跟踪密钥

## 打包前检查

```powershell
python -m src.cli doctor
python -m src.cli validate
python -m pytest -q
python -m src.cli evaluate
```

确认：

- [ ] `.env` 和 API 密钥未进入 ZIP
- [ ] `data/fixtures/` 不被口播成真实论文
- [ ] `claim-008` 仍为 pending
- [ ] 界面能同时看到 include / exclude / pending、verified / abstract_only、429 失败
- [ ] `runs/phase2-real/` 可回放

## 视频建议镜头

1. doctor / evaluate 终端输出  
2. 漏斗：2 include / 5 exclude，429 行  
3. 地图：claim-008 矛盾对  
4. 证据卡：claim-001 verified 与 claim-008 pending  
5. 证伪：hit-001 / hit-002 来自 exclude 论文  
6. 评测对照：相对无检索代理的差值，并口头限定含义

## 不要写进材料的话

- RAG 已被证明全面优于无检索 LLM  
- 我们已经完成全部论文的全文审阅  
- Semantic Scholar 429 等于没有相关文献  
