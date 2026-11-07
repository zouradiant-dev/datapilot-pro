# P7 收口修复与后续业务验收

本轮零付费源码修复及所列工程控制已完成，业务质量验收仍待通过。新候选455文件，Manifest SHA256 `3cb3c353ad4ffad7010e0954a151c0dc65bd5d3c22fd63de5af5387914e6abd7`。Provider调用0、正式Runtime新Run0；工程测试使用新55456/55458合成实例，测试容器已停止、卷保留，原有实例状态不变。另获准的新55457公开Dev物化与准入见独立证据。未提交或推送。

## 修复与实际作用

1. 报告规划使用专用ReportPlan：已有宿主有限目标必须形成非空计划、unsupported必须为字面false。保留DAG、任务绑定和Worker能力验证；模型矛盾输出仍拒绝，不强制改写或增加重试。真实DeepSeek遵守新提示的效果尚未测量。
2. 新发布准入调用真实ReportService.build/verify_report，核对业务状态、数值与证据目标及逐字事实是否真正进入报告。公开同/异授权Dataset控制均保持因果未验证和partial；依赖性结论仍受TOPICS与Dataset保护，未弱化校验。
3. 新预算诊断按实际准备的模型视图，同时核对静态18k窗口与父子账本、已有消耗和pending预留。它不预留预算或产生许可，最终仍由原Gateway原子预留。
4. 公共Profile评分模块固定预算身份，在原基础评分预算边界重新计算，再运行原partial/SourceGoal政策。原18k分数完整保留为同Run诊断，早返缺dimensions保持失败。继续决策重新鉴签并核对当前collection/payload/Profile/usage；跨题记录、错Profile、未结算、unknown或证据故障不能凭旧结果继续。聚焦审查发现的P2绑定缺口已修复并复核。

## 工程验证

| 实际范围 | JUnit结果 |
|---|---|
| windows_python311_nonintegration | 1630 passed / 0 skipped |
| windows_python313_nonintegration | 1630 passed / 0 skipped |
| fixed_image_new_unit_controls | 106 passed / 0 skipped |
| fixed_image_full_integration_coverage | 375 passed / 62 skipped |
| fixed_image_public_sdk_faults | 14 passed / 0 skipped |
| windows_python313_native_and_public_faults | 46 passed / 0 skipped |

固定镜像为 `sha256:6c78a77b7ca5604bf4ac4ff8e725bc72370d550aef6c9c5b545eb27b8fa87339`，只读挂载精确候选和本机固定纯Python测试工具，没有网络安装或改生产依赖。v3到最终v4仅修改公开攻击测试的模拟usage元数据，全部产品/Prompt/Runtime/评分器及其他454成员逐字节相同，原native44等见证按精确test-only差分证明沿用，不改原Seal。真实业务值与引用由PG/MCP/P3/BGE执行；脚本/Fake仅提供模型决策，公开SDK故障使用HTTP Mock，不是Provider调用。

Windows完整集成首试触及900秒测试时限，该次不计PASS。镜像首试36通过后遇旧fixture需要写/app/artifacts而容器只读的setup error；增加独立scratch后，第二试124通过/44跳过，随后管理入口因harness漏传13个PASSWORD字段失败。仅补原字段、未改数据库口令。第三试65通过/20跳过后，旧公开攻击脚本未声明usage，先触及保守预算而未达权限断言；v4只补三条已知模拟响应的15-token元数据，保留18k、全部权限守卫及TOOL_FORBIDDEN断言。新快照单题验证后完成147未运行节点；公开SDK14项另实测，覆盖清单仅将对应原skip计入实际PASS。逐node审计437全集，保留所有原错误/skip；这是跨harness尝试与test-only修订的覆盖，不称同一快照单次全绿。代码ruff检查/format通过；全仓format仍在3份与HEAD文本一致的历史Markdown代码块失败，未改这些历史文档。远端CI、Python3.13完整集成矩阵和私有14项故障目录逐项注入未宣称完成；实际可选项skip以JUnit为准。3.13故障控制的Pydantic警告来自刻意注入malformed usage，断言通过。

## 合同、历史与剩余决定

负责人已具体采用XSRC-010/015文档角色facts、independent_facts=true、evidence_only=true；原问题、partial Gold、两层causal_requested=true、Oracle、权限和全部来源pin保持。[采用回执](../../artifacts/p7/p7-closeout-repair-20261106/OWNER-ADOPTION.json)单独追加，原PENDING提案与Seal不覆写；本轮没有签发私题新attestation或重跑两私题，原失败不重新评分为通过。[两合同原审阅](../../artifacts/p7/p7-closeout-repair-20261106/contracts-proposal-v1/OWNER-REVIEW.md)对应Seal原始SHA256 `92f8db31176780760a30d33c83f602f83443933f382d28d395da4d2e834da4a8`。

负责人同时采用四题公开Dev及精确新55457零付费物化计划；5 Dataset、4语义、4指标、6文档/3索引精确物化。初次原生准入001–003通过、004空检索STOP，P3恰好5条Evidence/Verification；原87成员STOP Seal保留。只读诊断原两query本地最高分0.541911/0.538931，低于0.55，未改Gold或阈值。负责人随后仅采用004两条中性等义query修订，新只读准入复用既有P3，不compute/追加：4/4预检、5/5数值、6/6事实及实际Report核验通过。004真实MCP目标chunk分数0.631135/0.624710，prepared视图含1200输出为10807/14709，均在原18k内；stats=[]，未发生压缩/L4或模型调用。新44成员Seal位于read-only-admission-v1，旧失败不改，不把本地复算冒充RPC原始score或预检当模型质量。55457已停止且卷保留；付费Dev及DeepSeek外发仍未授权。

历史5066个封存成员、447文件快照及7项合同提案成员均经复核；被版本化的入口先保留原始字节。旧56/60、边界33/37、32项计划数值中完成29且29/29正确、引用34/34真实保持；这是混合预算已观测集，完整业务Gate仍未通过。

拟议后续统一累计36k、调用8/Worker4、输出1200；窗口仍18k、输入字符16k。具体配置见本轮PROPOSED-BUDGET-PROFILE-v2.json，身份为 `90a5891309ed4d325823edcdd5fc001f48d4750c61fdf524ad1825f128a4e61f`；它尚不产生付费或外发授权。负责人最新明确本轮不调用，完成现阶段后结束，已单独记录OWNER-NO-LIVE-THIS-ROUND.json；本轮不再发起Live授权请求。后续只有重新收到明确指令时，才进入小Dev独立付费决定；其后候选稳定，再按[后续准入](../../artifacts/p7/p7-closeout-repair-20261106/NEXT-ADMISSION.md)先冻结协议、编制全新至少50/目标60未观测正式集合并逐题审阅封存。全部适用Gate通过才可宣布对应范围业务质量验收通过。

本报告不把工程通过写成Live效果已改善，不把公开Dev、旧题或pytest数量填入正式业务分母。消融与完整P7研究交付分别登记，不沿用历史付费额度。
