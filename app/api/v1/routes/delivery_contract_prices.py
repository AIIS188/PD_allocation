"""
报单维度：关联合同的品类及单价（从合同同步、支持改价）
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.services.delivery_contract_price_service import (
    DeliveryContractPriceService,
    get_delivery_contract_price_service,
)
from core.auth import get_current_user

router = APIRouter(prefix="/deliveries", tags=["报单合同品类单价"])


class ContractProductPriceUpdateItem(BaseModel):
    unit_price: float = Field(..., ge=0, description="新单价（元）")
    id: Optional[int] = Field(None, description="明细行 id（与 product_name 二选一）")
    product_name: Optional[str] = Field(
        None, max_length=64, description="品类名称（与 id 二选一）"
    )

    @model_validator(mode="after")
    def require_id_or_name(self):
        if self.id is None and (
            self.product_name is None or not str(self.product_name).strip()
        ):
            raise ValueError("每项须提供 id 或 product_name")
        return self


class ContractProductPricesPatchBody(BaseModel):
    items: List[ContractProductPriceUpdateItem] = Field(
        ...,
        min_length=1,
        description="至少一条；每条用 id 或 product_name 指定行",
    )


@router.get(
    "/{delivery_id}/contract-product-prices",
    summary="查询报单关联的合同品类及单价",
    response_model=dict,
)
async def list_delivery_contract_product_prices(
    delivery_id: int,
    service: DeliveryContractPriceService = Depends(get_delivery_contract_price_service),
):
    result = service.list_by_delivery(delivery_id)
    if result.get("success"):
        return result
    if "不存在" in str(result.get("error", "")):
        raise HTTPException(status_code=404, detail=result.get("error"))
    raise HTTPException(status_code=400, detail=result.get("error", "查询失败"))


@router.post(
    "/{delivery_id}/contract-product-prices/sync-from-contract",
    summary="从报单关联合同同步品类及单价（会覆盖本表已有数据）",
    response_model=dict,
)
async def sync_delivery_contract_product_prices(
    delivery_id: int,
    _: dict = Depends(get_current_user),
    service: DeliveryContractPriceService = Depends(get_delivery_contract_price_service),
):
    result = service.sync_from_contract(delivery_id)
    if result.get("success"):
        return result
    err = result.get("error", "同步失败")
    if "报单" in str(err) and "不存在" in str(err):
        raise HTTPException(status_code=404, detail=err)
    raise HTTPException(status_code=400, detail=err)


@router.patch(
    "/{delivery_id}/contract-product-prices",
    summary="批量修改本报单下各品类单价",
    response_model=dict,
)
async def patch_delivery_contract_product_prices(
    delivery_id: int,
    body: ContractProductPricesPatchBody,
    _: dict = Depends(get_current_user),
    service: DeliveryContractPriceService = Depends(get_delivery_contract_price_service),
):
    items = [it.model_dump(exclude_none=True) for it in body.items]
    result = service.update_unit_prices(delivery_id, items)
    if result.get("success"):
        return result
    err = result.get("error", "更新失败")
    if "报单" in str(err) and "不存在" in str(err):
        raise HTTPException(status_code=404, detail=err)
    raise HTTPException(status_code=400, detail=err)
