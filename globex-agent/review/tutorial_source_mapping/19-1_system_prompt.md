# 19-1 系统提示词架构与分级强调

> [钉钉原文](https://docs.dingtalk.com/i/nodes/7dx2rn0JbYBAo2X7fZ25bwQnVMGjLRb3) · 当前结论：**基础架构已落地**。

## 当前 Prompt 事实来源

[globex.yml](../../app/application/prompts/globex.yml) 定义 Main/Search/Trade Agent 的系统提示；[loader.py](../../app/application/prompts/loader.py) 负责加载；各 AgentFactory 在 build 时注入。

## 分层结构映射

主 Prompt 已按身份/目标、工具边界、派发准则、记忆、交易确认、事实边界和错误处理组织；Search/Trade Prompt 进一步缩小职责。Python 工具签名/docstring 提供参数级指令，领域/权限代码提供硬边界。

## 运行链路

[globex.yml](../../app/application/prompts/globex.yml#L3) → [Prompt loader](../../app/application/prompts/loader.py#L17) → [MainAgentFactory.build](../../app/application/agents/main_agent.py#L106) → system prompt + Toolkit schema → 模型决策 → ToolCall/回复。运行时偏好等动态上下文由 [Orchestrator._build_inputs](../../app/application/agents/orchestrator.py#L411) 后置注入，不直接改写稳定系统提示。

## 数据与风险

Prompt 改动会改变路由、工具选择和表达，但不会自动改变服务端权限。交易确认若只写在 Prompt 中仍是软约束；事实准确性需由工具和领域层保证。

## 当前缺口

未找到独立 Prompt 版本实体、实验分流和自动回滚。缓存通过 Prompt 内容指纹失效，但这不等于完整 PromptOps（提示词运维）平台。
