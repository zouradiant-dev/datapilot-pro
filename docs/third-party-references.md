# 第三方研究引用与归属

本文件记录源码研究来源，不替代依赖分发时所需的许可证清单，也不替 DataPilot Pro 选择开源许可证。

## 本轮引用

| 项目 | 固定来源 | 核查到的许可证与版权 |
|---|---|---|
| LangGraph | [源码提交](https://github.com/langchain-ai/langgraph/tree/41c9c22fdc83d68a2859d0c9a2b627c8615a792f) | [MIT LICENSE](https://github.com/langchain-ai/langgraph/blob/41c9c22fdc83d68a2859d0c9a2b627c8615a792f/LICENSE)，Copyright (c) 2024 LangChain, Inc. |
| Mini Claude Code | [源码提交](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/tree/0b452360866433fde0dc77cd37ada9d303546592) | [MIT LICENSE](https://github.com/Windy3f3f3f3f/claude-code-from-scratch/blob/0b452360866433fde0dc77cd37ada9d303546592/LICENSE)，Copyright (c) 2025 Windy3f3f3f3f |

本轮为原创架构分析、函数/路径引用与本项目编写的公开 API 探针，未将第三方 Runtime、工具实现、Prompt 或迁移 SQL 复制到生产源码。研究快照位于被忽略的 `.cache/`，不作为 vendored 发布内容。当前 LangGraph 通过正常依赖安装使用，包内的许可证应随其分发保留。

后续 P0 补读 autonomy.py 并引用控制逻辑，仍未复制实现或 Prompt。用户允许直接复用现有实现，不将进一步来源核验作为当前规划/开发阻塞；实际引入时继续保留随代码附带的 LICENSE/版权与修改记录。上游注释对私有实现的描述不构成本项目已验证的事实。

Mini 是教学重实现；其名称、README 或公开行为参考不代表本项目与 Anthropic 存在关联，也不代表已验证 Claude Code 私有机制。

## 后续直接复用时

如确需复制或改编代码、迁移 SQL、Prompt 或其他实质内容，应在对应目录加入上游完整 LICENSE 和版权声明，记录来源提交、源文件、修改内容及适用范围；适当加入 SPDX 标识。仅放一个仓库链接不能替代 MIT 要求保留的许可及版权文本。

依赖升级时重新检查实际分发包及其组件许可证，不能仅凭仓库根许可证推断所有第三方依赖相同。生成项目级 NOTICE/依赖清单时应从锁定分发物核查，本轮未声称已完成全面许可证审计。
