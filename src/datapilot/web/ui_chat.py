"""Chat interactions; HTTP only, candidates and history are never authority."""

import json
from datetime import date

import streamlit as st

from datapilot.web.client import ClientError, creation_intent
from datapilot.web.ui_components import document_requirements, metric_label, render_run, time_label


def send_intent(api, slot, path, body):
    intent = creation_intent(st.session_state.get(slot), body)
    st.session_state[slot] = intent
    result = api.post(path, intent["body"], key=intent["key"])
    del st.session_state[slot]
    return result


def new_conversation(api):
    ack = send_intent(api, "conversation_intent", "/conversations", {})
    st.session_state.conversation_id = ack["conversation_id"]
    st.query_params["conversation"] = ack["conversation_id"]
    st.session_state.messages_before = 201
    return ack["conversation_id"]


def append(api, cid, body):
    # Bind retry to BOTH conversation and message; reconnect cannot redirect it.
    intent = creation_intent(
        st.session_state.get("message_intent"), {"conversation_id": cid, "message": body}
    )
    st.session_state.message_intent = intent
    try:
        result = api.post(f"/conversations/{cid}/messages", body, key=intent["key"])
    except ClientError as exc:
        # These guards reject before the handler commits a message. All unknown
        # outcomes (including transport failures) keep the original body/key.
        if exc.error.get("code") in {
            "WEB_VALIDATION",
            "WEB_BODY_LIMIT",
            "GOAL_INPUT_LIMIT",
            "GOAL_SOURCE_QUOTA",
            "GOAL_SIZE",
            "WEB_SCOPE",
        }:
            del st.session_state["message_intent"]
        raise
    del st.session_state["message_intent"]
    st.session_state.poll_count = 0
    return result


def schema_card(api, id_, prefix):
    p = api.get("/uploads/" + id_)
    st.write("文件：", p["upload"]["filename"])
    st.caption("只显示字段画像；私密原始行不会传入浏览器。")
    for t in p["tables"]:
        st.write(t["source_name"], " · 行数：", t["row_count"])
        st.dataframe(
            [
                {
                    "字段": c["column"]["original_name"],
                    "SQL 列名": c["column"]["normalized_name"],
                    "类型建议": c["suggested_type"],
                    "空值": c["null_count"],
                    "重复": c["duplicate_count"],
                    "需确认": c["requires_confirmation"],
                }
                for c in t["columns"]
            ],
            hide_index=True,
        )
    with st.form(prefix + "-schema"):
        overrides = st.text_area("类型/名称覆盖（可选 JSON）", "{}")
        reviewed = st.checkbox("我已审阅字段、类型和歧义，确认 Schema")
        if st.form_submit_button("确认此文件的 Schema"):
            api.post(
                f"/uploads/{id_}/confirm",
                {
                    "proposal_sha256": p["proposal_sha256"],
                    "reviewed": reviewed,
                    "overrides": json.loads(overrides),
                },
            )
            st.rerun()
    if p.get("confirmation"):
        st.success("Schema 已确认；下一步才会受限入库。")
        if st.button("将此快照导入 PostgreSQL", key=prefix + "-import"):
            # Fixed name uses P2 idempotency even after browser reconnect.
            api.post(
                f"/uploads/{id_}/import",
                {
                    "confirmation_sha256": p["confirmation"]["confirmation_sha256"],
                    "name": "chat-" + id_,
                },
            )
            st.session_state.notice = (
                "快照已导入。请到数据管理确认业务映射、指标口径与单位，再回到对话。"
            )
            st.rerun()


