"""Finite SaaS intent adapter. No model, permission, Registry write or arithmetic."""

import json
import re
from datetime import date

from datapilot.web.chat_contracts import ChatDraft, ChatSelection
from datapilot.web.contracts import CreateTask


def month_window(year, month):
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return {"start": start.isoformat(), "end_exclusive": end.isoformat()}


def parse_window(text, today, previous=None):
    """No silent year guesses. Only an explicit prior Run supplies follow-up year."""
    dates = re.findall(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", text)
    if dates:
        if len(dates) != 2 or not any(x in text for x in ("不含", "右开", "end_exclusive")):
            return None
        return {"start": dates[0], "end_exclusive": dates[1]}
    if re.search(r"月\s*\d{1,2}\s*[日号]", text):
        return None  # A day request must never silently become an entire month.
    mentions = re.findall(
        r"上个月|本月|这个月|(?<!\d)\d{4}-\d{2}(?![-\d])|"
        r"(?:\d{1,2}|[一二三四五六七八九十]{1,2})\s*月",
        text,
    )
    if len(mentions) > 1:
        return None  # Never drop another window, including mixed month notation.
    if "上个月" in text:
        return month_window(today.year - (today.month == 1), (today.month - 2) % 12 + 1)
    if "本月" in text or "这个月" in text:
        return month_window(today.year, today.month)
    months = re.findall(r"(?:(\d{4})\s*[年/-]\s*)?(\d{1,2})\s*月", text)
    if not months:
        match = re.search(r"(\d{4})-(\d{2})(?![-\d])", text)
        months = [match.groups()] if match else []
    if not months:
        chinese = {
            "十": 10,
            "十一": 11,
            "十二": 12,
            "九": 9,
            "八": 8,
            "七": 7,
            "六": 6,
            "五": 5,
            "四": 4,
            "三": 3,
            "二": 2,
            "一": 1,
        }
        found = re.findall(r"([一二三四五六七八九十]{1,2})月", text)
        months = [("", str(chinese[m])) for m in found if m in chinese]
    if len(months) != 1:
        return None
    year, month = months[0]
    if not year and previous and previous.get("window"):
        year = previous["window"]["start"][:4]
    if not year or not 1 <= int(month) <= 12:
        return None
    try:
        return month_window(int(year), int(month))
    except ValueError:
        return None


def resolve(text: str, selection: ChatSelection, datasets, *, today: date, previous=None):
    """Return a candidate or explicit clarification. Host revalidates on Run creation."""
    missing, notes = [], []
    document_question = bool(re.search(r"文档|资料|\.md\b|\.txt\b", text, re.I)) and not bool(
        re.search(
            r"计算|统计|分析|汇总|多少|总额|总数|趋势|环比|同比|查询.*(?:收入|营收|使用量|流失)",
            text,
        )
    )
    if document_question and selection.metric_id is None:
        notes = ["仅文档问答：不计算指标；仅引用授权原文，仍须人工审批。"]
        if len(text) > 512:
            return ChatDraft(
                missing=["请将完整文档问题缩短至 512 字符；不会截断原始目标。"], notes=notes
            )
        if not selection.corpus_ids:
            return ChatDraft(
                missing=["请选择明确授权的 Corpus；聊天中的文件名不是授权。"], notes=notes
            )
        if selection.window is not None:
            return ChatDraft(
                missing=["文档问答不使用指标日期筛选；请重新确认文档范围。"], notes=notes
            )
        return ChatDraft(
            request=CreateTask(
                question=text,
                metrics=[],
                documents={
                    "question": text,
                    "metric_goals": [],
                    "corpus_ids": selection.corpus_ids,
                },
            ),
            notes=notes,
        )
    if re.search(
        r"(?<![A-Za-z])mrr(?![A-Za-z])|monthly\s+recurring\s+revenue|月度经常性", text, re.I
    ):
        return ChatDraft(missing=["MRR 尚无已审查配方，不能通过选择账单收入替代；请修改问题。"])
    if re.search(r"(?:未支付|未付|未付款|未收款|unpaid).*(?:收入|营收|revenue)", text, re.I):
        return ChatDraft(missing=["当前仅支持已支付账单收入，不能替代未支付口径；请修改问题。"])
    previous_metric = previous["metrics"][0] if previous and previous.get("metrics") else None
    follow = bool(re.search(r"那|继续|同样|对比|比较|比呢", text))
    metric = selection.metric_id
    if metric is None:
        patterns = {
            "mrr": r"\bmrr\b|月度经常性",
            "paid_invoice_revenue": r"收入|营收|revenue",
            "customer_churn": r"客户流失|customer churn",
            "subscription_churn": r"订阅流失|subscription churn",
            "active_subscriptions": r"活跃订阅|active subscription",
            "usage": r"使用量|用量|usage",
        }
        matches = [k for k, p in patterns.items() if re.search(p, text, re.I)]
        if len(matches) == 1:
            metric = matches[0]
        elif not matches and follow and previous_metric:
            metric = previous_metric["metric_id"]
        else:
            missing.append(
                "请明确选择一个受支持的业务指标；收入、MRR、客户流失与订阅流失口径不同。"
            )
    if metric == "mrr":
        return ChatDraft(missing=["MRR 尚无已审查计算配方，不能用账单收入代替。"])
    chosen = None
    if selection.dataset_id:
        chosen = next(
            (
                d
                for d in datasets
                if (d["schema"]["dataset_id"], d["schema"]["version"])
                == (selection.dataset_id, selection.dataset_version)
            ),
            None,
        )
    elif follow and previous_metric:
        chosen = next(
            (
                d
                for d in datasets
                if (d["schema"]["dataset_id"], d["schema"]["version"])
                == (previous_metric["dataset_id"], previous_metric["dataset_version"])
            ),
            None,
        )
    elif len(datasets) == 1:
        chosen = datasets[0]
    if chosen is None:
        missing.append("请选择当前已授权的 Dataset 和版本；不能从聊天文本取得授权。")
    definitions = [m for m in chosen["metrics"] if m["metric_id"] == metric] if chosen else []
    if selection.metric_version:
        definitions = [m for m in definitions if m["metric_version"] == selection.metric_version]
    elif follow and previous_metric and metric == previous_metric["metric_id"]:
        definitions = [
            m for m in definitions if m["metric_version"] == previous_metric["metric_version"]
        ]
    if metric and chosen and len(definitions) != 1:
        missing.append("请先确认业务字段映射、指标口径及单位，并选择唯一的已确认指标版本。")
    window = (
        selection.window.model_dump(mode="json")
        if selection.window
        else parse_window(text, today, previous_metric if follow else None)
    )
    if window is None:
        missing.append("请补充明确的年份/月或起止日期（结束不含）；选择卡片中的日期也可。")
    if missing:
        return ChatDraft(missing=missing)
    definition = definitions[0]
    requested_currency = next(
        (
            code
            for code, pattern in (
                ("USD", r"美元|(?<![A-Za-z])USD(?![A-Za-z])"),
                ("CNY", r"人民币|(?<![A-Za-z])CNY(?![A-Za-z])"),
                ("EUR", r"欧元|(?<![A-Za-z])EUR(?![A-Za-z])"),
            )
            if re.search(pattern, text, re.I)
        ),
        None,
    )
    if (
        metric == "paid_invoice_revenue"
        and requested_currency
        and definition["definition"].get("currency") != requested_currency
    ):
        return ChatDraft(missing=["提问币种与已确认指标单位不一致；请确认真实口径，不能自动换算。"])
    temporal = (
        {"as_of": window["end_exclusive"]}
        if metric == "active_subscriptions"
        else {"window": window}
    )
    base = {
        k: definition[k]
        for k in (
            "dataset_id",
            "dataset_version",
            "semantic_version",
            "metric_id",
            "metric_version",
        )
    }
    metrics = [{**base, "goal_id": "metric_1", **temporal}]
    if follow and previous_metric and re.search(r"比较|对比|比呢|和.*比", text):
        if any(previous_metric[k] != base[k] for k in base):
            return ChatDraft(
                missing=["跨口径比较需重新确认；本入口只并列同一指标与数据版本的两个窗口。"]
            )
        metrics.insert(0, {**previous_metric, "goal_id": "metric_0"})
        notes.append("仅并列两个独立验证的窗口；未计算环比、同比或证明因果。")
    causal = bool(re.search(r"原因|为何|为什么|导致|cause", text, re.I))
    if causal:
        notes.append("文档只能提供背景，相关性不证明因果；缺证据会明确展示部分完成。")
    body = {
        "question": text,
        "metrics": metrics,
        "require_review": True,
        "causal_requested": causal,
    }
    if selection.corpus_ids:
        body["documents"] = {
            "question": text[:512],
            "corpus_ids": selection.corpus_ids,
            "metric_goals": [m["goal_id"] for m in metrics],
        }
    try:
        request = CreateTask.model_validate_json(json.dumps(body))
    except ValueError:
        return ChatDraft(missing=["日期范围无效；请确认有效日期和右开边界。"])
    notes.append("候选请求仍需提交宿主校验并人工审批；不会自动确认任何业务定义。")
    return ChatDraft(request=request, notes=notes)
