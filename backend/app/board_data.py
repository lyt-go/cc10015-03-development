"""评估看板消费侧的基础数据与口径目录（V003）。

这里集中放置看板聚合会读取的三张底表样例数据：
- ``ab_result``：AB 对比结果表（实验 × 指标 × 口径版本）；
- ``retention_matrix``：留存矩阵表（实验 × 指标 × 分组 × 周期）；
- ``metric_alias``：口径注册表（指标 × 口径版本 × 生效状态）。

``store`` 启动时会用 ``SEED_OVERRIDES`` 覆盖对应的示例表；看板聚合服务在
底表被清空时也会按同一份目录补充，保证快照生成统一环节有稳定的输入。

本模块只放纯数据，不导入 ``store``，避免和 ``store`` 相互 import。
"""
from __future__ import annotations

from typing import Any

# 指标定义 V003 允许的统计粒度：看板聚合快照里的卡片只引用这里的粒度。
REGISTERED_GRANULARITIES: tuple[str, ...] = ("日", "周", "月")

# 指标目录：快照卡片与指标定义模块共用同一份指标编码。
METRIC_CATALOG: list[dict[str, Any]] = [
    {
        "指标编码": "METR-0001",
        "指标名称": "支付转化率",
        "计算公式": "支付订单数 / 下单数",
        "统计粒度": "日",
        "口径版本": "v2",
    },
    {
        "指标编码": "METR-0002",
        "指标名称": "次日留存率",
        "计算公式": "次日留存用户 / 当日新增用户",
        "统计粒度": "日",
        "口径版本": "v2",
    },
    {
        "指标编码": "METR-0003",
        "指标名称": "人均GMV",
        "计算公式": "GMV / 活跃用户数",
        "统计粒度": "周",
        "口径版本": "v1",
    },
]

METRIC_BY_CODE: dict[str, dict[str, Any]] = {row["指标编码"]: row for row in METRIC_CATALOG}

# 实验目录：关联实验字段缺失时兜底，并为快照补充可读的实验名称。
EXPERIMENTS: list[dict[str, str]] = [
    {"实验编号": "EXPE-0001", "实验名称": "结算页改版"},
    {"实验编号": "EXPE-0002", "实验名称": "推荐位调优"},
    {"实验编号": "EXPE-0003", "实验名称": "会员权益改版"},
]

EXPERIMENT_BY_CODE: dict[str, dict[str, str]] = {row["实验编号"]: row for row in EXPERIMENTS}

# 看板配置：内部字段把展示用的“关联实验/展示指标”转成可聚合的范围。
BOARD_SCOPES: dict[str, dict[str, list[str]]] = {
    "EVAL-0001": {"experiments": ["EXPE-0001", "EXPE-0002"], "metrics": ["METR-0001", "METR-0002"]},
    "EVAL-0002": {"experiments": ["EXPE-0002", "EXPE-0003"], "metrics": ["METR-0002", "METR-0003"]},
    "EVAL-0003": {
        "experiments": ["EXPE-0001", "EXPE-0002", "EXPE-0003"],
        "metrics": ["METR-0001", "METR-0002", "METR-0003"],
    },
}

# 口径版本换算系数：统一口径重算时按系数把源版本取值换算到目标版本。
VERSION_FACTOR: dict[str, float] = {"v1": 1.0, "v2": 1.012, "v3": 0.992}

