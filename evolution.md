# 进化史

系统每 7 天评估一次自己的配置：留下更好的，回滚更差的。适应度公式与权重写在基因组里，**系统无权修改自己的评分标准**。

## 当前状态（第 2 代）

- 适应度：**0.6117**（公式 v3，窗口 7 天）
- 深加工率：0.528
- 断言校验率：0.965
- 预测校准：0.771（来源 `all_time n=3`）
- 成本指数：0.676（每条目 0.68 次模型调用）

## 代际

| 代 | 父代 | 状态 | 适应度 | 变更 |
|---|---|---|---|---|
| 0 | — | kept | 0.5661 | — |
| 1 | 0 | kept | 0.5798 | up google-research params.max_items→19；down marginalrevolution params.max_items→11 |
| 2 | 1 | active | — | down dwarkesh params.max_items→6；down noahpinion params.max_items→6 |
