"""HTTP-only projections shared by chat and the retained management workspace."""

import math

import streamlit as st

from datapilot.web.client import ClientError

METRIC_LABELS = {
    "paid_invoice_revenue": "已支付账单收入（非 MRR）",
    "customer_churn": "客户流失率",
    "subscription_churn": "订阅流失率",
    "active_subscriptions": "活跃订阅",
    "usage": "产品使用量",
}


def metric_label(id_):
    return METRIC_LABELS.get(id_, id_)


def document_requirements(key):
    purpose = st.selectbox(
        "文档用途（需明确确认）",
        [None, "locate", "summary", "facts", "conclusion"],
        format_func=lambda p: {
            None: "请选择用途",
            "locate": "定位原文",
            "summary": "总结授权文档",
            "facts": "核验具体事实",
            "conclusion": "分析结论（可能无法验证）",
        }[p],
        key=key + "-purpose",
    )
    facts = []
    if purpose in {"facts", "conclusion"}:
        st.caption("待核验问题不是证明；请另填授权原文中的精确引述，宿主会核实来源、版本与Chunk。")
        text = st.text_area("必需事实（每行一项，最多 8 项，每项 256 字符）", key=key + "-facts")
        quotes = st.text_area(
            "逐项原文引述（与上一栏同序；没有引述时保持未验证）",
            key=key + "-quotes",
            help="只填授权原件中逐字出现的文本；不会把问题描述当作证明。",
        )
        descriptions = [line.strip() for line in text.splitlines() if line.strip()]
        quotations = [line.strip() for line in quotes.splitlines() if line.strip()]
        facts = [
            {
                "fact_id": f"fact_{i}",
                "description": line,
                **({"quotation": quotations[i - 1]} if i <= len(quotations) else {}),
            }
            for i, line in enumerate(descriptions, 1)
        ]
    return {"purpose": purpose, "required_facts": facts}


def time_label(request):
    window = request.get("window")
    return (
        (window["start"] + " 至 " + window["end_exclusive"] + "（结束不含）")
        if window
        else "截至 " + request["as_of"]
    )


def show_error(exc):
    if isinstance(exc, ClientError):
        error = exc.error
        st.error(f"{error.get('code')}: {error.get('message')}")
        if error.get("manual_action_required"):
            st.warning("需要人工对账；未知外部调用不会自动重发，也不要新建替代任务隐藏未知状态。")
    else:
        st.error("API 暂时不可用。请重新连接，再查看原任务；不要重复新建。")


def render_report(report):
    completion = report["business_completion"]["status"]
    labels = {
        "completed": "必需目标已验证",
        "partial": "部分完成",
        "unavailable": "数据不足",
        "blocked": "已阻断",
    }
    st.subheader(labels.get(completion, completion))
    if completion != "completed":
        st.warning("当前结果并非完整业务分析；请查看缺失信息和局限。")
    for fact in report["facts"]:
        st.metric(
            metric_label(fact["request"]["metric_id"]),
            fact["value"]["value"] + " " + fact["value"]["unit"],
        )
        st.caption(time_label(fact["request"]))
    st.markdown(report["markdown"], unsafe_allow_html=False)
    for item in report.get("citations", []):
        if item.get("quotation"):
            st.text(item["quotation"])
            c = item["citation"]
            st.caption(
                f"授权原文引述 · 行 {c['line_start']}–{c['line_end']} · Chunk {c['chunk_id']}"
            )
    labels = {f["request"]["goal_id"]: time_label(f["request"]) for f in report["facts"]}
    for chart in report["charts"]:
        values = [float(p["value"]) for p in chart["points"]]
        if all(math.isfinite(v) for v in values):
            st.bar_chart(
                {
                    "目标": [labels.get(p["goal_id"], p["goal_id"]) for p in chart["points"]],
                    "展示值": values,
                },
                x="目标",
                y="展示值",
                y_label=chart["unit"],
            )
            st.caption(
                "图表只作展示；上方精确数值及原 Evidence 为准。两个窗口并列不代表已计算环比。"
            )
    with st.expander("来源、口径、时间和验证依据"):
        st.json(
            {
                "verified_facts": report["facts"],
                "document_citations": report["citations"],
                "missing_requirements": report["missing_requirements"],
            }
        )