# AB 对比结果：EXPE-0001 的支付转化率仍用 v1，EXPE-0002 已切到 v2，
# 构成“同一指标不同口径版本”的新旧版本冲突场景。
AB_RESULTS: list[dict[str, Any]] = [
    {
        "实验编号": "EXPE-0001",
        "指标编码": "METR-0001",
        "分析指标": "支付转化率",
        "口径版本": "v1",
        "对照组均值": 0.412,
        "实验组均值": 0.458,
        "置信水平": 0.95,
        "效果方向": "正向",
    },
    {
        "实验编号": "EXPE-0001",
        "指标编码": "METR-0002",
        "分析指标": "次日留存率",
        "口径版本": "v1",
        "对照组均值": 0.331,
        "实验组均值": 0.347,
        "置信水平": 0.90,
        "效果方向": "正向",
    },
    {
        "实验编号": "EXPE-0002",
        "指标编码": "METR-0001",
        "分析指标": "支付转化率",
        "口径版本": "v2",
        "对照组均值": 0.415,
        "实验组均值": 0.451,
        "置信水平": 0.95,
        "效果方向": "正向",
    },
    {
        "实验编号": "EXPE-0002",
        "指标编码": "METR-0002",
        "分析指标": "次日留存率",
        "口径版本": "v2",
        "对照组均值": 0.335,
        "实验组均值": 0.322,
        "置信水平": 0.90,
        "效果方向": "负向",
    },
    {
        "实验编号": "EXPE-0003",
        "指标编码": "METR-0002",
        "分析指标": "次日留存率",
        "口径版本": "v1",
        "对照组均值": 0.328,
        "实验组均值": 0.349,
        "置信水平": 0.95,
        "效果方向": "正向",
    },
    {
        "实验编号": "EXPE-0003",
        "指标编码": "METR-0003",
        "分析指标": "人均GMV",
        "口径版本": "v1",
        "对照组均值": 58.2,
        "实验组均值": 63.7,
        "置信水平": 0.90,
        "效果方向": "正向",
    },
]

# 留存矩阵：周期 D1/D3/D7，按分组记录留存率。
RETENTION_ROWS: list[dict[str, Any]] = [
    {"实验编号": "EXPE-0001", "指标编码": "METR-0002", "分组": "对照组", "周期": "D1", "留存率": 0.401},
    {"实验编号": "EXPE-0001", "指标编码": "METR-0002", "分组": "对照组", "周期": "D7", "留存率": 0.213},
    {"实验编号": "EXPE-0001", "指标编码": "METR-0002", "分组": "实验组", "周期": "D1", "留存率": 0.418},
    {"实验编号": "EXPE-0001", "指标编码": "METR-0002", "分组": "实验组", "周期": "D7", "留存率": 0.226},
    {"实验编号": "EXPE-0002", "指标编码": "METR-0002", "分组": "对照组", "周期": "D1", "留存率": 0.406},
    {"实验编号": "EXPE-0002", "指标编码": "METR-0002", "分组": "对照组", "周期": "D7", "留存率": 0.219},
    {"实验编号": "EXPE-0002", "指标编码": "METR-0002", "分组": "实验组", "周期": "D1", "留存率": 0.392},
    {"实验编号": "EXPE-0002", "指标编码": "METR-0002", "分组": "实验组", "周期": "D7", "留存率": 0.205},
    {"实验编号": "EXPE-0003", "指标编码": "METR-0002", "分组": "对照组", "周期": "D1", "留存率": 0.398},
    {"实验编号": "EXPE-0003", "指标编码": "METR-0002", "分组": "对照组", "周期": "D7", "留存率": 0.211},
    {"实验编号": "EXPE-0003", "指标编码": "METR-0002", "分组": "实验组", "周期": "D1", "留存率": 0.421},
    {"实验编号": "EXPE-0003", "指标编码": "METR-0002", "分组": "实验组", "周期": "D7", "留存率": 0.232},
]

# 口径注册样例：每个指标只保留一条已生效的登记口径；AB 结果表里仍可能留有计划期
# 的旧版本（v1），快照统一到这里的登记版本后会在实验差异说明里保留旧版本。
METRIC_ALIASES: list[dict[str, Any]] = [
    {
        "版本编号": "ALIAS-METR-0001-v2",
        "指标编号": "METR-0001",
        "变更说明": "剔除退款订单后重算",
        "旧口径": "v1",
        "新口径": "v2",
        "生效时间": "2026-10-15",
        "审批状态": "已通过",
        "变更人": "metric-admin",
        "口径版本": "v2",
        "status": "已生效",
        "pending": False,
        "abnormal": False,
    },
    {
        "版本编号": "ALIAS-METR-0002-v2",
        "指标编号": "METR-0002",
        "变更说明": "剔除异常设备后重算",
        "旧口径": "v1",
        "新口径": "v2",
        "生效时间": "2026-10-20",
        "审批状态": "已通过",
        "变更人": "metric-admin",
        "口径版本": "v2",
        "status": "已生效",
        "pending": False,
        "abnormal": False,
    },
    {
        "版本编号": "ALIAS-METR-0003-v1",
        "指标编号": "METR-0003",
        "变更说明": "人均 GMV 首版",
        "旧口径": "",
        "新口径": "v1",
        "生效时间": "2026-09-10",
        "审批状态": "已通过",
        "变更人": "metric-admin",
        "口径版本": "v1",
        "status": "已生效",
        "pending": False,
        "abnormal": False,
    },
]


