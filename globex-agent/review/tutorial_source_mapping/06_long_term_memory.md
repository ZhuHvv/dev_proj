# 06 长期记忆与用户偏好Store

> [钉钉原文](https://docs.dingtalk.com/i/nodes/4lgGw3P8vRpPz59DFg3Xd6xA85daZ90D) · 当前结论：**已落地**。

## 教程概念与源码

[remember_preference_tool.py](../../app/application/tools/remember_preference_tool.py) 和 [forget_preference_tool.py](../../app/application/tools/forget_preference_tool.py) 负责显式写/删；[preference_selector.py](../../app/application/memory/preference_selector.py) 从长期偏好中选择与当前 query 相关的项；SQL/JSON Store 负责持久化。

## 真实调用链

写入：[remember_preference_tool](D:/codes/dev_proj/globex-agent/app/application/tools/remember_preference_tool.py:22) → 从 ShoppingContext 取得 buyer_id → `store.append(BuyerPreference(...))` → 发布 tool.result → 返回 ToolChunk。是否属于稳定偏好由模型依据说明判断，函数内没有独立确认校验；它捕获 ValueError，其他异常需要由调用层处理。

读取：[Orchestrator._build_inputs](../../app/application/agents/orchestrator.py#L411) → [PreferenceSelector.select](../../app/application/memory/preference_selector.py#L70) → `<buyer-preferences>` 注入 MainAgent；派发 SearchAgent 时，[task_dispatch](../../app/application/tools/task_dispatch_tool.py#L73) 再由服务端拼入相关偏好，避免仅依赖主 Agent 转述。

## 数据与边界

- 键是 buyer 维度，可跨 shopping session；对话上下文则是 session 维度，两者不能混为一谈。
- SearchAgent 获得偏好提示，TradeAgent 默认不注入，减少交易副作用受模糊偏好驱动。
- 读失败按“无偏好”继续；写/删失败需如实返回，不能假装已记住。

## 与教程的差异

这是结构化偏好存储。稳定偏好与临时要求的区分写在工具说明中，由模型判断；不能称为已经实现服务端显式授权的记忆写入流程。