def clarification(api, cid, message, datasets):
    draft, prefix = message["draft"], message["message_id"]
    for missing in draft["missing"]:
        st.info(missing)
    if not datasets:
        st.info("请先上传文件；入库后从左侧数据管理确认业务映射和指标。")
        return
    # Outside the form so changing Dataset reruns and refreshes metric/document choices.
    ds = st.selectbox(
        "选择已授权数据快照",
        datasets,
        key=prefix + "-dataset",
        format_func=lambda d: d["schema"]["name"] + " · v" + str(d["schema"]["version"]),
    )
    definitions = ds["metrics"]
    corpora = [
        c
        for c in api.get("/corpora")["corpora"]
        if (c["dataset_id"], c["dataset_version"])
        == (ds["schema"]["dataset_id"], ds["schema"]["version"])
    ]
    metric = st.selectbox(
        "已确认的指标与版本",
        [None, *definitions],
        index=0 if any("仅文档问答" in n for n in draft.get("notes", [])) or not definitions else 1,
        key=prefix + "-metric",
        format_func=lambda m: (
            "不计算指标（仅文档问答）"
            if m is None
            else (metric_label(m["metric_id"]) + " · v" + str(m["metric_version"]))
        ),
    )
    requirements = document_requirements(prefix) if corpora else None
    sources = (message.get("goal_contract") or {}).get("sources", [])
    with st.form("clarify-" + prefix):
        revised = (
            st.text_area("修改完整问题（新合同版本）", message["text"])
            if message.get("goal_contract")
            else message["text"]
        )
        if metric:
            start = st.date_input("开始日期（含）", date(2025, 10, 1))
            end = st.date_input("结束日期（不含）", date(2025, 11, 1))
        else:
            st.caption("仅引用授权文档，不计算指标或生成财务图表；日期筛选不适用。")
        docs = st.multiselect("关联授权文档（可选）", [c["corpus_id"] for c in corpora])
        required_sources = (
            st.multiselect(
                "必需原件（空选表示所选范围全部必需）",
                [s["source_id"] for s in sources],
                format_func=lambda id_: next(s["name"] for s in sources if s["source_id"] == id_),
            )
            if sources
            else []
        )
        reviewed = st.checkbox("我确认此快照、指标、时间和文档范围")
        if st.form_submit_button("补充条件并重新确认", disabled=metric is None and not corpora):
            if not reviewed:
                st.warning("请先明确确认条件。")
            else:
                selection = {
                    "dataset_id": ds["schema"]["dataset_id"],
                    "dataset_version": ds["schema"]["version"],
                    "corpus_ids": docs,
                }
                if metric:
                    selection.update(
                        metric_id=metric["metric_id"],
                        metric_version=metric["metric_version"],
                        window={"start": start.isoformat(), "end_exclusive": end.isoformat()},
                    )
                if docs and requirements:
                    selection.update(
                        document_purpose=requirements["purpose"],
                        required_facts=requirements["required_facts"],
                    )
                    if required_sources:
                        selection["required_source_ids"] = required_sources
                body = {"text": revised, "selection": selection}
                if message.get("goal_contract"):
                    body["supersedes"] = message["message_id"]
                append(api, cid, body)
                st.rerun()


def attachments(api, cid, datasets):
    with st.expander("上传业务快照 / 授权业务文档"):
        file = st.file_uploader(
            "CSV / XLSX 业务快照（最多 10 MiB）", type=["csv", "xlsx"], max_upload_size=10
        )
        if st.button("解析并添加到对话", disabled=file is None):
            p = api.post("/uploads", files={"file": (file.name, file.getvalue())})
            append(api, cid, {"upload_id": p["upload_id"]})
            st.rerun()
        if st.button("添加合成 SaaS 样例到对话"):
            p = api.post("/samples", {})
            append(api, cid, {"upload_id": p["upload_id"]})
            st.rerun()
        if datasets:
            ds = st.selectbox(
                "文档关联的已授权快照",
                datasets,
                format_func=lambda d: d["schema"]["name"] + " v" + str(d["schema"]["version"]),
            )
            doc = st.file_uploader(
                "TXT / Markdown（最多 256 KiB）", type=["txt", "md"], max_upload_size=1
            )
            reviewed = st.checkbox("我授权此文档用于所选快照的本地 Embedding 和只读检索")
            if st.button("摄取已授权文档", disabled=doc is None or not reviewed):
                s = ds["schema"]
                api.post(
                    f"/datasets/{s['dataset_id']}/versions/{s['version']}/documents",
                    files={"file": (doc.name, doc.getvalue())},
                    data={"reviewed": "true"},
                )
                st.success("文档已授权；可在候选请求的补充条件中选择。")


