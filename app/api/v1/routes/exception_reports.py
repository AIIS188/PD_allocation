"""
异常上报路由 - 异常审核模块
支持异常上报的新增、修改、删除、列表查询与详情查看
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.exception_report_service import (
    ExceptionReportService,
    get_exception_report_service,
)

router = APIRouter(prefix="/exception-reports", tags=["异常审核"])


class ExceptionReportCreateRequest(BaseModel):
    status: str = Field("待处理", description="异常状态：待处理/已处理")
    driver_name: Optional[str] = Field(None, description="司机姓名", max_length=64)
    vehicle_no: Optional[str] = Field(None, description="车牌号", max_length=32)
    phone: Optional[str] = Field(None, description="电话", max_length=32)
    exception_type_id: Optional[int] = Field(None, description="异常类型ID（下拉选择）")
    description: Optional[str] = Field(None, description="异常说明")
    reporter: Optional[str] = Field(None, description="上报人", max_length=64)
    reported_at: Optional[str] = Field(None, description="上报时间（不填则用当前时间）")


class ExceptionReportUpdateRequest(BaseModel):
    status: Optional[str] = Field(None, description="异常状态：待处理/已处理")
    driver_name: Optional[str] = Field(None, description="司机姓名", max_length=64)
    vehicle_no: Optional[str] = Field(None, description="车牌号", max_length=32)
    phone: Optional[str] = Field(None, description="电话", max_length=32)
    exception_type_id: Optional[int] = Field(None, description="异常类型ID（下拉选择）")
    description: Optional[str] = Field(None, description="异常说明")
    reporter: Optional[str] = Field(None, description="上报人", max_length=64)
    reported_at: Optional[str] = Field(None, description="上报时间")


@router.get("/", summary="查询异常上报列表", response_model=dict)
async def list_exception_reports(
    status: Optional[str] = Query(None, description="异常状态：待处理/已处理"),
    driver_name: Optional[str] = Query(None, description="司机姓名（模糊）"),
    vehicle_no: Optional[str] = Query(None, description="车牌号（模糊）"),
    exception_type_id: Optional[int] = Query(None, description="异常类型ID"),
    reporter: Optional[str] = Query(None, description="上报人（模糊）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    service: ExceptionReportService = Depends(get_exception_report_service),
):
    """分页查询异常上报列表"""
    result = service.list_reports(
        status=status,
        driver_name=driver_name,
        vehicle_no=vehicle_no,
        exception_type_id=exception_type_id,
        reporter=reporter,
        page=page,
        page_size=page_size,
    )
    if result.get("success"):
        return result
    raise HTTPException(status_code=500, detail=result.get("error", "查询异常上报列表失败"))


@router.get("/{report_id}", summary="查看异常上报详情", response_model=dict)
async def get_exception_report(
    report_id: int,
    service: ExceptionReportService = Depends(get_exception_report_service),
):
    """查看单条异常上报详情"""
    report = service.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="异常上报不存在")
    return {"success": True, "data": report}


@router.post("/", summary="新增异常上报", response_model=dict)
async def create_exception_report(
    request: ExceptionReportCreateRequest,
    service: ExceptionReportService = Depends(get_exception_report_service),
):
    """新增异常上报"""
    data = request.model_dump(exclude_unset=True)
    result = service.create_report(data)
    if result.get("success"):
        return result
    if "不存在" in str(result.get("error", "")):
        raise HTTPException(status_code=404, detail=result.get("error"))
    raise HTTPException(status_code=400, detail=result.get("error", "新增异常上报失败"))


@router.put("/{report_id}", summary="修改异常上报", response_model=dict)
async def update_exception_report(
    report_id: int,
    request: ExceptionReportUpdateRequest,
    service: ExceptionReportService = Depends(get_exception_report_service),
):
    """修改异常上报"""
    data = request.model_dump(exclude_unset=True)
    result = service.update_report(report_id, data)
    if result.get("success"):
        return result
    if "不存在" in str(result.get("error", "")):
        raise HTTPException(status_code=404, detail=result.get("error"))
    raise HTTPException(status_code=400, detail=result.get("error", "修改异常上报失败"))


@router.delete("/{report_id}", summary="删除异常上报", response_model=dict)
async def delete_exception_report(
    report_id: int,
    service: ExceptionReportService = Depends(get_exception_report_service),
):
    """删除异常上报"""
    result = service.delete_report(report_id)
    if result.get("success"):
        return result
    if "不存在" in str(result.get("error", "")):
        raise HTTPException(status_code=404, detail=result.get("error"))
    raise HTTPException(status_code=500, detail=result.get("error", "删除异常上报失败"))
