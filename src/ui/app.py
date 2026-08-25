from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.config import load_settings
from src.pipeline import run_pipeline
from src.replay import list_runs, load_run
from src.ui.evidence_view import render_evidence
from src.ui.falsification_view import render_falsification
from src.ui.funnel_view import render_funnel
from src.ui.map_view import render_map


def _cli_run_id() -> str | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-id")
    args, _ = parser.parse_known_args()
    return args.run_id


def main() -> None:
    st.set_page_config(page_title="LitAudit", layout="wide")
    settings = load_settings()
    st.title("LitAudit")
    st.caption("可核验文献调研。默认展示漏斗、地图、证据卡和证伪报告，不生成长综述。")

    runs = list_runs(settings.runs_dir)
    requested = _cli_run_id()
    col_a, col_b = st.columns([3, 1])
    with col_b:
        if st.button("生成离线 run"):
            result = run_pipeline(settings, source="data")
            st.session_state["run_id"] = result["run_id"]
            st.rerun()
        if st.button("生成 fixture run"):
            result = run_pipeline(settings, source="fixture", run_id="demo")
            st.session_state["run_id"] = result["run_id"]
            st.rerun()

    if not runs and "run_id" not in st.session_state:
        st.warning("还没有可回放的 run。点击右侧按钮，或在终端执行 `python -m src.cli run --offline`。")
        return

    default_run = st.session_state.get("run_id") or requested or runs[0]
    options = list(dict.fromkeys([default_run, *runs]))
    with col_a:
        run_id = st.selectbox("回放 run", options=options, index=0)
    payload = load_run(settings.runs_dir, run_id)
    dataset = payload["dataset"]
    manifest = payload["manifest"]
    st.json(
        {
            "run_id": run_id,
            "offline": manifest.get("offline"),
            "stats": payload.get("stats"),
            "limitations": manifest.get("limitations"),
        }
    )

    funnel_tab, map_tab, evidence_tab, falsify_tab = st.tabs(["筛选漏斗", "研究地图", "证据卡", "证伪报告"])
    with funnel_tab:
        render_funnel(dataset)
    with map_tab:
        render_map(dataset, payload.get("map") or {})
    with evidence_tab:
        render_evidence(dataset)
    with falsify_tab:
        render_falsification(dataset)


main()
