"""旧 Streamlit 入口的兼容层。正式界面已改为 python -m src.cli ui。"""

MESSAGE = (
    "旧 Streamlit 界面已停用。请在该终端按 Ctrl+C，然后运行：\n"
    "python -m src.cli ui --run-id phase2-real\n"
    "新界面默认地址：http://127.0.0.1:8787/?run=phase2-real"
)


def main() -> int:
    try:
        import streamlit as st
    except ImportError:
        print(MESSAGE)
        from src.ui.server import serve_ui

        return serve_ui(run_id="phase2-real")

    st.set_page_config(page_title="勘文 LitAudit", layout="wide")
    st.title("勘文 / LitAudit")
    st.error(MESSAGE)
    st.markdown("新界面：[http://127.0.0.1:8787/?run=phase2-real](http://127.0.0.1:8787/?run=phase2-real)")
    return 0


main()
