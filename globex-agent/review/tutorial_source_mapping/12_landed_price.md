# 12 到手价内联计算与关税运费规则

> [钉钉原文](https://docs.dingtalk.com/i/nodes/PwkYGxZV3ZOp3jngU9MBxd9jWAgozOKL) · 当前结论：**已落地为静态 MVP 规则**。

## 当前源码对应

[tariff_schedule.py](../../app/domain/shipping/tariff_schedule.py) 的 `quote()` 计算运费、关税与到手价；[exchange_rate.py](../../app/domain/catalog/exchange_rate.py) 负责币种换算；[catalog_search.py](../../app/application/usecases/catalog_search.py) 在组装商品卡片时内联调用报价。

## 真实计算链

商品/SKU 标价 → [目标币种换算](../../app/domain/catalog/exchange_rate.py) → [目的地/品类报价规则](../../app/domain/shipping/tariff_schedule.py#L78) → `shipping + tariff → landed_price` → [CatalogSearchUseCase 组装商品卡片](../../app/application/usecases/catalog_search.py#L104) → [product_search 工具结果](../../app/application/tools/product_search_tool.py#L23) → Agent 展示。

## 数据与副作用

报价是纯计算，不写订单；订单创建时会根据选择的 SKU 和数量执行库存与订单副作用。搜索阶段的到手价只能作为估算，不应承诺为最终海关/物流账单。

## 异常路径

缺少汇率、目的地或规则时应返回明确不可计算/回退结果，不能让模型自行编造金额。金额计算使用领域值对象，展示层再格式化，避免浮点和币种混算。

## 与教程的差异

当前规则来自源码静态表，不接实时海关税则、承运商报价或平台促销；多平台券、税号、清关模式等复杂条件尚未进入定价模型。
