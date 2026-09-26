"""坑槽修补接口：维护修补单，覆盖安排修补、确认完成、取消修补等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PotholeListResult
from app.services.pothole import PotholeService

router = APIRouter(prefix="/api/pothole", tags=["坑槽修补"])

service = PotholeService()

LIST_FIELDS = ["修补单号", "所在路段", "修补面积", "修补材料", "用料数量", "作业班组", "完成日期", "修补状态"]
STATUSES = ["待安排", "修补中", "已完成", "已取消"]


@router.get("", response_model=PotholeListResult)
def list_entries(
    keyword: str | None = Query(default=None, description="按修补单号检索"),
    status: str | None = Query(default=None, description="待安排、修补中、已完成、已取消"),
    page: int = 1,
    size: int = 20,
) -> PotholeListResult:
    """列表、统计卡、底部合计一次返回，全部出自同一份数据，口径不会对不上。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    summary = service.summarize(service.filtered_entries(keyword=keyword, status=status))
    return PotholeListResult(
        items=items,
        total=total,
        page=page,
        size=size,
        cards=summary["cards"],
        totals=summary["totals"],
    )


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出坑槽修补清单：返回当前全量数据。"""
    items = service.filtered_entries()
    return {"module": "pothole", "total": len(items), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条修补单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"修补单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条修补单；缺字段或数值不合规时说明原因，原结果不受影响。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条修补单执行安排修补、确认完成、取消修补；不允许的动作会被拦下并说明原因。

    随动作一起提交的修补面积、用料数量等字段会先过校验：面积缺失或用料为负时
    整体不生效，保留原来已生效的值。
    """
    values = dict(payload.values)
    action = str(values.pop("action", "") or "").strip()
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
