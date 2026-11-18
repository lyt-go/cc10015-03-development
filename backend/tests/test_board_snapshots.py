"""评估看板聚合快照（V003）链路测试。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.store import store
from app.services.evaluate_board_snapshot import EvaluateBoardSnapshotService
from app.services.metric_def import MetricDefService


def _reset():
    """恢复看板底表：清空快照/阶段/留档，重建 AB 与留存矩阵样例。"""
    from app import board_data

    for name in ("board_snapshot", "board_snapshot_card", "experiment_snapshot",
                 "board_snapshot_stage", "board_verification"):
        store._tables[name] = []
    store._tables["ab_result"] = [dict(row) for row in board_data._ab_result_rows()]
    store._tables["retention_matrix"] = [dict(row) for row in board_data.RETENTION_ROWS]
    store._tables["metric_alias"] = [dict(row) for row in board_data.METRIC_ALIASES]
    store._tables["evaluate_board"] = [dict(row) for row in board_data._evaluate_board_rows()]
    return EvaluateBoardSnapshotService()


def test_snapshot_cards_bind_single_registered_caliber():
    """每张卡片只引用一个已登记口径，并保留到实验快照的展开链路。"""
    service = _reset()
    snapshot = service.refresh(board_code="EVAL-0001")[0]
    assert snapshot["状态"] == "已完成" and snapshot["是否发布"] is True
    assert snapshot["卡片"], "快照应聚合出卡片"
    for card in snapshot["卡片"]:
        assert card["口径版本"] == "v2"
        assert card["口径版本编号"] == f"ALIAS-{card['指标编码']}-v2"
        assert card["口径状态"] == "已生效"
        assert card["实验快照"], "卡片应可展开到实验快照"
        assert {row["统一口径版本"] for row in card["实验快照"]} == {card["口径版本"]}
        for row in card["实验快照"]:
            assert row["口径版本编号"] == card["口径版本编号"]


def test_version_conflict_recomputed_to_unified_caliber():
    """同一指标跨实验口径版本不同：统一口径重算并保留实验差异说明。"""
    service = _reset()
    snapshot = service.refresh(board_code="EVAL-0001")[0]
    card = next(item for item in snapshot["卡片"] if item["指标编码"] == "METR-0001")
    assert card["口径冲突"] is True
    assert set(card["冲突版本"]) == {"v1", "v2"}
    assert card["处理方式"] == "按看板统一口径重算"
    assert card["口径版本"] == "v2"
    notes = " ".join(card["实验差异说明"])
    assert "EXPE-0001" in notes and "源口径 v1" in notes
    expe1 = next(row for row in card["实验快照"] if row["实验编号"] == "EXPE-0001")
    assert expe1["源口径版本"] == "v1"
    assert expe1["统一口径版本"] == "v2"
    assert expe1["对照组原值"] != expe1["对照组统一值"]


def test_failed_aggregation_keeps_previous_published_snapshot():
    """聚合失败时保留上一完整快照，且失败快照不发布任何卡片。"""
    service = _reset()
    first = service.refresh(board_code="EVAL-0001")[0]
    failed = service.refresh(board_code="EVAL-0001", fail_experiments=["EXPE-0002"])[0]
    assert failed["状态"] == "失败"
    assert failed["是否发布"] is False
    assert failed["完成实验"] == ["EXPE-0001"]
    assert failed["未完成实验"] == ["EXPE-0002"]
    assert failed["上一完整快照"] == first["id"]
    assert service.get_snapshot(first["id"])["是否发布"] is True
    assert service.get_snapshot(first["id"])["卡片数"] == first["卡片数"]


def test_recover_resumes_from_unfinished_experiments():
    """恢复按未完成实验续写，不重复已完成实验，完成后替换上一快照。"""
    service = _reset()
    first = service.refresh(board_code="EVAL-0001")[0]
    failed = service.refresh(board_code="EVAL-0001", fail_experiments=["EXPE-0002"])[0]
    result = service.recover(failed["id"])
    assert result["已发布"] is True
    recovered = result["快照"]
    assert recovered["完成实验"] == ["EXPE-0001", "EXPE-0002"]
    assert recovered["未完成实验"] == []
    for card in recovered["卡片"]:
        experiments = {row["实验编号"] for row in card["实验快照"]}
        assert experiments == {"EXPE-0001", "EXPE-0002"}
        # 已完成的 EXPE-0001 只保留一份，未被重复续写
        expe1_rows = [row for row in card["实验快照"] if row["实验编号"] == "EXPE-0001"]
        assert len(expe1_rows) == len({row["来源"] + row["周期"] for row in expe1_rows})
    assert service.get_snapshot(first["id"])["是否发布"] is False
    assert service.registered_calibers()


def test_verify_rolls_back_residue_and_archives():
    """V003 核对：统一生成 → 按实验列 → 按实验口径映射 → 残留回滚 → 留档。"""
    service = _reset()
    failed = service.refresh(board_code="EVAL-0002",
                             fail_experiments=["EXPE-0002", "EXPE-0003"])[0]
    assert failed["状态"] == "失败"
    result = service.verify(failed["id"])
    assert result["ok"] is False
    steps = {step["步骤"]: step for step in result["校验"]}
    assert steps["快照生成统一"]["通过"] is False
    assert steps["按实验列校验"]["通过"] is False
    assert steps["按实验口径分对应看板聚合快照"]["通过"] is True
    assert steps["按看板统一口径检查事务残留后回滚"]["通过"] is True
    assert steps["按看板统一口径检查事务残留后回滚"]["已回滚"] is True
    snapshot = service.get_snapshot(failed["id"])
    assert snapshot["状态"] == "已回滚"
    assert service.audit(failed["id"])["残留数"] == 0
    archives = service.verifications(failed["id"])
    assert archives and archives[0]["结论"] == "不通过"
    assert archives[0]["已回滚"] is True


def test_audit_clean_published_snapshot():
    """已发布快照核对无事务残留，重复核对均留档。"""
    service = _reset()
    snapshot = service.refresh(board_code="EVAL-0003")[0]
    audit = service.audit(snapshot["id"])
    assert audit["残留数"] == 0
    first = service.verify(snapshot["id"])
    second = service.verify(snapshot["id"])
    assert first["ok"] is True and second["ok"] is True
    assert first["留档"]["指纹"] == second["留档"]["指纹"]
    assert len(service.verifications(snapshot["id"])) == 2
    for step in first["校验"]:
        assert step["通过"] is True


def test_metric_def_rejects_unregistered_version_and_granularity():
    """跨模块联动：指标定义读取快照口径，拒绝未登记的版本与统计粒度。"""
    service = _reset()
    service.refresh(board_code="EVAL-0001")
    metric_def = MetricDefService()
    entry, missing = metric_def.create_entry({
        "指标编号": "METR-0001", "指标名称": "支付转化率", "计算公式": "pay/order",
        "统计粒度": "日", "口径版本": "v1",
    })
    assert entry is None and "v2" in missing[0]
    entry, missing = metric_def.create_entry({
        "指标编号": "METR-0001", "指标名称": "支付转化率", "计算公式": "pay/order",
        "统计粒度": "小时", "口径版本": "v2",
    })
    assert entry is None and "统计粒度" in missing[0]
    entry, missing = metric_def.create_entry({
        "指标编号": "METR-0001", "指标名称": "支付转化率", "计算公式": "pay/order",
        "统计粒度": "日", "口径版本": "v2",
    })
    assert entry is not None, missing


def test_list_and_detail_share_same_view():
    """列表入口与详情面板共用同一份快照视图。"""
    service = _reset()
    snapshot = service.refresh(board_code="EVAL-0001")[0]
    listed = service.list_snapshots(board_code="EVAL-0001")[0]
    detail = service.get_snapshot(snapshot["id"])
    assert listed["卡片"] == detail["卡片"]
    assert listed["概览"] == detail["概览"]
    card = service.get_card(snapshot["id"], listed["卡片"][0]["id"])
    assert card["口径版本编号"] == listed["卡片"][0]["口径版本编号"]
    assert len(card["实验快照"]) == len(listed["卡片"][0]["实验快照"])


def test_refresh_without_effective_caliber_keeps_previous_snapshot():
    """口径全部回滚导致没有已生效版本时，刷新整份失败且不发布任何卡片。"""
    service = _reset()
    published = service.refresh(board_code="EVAL-0001")[0]
    for row in store.rows("metric_alias"):
        if row.get("指标编号") == "METR-0001":
            row["status"] = "已回滚"
    failed = service.refresh(board_code="EVAL-0001")[0]
    assert failed["状态"] == "失败"
    assert failed["是否发布"] is False
    assert "METR-0001" in failed["失败原因"]
    assert failed["卡片"] == []
    assert service.get_snapshot(published["id"])["是否发布"] is True
    assert service.get_snapshot(published["id"])["卡片数"] == published["卡片数"]
