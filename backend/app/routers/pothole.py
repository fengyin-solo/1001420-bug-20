"""坑槽修补接口：维护修补单，覆盖安排修补、确认完成、取消修补与结果修改。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.pothole import STATUS_ORDER, PotholeService

router = APIRouter(prefix="/api/pothole", tags=["坑槽修补"])

service = PotholeService()

LIST_FIELDS = ["修补单号", "所在路段", "修补面积", "修补材料", "用料数量", "作业班组", "完成日期", "修补状态"]
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按修补单号检索"),
    status: str | None = Query(default=None, description="待安排、修补中、已完成、已取消"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按修补单号与状态过滤坑槽修补列表；返回明细的同时给出同口径合计。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"状态需为：{'、'.join(STATUSES)}")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    summary = service.summary(keyword=keyword, status=status)
    return PageResult(items=items, total=total, page=page, size=size, summary=summary)


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    """统计卡：待安排、本月修补面积、取消单数，与列表读同一份数据。"""
    return {"cards": service.stats()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出坑槽修补清单：返回当前全部数据及合计。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "pothole", "total": total, "items": items, "summary": service.summary()}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条修补单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"修补单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条修补单，缺字段或数值不合规时说明原因而不是静默丢弃。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="修补单已登记", entry=entry)


@router.put("/{entry_id}/result", response_model=ActionResult)
def update_result(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改修补面积、用料数量等结果；非法提交保留原值并逐字段说明原因。"""
    entry, message = service.update_result(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条修补单执行安排修补、确认完成、取消修补；不允许的动作会被拦下并说明原因。

    同一动作重复提交只返回当前最新结果，不会产生重复流转。
    """
    action = str(payload.values.get("action") or "").strip()
    extra = {key: value for key, value in payload.values.items() if key != "action"}
    entry, message = service.run_action(entry_id, action, extra)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
