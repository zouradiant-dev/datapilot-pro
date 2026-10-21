# 合成 RAG 文档

全部由本项目编写，不含真实用户或业务数据。onboarding/billing/release 为三个独立来源；injection 是不会执行的恶意文本夹具，不参与正常同义检索语料。

预先指定的同义查询及目标：客户首次使用怎样更快体会价值→onboarding；提升顾客续订意愿的候选措施→onboarding；已付款账单与经常性订阅金额的区别→billing；新版本如何改善仪表板响应→release。测试保持来源、跨度和 hash 断言；不将 cosine 分数当作真实性或因果证明。
