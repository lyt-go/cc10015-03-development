"""评估看板聚合快照服务（V003）。

职责：按看板配置读取 AB 对比结果表与留存矩阵表，按实验聚合指标，生成一份
“看板聚合快照”。每个快照里的每张卡片只绑定一个已生效的登记口径，并保留
到实验快照的展开链路。

关键约束：
- 快照与消费口径同步发布：卡片先在内存里完成口径绑定和落库校验，全部通过
  才一起写入并置为已发布；任何一张卡绑不到唯一口径就整份快照失败。
- 聚合失败保留上一份完整快照：失败快照只记录本轮的完成/未完成实验，已发布
  的上一份快照原样保留，恢复时按未完成实验续写。
- 新旧口径冲突：同一指标在不同实验使用不同口径版本时，按看板统一口径重算
  （取最新已生效口径），并在卡片的实验差异说明里保留源口径。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.board_data import (
    BOARD_SCOPES,
    EXPERIMENT_BY_CODE,
    METRIC_BY_CODE,
    REGISTERED_GRANULARITIES,
    VERSION_FACTOR,
)
from app.store import store

BOARD_MODULE = "evaluate_board"
SNAPSHOT = "board_snapshot"
CARD = "board_snapshot_card"
EXP_SNAPSHOT = "experiment_snapshot"
STAGE = "board_snapshot_stage"
VERIFICATION = "board_verification"

UNIFIED_MODE = "按看板统一口径"


def _round(value: float) -> float:
    return round(float(value), 4)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _factor(version: str) -> float:
    return VERSION_FACTOR.get(version, 1.0)


class AggregationError(Exception):
    """聚合过程中的可解释错误：口径未登记、没有可聚合数据等。"""


class EvaluateBoardSnapshotService:
    # ---------- 口径目录 ----------

    @staticmethod
    def _aliases(metric_code: str) -> list[dict[str, Any]]:
        return [
            row for row in store.rows("metric_alias")
            if row.get("指标编号") == metric_code and str(row.get("口径版本") or "").strip()
        ]

    def _effective_alias(self, metric_code: str) -> dict[str, Any] | None:
        """取最新已生效口径：没有已生效版本时返回 None，聚合随即失败。"""
        rows = [row for row in self._aliases(metric_code) if row.get("status") == "已生效"]
        rows.sort(key=lambda row: (str(row.get("生效时间") or ""), str(row.get("口径版本") or "")))
        return rows[-1] if rows else None

    def _resolve_caliber(self, metric_code: str) -> dict[str, Any]:
        metric = METRIC_BY_CODE.get(metric_code)
        if metric is None:
            raise AggregationError(f"指标编码 {metric_code} 未在指标目录登记")
        granularity = str(metric.get("统计粒度") or "")
        if granularity not in REGISTERED_GRANULARITIES:
            raise AggregationError(f"指标 {metric_code} 的统计粒度「{granularity}」未登记")
        alias = self._effective_alias(metric_code)
        if alias is None:
            raise AggregationError(f"指标 {metric_code} 没有已生效的登记口径，快照不能发布")
        return {
            "指标编码": metric_code,
            "指标名称": metric["指标名称"],
            "统计粒度": granularity,
            "口径版本": str(alias["口径版本"]),
            "口径版本编号": str(alias["版本编号"]),
            "口径状态": "已生效",
        }

    def registered_calibers(self) -> list[dict[str, Any]]:
        """已发布快照消费的口径目录，供指标定义等模块跨模块读取。

        同一指标如被多份快照消费，以最新发布的那份为准，保证跨模块只看到一个版本。
        """
        self.ensure_initialized()
        seen: dict[tuple[str, str], dict[str, Any]] = {}
        snapshots = sorted(
            (row for row in store.rows(SNAPSHOT) if row.get("是否发布")),
            key=lambda row: int(row.get("id", 0)),
        )
        for snapshot in snapshots:
            for card in self._cards(snapshot["id"]):
                key = (str(card.get("指标编码")), str(card.get("口径版本")))
                seen[key] = {
                    "指标编码": card.get("指标编码"),
                    "指标名称": card.get("指标名称"),
                    "统计粒度": card.get("统计粒度"),
                    "口径版本": card.get("口径版本"),
                    "口径版本编号": card.get("口径版本编号"),
                    "口径状态": card.get("口径状态"),
                    "快照编号": snapshot.get("快照编号"),
                    "看板编号": snapshot.get("看板编号"),
                }
        return sorted(seen.values(), key=lambda item: (item["指标编码"], item["口径版本"]))

    def caliber_for_metric(self, metric_code: str) -> dict[str, Any] | None:
        for caliber in self.registered_calibers():
            if caliber["指标编码"] == metric_code:
                return caliber
        return None

    # ---------- 看板配置 ----------

    def _board_row(self, board_code: str) -> dict[str, Any]:
        board = store.find_by_field(BOARD_MODULE, "看板编号", board_code)
        if board is None:
            raise AggregationError(f"看板配置 {board_code} 不存在")
        return board

    @staticmethod
    def _scope(board: dict[str, Any]) -> tuple[list[str], list[str]]:
        code = str(board.get("看板编号") or "")
        scope = BOARD_SCOPES.get(code)
        if scope:
            return list(scope["experiments"]), list(scope["metrics"])
        experiments = [part.strip() for part in str(board.get("关联实验") or "").split(",") if part.strip()]
        metrics = [part.strip() for part in str(board.get("展示指标") or "").split(",") if part.strip()]
        return experiments, metrics

    def board_codes(self) -> list[str]:
        return [str(row.get("看板编号")) for row in store.rows(BOARD_MODULE) if row.get("看板编号")]

    # ---------- 快照读写 ----------

    def _cards(self, snapshot_id: int) -> list[dict[str, Any]]:
        return [card for card in store.rows(CARD) if card.get("看板快照id") == snapshot_id]

    def _experiment_rows(self, snapshot_id: int) -> list[dict[str, Any]]:
        return [row for row in store.rows(EXP_SNAPSHOT) if row.get("看板快照id") == snapshot_id]

    def _published_for_board(self, board_code: str) -> dict[str, Any] | None:
        rows = [
            row for row in store.rows(SNAPSHOT)
            if row.get("看板编号") == board_code and row.get("是否发布")
        ]
        return rows[-1] if rows else None

    def list_snapshots(
        self,
        *,
        board_code: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_initialized()
        rows = list(store.rows(SNAPSHOT))
        if board_code:
            rows = [row for row in rows if row.get("看板编号") == board_code]
        if status:
            rows = [row for row in rows if row.get("状态") == status]
        rows.sort(key=lambda row: int(row.get("id", 0)), reverse=True)
        return [self.snapshot_view(row) for row in rows]

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        row = store.find(SNAPSHOT, snapshot_id)
        return self.snapshot_view(row) if row else None

    def get_card(self, snapshot_id: int, card_id: int) -> dict[str, Any] | None:
        snapshot = store.find(SNAPSHOT, snapshot_id)
        if snapshot is None:
            return None
        for card in self._cards(snapshot_id):
            if int(card.get("id", 0)) == card_id:
                return self._card_view(card, self._experiment_rows(snapshot_id))
        return None

    def snapshot_view(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """列表与详情共用同一个视图构造函数，保证两处结果完全一致。"""
        view = dict(snapshot)
        experiment_rows = self._experiment_rows(int(snapshot["id"]))
        cards = []
        for card in sorted(self._cards(int(snapshot["id"])), key=lambda row: int(row.get("id", 0))):
            cards.append(self._card_view(card, experiment_rows))
        view["卡片"] = cards
        view["实验快照"] = [self._experiment_view(row) for row in sorted(
            experiment_rows, key=lambda row: (str(row.get("实验编号")), str(row.get("指标编码")),
                                              str(row.get("来源")), str(row.get("周期"))))]
        view["卡片数"] = len(cards)
        view["已绑定口径数"] = len({card.get("口径版本编号") for card in cards})
        view["覆盖实验数"] = len({row.get("实验编号") for row in experiment_rows})
        view["概览"] = {
            "卡片数": len(cards),
            "已绑定口径数": view["已绑定口径数"],
            "覆盖实验数": view["覆盖实验数"],
            "完成实验": list(snapshot.get("完成实验") or []),
            "未完成实验": list(snapshot.get("未完成实验") or []),
        }
        return view

    @staticmethod
    def _experiment_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "实验编号": row.get("实验编号"),
            "实验名称": row.get("实验名称"),
            "指标编码": row.get("指标编码"),
            "指标名称": row.get("指标名称"),
            "统计粒度": row.get("统计粒度"),
            "来源": row.get("来源"),
            "分组": row.get("分组"),
            "周期": row.get("周期"),
            "源口径版本": row.get("源口径版本"),
            "统一口径版本": row.get("统一口径版本"),
            "口径版本编号": row.get("口径版本编号"),
            "换算系数": row.get("换算系数"),
            "对照组原值": row.get("对照组原值"),
            "实验组原值": row.get("实验组原值"),
            "对照组统一值": row.get("对照组统一值"),
            "实验组统一值": row.get("实验组统一值"),
            "差异": row.get("差异"),
            "说明": row.get("说明"),
        }

    def _card_view(self, card: dict[str, Any], all_rows: list[dict[str, Any]]) -> dict[str, Any]:
        view = dict(card)
        view["实验快照"] = [
            self._experiment_view(row) for row in all_rows
            if row.get("指标编码") == card.get("指标编码")
        ]
        view["可展开实验数"] = len({row.get("实验编号") for row in view["实验快照"]})
        return view

    # ---------- 快照生成 ----------

    def ensure_initialized(self) -> None:
        """首次访问时为每个看板生成一份基线快照，让列表入口立即可见。"""
        if getattr(self, "_initializing", False):
            return
        self._initializing = True
        try:
            for board_code in self.board_codes():
                if self._published_for_board(board_code) is None:
                    already = [row for row in store.rows(SNAPSHOT) if row.get("看板编号") == board_code]
                    if already:
                        continue
                    try:
                        self.refresh(board_code=board_code)
                    except AggregationError:
                        continue
        finally:
            self._initializing = False

    def refresh(
        self,
        *,
        board_code: str | None = None,
        fail_experiments: list[str] | None = None,
        remark: str = "",
    ) -> list[dict[str, Any]]:
        """按看板生成快照；不指定看板时为全部看板各生成一份。"""
        boards = [board_code] if board_code else self.board_codes()
        results: list[dict[str, Any]] = []
        for code in boards:
            results.append(self._generate(code, fail_experiments or [], remark))
        return results

    def _generate(self, board_code: str, fail_experiments: list[str], remark: str) -> dict[str, Any]:
        board = self._board_row(board_code)
        experiments, metrics = self._scope(board)
        previous = self._published_for_board(board_code)
        sequence = len([row for row in store.rows(SNAPSHOT) if row.get("看板编号") == board_code]) + 1
        snapshot = {
            "id": store.next_id(SNAPSHOT),
            "快照编号": f"SNAP-{board_code}-{datetime.now():%Y%m%d}-{sequence:03d}",
            "看板编号": board_code,
            "看板名称": board.get("看板名称", ""),
            "状态": "生成中",
            "是否发布": False,
            "口径模式": UNIFIED_MODE,
            "实验范围": experiments,
            "指标范围": metrics,
            "完成实验": [],
            "未完成实验": list(experiments),
            "上一完整快照": previous.get("id") if previous else None,
            "上一完整快照编号": previous.get("快照编号") if previous else "",
            "卡片数": 0,
            "失败原因": "",
            "备注": remark,
            "生成时间": _now(),
            "完成时间": None,
            "回滚记录": None,
        }
        store.rows(SNAPSHOT).append(snapshot)
        for experiment in experiments:
            store.rows(STAGE).append({
                "id": store.next_id(STAGE),
                "看板快照id": snapshot["id"],
                "快照编号": snapshot["快照编号"],
                "实验编号": experiment,
                "阶段": "聚合实验",
                "状态": "待处理",
                "尝试次数": 0,
                "备注": "",
            })
        if not experiments:
            snapshot["状态"] = "失败"
            snapshot["失败原因"] = "看板没有关联实验，无法聚合"
            return self.snapshot_view(snapshot)
        self._run_experiments(snapshot, fail_experiments)
        if snapshot["状态"] != "失败":
            self._publish(snapshot)
        return self.snapshot_view(snapshot)

    def _stage_row(self, snapshot_id: int, experiment: str) -> dict[str, Any]:
        for row in store.rows(STAGE):
            if row.get("看板快照id") == snapshot_id and row.get("实验编号") == experiment:
                return row
        row = {
            "id": store.next_id(STAGE),
            "看板快照id": snapshot_id,
            "实验编号": experiment,
            "阶段": "聚合实验",
            "状态": "待处理",
            "尝试次数": 0,
            "备注": "",
        }
        store.rows(STAGE).append(row)
        return row

    def _run_experiments(self, snapshot: dict[str, Any], fail_experiments: list[str]) -> bool:
        """逐实验续写；已完成的实验直接跳过，失败时保留上一份完整快照。"""
        for experiment in list(snapshot.get("实验范围") or []):
            if experiment in (snapshot.get("完成实验") or []):
                continue
            stage = self._stage_row(int(snapshot["id"]), experiment)
            stage["尝试次数"] = int(stage.get("尝试次数", 0)) + 1
            if experiment in fail_experiments:
                stage["状态"] = "失败"
                stage["备注"] = f"实验 {experiment} 聚合失败（模拟采集超时）"
                snapshot["状态"] = "失败"
                snapshot["失败原因"] = f"实验 {experiment} 聚合失败（模拟采集超时）"
                snapshot["未完成实验"] = [
                    item for item in snapshot["实验范围"] if item not in (snapshot.get("完成实验") or [])
                ]
                return False
            stage["状态"] = "处理中"
            try:
                self._clear_experiment_rows(int(snapshot["id"]), experiment)
                self._write_experiment_rows(snapshot, experiment)
            except AggregationError as error:
                stage["状态"] = "失败"
                stage["备注"] = str(error)
                snapshot["状态"] = "失败"
                snapshot["失败原因"] = str(error)
                snapshot["未完成实验"] = [
                    item for item in snapshot["实验范围"] if item not in (snapshot.get("完成实验") or [])
                ]
                return False
            stage["状态"] = "已完成"
            stage["备注"] = "聚合完成"
            if experiment not in (snapshot.get("完成实验") or []):
                snapshot["完成实验"].append(experiment)
            snapshot["未完成实验"] = [
                item for item in snapshot["实验范围"] if item not in snapshot["完成实验"]
            ]
        return True

    def _clear_experiment_rows(self, snapshot_id: int, experiment: str) -> None:
        """续写前清掉该实验的旧半成品，避免重复行。"""
        store._tables[EXP_SNAPSHOT] = [
            row for row in store.rows(EXP_SNAPSHOT)
            if not (row.get("看板快照id") == snapshot_id and row.get("实验编号") == experiment)
        ]

    def _write_experiment_rows(self, snapshot: dict[str, Any], experiment: str) -> None:
        board_metrics = list(snapshot.get("指标范围") or [])
        if not board_metrics:
            raise AggregationError("看板没有展示指标，无法聚合")
        experiment_name = (EXPERIMENT_BY_CODE.get(experiment) or {}).get("实验名称", experiment)
        wrote = 0
        for metric_code in board_metrics:
            caliber = self._resolve_caliber(metric_code)
            target = caliber["口径版本"]
            ab_rows = [
                row for row in store.rows("ab_result")
                if row.get("实验编号") == experiment and row.get("指标编码") == metric_code
            ]
            for row in ab_rows:
                source = str(row.get("口径版本") or target)
                factor = _factor(target) / _factor(source)
                control = _round(float(row.get("对照组均值") or 0))
                treated = _round(float(row.get("实验组均值") or 0))
                control_unified = _round(control * factor)
                treated_unified = _round(treated * factor)
                note = (
                    f"{experiment} 源口径 {source} → 统一口径 {target}（换算系数 {factor:.3f}）"
                    if source != target else f"{experiment} 源口径 {target} 与看板口径一致"
                )
                store.rows(EXP_SNAPSHOT).append({
                    "id": store.next_id(EXP_SNAPSHOT),
                    "看板快照id": snapshot["id"],
                    "快照编号": snapshot["快照编号"],
                    "实验编号": experiment,
                    "实验名称": experiment_name,
                    "指标编码": metric_code,
                    "指标名称": caliber["指标名称"],
                    "统计粒度": caliber["统计粒度"],
                    "来源": "AB对比结果表",
                    "分组": "全量",
                    "周期": "-",
                    "源口径版本": source,
                    "统一口径版本": target,
                    "口径版本编号": caliber["口径版本编号"],
                    "换算系数": round(factor, 4),
                    "对照组原值": control,
                    "实验组原值": treated,
                    "对照组统一值": control_unified,
                    "实验组统一值": treated_unified,
                    "差异": _round(treated_unified - control_unified),
                    "说明": note,
                })
                wrote += 1
            retention_rows = [
                row for row in store.rows("retention_matrix")
                if row.get("实验编号") == experiment and row.get("指标编码") == metric_code
            ]
            periods = sorted({str(row.get("周期")) for row in retention_rows})
            for period in periods:
                group_rows = [row for row in retention_rows if str(row.get("周期")) == period]
                control = _round(_mean([float(row.get("留存率") or 0) for row in group_rows
                                        if row.get("分组") == "对照组"]))
                treated = _round(_mean([float(row.get("留存率") or 0) for row in group_rows
                                        if row.get("分组") == "实验组"]))
                store.rows(EXP_SNAPSHOT).append({
                    "id": store.next_id(EXP_SNAPSHOT),
                    "看板快照id": snapshot["id"],
                    "快照编号": snapshot["快照编号"],
                    "实验编号": experiment,
                    "实验名称": experiment_name,
                    "指标编码": metric_code,
                    "指标名称": caliber["指标名称"],
                    "统计粒度": caliber["统计粒度"],
                    "来源": "留存矩阵",
                    "分组": "对照/实验",
                    "周期": period,
                    "源口径版本": target,
                    "统一口径版本": target,
                    "口径版本编号": caliber["口径版本编号"],
                    "换算系数": 1.0,
                    "对照组原值": control,
                    "实验组原值": treated,
                    "对照组统一值": control,
                    "实验组统一值": treated,
                    "差异": _round(treated - control),
                    "说明": f"{experiment} 留存矩阵 {period} 按看板口径 {target} 直接汇总",
                })
                wrote += 1
        if wrote == 0:
            raise AggregationError(f"实验 {experiment} 在看板配置的指标范围内没有可聚合数据")

    # ---------- 发布与失败处理 ----------

    def _publish(self, snapshot: dict[str, Any]) -> bool:
        """先完成整份卡片的口径绑定校验，再原子写入并发布。"""
        rows = self._experiment_rows(int(snapshot["id"]))
        cards: list[dict[str, Any]] = []
        problems: list[str] = []
        for metric_code in snapshot.get("指标范围") or []:
            metric_rows = [row for row in rows if row.get("指标编码") == metric_code]
            if not metric_rows:
                continue
            try:
                card = self._build_card(snapshot, metric_code, metric_rows)
            except AggregationError as error:
                problems.append(str(error))
                continue
            cards.append(card)
        if not cards:
            problems.append("没有可聚合的指标卡片")
        versions = {card["口径版本编号"] for card in cards}
        card_metrics = [card["指标编码"] for card in cards]
        if len(card_metrics) != len(set(card_metrics)):
            problems.append("同一指标生成了多张卡片，存在口径串联风险")
        for card in cards:
            if not card.get("口径版本"):
                problems.append(f"卡片 {card.get('指标编码')} 未绑定口径版本")
            elif not card.get("口径版本已登记", False):
                problems.append(f"卡片 {card.get('指标编码')} 引用的口径未在口径注册中生效")
        if problems:
            snapshot["状态"] = "失败"
            snapshot["失败原因"] = "；".join(problems)
            snapshot["未完成实验"] = list(snapshot.get("实验范围") or [])
            return False
        # 原子发布：所有卡片一次性写入，同一时刻只暴露一份完整快照。
        for index, card in enumerate(cards, start=1):
            card["id"] = store.next_id(CARD)
            card["卡片编号"] = f"{snapshot['快照编号']}-C{index:02d}"
            card["看板快照id"] = snapshot["id"]
            card["快照编号"] = snapshot["快照编号"]
            store.rows(CARD).append(card)
        snapshot["状态"] = "已完成"
        snapshot["是否发布"] = True
        snapshot["卡片数"] = len(cards)
        snapshot["已绑定口径数"] = len(versions)
        # 快照级别也标识本份快照消费的指标口径版本，便于跨模块直接读取。
        snapshot["口径版本清单"] = [
            {
                "指标编码": card["指标编码"],
                "指标名称": card["指标名称"],
                "统计粒度": card["统计粒度"],
                "口径版本": card["口径版本"],
                "口径版本编号": card["口径版本编号"],
            }
            for card in cards
        ]
        snapshot["完成实验"] = list(snapshot.get("实验范围") or [])
        snapshot["未完成实验"] = []
        snapshot["完成时间"] = _now()
        previous = store.find(SNAPSHOT, int(snapshot.get("上一完整快照") or 0))
        if previous is not None and previous.get("是否发布"):
            previous["是否发布"] = False
            previous["被替代快照"] = snapshot["id"]
        return True

    def _build_card(self, snapshot: dict[str, Any], metric_code: str,
                    metric_rows: list[dict[str, Any]]) -> dict[str, Any]:
        caliber = self._resolve_caliber(metric_code)
        target = caliber["口径版本"]
        ab_rows = [row for row in metric_rows if row.get("来源") == "AB对比结果表"]
        retention_rows = [row for row in metric_rows if row.get("来源") == "留存矩阵"]
        if not ab_rows and not retention_rows:
            raise AggregationError(f"指标 {metric_code} 没有可聚合数据")
        source_versions = sorted({str(row.get("源口径版本")) for row in ab_rows})
        if ab_rows:
            treated = [_round(float(row.get("实验组统一值") or 0)) for row in ab_rows]
            control = [_round(float(row.get("对照组统一值") or 0)) for row in ab_rows]
            value = _round(_mean(treated))
            baseline = _round(_mean(control))
            source_label = "AB对比结果表+留存矩阵" if retention_rows else "AB对比结果表"
        else:
            treated = [_round(float(row.get("实验组统一值") or 0)) for row in retention_rows]
            control = [_round(float(row.get("对照组统一值") or 0)) for row in retention_rows]
            value = _round(_mean(treated))
            baseline = _round(_mean(control))
            source_label = "留存矩阵"
        notes = []
        for experiment in sorted({str(row.get("实验编号")) for row in metric_rows}):
            experiment_row = next(row for row in metric_rows if row.get("实验编号") == experiment)
            notes.append(str(experiment_row.get("说明")))
        conflict = len(source_versions) > 1
        retention_summary: dict[str, Any] = {}
        for period in sorted({str(row.get("周期")) for row in retention_rows}):
            period_rows = [row for row in retention_rows if str(row.get("周期")) == period]
            retention_summary[period] = {
                "对照组留存率": _round(_mean([float(row.get("对照组统一值") or 0) for row in period_rows])),
                "实验组留存率": _round(_mean([float(row.get("实验组统一值") or 0) for row in period_rows])),
                "差异": _round(_mean([float(row.get("差异") or 0) for row in period_rows])),
            }
        alias = self._effective_alias(metric_code)
        return {
            "指标编码": metric_code,
            "指标名称": caliber["指标名称"],
            "统计粒度": caliber["统计粒度"],
            "口径版本": target,
            "口径版本编号": caliber["口径版本编号"],
            "口径状态": caliber["口径状态"],
            "口径版本已登记": alias is not None and str(alias.get("口径版本")) == target,
            "口径来源": "口径注册",
            "指标值": value,
            "对比基准": baseline,
            "差异": _round(value - baseline),
            "数据来源": source_label,
            "样本实验数": len({str(row.get("实验编号")) for row in metric_rows}),
            "覆盖实验": sorted({str(row.get("实验编号")) for row in metric_rows}),
            "口径冲突": conflict,
            "冲突版本": source_versions if conflict else [],
            "处理方式": "按看板统一口径重算" if conflict else "口径一致",
            "实验差异说明": notes,
            "留存摘要": retention_summary,
        }

    # ---------- 恢复、核对、回滚 ----------

    def recover(self, snapshot_id: int, fail_experiments: list[str] | None = None) -> dict[str, Any] | None:
        snapshot = store.find(SNAPSHOT, snapshot_id)
        if snapshot is None:
            return None
        if snapshot.get("是否发布"):
            return {"快照": self.snapshot_view(snapshot), "已发布": True, "消息": "快照已完整发布，无需续写"}
        if snapshot.get("状态") not in ("失败", "生成中"):
            return {"快照": self.snapshot_view(snapshot), "已发布": False,
                    "消息": f"快照当前状态为 {snapshot.get('状态')}，不允许续写"}
        snapshot["状态"] = "生成中"
        snapshot["失败原因"] = ""
        completed = self._run_experiments(snapshot, fail_experiments or [])
        if completed:
            self._publish(snapshot)
        return {
            "快照": self.snapshot_view(snapshot),
            "已发布": bool(snapshot.get("是否发布")),
            "消息": "已按未完成实验续写并发布" if snapshot.get("是否发布") else "续写仍未完成，已保留上一完整快照",
        }

    def audit(self, snapshot_id: int) -> dict[str, Any]:
        snapshot = store.find(SNAPSHOT, snapshot_id)
        if snapshot is None:
            return {"存在": False, "残留项": ["快照不存在"], "残留数": 1}
        residues: list[str] = []
        cards = self._cards(snapshot_id)
        experiment_rows = self._experiment_rows(snapshot_id)
        if cards and not snapshot.get("是否发布"):
            residues.append(f"未发布快照存在 {len(cards)} 张已写入卡片")
        if experiment_rows and not snapshot.get("是否发布"):
            residues.append(f"未发布快照存在 {len(experiment_rows)} 行实验快照（半成品）")
        if experiment_rows and snapshot.get("状态") == "已回滚":
            residues.append(f"已回滚快照仍残留 {len(experiment_rows)} 行实验快照")
        stage_rows = [row for row in store.rows(STAGE) if row.get("看板快照id") == snapshot_id]
        incomplete_stage = [row for row in stage_rows if row.get("状态") != "已完成"]
        if incomplete_stage and snapshot.get("是否发布"):
            residues.append(f"已发布快照存在 {len(incomplete_stage)} 个未完成聚合阶段")
        elif incomplete_stage:
            residues.append(f"未发布快照存在 {len(incomplete_stage)} 个未完成聚合阶段（事务残留）")
        by_metric: dict[str, set[str]] = {}
        for card in cards:
            by_metric.setdefault(str(card.get("指标编码")), set()).add(str(card.get("口径版本")))
        for metric_code, versions in by_metric.items():
            if len(versions) > 1:
                residues.append(f"指标 {metric_code} 同时引用了 {len(versions)} 个口径版本")
        return {
            "存在": True,
            "快照编号": snapshot.get("快照编号"),
            "状态": snapshot.get("状态"),
            "是否发布": bool(snapshot.get("是否发布")),
            "卡片数": len(cards),
            "实验快照行数": len(experiment_rows),
            "未完成阶段数": len(incomplete_stage),
            "残留项": residues,
            "残留数": len(residues),
            "检查项": {
                "未发布卡片": any("卡片" in item for item in residues),
                "实验快照半成品": bool(experiment_rows) and not snapshot.get("是否发布"),
                "事务残留": bool(residues),
            },
        }

    def rollback(self, snapshot_id: int) -> dict[str, Any] | None:
        snapshot = store.find(SNAPSHOT, snapshot_id)
        if snapshot is None:
            return None
        if snapshot.get("是否发布"):
            return {
                "ok": False,
                "message": "已发布的完整快照不允许回滚，请基于新快照刷新",
                "快照": self.snapshot_view(snapshot),
                "核对": self.audit(snapshot_id),
            }
        audit_before = self.audit(snapshot_id)
        cards = self._cards(snapshot_id)
        rows = self._experiment_rows(snapshot_id)
        stages = [row for row in store.rows(STAGE) if row.get("看板快照id") == snapshot_id]
        store._tables[CARD] = [row for row in store.rows(CARD) if row.get("看板快照id") != snapshot_id]
        store._tables[EXP_SNAPSHOT] = [
            row for row in store.rows(EXP_SNAPSHOT) if row.get("看板快照id") != snapshot_id
        ]
        store._tables[STAGE] = [
            row for row in store.rows(STAGE) if row.get("看板快照id") != snapshot_id
        ]
        snapshot["状态"] = "已回滚"
        snapshot["是否发布"] = False
        snapshot["完成实验"] = []
        snapshot["未完成实验"] = list(snapshot.get("实验范围") or [])
        snapshot["回滚记录"] = {
            "回滚时间": _now(),
            "清理卡片": len(cards),
            "清理实验快照": len(rows),
            "清理阶段": len(stages),
            "残留核对": audit_before["残留项"],
            "保留上一完整快照": snapshot.get("上一完整快照"),
        }
        return {
            "ok": True,
            "message": f"已回滚未发布快照，清理 {len(cards)} 张卡片、{len(rows)} 行实验快照",
            "快照": self.snapshot_view(snapshot),
            "回滚前核对": audit_before,
        }

    def verify(self, snapshot_id: int) -> dict[str, Any] | None:
        """V003 核对：统一生成 → 按实验列 → 按实验口径映射 → 事务残留回滚 → 留档。"""
        snapshot = store.find(SNAPSHOT, snapshot_id)
        if snapshot is None:
            return None
        view = self.snapshot_view(snapshot)
        cards = view["卡片"]
        experiment_rows = view["实验快照"]
        experiments = list(snapshot.get("实验范围") or [])

        experiments_seen = {str(row.get("实验编号")) for row in experiment_rows}
        by_experiment = {
            experiment: len([row for row in experiment_rows if row.get("实验编号") == experiment])
            for experiment in experiments
        }
        step_unified = {
            "步骤": "快照生成统一",
            "通过": bool(cards) and snapshot.get("口径模式") == UNIFIED_MODE,
            "说明": f"共 {len(cards)} 张卡片，口径模式为 {snapshot.get('口径模式')}",
        }
        step_experiment = {
            "步骤": "按实验列校验",
            "通过": all(count > 0 for count in by_experiment.values()) and experiments_seen == set(experiments),
            "说明": f"按实验列计数 {by_experiment}",
        }
        mapping_ok = True
        mapping_details: list[str] = []
        for card in cards:
            card_rows = [row for row in experiment_rows if row.get("指标编码") == card.get("指标编码")]
            versions = {str(row.get("统一口径版本")) for row in card_rows}
            if versions != {str(card.get("口径版本"))}:
                mapping_ok = False
                mapping_details.append(
                    f"指标 {card.get('指标编码')} 卡片口径 {card.get('口径版本')} 与实验口径 {sorted(versions)} 不一致")
            for row in card_rows:
                if row.get("口径版本编号") != card.get("口径版本编号"):
                    mapping_ok = False
                    mapping_details.append(
                        f"实验 {row.get('实验编号')} 记录的登记口径 {row.get('口径版本编号')} 与卡片 "
                        f"{card.get('口径版本编号')} 不一致")
                if row.get("源口径版本") != row.get("统一口径版本"):
                    mapping_details.append(str(row.get("说明")))
        step_mapping = {
            "步骤": "按实验口径分对应看板聚合快照",
            "通过": mapping_ok,
            "说明": "；".join(sorted(set(mapping_details))) or "所有实验源口径均可映射到看板统一口径",
        }
        audit = self.audit(snapshot_id)
        rolled_back = False
        if audit["残留数"] and not snapshot.get("是否发布"):
            result = self.rollback(snapshot_id)
            rolled_back = bool(result and result.get("ok"))
            view = self.snapshot_view(store.find(SNAPSHOT, snapshot_id))
        step_residue = {
            "步骤": "按看板统一口径检查事务残留后回滚",
            "通过": audit["残留数"] == 0 or rolled_back,
            "说明": (
                f"发现残留：{'、'.join(audit['残留项'])}；已回滚未发布快照"
                if rolled_back else f"残留 {audit['残留数']} 项"
            ),
            "残留": audit,
            "已回滚": rolled_back,
        }
        steps = [step_unified, step_experiment, step_mapping, step_residue]
        passed = all(step["通过"] for step in steps)
        archive = {
            "id": store.next_id(VERIFICATION),
            "校验编号": f"VERIFY-{snapshot.get('快照编号')}",
            "看板快照id": snapshot_id,
            "快照编号": snapshot.get("快照编号"),
            "结论": "通过" if passed else "不通过",
            "校验步骤": steps,
            "指纹": hashlib.sha256(json.dumps(
                [[card.get("指标编码"), card.get("口径版本"), card.get("指标值")] for card in cards],
                ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
            "校验时间": _now(),
            "已回滚": rolled_back,
        }
        store.rows(VERIFICATION).append(archive)
        return {
            "ok": passed,
            "快照": view,
            "校验": steps,
            "留档": archive,
            "message": "核对通过并已留档" if passed else "核对未通过，事务残留已回滚并留档",
        }

    def verifications(self, snapshot_id: int | None = None) -> list[dict[str, Any]]:
        rows = list(store.rows(VERIFICATION))
        if snapshot_id is not None:
            rows = [row for row in rows if row.get("看板快照id") == snapshot_id]
        rows.sort(key=lambda row: int(row.get("id", 0)), reverse=True)
        return rows
