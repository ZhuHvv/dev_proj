# 06 长期记忆与用户偏好Store

> [钉钉原文](https://docs.dingtalk.com/i/nodes/4lgGw3P8vRpPz59DFg3Xd6xA85daZ90D) · 当前结论：**已落地**。

## 教程概念与源码

[remember_preference_tool.py](../../app/application/tools/remember_preference_tool.py) 和 [forget_preference_tool.py](../../app/application/tools/forget_preference_tool.py) 负责显式写/删；[preference_selector.py](../../app/application/memory/preference_selector.py) 从长期偏好中选择与当前 query 相关的项；SQL/JSON Store 负责持久化。

## 真实调用链

写入：用户明确表达长期偏好 → [remember_preference 工具](../../app/application/tools/remember_preference_tool.py#L22) → `PreferenceStore.upsert` → `ToolChunk`。

读取：[Orchestrator._build_inputs](../../app/application/agents/orchestrator.py#L411) → [PreferenceSelector.select](../../app/application/memory/preference_selector.py#L70) → `<buyer-preferences>` 注入 MainAgent；派发 SearchAgent 时，[task_dispatch](../../app/application/tools/task_dispatch_tool.py#L73) 再由服务端拼入相关偏好，避免仅依赖主 Agent 转述。

## 数据与边界

- 键是 buyer 维度，可跨 shopping session；对话上下文则是 session 维度，两者不能混为一谈。
- SearchAgent 获得偏好提示，TradeAgent 默认不注入，减少交易副作用受模糊偏好驱动。
- 读失败按“无偏好”继续；写/删失败需如实返回，不能假装已记住。

## 与教程的差异

这是结构化、显式授权的偏好记忆，不是让模型自动总结所有对话并永久保存。当前没有记忆自进化、冲突自动消解或向量记忆库。
