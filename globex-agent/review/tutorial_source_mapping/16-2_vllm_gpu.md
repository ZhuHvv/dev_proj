# 16-2 vLLM推理服务与GPU部署

> [钉钉原文](https://docs.dingtalk.com/i/nodes/nYMoO1rWxaz265gMtjZXNXdBV47Z3je9) · 当前结论：**仅落地调用边界，未落地 vLLM/GPU 服务**。

## 本仓对应位置

[settings.py](../../app/infrastructure/settings.py) 的模型 base URL/key/name 允许连接 OpenAI-compatible 服务；[llm.py](../../app/infrastructure/llm.py) 构造推理客户端；Reranker 也通过独立 HTTP base URL 接入。

## 如果外接 vLLM，调用链

[MainAgentFactory](../../app/application/agents/main_agent.py#L59) / 子 Agent Factory → [ThrottledChatModel 调用入口](../../app/infrastructure/llm.py#L59) → [上游 OpenAI-compatible HTTP](../../app/infrastructure/llm.py#L94) → 外部 vLLM → stream/non-stream 响应 → AgentScope。

## 当前缺失

[docker-compose.yaml](../../docker/docker-compose.yaml) 中没有 vLLM service、GPU device reservation、模型卷、tensor parallel、显存监控或预热探针；仓库也没有模型权重下载与部署脚本。

## 工程边界

本仓只应负责接口契约、超时、并发、预算、降级和可观测性。GPU 调度、权重生命周期和推理容量属于外部模型服务。接入后需用真实并发测 TTFT（首 token 延迟）、吞吐、显存和长上下文 OOM，而不能只验证 API 可通。
