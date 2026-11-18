"""评估看板接口：看板配置 + 看板聚合快照（生成、恢复、核对、回滚）。

列表/详情/卡片展开共用同一个快照视图构造函数，保证入口点击与详情面板展示一致。
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.schemas import ActionPayload, ActionResult, EntryPayload
from app.services.evaluate_board import EvaluateBoardService
from app.services.evaluate_board_snapshot import EvaluateBoardSnapshotService

router = APIRouter(prefix="/api/evaluate_board", tags=["评估看板"])
service = EvaluateBoardService()
snapshots = EvaluateBoardSnapshotService()
LIST_FIELDS = ["看板编号", "看板名称", "关联实验", "展示指标", "数据范围", "刷新策略", "消费范围", "看板版本"]
STATUSES = ["草稿", "待校验", "已发布", "已停用"]


class RefreshPayload(BaseModel):
    """生成/续写快照的请求体：看板可空（空则刷新全部看板），可模拟失败实验。"""

    board_code: str | None = None
    fail_experiments: list[str] = Field(default_factory=list)
    remark: str = ""


class RecoverPayload(BaseModel):
    fail_experiments: list[str] = Field(default_factory=list)


def snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    """列表入口摘要：卡片字段与详情面板完全一致，只裁掉顶层的逐行实验快照。"""
    return {key: value for key, value in snapshot.items() if key != "实验快照"}


def csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    if text and text[0] in "=+-@":
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


@router.get("/summary")
def get_summary() -> dict[str, Any]:
    """概览指标来自已发布快照，不再是随机数。"""
    items = snapshots.list_snapshots()
    published = [item for item in items if item.get("是否发布")]
    cards = sum(int(item.get("卡片数") or 0) for item in published)
    experiments = {exp for item in published for exp in item.get("实验范围") or []}
    return {"metrics": [
        {"label": "看板快照", "value": len(items), "trend": len(published)},
        {"label": "聚合卡片", "value": cards, "trend": len(experiments)},
        {"label": "已发布口径", "value": len(snapshots.registered_calibers()), "trend": 0},
        {"label": "覆盖实验", "value": len(experiments), "trend": len(published)},
    ]}


@router.get("/calibers")
def list_calibers() -> dict[str, Any]:
    """快照实际消费的登记口径目录，供指标定义等模块跨模块读取。"""
    return {"items": snapshots.registered_calibers()}


@router.get("/snapshots")
def list_snapshots(
    board_code: str | None = None,
    status: str | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    """列表入口；compact 时只返回摘要，卡片明细按卡片接口展开。"""
    items = snapshots.list_snapshots(board_code=board_code, status=status)
    if compact:
        items = [snapshot_summary(item) for item in items]
    return {"items": items, "total": len(items)}


@router.post("/snapshots/refresh")
def refresh_snapshots(payload: RefreshPayload) -> dict[str, Any]:
    """按看板配置读取 AB 对比结果表和留存矩阵，聚合生成看板聚合快照。"""
    try:
        items = snapshots.refresh(
            board_code=payload.board_code,
            fail_experiments=payload.fail_experiments,
            remark=payload.remark,
        )
    except Exception as error:  # 看板不存在等可解释错误
        return {"ok": False, "message": str(error), "items": []}
    failed = [item for item in items if item.get("状态") == "失败"]
    message = "快照已发布" if not failed else f"{len(failed)} 份快照生成失败，已保留上一完整快照"
    return {"ok": not failed, "message": message, "items": items}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: int) -> dict:
    snapshot = snapshots.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"看板聚合快照 {snapshot_id} 不存在")
    return snapshot


@router.get("/snapshots/{snapshot_id}/cards/{card_id}")
def get_snapshot_card(snapshot_id: int, card_id: int) -> dict:
    card = snapshots.get_card(snapshot_id, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"快照 {snapshot_id} 的卡片 {card_id} 不存在")
    return card


@router.post("/snapshots/{snapshot_id}/recover")
def recover_snapshot(snapshot_id: int, payload: RecoverPayload | None = None) -> dict:
    result = snapshots.recover(snapshot_id, (payload.fail_experiments if payload else []))
    if result is None:
        raise HTTPException(status_code=404, detail=f"看板聚合快照 {snapshot_id} 不存在")
    return result


@router.post("/snapshots/{snapshot_id}/rollback")
def rollback_snapshot(snapshot_id: int) -> dict:
    result = snapshots.rollback(snapshot_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"看板聚合快照 {snapshot_id} 不存在")
    return result


@router.post("/snapshots/{snapshot_id}/verify")
def verify_snapshot(snapshot_id: int) -> dict:
    result = snapshots.verify(snapshot_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"看板聚合快照 {snapshot_id} 不存在")
    return result


@router.get("/snapshots/{snapshot_id}/verifications")
def list_verifications(snapshot_id: int) -> dict[str, Any]:
    items = snapshots.verifications(snapshot_id)
    return {"items": items, "total": len(items)}


@router.get("")
def list_results() -> dict[str, Any]:
    return {"items": service.list_results()}


@router.post("/run")
def run_analysis(payload: EntryPayload) -> dict[str, Any]:
    results = service.run_analysis(payload.values)
    return {"items": results}


@router.get("/export")
def export_entries() -> StreamingResponse:
    items = service.list_results()
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    all_keys = ["id"]
    if items:
        all_keys = list(items[0].keys())
    writer.writerow(all_keys)
    for item in items:
        writer.writerow([csv_cell(item.get(k, "")) for k in all_keys])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=evaluate_board.csv"})


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"看板配置 {entry_id} 不存在")
    return entry
