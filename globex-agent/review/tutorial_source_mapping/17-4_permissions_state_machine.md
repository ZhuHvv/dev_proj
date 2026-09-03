# 17-4 动态工具权限与对话阶段状态机

> [钉钉原文](https://docs.dingtalk.com/i/nodes/wva2dxOW4YPD3NrMfkQwy91yVbkz3BRL) · 当前结论：**权限部分落地；四阶段状态机明确未实现**。

## 当前权限实现

[permissions.py](../../app/application/agents/permissions.py) 构造 AgentScope 权限规则，限制各 Agent 可见/可调用工具；MainAgent、SearchAgent、TradeAgent 的 Toolkit 也形成静态能力边界。

## 当前路由

[MainAgent 构建](../../app/application/agents/main_agent.py#L106) → 注册固定工具集 + [allow 规则](../../app/application/agents/permissions.py#L32) → 模型发起 ToolCall → 权限检查 → middleware/tool。派发子 Agent 时，[task_dispatch](../../app/application/tools/task_dispatch_tool.py#L73) 选择 agent 类型并创建新 Toolkit，而不是在同一 Agent 内按阶段动态增删工具。

## 与教程状态机的差异

仓库没有“需求澄清 → 检索 → 选择 → 交易”四阶段状态对象、合法转换表和按阶段动态工具白名单。相关设计记录将其视为 WON'T DO/非当前路线，因此不能从 Prompt 流程推断存在强状态机。

## 确认边界

Prompt 要求创建/取消订单前给确认卡，但 `permissions.py` 对这些工具允许调用，未找到服务端确认令牌。动态权限若要成为安全控制，应由服务器基于可验证状态决定，而不是由模型自报阶段。

## 数据与副作用

权限拒绝发生在工具副作用之前；一旦放行，订单 UseCase 仍会写订单/库存。测试需要覆盖越权工具、伪造阶段、跨 session 和并发确认。