def goal_card(api, cid, message, datasets):
    goal = message["goal_contract"]
    prefix = message["message_id"] + "-" + goal["contract_sha256"]
    st.subheader("有限目标合同 · " + goal["status"])
    st.caption("合同版本：" + str(goal["version"]) + " · 服务器保存，刷新不会自动确认")
    st.write("用户原始问题")
    st.text(goal["original_question"])
    request = goal["review"]["request"]
    st.write("待确认的有限任务")
    for metric in request["metrics"]:
        st.write(metric_label(metric["metric_id"]), time_label(metric))
    doc = request["documents"]
    st.text("文档子目标：" + doc["question"])
    st.write("输出用途：", doc.get("purpose"))
    for d in goal["datasets"]:
        st.text(f"数据：{d['name']} · v{d['version']} · {d['dataset_id']}")
    for source in goal["sources"]:
        st.text(("必需来源：" if source["required"] else "授权背景：") + source["name"])
        st.caption("Source " + source["source_id"] + " · IndexVersion " + source["index_version"])
    for fact in doc.get("required_facts", []):
        st.text("待核验事实（尚非证明）：" + fact["description"])
    for note in goal["limitations"]:
        st.caption(note)
    for note in goal["unresolved"]:
        st.warning("前置条件未解决：" + note + "；请先修改问题")
    with st.expander("完整合同、指标口径与版本"):
        st.json(goal)
    if goal["status"] == "confirmed":
        st.success("服务器已记录范围确认；最终事实与业务完成状态仍由原Verifier判定")
        if message.get("run_id"):
            render_run(api, message["run_id"], prefix=message["message_id"])
    if goal["status"] in {"pending_confirmation", "confirmed"}:
        if goal["status"] == "pending_confirmation":
            st.write(
                "执行预算：",
                goal["review"]["max_model_calls"],
                "次模型调用 / ",
                goal["review"]["max_tokens"],
                "Token上限",
            )
            st.caption(goal["review"]["cost"])
            a = st.checkbox(
                "我已审阅完整问题、目标、数据、来源与业务口径", key=prefix + "-reviewed"
            )
            b = st.checkbox(
                "我确认此有限合同覆盖完整目标，不要求证明材料齐备或全语料无遗漏",
                key=prefix + "-covered",
            )
            c = st.checkbox("我确认必要前提已解决；不确定时先修改或拒绝", key=prefix + "-resolved")
            if st.button(
                "确认范围并创建待审批任务",
                key=prefix + "-confirm",
                disabled=not (goal["can_confirm"] and a and b and c),
            ):
                api.post(
                    f"/conversations/{cid}/messages/{message['message_id']}/launch",
                    {
                        "confirmed": True,
                        "expected_version": goal["version"],
                        "expected_contract_sha256": goal["contract_sha256"],
                        "reviewed_contract": a,
                        "covers_original_goal": b,
                        "prerequisites_resolved": c,
                    },
                    key="goal-confirm-" + message["message_id"],
                )
                st.rerun()
        if st.button("取消或撤回本次合同", key=prefix + "-reject"):
            api.post(
                f"/conversations/{cid}/messages/{message['message_id']}/goal/reject",
                {
                    "expected_version": goal["version"],
                    "expected_contract_sha256": goal["contract_sha256"],
                },
                key="goal-reject-" + message["message_id"],
            )
            st.rerun()
        with st.expander("修改任务范围（新版本，旧确认失效）"):
            clarification(api, cid, message, datasets)


