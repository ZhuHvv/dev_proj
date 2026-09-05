# 05 Cache-Breakpoint上下文压缩与缓存治理

> [钉钉原文](https://docs.dingtalk.com/i/nodes/pYLaezmVNe26kznBHPORX03GWrMqPxX6) · 当前结论：**已落地，但由三套机制共同完成**。

## 三种机制不要混淆

| 机制 | 目的 | 源码 |
| --- | --- | --- |
| 对话上下文压缩 | 控制 session 上下文长度 | [context_policy.py](../../app/application/agents/context_policy.py) |
| 最终回复语义缓存 | 相似首轮咨询直接复用答案 | [semantic_cache.py](../../app/infrastructure/cache/semantic_cache.py) |
| Embedding 缓存 | 避免相同文本重复向量化 | [cached_embedding_client.py](../../app/infrastructure/cache/cached_embedding_client.py) |

## 真实链路

[handle_intent](D:/codes/dev_proj/globex-agent/app/application/agents/orchestrator.py:140) → 恢复 Agent 并判断 has_history → [_lookup_cache](D:/codes/dev_proj/globex-agent/app/application/agents/orchestrator.py:215)。命中时审核缓存答复、发布 final.result 并返回；未命中才调用 [_build_inputs](D:/codes/dev_proj/globex-agent/app/application/agents/orchestrator.py:411) → _reply_with_retry → 最终审核 → 漂移检查 → 压缩事件 → final.result → _remember_cache。两条分支都会进入 finally 保存状态。上下文压缩由 AgentScope 使用 context_config 执行，本仓在轮末比较 summary。

## 数据、失效与失败

- Agent 摘要属于 session 状态；语义缓存跨 session，但键包含模型、Prompt 指纹、buyer 与偏好指纹。
- 写操作、上下文依赖问句和非首轮对话绕过最终回复缓存，避免复用错误结果。
- Redis/Embedding 失败按缓存未命中处理，不应阻断主链。

## 与教程的连接

教程的 Cache Breakpoint（缓存断点）在这里不是一个单独类，而是“Prompt 稳定前缀 + 状态压缩 + 两类缓存 + 指纹失效”的组合治理。