def render_run(api, run_id, *, prefix):
    state = api.get("/tasks/" + run_id)
    status = state["status"]
    st.write(
        "任务 / 审批状态：",
        status,
        " · 执行状态：",
        state.get("execution_status") or "尚未执行",
        " · 业务完成：",
        (state.get("business_completion") or {}).get("status", "尚未判定"),
    )
    if state.get("error"):
        show_error(ClientError(state["error"]))
    if state["tasks"]:
        workers = {
            "sql": "指标查询",
            "rag": "文档检索",
            "analysis": "确定性分析",
            "report": "证据验证与报告",
        }
        for task in state["tasks"]:
            st.caption(workers.get(task["worker"], task["worker"]) + "：" + task["status"])
        with st.expander("节点执行明细"):
            st.dataframe(state["tasks"], hide_index=True)
    if status == "awaiting_review":
        review = api.get(f"/tasks/{run_id}/review")
        st.subheader("执行前人工审批")
        st.text(review["request"]["question"])
        for i, req in enumerate(review["request"]["metrics"]):
            definition = review["definitions"][i]
            st.write(
                metric_label(req["metric_id"]),
                " · " + review["dataset_names"][i] + " v",
                req["dataset_version"],
                " · Metric v",
                req["metric_version"],
            )
            st.write("时间（右开）：", req.get("window") or {"as_of": req.get("as_of")})
            st.write(
                "单位/状态口径：",
                definition["definition"].get("currency"),
                definition["definition"].get("paid_values"),
            )
        st.write(
            "模型：",
            review["model_mode"],
            " · 调用上限：",
            review["max_model_calls"],
            " · Token 上限：",
            review["max_tokens"],
        )
        st.caption(review["cost"])
        st.write("文档范围：", review["document_scope"] or "未绑定文档")
        with st.expander("审批配置与版本引用"):
            st.json(review)
        approved = st.checkbox(
            "我已核对目标、数据版本、口径、时间及费用，批准执行", key=prefix + "-review"
        )
        if st.button("批准执行", key=prefix + "-approve", disabled=not approved):
            api.post(f"/tasks/{run_id}/approve", {"confirmed": True}, key="approve-" + run_id)
            st.rerun()
        if review["request"].get("documents"):
            st.caption("修改文档任务请使用原对话的合同卡，新版本会使旧确认失效。")
        elif st.button("返回修改（先取消原任务）", key=prefix + "-edit"):
            api.post(f"/tasks/{run_id}/cancel", {}, key="cancel-" + run_id)
            st.session_state.edit_question = state["question"]
            st.rerun()
    if status in {"pending", "running", "paused", "awaiting_review"}:
        if st.button("取消任务", key=prefix + "-cancel"):
            api.post(f"/tasks/{run_id}/cancel", {}, key="cancel-" + run_id)
            st.rerun()
    if status in {"paused", "failed"} and not (state.get("error") or {}).get(
        "manual_action_required"
    ):
        if st.button("请求安全恢复", key=prefix + "-resume"):
            # The existing backend rechecks the Manifest and Journal. No implicit resume.
            api.post(f"/tasks/{run_id}/resume", {})
            st.rerun()
    if state["report_available"]:
        render_report(api.get(f"/tasks/{run_id}/report"))
    with st.expander("技术诊断与脱敏用量"):
        st.caption("Run：" + run_id)
        if st.button("读取 Trace", key=prefix + "-trace"):
            st.json(api.get(f"/tasks/{run_id}/trace"))
    return status
