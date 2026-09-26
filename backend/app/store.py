"""数据仓库：给每个业务模块准备一份可筛选、可流转的数据。

坑槽修补的每一次动作与结果修改都会落盘到 data/store.json：
刷新页面或重启服务后读到的仍是最新一次提交的结果，不会退回上一档。
真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.seed import SEED_ROWS

DATA_FILE = Path(
    os.environ.get(
        "APP_DATA_FILE",
        Path(__file__).resolve().parent.parent / "data" / "store.json",
    )
)


class Store:
    def __init__(self) -> None:
        # 先放种子数据，再用磁盘上的最新结果整表覆盖，保证落盘结果优先。
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not DATA_FILE.exists():
            # 首次启动不预写磁盘：只有真正产生结果的模块（坑槽修补）才会落盘。
            return
        try:
            persisted = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 落盘文件损坏时不吞掉数据，保留种子数据并回写一份干净的。
            self._persist_locked()
            return
        if isinstance(persisted, dict):
            for name, rows in persisted.items():
                if isinstance(rows, list):
                    self._tables[name] = [dict(row) for row in rows if isinstance(row, dict)]

    def _persist_locked(self, module: str | None = None) -> None:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        persisted: dict[str, Any] = {}
        if DATA_FILE.exists():
            try:
                existing = json.loads(DATA_FILE.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    persisted = existing
            except (json.JSONDecodeError, OSError):
                persisted = {}
        if module is not None:
            # 只快照指定模块，不影响其他模块每次启动回到各自种子数据的口径。
            persisted[module] = self._tables.get(module, [])
        else:
            persisted = self._tables
        tmp_file = DATA_FILE.with_suffix(".json.tmp")
        tmp_file.write_text(
            json.dumps(persisted, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_file.replace(DATA_FILE)

    def persist(self, module: str | None = None) -> None:
        """把指定模块（不传则全部模块）的最新结果原子写入磁盘。"""
        with self._lock:
            self._persist_locked(module)

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

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
