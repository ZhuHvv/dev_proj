# 17-3 单步验证与Silent-Drift漂移检测

> [钉钉原文](https://docs.dingtalk.com/i/nodes/bva6QBXJwa2OR5DgtMzA047NWn4qY5Pr) · 当前结论：**部分落地**。

## 当前组件

[assertions.py](../../app/application/harness/assertions.py) 提供 schema 与 sequencing 断言；[loop_detector.py](../../app/application/harness/loop_detector.py) 检测重复调用；[drift_detector.py](../../app/application/harness/drift_detector.py) 对比计划、动作和结果信号；Orchestrator 在轮初/轮末管理漂移状态。

## 真实链路

[Orchestrator 轮初初始化](../../app/application/agents/orchestrator.py#L140) → 工具前后 [schema/sequencing 断言](../../app/application/harness/assertions.py#L63) → [loop 记录](../../app/application/harness/loop_detector.py#L66) → [轮末 DriftDetector.check](../../app/application/harness/drift_detector.py#L169) → violation/event → Orchestrator `finally` 清理本轮状态。

## 当前有效边界

- Schema/Sequencing/Loop 有实现，但受 Harness 实际接线范围限制。
- 漂移检测默认关闭；Orchestrator 当前主要传动作摘要和空/有限结果信号。
- composition 没有注入语义 judge，因此语义断言能力没有形成在线闭环。

## Silent Drift 为什么仍可能发生

如果工具返回“格式正确但语义错”、模型计划悄然改变或业务工具根本未经过 Harness，规则检查可能不报警。当前能力更接近可选的结构化启发式检测，而非完备验证器。

## 验证建议

用固定轨迹分别制造参数错、调用顺序错、重复调用、目标偏离和格式正确但语义错，断言在线主链事件，而不是只测 detector 类。
