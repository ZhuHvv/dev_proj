# 11 ProductSearch商品检索工具与子Agent派发触发场景

> [钉钉原文](https://docs.dingtalk.com/i/nodes/7dx2rn0JbYBAo2X7fZY3zqA3VMGjLRb3) · 当前结论：**已落地**。

## 工具与路由是两层

[product_search_tool.py](../../app/application/tools/product_search_tool.py) 把模型参数适配为 `CatalogSearchQuery`；[catalog_search.py](../../app/application/usecases/catalog_search.py) 执行确定性检索；[task_dispatch_tool.py](../../app/application/tools/task_dispatch_tool.py) 负责把复杂搜索任务派给 SearchAgent。

## 真实调用链

直接模式：[MainAgent 工具集](../../app/application/agents/main_agent.py#L106) → [product_search 工具](../../app/application/tools/product_search_tool.py#L23) → [CatalogSearchUseCase.execute](../../app/application/usecases/catalog_search.py#L104)。

派发模式：[MainAgent](../../app/application/agents/main_agent.py#L106) → `TaskCreate` → [task_dispatch(search)](../../app/application/tools/task_dispatch_tool.py#L73) → [SearchAgent](../../app/application/agents/search_agent.py#L84) → [product_search](../../app/application/tools/product_search_tool.py#L23) → [CatalogSearchUseCase.execute](../../app/application/usecases/catalog_search.py#L104) → 子 Agent 总结 → MainAgent。

UseCase 内部继续走：`query 规范化 → 偏好/条件 → vector → optional rerank → keyword fallback → 商品实体补全 → 价格库存过滤 → 到手价卡片`。

## 数据、副作用与失败

商品搜索本身只读，但会产生外部 Embedding/Qdrant/Reranker 调用和过程事件。向量或精排失败时逐级降级，工具结果应携带实际 `search_strategy`，以便评测识别静默退化。

## 与教程的差异

“何时派发”由 [globex.yml](../../app/application/prompts/globex.yml) 的软规则决定，没有 Python 分类器；MainAgent 自己也拥有 `product_search`，所以简单请求不必经过 SearchAgent。
