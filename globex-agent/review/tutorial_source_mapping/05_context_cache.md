# 05 Cache-Breakpoint上下文压缩与缓存治理

> [钉钉原文](https://docs.dingtalk.com/i/nodes/pYLaezmVNe26kznBHPORX03GWrMqPxX6) · 当前结论：**已落地，但由三套机制共同完成**。

## 三种机制不要混淆

| 机制 | 目的 | 源码 |
| --- | --- | --- |
| 对话上下文压缩 | 控制 session 上下文长度 | [context_policy.py](../../app/application/agents/context_policy.py) |
| 最终回复语义缓存 | 相似首轮咨询直接复用答案 | [semantic_cache.py](../../app/infrastructure/cache/semantic_cache.py) |
| Embedding 缓存 | 避免相同文本重复向量化 | [cached_embedding_client.py](../../app/infrastructure/cache/cached_embedding_client.py) |

## 真实链路

[Orchestrator 构造本轮输入](../../app/application/agents/orchestrator.py#L411) → [语义缓存 lookup](../../app/infrastructure/cache/semantic_cache.py#L124) → 未命中才进入 [Agent 流式回复](../../app/application/agents/orchestrator.py#L329)；AgentScope 使用 [Context 配置](../../app/application/agents/context_policy.py#L52) 在窗口约 0.75 处压缩并保留尾部约 0.15；轮末发布 `context.compressed`，成功的可缓存首轮答复再 [写入 Redis 缓存](../../app/infrastructure/cache/semantic_cache.py#L150)。

## 数据、失效与失败

- Agent 摘要属于 session 状态；语义缓存跨 session，但键包含模型、Prompt 指纹、buyer 与偏好指纹。
- 写操作、上下文依赖问句和非首轮对话绕过最终回复缓存，避免复用错误结果。
- Redis/Embedding 失败按缓存未命中处理，不应阻断主链。

## 与教程的连接

教程的 Cache Breakpoint（缓存断点）在这里不是一个单独类，而是“Prompt 稳定前缀 + 状态压缩 + 两类缓存 + 指纹失效”的组合治理。
