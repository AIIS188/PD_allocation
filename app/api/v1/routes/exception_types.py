"""
异常类型路由 - 异常审核模块
支持异常类型的新增、删除、修改与列表查询（用于下拉选择）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.exception_type_service import ExceptionTypeService, get_exception_type_service

router = APIRouter(prefix="/exception-types", tags=["异常审核"])


class ExceptionTypeCreateRequest(BaseModel):
    type_name: str = Field(..., description="异常类型名称", min_length=1, max_length=64)


class ExceptionTypeUpdateRequest(BaseModel):
    type_name: str = Field(..., description="异常类型名称", min_length=1, max_length=64)


@router.get("/", summary="查询异常类型列表（下拉用）", response_model=dict)
async def list_exception_types(
    service: ExceptionTypeService = Depends(get_exception_type_service),
):
    """查询所有异常类型，用于下拉选择"""
    result = service.list_types()
    if result.get("success"):
        return result
    raise HTTPException(status_code=500, detail=result.get("error", "查询异常类型列表失败"))


@router.post("/", summary="新增异常类型", response_model=dict)
async def create_exception_type(
    request: ExceptionTypeCreateRequest,
    service: ExceptionTypeService = Depends(get_exception_type_service),
):
    """新增异常类型"""
    result = service.create_type(request.type_name)
    if result.get("success"):
        return result
    if "已存在" in str(result.get("error", "")):
        raise HTTPException(status_code=400, detail=result.get("error"))
    raise HTTPException(status_code=500, detail=result.get("error", "新增异常类型失败"))


@router.put("/{type_id}", summary="修改异常类型", response_model=dict)
async def update_exception_type(
    type_id: int,
    request: ExceptionTypeUpdateRequest,
    service: ExceptionTypeService = Depends(get_exception_type_service),
):
    """修改异常类型"""
    result = service.update_type(type_id, request.type_name)
    if result.get("success"):
        return result
    if "不存在" in str(result.get("error", "")):
        raise HTTPException(status_code=404, detail=result.get("error"))
    if "已存在" in str(result.get("error", "")):
        raise HTTPException(status_code=400, detail=result.get("error"))
    raise HTTPException(status_code=500, detail=result.get("error", "修改异常类型失败"))


@router.delete("/{type_id}", summary="删除异常类型", response_model=dict)
async def delete_exception_type(
    type_id: int,
    service: ExceptionTypeService = Depends(get_exception_type_service),
):
    """删除异常类型"""
    result = service.delete_type(type_id)
    if result.get("success"):
        return result
    if "不存在" in str(result.get("error", "")):
        raise HTTPException(status_code=404, detail=result.get("error"))
    raise HTTPException(status_code=500, detail=result.get("error", "删除异常类型失败"))
