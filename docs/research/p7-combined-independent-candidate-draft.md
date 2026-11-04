# Combined 独立事实：候选 Freeze / Permit 草稿（authorized=false）

日期：2026-11-03。绑定提交 **`2628b612a8977a0d21695e18b14f06ad4c82e0c5`**（分支 `p7-engineering-candidate-v1`）。

**状态（2026-11-03 更新）：负责人授权后已签署并完成 Live。** 结果见 [p7-combined-independent-ci2628b61-live-results.md](p7-combined-independent-ci2628b61-live-results.md)。本草稿保留为签署前快照说明；Permit 已消费，STOP 已写入，不可复用。

## 完整 CI

| 项 | 值 |
|---|---|
| 结果 | **PASS**（3.11 / 3.13） |
| Run | [#41629097042](https://github.com/zouradiant-dev/datapilot-pro/actions/runs/41629097042) |
| HEAD | `2628b61` |
| 前序失败 | `2121e02` 仅 Ruff/format 失败；业务与 PG 集成已通过，由本提交修复后重跑 |

旧草稿 `p7-combined-independent-candidate-2121e02d8acd` **作废**，Live 必须绑定本 CI PASS 提交。

## 草稿身份

| 项 | 值 |
|---|---|
| Freeze ID | `p7-combined-independent-candidate-2628b612a897` |
| Freeze SHA256 | `f09f62363f9e2456c7bc79a5a8111826bb8898a0087d5b5db4dba9d914f47bc7` |
| Campaign | `combined-independent-ci2628b61-v1` |
| Case | `combined-repair-independent-01`（fact-scoped 文档子问题） |
| 预算 | 1 Run / 8 calls / 18,000 Token / 并发 1 / 重试 0 |
| 模型 | deepseek / deepseek-flash / thinking=disabled |

私密草稿（local-only）：

- `artifacts/p7/combined-independent-ci2628b61-v1/private/freeze-draft.json`
- `artifacts/p7/combined-independent-ci2628b61-v1/private/admission-template.json`

机器摘要：`docs/research/p7-combined-independent-candidate-draft.json`

## 签署前仍缺

1. 工作区对 Freeze 内 29 个文件逐项 **raw SHA** 复核（不能只比 LF）。
2. Host：`max_workers=1`，`DATAPILOT_MAX_PARALLEL_WORKERS=1`，重算 `host_settings_hash`。
3. 页面显式 `document_facts_independent=true`；文档子问题为「请依据授权文档核验以下事实：企业版退款申请的审核时限」。
4. 负责人授权消息 + 24 小时窗口；填写时间/`owner`/引用后 HMAC 签名，`authorized=true`。
5. 失败不重跑；旧 Permit / 旧 Run 不复用。

## Formal 50

不在本草稿范围。v3 已封存；另开 Formal 须独立 Freeze/Permit。
