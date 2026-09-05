# 16-6 安全护栏与K8s生产化

> [钉钉原文](https://docs.dingtalk.com/i/nodes/NDoBb60VLQXykpaqcmjEDd4pJlemrZQ3) · 当前结论：**安全护栏部分落地，K8s 未落地**。

## 已有安全层

[sanitize_tool_output](D:/codes/dev_proj/globex-agent/app/infrastructure/security/content_filter.py:35) 清理的是工具返回文本，由 Harness 后置处理调用；[audit_output](D:/codes/dev_proj/globex-agent/app/infrastructure/security/output_guard.py:50) 审核最终答复；permissions.py 设置工具 allow 规则。不能把工具结果过滤写成用户输入过滤。

## 真实链路

当前可核实的路径：submit_intent → handle_intent → Agent/工具调用 → 最终文本 _guard_final_text → final.result。读取的入口代码未找到统一用户输入安全过滤。L3 只作用于实际挂 Harness 的工具；L4 在回复完成后执行，而 token.delta 在 _consume_reply 中已经发出，因此最终审核不保证此前流式片段也已脱敏。

## 当前高风险边界

下单确认主要写在 [globex.yml](../../app/application/prompts/globex.yml) 中，而工具权限对 create/cancel 自动允许；未找到服务端确认 token/状态。这意味着模型遵循性仍是关键控制点，不能称为强确认。

## K8s 对应情况

当前检索范围内没有 Deployment、Service、Ingress、HPA、PDB、NetworkPolicy、Secret 或探针 manifests。Compose 不能替代 K8s 生产化。

## 后续生产化要求

需明确密钥管理、网络隔离、资源限制、滚动发布、队列 worker 扩缩容、共享存储/库存一致性及审计；尤其要先消除当前内存商品库存的多副本不一致。
