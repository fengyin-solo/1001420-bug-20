"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
被保存过的模块会落到 data/ 目录下的 JSON 文件，重启或重新打开页面后读同一份结果，
不会退回上一档。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.seed import SEED_ROWS

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class Store:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or DATA_DIR
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: self._load(name, rows) for name, rows in SEED_ROWS.items()
        }

    def _load(self, module: str, seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """优先读磁盘上已保存的结果；没有或文件损坏时回退到示例数据。"""
        path = self._data_dir / f"{module}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = None
            if isinstance(data, list):
                return [dict(row) for row in data]
        return [dict(row) for row in seed_rows]

    def save(self, module: str) -> None:
        """把指定模块的当前结果写到磁盘，之后刷新或重启都读这一份。"""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._data_dir / f"{module}.json"
        path.write_text(
            json.dumps(self.rows(module), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
