"""坑槽修补业务规则：状态流转、结果校验、统计口径都收在这里。

约定：
- ``status`` 是唯一的状态来源，中文列「修补状态」始终与它同步，
  列表、详情、统计卡读到的状态必然一致。
- 每次动作或结果修改成功后立即落盘，最新一次提交即为唯一有效结果，
  刷新页面或重启服务都不会退回上一档。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "pothole"
REQUIRED_FIELDS = ["修补单号", "所在路段", "修补面积"]
OPTIONAL_FIELDS = ["修补材料", "用料数量", "作业班组", "完成日期"]
EDITABLE_FIELDS = ["所在路段", "修补面积", "修补材料", "用料数量", "作业班组", "完成日期"]
NUMERIC_FIELDS = {"修补面积": "面积", "用料数量": "用料数量"}
# 面积必须大于 0；用料数量允许 0，但负数不合规。
NUMERIC_RULES = {"修补面积": (lambda value: value > 0, "必须为大于 0 的数字"),
                 "用料数量": (lambda value: value >= 0, "不能为负数")}

STATUS_PENDING = "待安排"
STATUS_DOING = "修补中"
STATUS_DONE = "已完成"
STATUS_CANCELLED = "已取消"
STATUS_ORDER = [STATUS_PENDING, STATUS_DOING, STATUS_DONE, STATUS_CANCELLED]

ACTION_ARRANGE = "安排修补"
ACTION_COMPLETE = "确认完成"
ACTION_CANCEL = "取消修补"
ACTION_RULES = {
    ACTION_ARRANGE: STATUS_DOING,
    ACTION_COMPLETE: STATUS_DONE,
    ACTION_CANCEL: STATUS_CANCELLED,
}
# 每个动作允许从哪些状态出发；已在目标状态时按幂等处理，不产生新结果。
ACTION_SOURCES = {
    ACTION_ARRANGE: [STATUS_PENDING],
    ACTION_COMPLETE: [STATUS_DOING],
    ACTION_CANCEL: [STATUS_PENDING, STATUS_DOING],
}


def _sync(row: dict[str, Any]) -> None:
    """让中文状态列与内部状态保持同一个值，杜绝列表与详情显示不一致。"""
    row["修补状态"] = row.get("status")
    # 待安排是唯一需要继续跟进的口径；修补中/已完成/已取消都不计入待安排。
    row["pending"] = row.get("status") == STATUS_PENDING
    row["abnormal"] = False


def _number_value(value: Any) -> float | None:
    """把提交值解析成数字；空值、无法解析的值返回 None（缺失）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class PotholeService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filtered(keyword=keyword, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._view(row) for row in rows[start:start + size]], total

    def summary(self, *, keyword: str | None = None, status: str | None = None) -> dict[str, float]:
        """合计口径：与当前过滤后的明细同源，底部合计永远对得上明细。"""
        rows = self._filtered(keyword=keyword, status=status)
        return {
            "修补面积合计": self._trim(
                sum(_number_value(row.get("修补面积")) or 0.0 for row in rows)
            ),
            "用料数量合计": self._trim(
                sum(_number_value(row.get("用料数量")) or 0.0 for row in rows)
            ),
            "单数": float(len(rows)),
        }

    def stats(self) -> list[dict[str, Any]]:
        """统计卡口径：待安排、本月已完成修补面积、取消单数，全部从同一份数据现算。"""
        rows = store.rows(MODULE)
        today = date.today()
        month_prefix = f"{today.year:04d}-{today.month:02d}"
        month_area = 0.0
        pending = 0
        cancelled = 0
        for row in rows:
            current = row.get("status")
            if current == STATUS_PENDING:
                pending += 1
            elif current == STATUS_CANCELLED:
                cancelled += 1
            elif current == STATUS_DONE and str(row.get("完成日期") or "").startswith(month_prefix):
                month_area += _number_value(row.get("修补面积")) or 0.0
        return [
            {"label": "待安排修补", "value": pending, "unit": "单"},
            {"label": "本月修补面积", "value": self._trim(month_area), "unit": "㎡"},
            {"label": "取消单数", "value": cancelled, "unit": "单"},
        ]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return self._view(row) if row is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        area = _number_value(values.get("修补面积"))
        if area is None or not NUMERIC_RULES["修补面积"][0](area):
            return None, ["修补面积必须为大于 0 的数字"]
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["修补面积"] = self._trim(area)
        for field in OPTIONAL_FIELDS:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["用料数量"] = self._coerce_material(values.get("用料数量"))
        entry.setdefault("完成日期", "")
        entry["status"] = STATUS_PENDING
        _sync(entry)
        rows.append(entry)
        store.persist(MODULE)
        return self._view(entry), []

    def update_result(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """修改面积、用料等结果字段。

        任一数值字段缺失或为负数，整次提交都不落库，保留原来已生效的值，
        并逐字段说明哪里不合规。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"修补单 {entry_id} 不存在或已归档"
        updates, problems = self._validate_values(values)
        if problems:
            return None, "结果未生效，已保留原值：" + "；".join(problems)
        if not updates:
            return self._view(entry), "没有需要更新的结果字段"
        entry.update(updates)
        _sync(entry)
        store.persist(MODULE)
        return self._view(entry), "修补结果已更新"

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"修补单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于坑槽修补可执行范围"

        # 动作附带结果字段时先校验：结果不合规则整个提交（含状态）都不生效。
        updates, problems = self._validate_values(values or {})
        if problems:
            return None, f"动作未生效：" + "；".join(problems)

        target = ACTION_RULES[action]
        current = str(entry.get("status") or "")
        if current == target:
            # 重复提交同一动作：直接返回当前最新结果，不产生新的一条。
            return self._view(entry), f"修补单当前已是「{target}」，无需重复{action}"
        if current not in ACTION_SOURCES[action]:
            return None, f"修补单当前为「{current}」，不能执行「{action}」"

        if updates:
            entry.update(updates)
        if action == ACTION_COMPLETE and not str(entry.get("完成日期") or "").strip():
            entry["完成日期"] = date.today().isoformat()
        entry["status"] = target
        _sync(entry)
        store.persist(MODULE)
        return self._view(entry), f"修补单已{action}"

    # ---- 内部辅助 --------------------------------------------------------

    def _filtered(self, *, keyword: str | None, status: str | None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("修补单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def _validate_values(self, values: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        updates: dict[str, Any] = {}
        problems: list[str] = []
        for field in EDITABLE_FIELDS:
            if field not in values or values.get(field) is None:
                continue
            raw = values.get(field)
            if field in NUMERIC_RULES:
                number = _number_value(raw)
                label = NUMERIC_FIELDS[field]
                if number is None:
                    problems.append(f"{label}缺失或不是数字（收到：{raw!r}）")
                    continue
                rule, hint = NUMERIC_RULES[field]
                if not rule(number):
                    problems.append(f"{label}{hint}（收到：{self._trim(number)}）")
                    continue
                updates[field] = self._trim(number)
            else:
                text = str(raw).strip()
                # 文本字段留空表示本次不修改；真正需要必填的字段在登记时已拦住。
                if not text:
                    continue
                updates[field] = text
        return updates, problems

    def _coerce_material(self, value: Any) -> float:
        number = _number_value(value)
        if number is None or number < 0:
            return 0.0
        return self._trim(number)

    def _view(self, row: dict[str, Any]) -> dict[str, Any]:
        """对外视图：状态列与内部状态始终同源后再返回。"""
        _sync(row)
        return row

    @staticmethod
    def _trim(number: float) -> float:
        """去掉浮点运算产生的尾巴，让合计与明细展示稳定。"""
        return round(number, 4)
