# 第28章：六轮调优与拐点分析 × 源码

- 钉钉原文：[第28章-六轮调优记录与拐点分析](https://docs.dingtalk.com/i/nodes/4lgGw3P8vRpPz59DFZO5PKB085daZ90D)
- 本地补充：[六轮调优模板](../../docs/%E5%8E%8B%E6%B5%8B%E6%96%B9%E6%A1%88%E4%B8%8E%E5%AE%B9%E9%87%8F%E8%AF%84%E4%BC%B0.md#L278)

## 可复查证据

历史报告位于 [`bench/reports`](../../bench/reports/report-P6-P7-20260822-complete.md#L1)。代码中的主要演进点包括 Redis Lua 预裁决、缓存详情、游标分页、Sentinel 热点限流和连接池定参。

## 如何读“拐点”

阶梯加压由 [`RampLoadClient.runStage()`](../../dash-bench/src/main/java/com/campusdash/bench/RampLoadClient.java#L49) 逐档记录 QPS（每秒查询数）、P95/P99 延迟和错误分类。出现吞吐不再增长而延迟/错误上升时，才说明达到当前环境容量拐点。

RampLoadClient 加压的是列表读接口，按响应完成继续发送，统计包括当档开始和结束阶段，没有自动剔除预热区间的实现。因此档位结果是该客户端与该接口的观测；要验证抢单写容量或稳态容量，还需对应负载和采样范围。

## 不能照抄的数字

报告是历史机器与依赖状态的快照，不是本轮重新压测结果。文档可解释调优因果和验证方法，但当前容量数字必须重新启动完整中间件并复压后才算现状。