def render_chat(api, datasets):
    st.title("DataPilot Pro")
    st.caption("SaaS 经营分析助手 · 数据有来源，执行需审批")
    cid = st.session_state.get("conversation_id") or st.query_params.get("conversation")
    cid = cid or new_conversation(api)
    st.session_state.conversation_id = cid
    before = st.session_state.get("messages_before", 201)
    page = api.get(f"/conversations/{cid}/messages?before={before}")
    if page.get("next_before") is not None and st.button("查看更早的消息"):
        st.session_state.messages_before = page["next_before"]
        st.rerun()
    if before != 201 and st.button("返回最新消息"):
        st.session_state.messages_before = 201
        st.rerun()
    if not page["messages"]:
        st.write("上传业务快照，或直接分析已确认的数据。缺少条件时，我会先请你确认。")
        for example in ["分析2025年10月已支付账单收入", "查询上个月产品使用量", "分析客户流失情况"]:
            if st.button(example, disabled=bool(st.session_state.get("message_intent"))):
                append(api, cid, {"text": example})
                st.rerun()
    if intent := st.session_state.get("message_intent"):
        st.warning("上次消息响应未确认；重试只关联原消息。")
        if st.button("重试同一消息"):
            append(api, intent["body"]["conversation_id"], intent["body"]["message"])
            st.session_state.conversation_id = intent["body"]["conversation_id"]
            st.query_params["conversation"] = intent["body"]["conversation_id"]
            st.rerun()
    if question := st.session_state.get("edit_question"):
        with st.form("edit-question"):
            revised = st.text_area("修改后的分析问题（新请求；原任务保持取消）", question)
            if st.form_submit_button("提交修改后的问题"):
                append(api, cid, {"text": revised})
                del st.session_state["edit_question"]
                st.rerun()
    for m in page["messages"]:
        if m.get("goal_event"):
            with st.chat_message("assistant"):
                st.info("服务器确认记录：" + m["text"])
            continue
        with st.chat_message("user"):
            st.text(m["text"] or "上传业务文件")
        with st.chat_message("assistant"):
            if m["unavailable"]:
                st.warning("此消息的授权、版本或保留时间已失效，内容与报告不可用。")
            elif m.get("goal_contract"):
                goal_card(api, cid, m, datasets)
            elif m["upload_id"]:
                schema_card(api, m["upload_id"], m["message_id"])
            elif m["run_id"]:
                render_run(api, m["run_id"], prefix=m["message_id"])
            elif m["draft"]:
                draft = m["draft"]
                if draft["request"]:
                    st.write("已形成候选请求，等待你提交审批。")
                    for req in draft["request"]["metrics"]:
                        st.write(metric_label(req["metric_id"]), " · 时间：", time_label(req))
                    if not draft["request"]["metrics"]:
                        st.write("文档问答 · 仅引用已授权来源，不计算业务指标")
                    for note in draft["notes"]:
                        st.caption(note)
                    with st.expander("候选数据与指标版本"):
                        st.json(draft["request"])
                    if st.button("提交并等待人工审批", key="launch-" + m["message_id"]):
                        api.post(
                            f"/conversations/{cid}/messages/{m['message_id']}/launch",
                            {"confirmed": True},
                            key="launch-" + m["message_id"],
                        )
                        st.session_state.poll_count = 0
                        st.rerun()
                    with st.expander("调整候选条件 / 选择文档"):
                        clarification(api, cid, m, datasets)
                else:
                    clarification(api, cid, m, datasets)
    attachments(api, cid, datasets)
    if text := st.chat_input(
        "例如：分析2025年10月收入；追问：那和九月份比呢？",
        disabled=bool(st.session_state.get("message_intent")),
    ):
        append(api, cid, {"text": text})
        st.rerun()
    if st.button("刷新真实任务进度"):
        st.session_state.poll_count = 0
        st.rerun()
    if st.checkbox("有界自动刷新（5 秒一次，最多 12 次；只读）", value=False):

        @st.fragment(run_every=5)
        def refresh_progress():
            count = st.session_state.get("poll_count", 0)
            if count >= 12:
                st.info("已到刷新上限，可手动查看原任务。")
                return
            ids = [
                m["run_id"]
                for m in page["messages"]
                if m.get("run_id")
                and (not m.get("goal_contract") or m["goal_contract"]["status"] == "confirmed")
            ]
            if ids:
                state = api.get("/tasks/" + ids[-1])
                st.write("最近任务真实状态：", state["status"])
                if state["status"] not in {"pending", "running"}:
                    st.info("状态已更新，请点“刷新真实任务进度”查看审批或报告。")
                    st.session_state.poll_count = 12
                    return
            st.session_state.poll_count = count + 1

        refresh_progress()
