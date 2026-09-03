# 19-3 缓存友好写法与元提示词

> [钉钉原文](https://docs.dingtalk.com/i/nodes/0eMKjyp813y4Yga9ue4dXAjPVxAZB1Gv) · 当前结论：**缓存友好结构部分落地，元提示词自动生成未落地**。

## 已有缓存友好设计

[globex.yml](../../app/application/prompts/globex.yml) 提供稳定 system prompt；[preference_selector.py](../../app/application/memory/preference_selector.py) 把动态偏好作为后置块注入；[composition.py](../../app/composition.py) 计算 Prompt 指纹；[semantic_cache.py](../../app/infrastructure/cache/semantic_cache.py) 用指纹和用户上下文组成 namespace/key。

## 真实链路

[稳定 Prompt 文件](../../app/application/prompts/globex.yml#L3) → [启动期计算 fingerprint](../../app/composition.py#L77) → 首轮可缓存 query 构造语义 key（模型/Prompt/buyer/偏好）→ [lookup](../../app/infrastructure/cache/semantic_cache.py#L124) → miss 才 [调用 Agent](../../app/application/agents/orchestrator.py#L140) → [成功后 remember](../../app/infrastructure/cache/semantic_cache.py#L150)。

Prompt 内容变化会改变指纹，使旧缓存自然失效；偏好变化也进入键，避免不同用户/偏好错误复用。

## 缓存边界

只缓存首轮、非写操作、非上下文依赖的最终回复；工具过程与订单结果不能随意复用。Embedding 还有独立缓存，不应与最终答案缓存混为一谈。

## 元提示词缺口

当前检索范围内没有“用元 Prompt 自动生成/重写系统 Prompt”、候选版本评测与晋级流程。Prompt 仍由人工维护 YAML，自动演进应接入 [18](18_bad_case_flywheel.md) 的审计和回归门禁。
