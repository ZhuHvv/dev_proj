# 11 ProductSearch商品检索工具与子Agent派发触发场景

> [钉钉原文](https://docs.dingtalk.com/i/nodes/7dx2rn0JbYBAo2X7fZY3zqA3VMGjLRb3) · 当前结论：**已落地**。

## 工具与路由是两层

[product_search_tool.py](../../app/application/tools/product_search_tool.py) 把模型参数适配为 `ProductSearchSpec`；[catalog_search.py](../../app/application/usecases/catalog_search.py) 执行确定性检索；[task_dispatch_tool.py](../../app/application/tools/task_dispatch_tool.py) 负责把复杂搜索任务派给 SearchAgent。

## 真实调用链

直接模式：[MainAgent 工具集](../../app/application/agents/main_agent.py#L106) → [product_search 工具](../../app/application/tools/product_search_tool.py#L23) → [CatalogSearchUseCase.execute](../../app/application/usecases/catalog_search.py#L104)。

派发模式：[MainAgent](../../app/application/agents/main_agent.py#L106) → `TaskCreate` → [task_dispatch(search)](../../app/application/tools/task_dispatch_tool.py#L73) → [SearchAgent](../../app/application/agents/search_agent.py#L84) → [product_search](../../app/application/tools/product_search_tool.py#L23) → [CatalogSearchUseCase.execute](../../app/application/usecases/catalog_search.py#L104) → 子 Agent 总结 → MainAgent。

UseCase 内部：[execute](D:/codes/dev_proj/globex-agent/app/application/usecases/catalog_search.py:104) → [_vector_recall](D:/codes/dev_proj/globex-agent/app/application/usecases/catalog_search.py:179)：Embedding → 向量 id → 商品实体补全 → [_rerank](D:/codes/dev_proj/globex-agent/app/application/usecases/catalog_search.py:192)。向量失败、未配置或没有候选才走 _keyword_recall；精排失败保留向量候选。随后按 ship_to 和主 SKU 标价上限过滤 → top_k 截断 → _to_card。这里没有库存硬过滤，也没有在 UseCase 内读取长期偏好。

## 数据、副作用与失败

商品搜索结果包含 `recall_strategy` 和 `rerank_applied`。精排失败退为 embedding_only；向量异常或无候选退为 keyword_2gram。商品实体在精排前补全，不能把所有分支写成必经步骤。

## 与教程的差异

“何时派发”由 [globex.yml](../../app/application/prompts/globex.yml) 的软规则决定，没有 Python 分类器；MainAgent 自己也拥有 `product_search`，所以简单请求不必经过 SearchAgent。