def _metric_def_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, metric in enumerate(METRIC_CATALOG, start=1):
        rows.append({
            "id": index,
            "status": "已生效" if index != 3 else "待校验",
            "pending": index == 3,
            "abnormal": False,
            "指标编号": metric["指标编码"],
            "指标名称": metric["指标名称"],
            "计算公式": metric["计算公式"],
            "统计粒度": metric["统计粒度"],
            "时间窗口": "最近30天",
            "基准取值": "0.35",
            "精度位数": "4",
            "口径版本": metric["口径版本"],
        })
    return rows


def _ab_result_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(AB_RESULTS, start=1):
        rows.append({
            "id": index,
            "status": "已完成" if index != 2 else "计算中",
            "pending": index == 2,
            "abnormal": index == 2,
            "报告编号": f"AB_R-{index:04d}",
            "实验编号": item["实验编号"],
            "分析指标": item["分析指标"],
            "对照组均值": item["对照组均值"],
            "实验组均值": item["实验组均值"],
            "置信水平": item["置信水平"],
            "效果方向": item["效果方向"],
            "生成时间": f"2026-11-{index:02d}",
            "指标编码": item["指标编码"],
            "口径版本": item["口径版本"],
        })
    return rows


def _evaluate_board_rows() -> list[dict[str, Any]]:
    configs = [
        {
            "id": 1,
            "status": "已发布",
            "pending": False,
            "abnormal": False,
            "看板编号": "EVAL-0001",
            "看板名称": "核心实验效果看板",
            "关联实验": "EXPE-0001,EXPE-0002",
            "展示指标": "METR-0001,METR-0002",
            "数据范围": "最近30天",
            "刷新策略": "每日 06:00",
            "消费范围": "AB对比结果表,留存矩阵",
            "看板版本": "v3",
        },
        {
            "id": 2,
            "status": "待校验",
            "pending": True,
            "abnormal": False,
            "看板编号": "EVAL-0002",
            "看板名称": "留存专项看板",
            "关联实验": "EXPE-0002,EXPE-0003",
            "展示指标": "METR-0002,METR-0003",
            "数据范围": "最近30天",
            "刷新策略": "每日 06:30",
            "消费范围": "AB对比结果表,留存矩阵",
            "看板版本": "v3",
        },
        {
            "id": 3,
            "status": "草稿",
            "pending": True,
            "abnormal": False,
            "看板编号": "EVAL-0003",
            "看板名称": "全量实验总览",
            "关联实验": "EXPE-0001,EXPE-0002,EXPE-0003",
            "展示指标": "METR-0001,METR-0002,METR-0003",
            "数据范围": "最近90天",
            "刷新策略": "每周一 07:00",
            "消费范围": "AB对比结果表,留存矩阵",
            "看板版本": "v3",
        },
    ]
    return configs


# store 启动时覆盖这些表示例数据，内部表不进入模块概览。
SEED_OVERRIDES: dict[str, list[dict[str, Any]]] = {
    "metric_def": _metric_def_rows(),
    "ab_result": _ab_result_rows(),
    "metric_alias": [dict(row) for row in METRIC_ALIASES],
    "evaluate_board": _evaluate_board_rows(),
    "retention_matrix": [dict(row) for row in RETENTION_ROWS],
}
