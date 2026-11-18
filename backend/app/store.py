"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import time
from typing import Any

from app.board_data import SEED_OVERRIDES
from app.seed import SEED_ROWS

# 快照与留存矩阵是看板内部消费的数据表，不作为业务模块出现在概览里。
INTERNAL_MODULES = {
    "retention_matrix",
    "board_snapshot",
    "board_snapshot_card",
    "experiment_snapshot",
    "board_snapshot_stage",
    "board_verification",
}

SNAPSHOT_MODULES = ("retention_matrix", "board_snapshot", "board_snapshot_card",
                    "experiment_snapshot", "board_snapshot_stage", "board_verification")


class Store:
    def __init__(self) -> None:
        seed: dict[str, list[dict[str, Any]]] = {name: rows for name, rows in SEED_ROWS.items()}
        seed.update(SEED_OVERRIDES)
        for name in SNAPSHOT_MODULES:
            seed.setdefault(name, [])
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in seed.items()
        }
        self._versions: dict[str, int] = {name: 1 for name in self._tables}
        self._created_at: dict[str, float] = {name: time.time() for name in self._tables}

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in INTERNAL_MODULES)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def find_by_field(self, module: str, field: str, value: Any) -> dict[str, Any] | None:
        for row in self.rows(module):
            if row.get(field) == value:
                return row
        return None

    def filter_by_field(self, module: str, field: str, value: Any) -> list[dict[str, Any]]:
        return [row for row in self.rows(module) if row.get(field) == value]

    def next_id(self, module: str) -> int:
        rows = self.rows(module)
        return max((int(r.get("id", 0)) for r in rows), default=0) + 1

    def bump_version(self, module: str) -> int:
        self._versions[module] = self._versions.get(module, 0) + 1
        return self._versions[module]

    def version(self, module: str) -> int:
        return self._versions.get(module, 1)

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
