# 10 基础模块与模型配置

> [钉钉原文](https://docs.dingtalk.com/i/nodes/Amq4vjg890Bn5z3pImG35DQXJ3kdP0wQ) · 当前结论：**已落地**。

## 配置流向

[settings.py](../../app/infrastructure/settings.py) 集中读取环境变量；[composition.py](../../app/composition.py) 把配置转成具体仓库、LLM、Embedding、Reranker、缓存和队列实例；[llm.py](../../app/infrastructure/llm.py) 统一创建主/便宜模型客户端；[globex.yml](../../app/application/prompts/globex.yml) 保存 Prompt。

## 真实调用链

环境变量/.env → [Settings 定义](../../app/infrastructure/settings.py#L26) → [build_container](../../app/composition.py#L129) → [create_chat_model](../../app/infrastructure/llm.py#L217) / Factories → [MainAgentFactory.build](../../app/application/agents/main_agent.py#L106) → [Orchestrator](../../app/application/agents/orchestrator.py#L140) / [FastAPI](../../app/presentation/server.py#L54)。

## 关键配置族

- LLM：base URL、API key、主模型/便宜模型、超时与并发。
- 检索：Embedding、Qdrant、Reranker 地址与开关。
- 状态：SQLite/JSON、Redis 语义缓存、Redis Stream 队列。
- 工程治理：token 预算、熔断、漂移、Tracing 与安全护栏。

## 失败与边界

可选基础设施通常设计为失败降级；核心模型或必需配置缺失会在启动/首次调用暴露。密钥只应通过环境注入，不应写进 Prompt、仓库或日志。

## 阅读建议

不要只看 `.env.example` 推断生效行为；沿 `Settings 字段 → composition 使用点 → 具体实现构造函数` 核对每个开关是否真的接入。
