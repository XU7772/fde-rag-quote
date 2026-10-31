# 工艺规则库

这份文件由工艺员维护。格式固定，`rules.py` 负责解析。

**每条规则只有四件事：** 什么条件下触发、严重程度、给业务员看的话、以及它属于哪一类。

- `level: error` —— 阻断，不允许出报价单
- `level: warn`  —— 提示，业务员可以确认后继续
- `level: info`  —— 仅记录，不打扰

条件语法（每条规则可写多个 `and`，全部满足才触发）：

```
material = 304不锈钢       材质等于（走别名归一，304 / SUS304 都认）
material != 6061-T6铝      材质不等于
process contains 镀锌      工序里包含
process lacks 去毛刺       工序里不包含
part_name contains 法兰     零件名包含
weight > 2.0               单件重量（kg）
quantity < 10              数量
delivery_days < 3          交期（天）
urgent = true              是否急单
unit_price > 500           单件价（在计价完成后才可用）
```

---

## R01 304 不锈钢不建议镀锌

- when: material = 304不锈钢
- and: process contains 镀锌
- level: warn
- message: 304 不锈钢镀锌附着力差，批量易起皮，建议改为电解抛光或直接钝化处理。

## R02 阳极氧化前必须去毛刺

- when: process contains 阳极氧化
- and: process lacks 去毛刺
- level: warn
- message: 阳极氧化前未列去毛刺工序，氧化后毛刺会变脆并造成色差，请补充。

## R03 铝件不得使用镀锌工艺

- when: material = 6061-T6铝
- and: process contains 镀锌
- level: error
- message: 铝件不能电镀锌，请改用阳极氧化或化学镀镍。

## R04 碳钢件必须有表面处理

- when: material = Q235碳钢
- and: process lacks 镀锌
- level: warn
- message: 碳钢件未列表面处理工序，交付后易锈蚀，请确认是否需要镀锌或喷塑。

## R05 45 钢件必须有防锈处理

- when: material = 45#钢
- and: process lacks 镀锌
- level: warn
- message: 45 钢件未列防锈工序，建议增加发黑或镀锌，否则运输途中会生锈。

## R06 急单交期不得少于 3 天

- when: urgent = true
- and: delivery_days < 3
- level: error
- message: 急单交期不足 3 天，产线无法排产，请与客户重新确认交期。

## R07 黄铜件不建议阳极氧化

- when: material = 黄铜H62
- and: process contains 阳极氧化
- level: warn
- message: 黄铜不适合阳极氧化，请改用钝化或镀镍。

## R08 重件需确认起重能力

- when: weight > 2.0
- level: warn
- message: 单件重量超过 2kg，请确认车间起重设备和夹具承载能力。

## R09 激光切割件必须去毛刺

- when: process contains 激光切割
- and: process lacks 去毛刺
- level: warn
- message: 激光切割件边缘存在挂渣，未列去毛刺工序，装配时会影响配合。

## R10 小批量需确认开机费

- when: quantity < 10
- level: info
- message: 单批数量不足 10 件，开机费占比高，建议向客户说明起订量。

## R11 高单价零件需二次复核

- when: unit_price > 500
- level: warn
- message: 单件报价超过 500 元，请复核重量与工艺录入是否正确。
