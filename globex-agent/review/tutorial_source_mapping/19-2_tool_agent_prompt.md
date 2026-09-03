# 19-2 工具与子 Agent 提示词与决策路由

> [钉钉原文](https://docs.dingtalk.com/i/nodes/ndMj49yWjXrj207OURw0Orq6J3pmz5aA) · 当前结论：**已落地**。

## 三类提示来源

- Agent 级： [globex.yml](../../app/application/prompts/globex.yml) 的 main/search/trade system prompt。
- 工具级：`app/application/tools/` 中构造函数暴露的函数签名与 docstring。
- 动态上下文：Orchestrator 注入 buyer 偏好，`task_dispatch` 注入子任务和相关偏好。

## 真实决策链

[MainAgent 读取系统提示与工具 schema](../../app/application/agents/main_agent.py#L106) → 判断直接工具或 [task_dispatch](../../app/application/tools/task_dispatch_tool.py#L73) → [子 Agent 读取专用 Prompt 与较小工具集](../../app/application/agents/search_agent.py#L84) → ToolCall → 结果回主 Agent → [Orchestrator 汇总流式输出](../../app/application/agents/orchestrator.py#L329)。

工具参数并非自然语言随意解析：框架根据 Python 类型和 docstring 生成 schema，工具再把参数转成 UseCase DTO，由领域层做最终校验。

## 数据与副作用

路由决定上下文、token 和延迟；TradeAgent 工具还可能产生订单副作用。工具描述必须清晰区分只读与写操作、必填字段、错误返回和确认前提。

## 当前边界

路由属于模型软决策，没有独立分类器；MainAgent 直接拥有业务工具，因此“定义了子 Agent”不意味着请求必然派发。权限与确认不能只依赖提示词措辞。
