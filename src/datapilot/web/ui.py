"""HTTP-only Streamlit UI. Browser state is never task authority or permission."""

import json
from datetime import date

import httpx
import streamlit as st

from datapilot.web.client import APIClient, ClientError, creation_intent

st.set_page_config(page_title="DataPilot Pro", page_icon="📊", layout="wide")
st.title("DataPilot Pro")
st.caption("可信本地 · SaaS 经营分析 · PostgreSQL 持久执行")
if notice := st.session_state.pop("notice", None):
    st.success(notice)


def show_error(exc):
    if isinstance(exc, ClientError):
        e = exc.error
        st.error(f"{e.get('code')}: {e.get('message')}")
        if e.get("manual_action_required"):
            st.warning("需要人工核对外部调用；系统不会自动重发未知结果。")
        elif e.get("retryable"):
            st.info("可检查服务状态后重试；重复请求沿用原幂等键。")
    else:
        st.error("API 暂时不可用，请检查本地服务。")


try:
    if "api" in st.session_state and not isinstance(st.session_state.api, APIClient):
        st.session_state.api.close()
        del st.session_state["api"]
    if "api" not in st.session_state:
        st.session_state.api = APIClient()
    api = st.session_state.api
    health = api.get("/health")
    st.info(
        "模型模式："
        + health["mode"]
        + "；任务通过原 P5B PostgreSQL Durable 路径执行。"
        + (
            " Fake 仅替代模型决策；数据库、MCP 和业务验证真实执行。"
            if health["mode"] == "fake"
            else " 真实模型会消耗 API 额度。"
        )
    )
    upload_tab, policy_tab, analysis_tab = st.tabs(
        ["1 上传与确认", "2 业务口径与文档", "3 分析与报告"]
    )
    with upload_tab:
        st.subheader("安全上传 CSV / XLSX")
        file = st.file_uploader(
            "选择业务快照（最多 10 MiB）", type=["csv", "xlsx"], max_upload_size=10
        )
        col1, col2 = st.columns(2)
        if col1.button("解析文件", disabled=file is None):
            st.session_state.upload = api.post(
                "/uploads", files={"file": (file.name, file.getvalue())}
            )
        if col2.button("加载合成 SaaS 样例"):
            st.session_state.upload = api.post("/samples", {})
        if p := st.session_state.get("upload"):
            st.caption("显示 Schema 和画像；私密原始行不传入浏览器。")
            for table in p["tables"]:
                st.write(table["source_name"], " · 行数：", table["row_count"])
                st.dataframe(
                    [
                        {
                            "原列名": c["column"]["original_name"],
                            "规范列名": c["column"]["normalized_name"],
                            "建议类型": c["suggested_type"],
                            "空值": c["null_count"],
                            "重复": c["duplicate_count"],
                            "需要确认": c["requires_confirmation"],
                        }
                        for c in table["columns"]
                    ],
                    hide_index=True,
                )
            with st.form("schema-review"):
                overrides = st.text_area("类型/名称覆盖（可选 JSON）", value="{}")
                reviewed = st.checkbox("我已审阅列名、类型、歧义及映射")
                if st.form_submit_button("确认 Schema"):
                    st.session_state.upload = api.post(
                        f"/uploads/{p['upload_id']}/confirm",
                        {
                            "proposal_sha256": p["proposal_sha256"],
                            "reviewed": reviewed,
                            "overrides": json.loads(overrides),
                        },
                    )
                    st.rerun()
            if p.get("confirmation"):
                name = st.text_input("Dataset 名称", "SaaS demo")
                if st.button("受限导入 PostgreSQL"):
                    result = api.post(
                        f"/uploads/{p['upload_id']}/import",
                        {
                            "confirmation_sha256": p["confirmation"]["confirmation_sha256"],
                            "name": name,
                        },
                    )
                    st.success(f"已发布 Dataset {result['dataset_id']} v{result['version']}")
    page_offset = st.session_state.get("dataset_offset", 0)
    page = api.get(f"/datasets?offset={page_offset}")
    datasets = page["datasets"]
    if page_offset or page.get("next_offset") is not None:
        st.caption(f"Dataset 列表：从第 {page_offset + 1} 项起，每页最多 100 项")
        previous_page, next_page = st.columns(2)
        if previous_page.button("上一页 Dataset", disabled=page_offset == 0):
            st.session_state.dataset_offset = max(0, page_offset - 100)
            st.rerun()
        if next_page.button("下一页 Dataset", disabled=page.get("next_offset") is None):
            st.session_state.dataset_offset = page["next_offset"]
            st.rerun()
    choices = {
        f"{p['schema']['name']} · v{p['schema']['version']} · {p['schema']['dataset_id'][:8]}": p
        for p in datasets
    }
    with policy_tab:
        st.subheader("确认业务语义与指标口径")
        if not choices:
            st.info("请先完成上传与入库。")
        else:
            chosen = st.selectbox("Dataset / version", list(choices))
            selected = choices[chosen]
            ds = selected["schema"]
            path = f"/datasets/{ds['dataset_id']}/versions/{ds['version']}"
            template = {
                "dataset_id": ds["dataset_id"],
                "dataset_version": ds["version"],
                "entities": [],
            }
            if st.session_state.get("mapping_dataset") != chosen:
                st.session_state.mapping_dataset = chosen
                st.session_state.mapping = json.dumps(template)
            if st.button("读取合成样例映射建议"):
                st.session_state["mapping-" + chosen] = json.dumps(
                    api.get(path + "/sample-mapping"), ensure_ascii=False, indent=2
                )
                st.session_state.mapping = st.session_state["mapping-" + chosen]
            with st.expander("Schema 列名", expanded=False):
                st.json(ds)
            with st.form("semantic-policy"):
                mapping = st.text_area(
                    "实体/字段/单位/覆盖范围映射 JSON",
                    height=220,
                    value=st.session_state.get("mapping-" + chosen, json.dumps(template)),
                    key="mapping",
                )
                reviewed = st.checkbox("我确认该业务映射与观察范围，未将账单收入当作 MRR")
                if st.form_submit_button("确认业务映射"):
                    result = api.post(
                        "/semantics/confirm", {"draft": json.loads(mapping), "reviewed": reviewed}
                    )
                    st.session_state.notice = f"Semantic v{result['semantic_version']} 已确认"
                    st.rerun()
            if selected["semantics"]:
                with st.form("metric-policy"):
                    kinds = [
                        "paid_invoice_revenue",
                        "customer_churn",
                        "subscription_churn",
                        "active_subscriptions",
                        "usage",
                        "mrr",
                    ]
                    kind = st.selectbox("指标", kinds)
                    semantic_version = st.selectbox(
                        "Semantic version", [s["semantic_version"] for s in selected["semantics"]]
                    )
                    currency = st.text_input("货币单位", "CNY")
                    paid = st.text_input("已支付状态（逗号分隔）", "paid")
                    reviewed = st.checkbox("我已确认该指标口径和单位")
                    if st.form_submit_button("确认指标定义"):
                        result = api.post(
                            "/metrics/confirm",
                            {
                                "reviewed": reviewed,
                                "draft": {
                                    "dataset_id": ds["dataset_id"],
                                    "dataset_version": ds["version"],
                                    "semantic_version": semantic_version,
                                    "metric_id": kind,
                                    "currency": currency,
                                    "paid_values": paid.split(","),
                                },
                            },
                        )
                        st.session_state.notice = f"Metric v{result['metric_version']} 已确认"
                        st.rerun()
            doc = st.file_uploader(
                "授权 TXT / Markdown 业务文档（最多 256 KiB）",
                type=["txt", "md"],
                max_upload_size=1,
            )
            doc_review = st.checkbox("我授权此文档用于当前 Dataset 的本地 Embedding 和只读检索")
            if st.button("摄取授权文档", disabled=doc is None or not doc_review):
                st.json(
                    api.post(
                        path + "/documents",
                        files={"file": (doc.name, doc.getvalue())},
                        data={"reviewed": "true"},
                    )
                )
    with analysis_tab:
        st.subheader("分析任务与持久进度")
        valid = {k: p for k, p in choices.items() if p["metrics"]}
        if valid:
            selected = valid[st.selectbox("已确认的业务数据", list(valid))]
            definitions = {
                f"{m['metric_id']} v{m['metric_version']}": m for m in selected["metrics"]
            }
            with st.form("analysis"):
                goal = st.text_area("经营分析目标", "计算2025年10月已支付账单收入")
                metrics = st.multiselect(
                    "必需指标目标", list(definitions), default=[next(iter(definitions))]
                )
                start, end = st.columns(2)
                from_date = start.date_input("开始日期（含）", date(2025, 10, 1))
                to_date = end.date_input(
                    "结束日期（不含）；活跃订阅使用此日为 as_of", date(2025, 11, 1)
                )
                corpora = api.get("/corpora")["corpora"]
                ids = [
                    c["corpus_id"]
                    for c in corpora
                    if c["dataset_id"] == selected["schema"]["dataset_id"]
                    and c["dataset_version"] == selected["schema"]["version"]
                ]
                doc_ids = st.multiselect("关联授权文档（可选）", ids)
                query = st.text_input("文档检索目标", "已付款账单收入和经常性订阅金额有什么区别？")
                review = st.checkbox("执行前等待宿主审核", value=True)
                if st.form_submit_button("创建持久分析任务"):
                    requests = []
                    for i, name in enumerate(metrics):
                        d = definitions[name]
                        req = {
                            k: d[k]
                            for k in (
                                "dataset_id",
                                "dataset_version",
                                "semantic_version",
                                "metric_id",
                                "metric_version",
                            )
                        }
                        req["goal_id"] = "goal_" + str(i)
                        if d["metric_id"] == "active_subscriptions":
                            req["as_of"] = to_date.isoformat()
                        else:
                            req["window"] = {
                                "start": from_date.isoformat(),
                                "end_exclusive": to_date.isoformat(),
                            }
                        requests.append(req)
                    body = {"question": goal, "metrics": requests, "require_review": review}
                    if doc_ids:
                        body["documents"] = {
                            "question": query,
                            "corpus_ids": doc_ids,
                            "metric_goals": [r["goal_id"] for r in requests],
                        }
                    intent = creation_intent(st.session_state.get("create_intent"), body)
                    st.session_state.create_intent = intent
                    ack = api.post("/tasks", intent["body"], key=intent["key"])
                    intent["run_id"] = ack["run_id"]
                    st.session_state.active_run = ack["run_id"]
        if intent := st.session_state.get("create_intent"):
            if intent.get("run_id"):
                st.caption("本次创建请求已关联 Run：" + intent["run_id"])
            else:
                st.warning("创建结果尚未确认；重试将使用原请求与幂等键。")
                if st.button("重试同一创建请求"):
                    ack = api.post("/tasks", intent["body"], key=intent["key"])
                    intent["run_id"] = ack["run_id"]
                    st.session_state.active_run = ack["run_id"]
                    st.rerun()
            if st.button("明确创建新的分析任务"):
                del st.session_state["create_intent"]
                st.rerun()
        ids = api.get("/tasks")["run_ids"]
        if ids:
            run_id = st.selectbox(
                "恢复查看任务",
                ids,
                index=ids.index(st.session_state.active_run)
                if st.session_state.get("active_run") in ids
                else 0,
            )
            if st.button("刷新真实进度"):
                st.rerun()
            state = api.get("/tasks/" + run_id)
            st.write("当前目标：", state["question"])
            with st.expander("宿主绑定的指标 / 版本 / 时间范围"):
                st.json(state["requested_metrics"])
            st.write("任务状态：", state["status"], " · 执行状态：", state["execution_status"])
            if state["business_completion"]:
                st.json(state["business_completion"])
            if state["error"]:
                show_error(ClientError(state["error"]))
            st.dataframe(state["tasks"], hide_index=True)
            if state["status"] == "awaiting_review":
                approved = st.checkbox("我已核对任务目标、口径与授权，批准执行")
                if st.button("批准任务", disabled=not approved):
                    api.post(f"/tasks/{run_id}/approve", {"confirmed": True})
                    st.rerun()
            if state["status"] in {"paused", "failed"} and not (state["error"] or {}).get(
                "manual_action_required"
            ):
                if st.button("请求安全恢复"):
                    api.post(f"/tasks/{run_id}/resume", {})
                    st.rerun()
            if state["status"] in {"pending", "running", "paused", "awaiting_review"}:
                if st.button("取消任务"):
                    api.post(f"/tasks/{run_id}/cancel", {})
                    st.rerun()
            if state["report_available"]:
                report = api.get(f"/tasks/{run_id}/report")
                st.markdown(report["markdown"])
                st.json(
                    {"verified_facts": report["facts"], "citations": report["citations"]},
                    expanded=False,
                )
                for chart in report["charts"]:
                    st.bar_chart(
                        {
                            "goal_id": [p["goal_id"] for p in chart["points"]],
                            "value": [float(p["value"]) for p in chart["points"]],
                        },
                        x="goal_id",
                        y="value",
                        y_label=chart["unit"],
                    )
            with st.expander("脱敏 Trace / usage"):
                st.json(api.get(f"/tasks/{run_id}/trace"))
except (ClientError, httpx.HTTPError) as exc:
    show_error(exc)
    if st.button("重新连接本地 API"):
        if "api" in st.session_state:
            st.session_state.api.close()
            del st.session_state["api"]
        st.rerun()
except (ValueError, KeyError):
    st.error("输入 JSON 或配置无效，请检查后重试。")
except Exception:
    st.error("界面暂时无法处理响应；内部详情不会公开，请刷新后检查任务实际状态。")
