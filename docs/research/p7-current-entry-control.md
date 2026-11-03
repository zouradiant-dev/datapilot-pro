# Current-source P7 evaluation entry: actual control result

## Implemented

- `evaluation/p7_v3_current/current_binding.py` — separate versioned entry; old v3 unchanged.
- `evaluation/p7_v3_current/container_adapter.py` — absolute current snapshot mount, isolated network/image, redacted env file.
- `evaluation/p7_v3_current/scorer.py` — public protocol adapter for trusted `rag_completion_correction` control rows; old v3 scorer unchanged.
- `evaluation/p7_v3_current/test_current_binding.py`, `test_container_command.py`, `test_scorer_control.py`.
- Source snapshot: `artifacts/p7/final-evaluation-v1/current-source-snapshot/` (114 files, LF).
- Manifest: `artifacts/p7/final-evaluation-v1/current-evaluation-manifest.json`.
- Old v3 Freeze/Gold/Scorer/INVALID result preserved; no old `verify` removal.

## Source identity

- LF manifest: `cfacd0bd0e23e31a06ac669375eaf266885c74afc92cd0b018fcf16123cdf13f`
- raw manifest: `46652e2b739d56789205a646f4934b3b648debec088c7d517e8be00bbaa8f5ed`
- 114 necessary source files; current working tree unchanged by this entry.

## Exact command

```powershell
Set-Location 'D:\桌面\llm-learning\datapilot-pro'
$env:PYTHONUTF8='1'
$env:DATAPILOT_LLM_MODE='fake'
$env:TEMP='D:\桌面\llm-learning\datapilot-pro\artifacts\p7\tmp-current'
Get-Content artifacts\p7\current-pg\private\environment.json -Raw |
  ConvertFrom-Json | ForEach-Object { $_.PSObject.Properties |
  ForEach-Object { Set-Item "Env:\$($_.Name)" $_.Value } }
& .venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'evaluation/p7_v3_current'); import current_binding; current_binding.run()"
```

## Container identity

- image: `datapilot-current:local`
- network: `datapilot-p7-current-v1_default`
- PG: `datapilot-p7-current-v1-postgres-1`
- DB: `datapilot_p7_current`
- volume: `datapilot-p7_currentdata`
- local port: 55443
- mount: `.../current-source-snapshot/src -> /app/src:ro`
- redacted command: `artifacts/p7/final-evaluation-v1/container-command-redacted.json`

## Results

Contract tests: **5 passed**.

Control chain: **3 public Fake/Toy cases**, not one Run:

| Case | Run | Business | Strict |
|---|---|---|---|
| probe-v3-completed | `de7f7c1f-5e62-4243-8c5c-fb99506e028c` | completed | True |
| probe-v3-partial | `2d9fa8c8-0c13-4d90-9a44-918217963a6c` | partial | True |
| probe-v3-unavailable | `62020c54-656c-41e5-8094-ac181e978129` | unavailable | True |

All three used `datapilot-current:local`, current source mount, isolated PG/MCP and Fake/Toy; no DeepSeek. The completed/partial/unavailable controls were all `strict_correct=True`.

Scorer public test:
- legacy `v3_score.call_integrity` rejects a trusted control-row fixture;
- current adapter accepts it;
- old scorer and historical results unchanged.

## Boundaries

- No 50-case set, no formal Holdout, no paid model, no paid Permit.
- No full pytest, no commit/push.
- The control is public synthetic engineering validation, not business quality.
