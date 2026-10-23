"""Chat-first entry; all business and execution access stays behind HTTP."""

import httpx
import streamlit as st

from datapilot.web.client import APIClient, ClientError
from datapilot.web.ui_chat import new_conversation, render_chat
from datapilot.web.ui_components import render_run, show_error
from datapilot.web.ui_management import render_management

st.set_page_config(page_title="DataPilot Pro", page_icon="📊", layout="wide")

try:
    if "api" not in st.session_state:
        st.session_state.api = APIClient()
    api = st.session_state.api
    health = api.get("/health")
    if health["mode"] == "fake":
        st.info("演示模式：模型决策使用 Fake，数据库、MCP 和业务验证使用真实服务。")
    else:
        st.warning("Live 模式：沿用宿主模型配置，执行可能产生 API 费用。")
    if notice := st.session_state.pop("notice", None):
        st.success(notice)
    with st.sidebar:
        st.header("DataPilot Pro")
        view = st.radio("工作区", ["对话工作台", "数据管理", "设置与诊断"], key="workspace")
        if st.button("新建对话", disabled=bool(st.session_state.get("message_intent"))):
            new_conversation(api)
            st.rerun()
        history = api.get("/conversations")["conversations"]
        st.caption("历史对话（最多 30 个，按宿主 TTL 保留）")
        for i, c in enumerate(history):
            label = c["created_at"].replace("T", " ")[:16] + " · 对话 " + str(len(history) - i)
            if st.button(label, key="history-" + c["conversation_id"]):
                st.session_state.conversation_id = c["conversation_id"]
                st.query_params["conversation"] = c["conversation_id"]
                st.session_state.messages_before = 201
                st.rerun()
        offset = st.session_state.get("sidebar_dataset_offset", 0)
        page = api.get(f"/datasets?offset={offset}")
        datasets = page["datasets"]
        with st.expander("已授权数据集"):
            for ds in datasets:
                st.text(ds["schema"]["name"] + " · v" + str(ds["schema"]["version"]))
            if offset and st.button("上一页快照"):
                st.session_state.sidebar_dataset_offset = max(0, offset - 100)
                st.rerun()
            if page.get("next_offset") is not None and st.button("下一页快照"):
                st.session_state.sidebar_dataset_offset = page["next_offset"]
                st.rerun()
        report_id = st.selectbox(
            "历史任务 / 报告",
            [None] + api.get("/tasks")["run_ids"],
            format_func=lambda v: "在对话中查看" if v is None else "任务 " + v[:8],
        )
    if view == "数据管理":
        st.title("数据管理")
        render_management(api)
    elif view == "设置与诊断":
        st.title("设置与诊断")
        st.json(health)
        st.caption("身份、模型与预算由可信宿主配置；聊天不能改变。")
    elif report_id:
        st.title("历史任务与报告")
        render_run(api, report_id, prefix="historical-" + report_id)
    else:
        render_chat(api, datasets)
except (ClientError, httpx.HTTPError) as exc:
    show_error(exc)
    if st.button("重新连接本地 API"):
        if "api" in st.session_state:
            st.session_state.api.close()
            del st.session_state["api"]
        st.rerun()
except (ValueError, KeyError):
    st.error("输入或响应格式无效。请检查确认条件；不会自动执行或重试。")
except Exception:
    st.error("界面暂时无法处理响应。内部详情不公开，请查看原任务或重新连接。")
