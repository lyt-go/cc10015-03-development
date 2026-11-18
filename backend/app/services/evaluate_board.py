"""评估看板业务规则：看板配置的登记、状态流转，以及按看板配置的聚合参数。

聚合快照的生成、恢复、核对与回滚在 ``evaluate_board_snapshot`` 中实现，
这里只保留看板配置本身的状态机与必填校验。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "evaluate_board"
REQUIRED_FIELDS = ["看板编号", "看板名称", "关联实验"]
STATUS_ORDER = ["草稿", "待校验", "已发布", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "确认发布": "已发布", "停用看板": "已停用"}
NEGATIVE_ACTIONS = ["停用看板"]


class EvaluateBoardService:
    def list_results(self) -> list[dict[str, Any]]:
        """看板配置列表（不含随机指标），聚合结果由快照接口提供。"""
        return [dict(row) for row in store.rows(MODULE)]

    def run_analysis(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """按看板配置触发一次聚合，返回本次生成的看板聚合快照（列表形态）。"""
        from app.services.evaluate_board_snapshot import EvaluateBoardSnapshotService

        service = EvaluateBoardSnapshotService()
        board_code = str(params.get("看板编号") or "").strip()
        if not board_code:
            boards = service.board_codes()
            if not boards:
                return []
            board_code = boards[0]
        failed = params.get("fail_experiments") or []
        if isinstance(failed, str):
            failed = [item.strip() for item in failed.split(",") if item.strip()]
        snapshots = service.refresh(board_code=board_code, fail_experiments=list(failed))
        return [snapshot for snapshot in snapshots]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        entry = {"id": store.next_id(MODULE)}
        for field in ["看板编号", "看板名称", "关联实验", "展示指标", "数据范围",
                      "刷新策略", "消费范围", "看板版本"]:
            entry[field] = values.get(field, "")
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        store.rows(MODULE).append(entry)
        store.bump_version(MODULE)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"看板配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于评估看板可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        store.bump_version(MODULE)
        return entry, f"看板配置已{action}"
