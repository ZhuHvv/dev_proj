# 第06章：JDK 21 虚拟线程 × 源码

- 钉钉原文：[第06章-JDK 21 虚拟线程与压测对比](https://docs.dingtalk.com/i/nodes/G53mjyd80p3KODZvCeqNkn3686zbX04v)
- 本地补充：[压测方案中的虚拟线程边界](../../docs/%E5%8E%8B%E6%B5%8B%E6%96%B9%E6%A1%88%E4%B8%8E%E5%AE%B9%E9%87%8F%E8%AF%84%E4%BC%B0.md#L302)

## 已落地位置

虚拟线程用于发压端和集成测试，不是默认 Tomcat 请求线程模型。[`SpikeLoadClient`](../../dash-bench/src/main/java/com/campusdash/bench/SpikeLoadClient.java#L69) 和 [`GrabConcurrencyIT`](../../dash-bootstrap/src/test/java/com/campusdash/it/GrabConcurrencyIT.java#L83) 用 ready/fire 门闩对齐开闸；[`RampLoadClient`](../../dash-bench/src/main/java/com/campusdash/bench/RampLoadClient.java#L61) 则启动固定数量的虚拟任务，循环同步请求到截止时间，done 门闩只等待完成，不统一控制开始。

## 正确认知

虚拟线程降低“等待型并发”的线程成本，不提高 MySQL/Redis 的真实吞吐上限。数据库连接池仍是 20，Redis 连接池也有上限；请求数超过下游容量时只会形成更多排队。

## 需要验证的对比

仓库有压测结果，但没有一份在完全同环境下把平台线程与虚拟线程作为唯一变量的完整基准。因此可以确认“代码使用了虚拟线程发压”，不能把性能增益百分比当作当前源码已证明的事实。
