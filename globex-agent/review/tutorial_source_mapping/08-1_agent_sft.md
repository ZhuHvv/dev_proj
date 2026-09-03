# 08-1 Agent SFT 冷启动训练全流程

> [钉钉原文](https://docs.dingtalk.com/i/nodes/4lgGw3P8vRpPz59DFgaNNoMM85daZ90D) · 当前结论：**训练侧内容，当前仓库未落地 SFT**。

## 可对应的数据来源

| 教程阶段 | 本仓可提供的材料 |
| --- | --- |
| 任务定义 | [eval/cases.yaml](../../eval/cases.yaml) 中的场景与 Rubric |
| 轨迹采集 | ConversationStore 保存的对话与非 token 事件 |
| 工具 schema | `app/application/tools/` 中的函数签名和 docstring |
| Prompt | [globex.yml](../../app/application/prompts/globex.yml) |

## 如果形成 SFT 数据，链路应是什么

`脱敏对话/人工示范 → 统一 messages + tool_calls 格式 → schema/事实/副作用校验 → train/validation/test 按会话切分 → 外部训练 → 模型注册 → 本仓 LLM 配置灰度 → eval 回归`。

## 当前代码边界

在线仓库只消费 OpenAI-compatible 模型接口，[llm.py](../../app/infrastructure/llm.py) 负责客户端、预算与降级。没有数据导出清洗脚本、训练配置、LoRA/全参训练、checkpoint 或模型注册表。

## 风险

订单、buyer 和对话数据可能包含敏感信息，不能直接作为训练集；工具轨迹还需过滤失败重试与错误事实。SFT 输出即便语气更稳定，也不能替代服务端权限和交易确认。
