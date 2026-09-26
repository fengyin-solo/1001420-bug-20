"""坑槽修补业务规则：状态流转、字段校验与统计口径都收在这里。

约定：
- 一次提交只算一条最新结果：同单号重复登记覆盖原记录，重复动作不重复生效；
- 状态只前进不后退，已取消是终态，取消单不再计入待安排；
- 列表、详情、统计卡、底部合计都从 store 里同一份行数据算出来；
- 每次生效的变更都会落盘，刷新或重新打开页面不会退回上一档。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "pothole"
REQUIRED_FIELDS = ["修补单号", "所在路段", "修补面积"]
EDITABLE_FIELDS = ["修补单号", "所在路段", "修补面积", "修补材料", "用料数量", "作业班组", "完成日期"]
STATUS_ORDER = ["待安排", "修补中", "已完成", "已取消"]
ACTION_RULES = {"安排修补": "修补中", "确认完成": "已完成", "取消修补": "已取消"}
ACTIVE_STATUSES = {"待安排", "修补中"}
TERMINAL_STATUSES = {"已取消"}


def _to_number(value: Any) -> float | None:
    """把输入解析成数字；空白或非数字返回 None。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    return not str(value or "").strip()


class PotholeService:
    def filtered_entries(
        self,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("修补单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self.filtered_entries(keyword, status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def summarize(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """统计卡看全量、底部合计看传入的（过滤后）行，都出自同一份数据。"""
        all_rows = store.rows(MODULE)
        month = date.today().strftime("%Y-%m")
        month_area = sum(
            area
            for row in all_rows
            if row.get("status") == "已完成"
            and str(row.get("完成日期") or "").startswith(month)
            for area in [_to_number(row.get("修补面积"))]
            if area is not None
        )
        cards = [
            {"label": "待安排修补", "value": sum(1 for row in all_rows if row.get("status") == "待安排")},
            {"label": "本月修补面积", "value": round(month_area, 2)},
            {"label": "取消单数", "value": sum(1 for row in all_rows if row.get("status") == "已取消")},
        ]
        scoped = all_rows if rows is None else rows
        totals = {
            "修补面积合计": round(sum(
                area for row in scoped
                for area in [_to_number(row.get("修补面积"))]
                if area is not None
            ), 2),
            "用料数量合计": round(sum(
                amount for row in scoped
                for amount in [_to_number(row.get("用料数量"))]
                if amount is not None
            ), 2),
        }
        return {"cards": cards, "totals": totals}

    def _validate(self, values: dict[str, Any], *, require: list[str]) -> list[str]:
        """返回不合规说明列表；空列表表示全部合规。"""
        problems: list[str] = []
        for field in require:
            if _is_blank(values.get(field)):
                problems.append(f"{field}缺失")
        if "修补面积" in values:
            if _is_blank(values.get("修补面积")):
                if "修补面积" not in require:  # require 场景前面已报过缺失
                    problems.append("修补面积缺失")
            elif _to_number(values.get("修补面积")) is None:
                problems.append("修补面积需为数字")
        if "用料数量" in values:
            amount = _to_number(values.get("用料数量"))
            if amount is None:
                problems.append("用料数量需为不小于 0 的数字")
            elif amount < 0:
                problems.append("用料数量不能为负数")
        return problems

    def _sync_flags(self, entry: dict[str, Any]) -> None:
        """状态派生字段只从当前 status 算：取消单不再计入待安排。"""
        status = str(entry.get("status") or STATUS_ORDER[0])
        entry["修补状态"] = status
        entry["pending"] = status in ACTIVE_STATUSES

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        problems = self._validate(values, require=REQUIRED_FIELDS)
        if problems:
            return None, f"提交未生效：{'、'.join(problems)}"
        rows = store.rows(MODULE)
        code = str(values.get("修补单号") or "").strip()
        existing = next((row for row in rows if str(row.get("修补单号", "")) == code), None)
        if existing is not None:
            # 同一张单子重复提交：只保留最新一次结果，不重复建档
            existing.update({field: values[field] for field in EDITABLE_FIELDS if field in values})
            self._sync_flags(existing)
            store.save(MODULE)
            return existing, "同单号修补单已存在，已用最新提交覆盖原结果"
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in EDITABLE_FIELDS if values.get(field) is not None})
        entry["status"] = STATUS_ORDER[0]
        entry["abnormal"] = False
        self._sync_flags(entry)
        rows.append(entry)
        store.save(MODULE)
        return entry, "修补单已登记"

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"修补单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于坑槽修补可执行范围"
        target = ACTION_RULES[action]
        current = str(entry.get("status") or STATUS_ORDER[0])
        updates = {field: values[field] for field in EDITABLE_FIELDS if values and field in values}
        problems = self._validate(updates, require=[])
        if problems:
            # 不合规的提交整体不生效，保留原来已生效的值
            return None, f"提交未生效，已保留原生效值：{'、'.join(problems)}"
        if current == target:
            # 重复提交同一个动作：结果已是最新，不重复生效
            return entry, f"修补单已是「{target}」，本次提交不重复生效"
        if current in TERMINAL_STATUSES:
            return None, f"修补单已取消，不能再{action}"
        if STATUS_ORDER.index(target) < STATUS_ORDER.index(current):
            return None, f"修补单已到「{current}」，不能退回「{target}」"
        entry.update(updates)
        entry["status"] = target
        self._sync_flags(entry)
        store.save(MODULE)
        return entry, f"修补单已{action}"
