# 18 Bad-Case驱动的数据飞轮

> [钉钉原文](https://docs.dingtalk.com/i/nodes/1OQX0akWmxvLXAb5UbrxKXz58GlDd3mE) · 当前结论：**底座存在，自动飞轮待实现**。

## 可作为飞轮输入的现有组件

ConversationStore 保存对话和非 token 事件；DriftDetector/Harness 可产生违规信号；[eval](../../eval/) 保存人工案例；[eval_regression.py](../../scripts/eval_regression.py) 与商品召回评测脚本提供回归度量。

## 教程闭环在本项目中的目标映射

[线上请求/事件](../../app/application/agents/orchestrator.py#L140) → 脱敏采集 → 失败归因（Prompt/工具/检索/数据/模型/工程）→ 生成或人工补充 [评测案例](../../eval/cases.yaml) → 修复候选 → [全量回归](../../scripts/eval_regression.py#L134) / [检索门禁](../../scripts/eval/run_product_recall.py#L135) → 灰度 → 指标晋级 → 成功策略沉淀。

## 当前缺口

没有自动 bad-case 聚类、根因分类、训练/Prompt 样本生成、Prompt A/B、模型/Prompt 版本注册、自动晋级和回滚控制器。现有数据与脚本是“可手工运行的评测底座”，不是自进化系统。

## 数据与安全

订单和 buyer 对话必须脱敏；失败案例不能直接喂给训练流程。自动修复不得改写权限、确认和领域不变量，所有副作用场景应在沙箱回放。

## 最小可落地顺序

先给失败事件增加稳定 taxonomy（分类标签）和版本指纹，再做“人工归因 → 自动回归门禁”，最后才考虑自动生成候选 Prompt/训练数据。这样每一步都有可审计证据。
