# 16-6 安全护栏与K8s生产化

> [钉钉原文](https://docs.dingtalk.com/i/nodes/NDoBb60VLQXykpaqcmjEDd4pJlemrZQ3) · 当前结论：**安全护栏部分落地，K8s 未落地**。

## 已有安全层

[content_filter.py](../../app/infrastructure/security/content_filter.py) 提供输入/内容规则过滤；[output_guard.py](../../app/infrastructure/security/output_guard.py) 在最终回复前执行输出审核；[permissions.py](../../app/application/agents/permissions.py) 限定 AgentScope 工具权限。

## 真实链路

用户输入 → [presentation `submit_intent`](../../app/presentation/server.py#L131) / [Orchestrator](../../app/application/agents/orchestrator.py#L140) 安全检查 → [Agent/工具权限](../../app/application/agents/permissions.py#L32) → [订单 UseCase 领域校验](../../app/application/usecases/order_usecases.py#L29) → [最终文本 L4 output audit](../../app/infrastructure/security/output_guard.py#L50) → [final.result 事件](../../app/infrastructure/eventbus.py#L107)。安全不能只靠 Prompt；库存、订单状态和参数合法性仍由领域层校验。

## 当前高风险边界

下单确认主要写在 [globex.yml](../../app/application/prompts/globex.yml) 中，而工具权限对 create/cancel 自动允许；未找到服务端确认 token/状态。这意味着模型遵循性仍是关键控制点，不能称为强确认。

## K8s 对应情况

当前检索范围内没有 Deployment、Service、Ingress、HPA、PDB、NetworkPolicy、Secret 或探针 manifests。Compose 不能替代 K8s 生产化。

## 后续生产化要求

需明确密钥管理、网络隔离、资源限制、滚动发布、队列 worker 扩缩容、共享存储/库存一致性及审计；尤其要先消除当前内存商品库存的多副本不一致。
