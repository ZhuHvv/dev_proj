# 19-5 Agent Skill 渐进式能力加载

> [钉钉原文](https://docs.dingtalk.com/i/nodes/ndMj49yWjXrj207OURnyxN9bJ3pmz5aA) · 当前结论：**待实现**。

## 当前 Toolkit 事实

[main_agent.py](../../app/application/agents/main_agent.py)、[search_agent.py](../../app/application/agents/search_agent.py) 和 [trade_agent.py](../../app/application/agents/trade_agent.py) 都在 Agent 构建时一次性注册固定工具集；当前检索范围内没有 `app/skills/`、Skill manifest、按任务检索 Skill 或运行时加载/卸载能力。

## 现有最接近的机制

`task_dispatch` 能按任务选择 SearchAgent/TradeAgent，从而缩小子 Agent 的工具和 Prompt；权限规则也限制可调用工具。但这是“固定 Agent/Toolkit 选择”，不是教程中的渐进式 Skill 加载。

## 若实现，建议接入点

[MainAgent 当前固定工具集](../../app/application/agents/main_agent.py#L106) 识别任务 → （未来）SkillRegistry 检索元数据 → 服务端校验权限/版本 → 加载 Skill prompt + tools → 执行 → 卸载/记录使用 → [eval](../../scripts/eval_regression.py#L134)。注册表应在 [composition 组装](../../app/composition.py#L129)，加载决策需可追踪并进入 Prompt/缓存指纹。

## 数据、安全与失败

- Skill 描述、工具 schema、版本和权限是新的持久配置；动态加载会改变 token、缓存和可用副作用。
- 不能让模型通过字符串指定任意 Python 路径或提升权限。
- 加载失败应回退到固定 Toolkit 或明确说明能力不可用；版本变化必须触发回归评测。

## 与当前路线的关系

短期可把 Search/Trade Agent 看作粗粒度能力包，但不要对外称已实现 Agent Skill。真正落地前还需注册、发现、授权、加载、观测和评测闭环。
