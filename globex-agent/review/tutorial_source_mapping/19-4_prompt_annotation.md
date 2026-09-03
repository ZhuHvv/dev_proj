# 19-4 Globex 主子Agent系统提示词全文与逐层注解

> [钉钉原文](https://docs.dingtalk.com/i/nodes/vNG4YZ7JnP9OlBYqtN9Z37q2W2LD0oRE) · 当前结论：**运行时全文已落地，以本地 YAML 为准**。

## 本地全文入口

[globex.yml](../../app/application/prompts/globex.yml) 是 MainAgent、SearchAgent、TradeAgent 的当前系统提示词；[loader.py](../../app/application/prompts/loader.py) 负责解析。若教程正文与 YAML 不同，应以当前工作区 YAML 判定实际行为。

## MainAgent 各层与代码连接

| Prompt 层 | 代码接点 |
| --- | --- |
| 工具使用 | `MainAgentFactory.build()` 注册 Search/Trade 工具 |
| 复杂任务派发 | `task_dispatch_tool.py` 与 AgentScope Task 工具 |
| 长期偏好 | remember/forget 工具与 `PreferenceSelector` |
| 订单确认 | order 工具与 `OrderUseCase`；目前主要是软约束 |
| 事实边界 | RAG/商品工具结果与 output guard |

## 子 Agent 各层

Search Prompt 约束商品检索、品类洞察与偏好；Trade Prompt 聚焦创建/查询/取消订单。专用 Toolkit 是比语言描述更硬的能力边界，但写操作确认仍需服务端状态加强。

## 运行时数据流

[YAML 静态提示](../../app/application/prompts/globex.yml#L3) → [Factory 注入](../../app/application/agents/main_agent.py#L106) → [Orchestrator 追加本轮 query/偏好](../../app/application/agents/orchestrator.py#L411) → AgentScope 追加工具 observation → 最终回复 → [L4 输出审核](../../app/infrastructure/security/output_guard.py#L50)。

## 阅读结论

逐句注解时必须同时看工具实现：Prompt 中“必须”“禁止”不自动成为代码保证。重点对照 `globex.yml → build_tools → permissions → UseCase` 四层是否一致。
