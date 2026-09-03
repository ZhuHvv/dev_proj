# 09-1 多平台商品数据底座：合规采买、同构与指标加工

> [钉钉原文](https://docs.dingtalk.com/i/nodes/7QG4Yx2JpLgYn5yBtQRLNgMXJ9dEq3XD) · 当前结论：**部分落地**；有统一模型和种子数据，没有多平台采买管线。

## 已有实现

[seed_products.py](../../app/infrastructure/persistence/seed_products.py) 提供约 60 个演示商品；[in_memory_repositories.py](../../app/infrastructure/persistence/in_memory_repositories.py) 提供内存商品仓库；Domain 中 `Product/Sku` 统一了标题、类目、属性、价格、币种和库存等字段。

## 当前数据流

[静态 seed 构造 Product/Sku](../../app/infrastructure/persistence/seed_products.py#L215) → 启动时载入仓库 → 构造可检索文本 → [批量 Embedding](../../app/infrastructure/embedding/openai_embedding_client.py#L39) / [Qdrant 索引](../../app/infrastructure/vector/qdrant_product_index.py#L43) → [CatalogSearchUseCase.execute](../../app/application/usecases/catalog_search.py#L104) 补全并过滤 → 商品卡片。

## 数据变化与副作用

- 下单会扣减内存 SKU 库存，取消会回补；多进程/多副本间并不共享这份库存真相。
- 向量库只保存检索载荷，价格和库存仍来自商品仓库。
- 运费关税来自静态领域规则，不是平台实时字段。

## 教程中尚未对应的部分

当前检索范围内没有平台 API/采买任务、原始层与标准层、字段映射版本、去重合并、增量 CDC、质量监控、数据血缘与合规审计。因此本章应被理解为目标数据架构；现有代码只是可运行的同构商品 MVP。
