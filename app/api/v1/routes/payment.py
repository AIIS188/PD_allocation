from fastapi import HTTPException, APIRouter, Depends, Query
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal
from enum import IntEnum

from core.database import get_conn
from core.logging import get_logger
from core.auth import get_current_user
from app.services.payment_services import (
    PaymentService,
    PaymentStatus,
    PaymentStage,
    calculate_payment_amount
)

logger = get_logger(__name__)


# ========== Pydantic 模型定义 ==========

class PaymentStageEnum(IntEnum):
    """回款阶段"""
    DEPOSIT = 0      # 定金
    DELIVERY = 1     # 到货款（90%）
    FINAL = 2        # 尾款（10%）


class CreatePaymentReq(BaseModel):
    """创建收款明细请求"""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "sales_order_id": 1001,
            "smelter_name": "某某冶炼厂",
            "contract_no": "HT-2025-001",
            "unit_price": 15000.00,
            "net_weight": 100.50,
            "material_name": "铜精矿",
            "remark": "第一季度供货"
        }
    })

    sales_order_id: int = Field(..., description="销售订单ID")
    smelter_name: str = Field(..., description="冶炼厂名称")
    contract_no: str = Field(..., description="合同编号")
    unit_price: float = Field(..., gt=0, description="合同单价（元/吨）")
    net_weight: float = Field(..., gt=0, description="净重（吨）")
    material_name: Optional[str] = Field(None, description="物料名称")
    remark: Optional[str] = Field(None, description="备注")


class RecordPaymentReq(BaseModel):
    """录入回款请求"""
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "payment_detail_id": 1,
            "payment_amount": 1356750.00,
            "payment_stage": 1,
            "payment_date": "2025-02-24",
            "payment_method": "银行转账",
            "transaction_no": "TRX20250224001",
            "remark": "到货款90%"
        }
    })

    payment_detail_id: int = Field(..., gt=0, description="收款明细ID")
    payment_amount: float = Field(..., gt=0, description="回款金额")
    payment_stage: PaymentStageEnum = Field(PaymentStageEnum.DELIVERY, description="回款阶段：0-定金, 1-到货款(90%), 2-尾款(10%)")
    payment_date: Optional[date] = Field(None, description="回款日期，默认今天")
    payment_method: Optional[str] = Field(None, description="支付方式")
    transaction_no: Optional[str] = Field(None, description="交易流水号")
    remark: Optional[str] = Field(None, description="备注")


class UpdatePaymentReq(BaseModel):
    """更新收款明细请求"""
    smelter_name: Optional[str] = Field(None, description="冶炼厂名称")
    contract_no: Optional[str] = Field(None, description="合同编号")
    material_name: Optional[str] = Field(None, description="物料名称")
    remark: Optional[str] = Field(None, description="备注")


class PaymentListQuery(BaseModel):
    """收款明细列表查询参数"""
    page: int = Field(1, ge=1, description="页码")
    size: int = Field(20, ge=1, le=100, description="每页数量")
    status: Optional[int] = Field(None, ge=0, le=3, description="状态筛选：0-未回款, 1-部分回款, 2-已结清, 3-超额回款")
    smelter_name: Optional[str] = Field(None, description="冶炼厂名称筛选")
    contract_no: Optional[str] = Field(None, description="合同编号筛选")
    start_date: Optional[date] = Field(None, description="开始日期")
    end_date: Optional[date] = Field(None, description="结束日期")
    keyword: Optional[str] = Field(None, description="关键词搜索（冶炼厂/合同号/物料）")


class PaymentResp(BaseModel):
    """收款明细响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    sales_order_id: int
    smelter_name: str
    contract_no: str
    material_name: Optional[str]
    unit_price: float
    net_weight: float
    total_amount: float
    paid_amount: float
    unpaid_amount: float
    arrival_payment_amount: Optional[float] = None
    final_payment_amount: Optional[float] = None
    arrival_paid_amount: Optional[float] = None
    final_paid_amount: Optional[float] = None
    collection_status: Optional[int] = None
    status: int
    status_name: str
    remark: Optional[str]
    created_at: datetime
    updated_at: datetime

    # 是否回款状态（计算字段：已回款金额 > 0 则为是）
    is_paid: Optional[int] = Field(None, description="是否回款：0-否, 1-是")
    # 是否支付状态（计算字段：从磅单或关联表获取）
    is_paid_out: Optional[int] = Field(None, description="是否支付：0-否, 1-是")

    # 磅单字段
    weighbill_id: Optional[int] = None
    weigh_date: Optional[str] = None
    delivery_time: Optional[str] = None
    weigh_ticket_no: Optional[str] = None
    weighbill_vehicle_no: Optional[str] = None
    weighbill_product_name: Optional[str] = None
    gross_weight: Optional[float] = None
    tare_weight: Optional[float] = None
    weighbill_net_weight: Optional[float] = None
    weighbill_unit_price: Optional[float] = None
    weighbill_total_amount: Optional[float] = None
    weighbill_image: Optional[str] = None
    ocr_status: Optional[str] = None
    is_manual_corrected: Optional[int] = None
    payment_schedule_date: Optional[str] = None
    weighbill_uploader_id: Optional[int] = None
    weighbill_uploader_name: Optional[str] = None
    weighbill_uploaded_at: Optional[str] = None

    # 销售台账/报货订单字段
    delivery_id: Optional[int] = None
    report_date: Optional[str] = None
    warehouse: Optional[str] = None
    target_factory_id: Optional[int] = None
    target_factory_name: Optional[str] = None
    delivery_quantity: Optional[float] = None
    delivery_vehicle_no: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    driver_id_card: Optional[str] = None
    has_delivery_order: Optional[str] = None
    delivery_order_image: Optional[str] = None
    source_type: Optional[str] = None
    shipper: Optional[str] = None
    payee: Optional[str] = None
    service_fee: Optional[float] = None
    # 联单费（计算字段：无联单时为150，有联单时为service_fee）
    delivery_fee: Optional[float] = None
    delivery_contract_no: Optional[str] = None
    delivery_contract_unit_price: Optional[float] = None
    delivery_total_amount: Optional[float] = None
    delivery_status: Optional[str] = None
    delivery_uploader_id: Optional[int] = None
    delivery_uploader_name: Optional[str] = None
    delivery_uploaded_at: Optional[str] = None


class PaymentListResp(BaseModel):
    """收款明细列表响应"""
    total: int
    page: int
    size: int
    items: List[PaymentResp]


class PaymentRecordResp(BaseModel):
    """回款记录响应"""
    id: int
    payment_amount: float
    payment_stage: int
    payment_stage_name: str
    payment_date: date
    payment_method: Optional[str]
    transaction_no: Optional[str]
    remark: Optional[str]
    created_at: datetime


class PaymentDetailResp(PaymentResp):
    """收款明细详情响应（含回款记录）"""
    payment_records: List[PaymentRecordResp]
    payment_count: int


class PaymentResultResp(BaseModel):
    """录入回款结果响应"""
    payment_detail_id: int
    total_amount: float
    paid_amount: float
    unpaid_amount: float
    status: int
    status_name: str
    current_payment: float
    payment_stage: int
    payment_stage_name: str


class PaymentStatsResp(BaseModel):
    """回款统计响应"""
    total_count: int
    total_amount: float
    total_paid: float
    total_unpaid: float
    collection_rate: float
    status_breakdown: List[dict]

class ContractShippingProgressResp(BaseModel):
    """合同发运进度响应"""
    contract_no: str
    smelter_name: str
    total_vehicles: int              # 总车数
    planned_total_weight: float      # 计划总吨数
    shipped_vehicles: int            # 已运车数
    remaining_vehicles: int          # 剩余车数
    shipped_weight: float            # 已运吨数
    remaining_weight: float          # 剩余吨数
    last_ship_date: Optional[str]
    progress_rate: float             # 发运进度百分比


class ContractPaymentSummaryResp(BaseModel):
    """合同回款汇总响应"""
    contract_no: str
    smelter_name: str
    order_count: int                 # 订单数量
    total_receivable: float          # 应收总额
    total_received: float            # 已收总额
    total_unreceived: float          # 未收总额
    collection_rate: float           # 回款率
    contract_status: int             # 合同整体状态
    contract_status_name: str
    status_breakdown: dict           # 状态分布
    last_payment_date: Optional[str]


class ContractOrderDetail(BaseModel):
    """合同下订单明细"""
    id: int
    sales_order_id: int
    material_name: Optional[str]
    unit_price: float
    net_weight: float
    total_amount: float
    paid_amount: float
    unpaid_amount: float
    arrival_payment_amount: Optional[float] = None
    final_payment_amount: Optional[float] = None
    arrival_paid_amount: Optional[float] = None
    final_paid_amount: Optional[float] = None
    collection_status: Optional[int] = None
    status: int
    status_name: Optional[str]
    remark: Optional[str]
    created_at: Optional[str]
    weigh_ticket_no: Optional[str]
    weigh_date: Optional[str]
    shipped_weight: Optional[float]
    payment_record_count: int


class ContractPaymentDetailResp(BaseModel):
    """合同回款明细响应"""
    contract_info: dict
    total_orders: int
    page: int
    size: int
    orders: List[ContractOrderDetail]
    payment_records: List[PaymentRecordResp]
    payment_record_count: int


# ========== 路由定义 ==========

router = APIRouter(tags=["PD收款明细管理"])


def register_pd_payment_routes(app):
    """注册收款明细路由到主应用"""
    app.include_router(router, prefix="/api/v1/payment")


def check_finance_permission(current_user: dict):
    """检查是否为财务人员（财务/会计/管理员）"""
    allowed_roles = ["管理员", "财务", "会计"]
    if current_user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="仅财务人员可操作")


def check_admin_or_finance_permission(current_user: dict):
    """检查是否为管理员或财务"""
    allowed_roles = ["管理员", "财务"]
    if current_user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="权限不足，需要管理员或财务权限")


# ========== 收款明细管理接口 ==========

@router.post("/details", summary="创建收款明细", response_model=dict)
def create_payment_detail(
    body: CreatePaymentReq,
    current_user: dict = Depends(get_current_user)
):
    """
    创建收款明细台账（根据销售业务数据生成）

    - 根据销售订单ID、冶炼厂、合同等信息生成
    - 自动计算回款总额 = 合同单价 × 净重
    - 初始状态为"未回款"
    """
    check_finance_permission(current_user)

    try:
        payment_id = PaymentService.create_payment_detail(
            sales_order_id=body.sales_order_id,
            smelter_name=body.smelter_name,
            contract_no=body.contract_no,
            unit_price=Decimal(str(body.unit_price)),
            net_weight=Decimal(str(body.net_weight)),
            material_name=body.material_name,
            remark=body.remark,
            created_by=current_user.get("id")
        )

        # 计算总额用于返回
        total_amount = calculate_payment_amount(
            Decimal(str(body.unit_price)),
            Decimal(str(body.net_weight))
        )

        return {
            "msg": "创建收款明细成功",
            "payment_id": payment_id,
            "total_amount": float(total_amount),
            "status": 0,
            "status_name": "未回款"
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("创建收款明细异常")
        raise HTTPException(status_code=500, detail="创建收款明细失败")


@router.get("/details", summary="收款明细列表", response_model=PaymentListResp)
def list_payment_details(
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    status: Optional[int] = Query(None, ge=0, le=3, description="状态筛选"),
    smelter_name: Optional[str] = Query(None, description="冶炼厂名称"),
    contract_no: Optional[str] = Query(None, description="合同编号"),
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取收款明细列表（支持分页、筛选）

    支持按状态、冶炼厂、合同号、日期范围筛选
    """
    check_finance_permission(current_user)

    try:
        result = PaymentService.list_payment_details(
            page=page,
            size=size,
            status=status,
            smelter_name=smelter_name,
            contract_no=contract_no,
            start_date=start_date,
            end_date=end_date,
            keyword=keyword
        )
        return result

    except Exception as e:
        logger.exception("查询收款明细列表异常")
        raise HTTPException(status_code=500, detail="查询失败")


@router.get("/details/{payment_id}", summary="收款明细详情", response_model=PaymentDetailResp)
def get_payment_detail(
    payment_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    获取收款明细详情（包含所有回款记录）
    """
    check_finance_permission(current_user)

    detail = PaymentService.get_payment_detail(payment_id)
    if not detail:
        raise HTTPException(status_code=404, detail="收款明细不存在")

    return detail


@router.put("/details/{payment_id}", summary="更新收款明细")
def update_payment_detail(
    payment_id: int,
    body: UpdatePaymentReq,
    current_user: dict = Depends(get_current_user)
):
    """
    更新收款明细基础信息

    注意：不允许修改金额相关字段（单价、重量、总额等）
    如需修改金额，请删除后重新创建或联系管理员
    """
    check_finance_permission(current_user)

    try:
        PaymentService.update_payment_detail(
            payment_id=payment_id,
            smelter_name=body.smelter_name,
            contract_no=body.contract_no,
            material_name=body.material_name,
            remark=body.remark,
            updated_by=current_user.get("id")
        )
        return {"msg": "更新成功"}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("更新收款明细异常")
        raise HTTPException(status_code=500, detail="更新失败")


@router.delete("/details/{payment_id}", summary="删除收款明细")
def delete_payment_detail(
    payment_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    删除收款明细

    注意：已有回款记录的明细无法删除
    """
    check_admin_or_finance_permission(current_user)

    try:
        PaymentService.delete_payment_detail(payment_id)
        return {"msg": "删除成功"}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("删除收款明细异常")
        raise HTTPException(status_code=500, detail="删除失败")


# ========== 合同发运进度接口（静态路由放在动态路由之前） ==========

@router.get("/contracts/shipping-progress", summary="合同发运进度列表", response_model=dict)
def list_contract_shipping_progress(
    contract_no: Optional[str] = Query(None, description="合同编号筛选"),
    smelter_name: Optional[str] = Query(None, description="冶炼厂名称筛选"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取合同发运进度列表
    
    统计每个合同的发运情况：
    - 总车数、总吨数（计划）
    - 已运车数、已运吨数（根据磅单）
    - 剩余车数、剩余吨数
    - 发运进度百分比
    
    关联逻辑：合同 -> 销售订单 -> 磅单
    """
    check_finance_permission(current_user)
    
    try:
        result = PaymentService.get_contract_shipping_progress(
            contract_no=contract_no,
            smelter_name=smelter_name,
            page=page,
            size=size
        )
        return {
            "msg": "查询成功",
            "data": result
        }
    except Exception as e:
        logger.exception("查询合同发运进度异常")
        raise HTTPException(status_code=500, detail="查询失败")


# ========== 合同回款汇总接口（静态路由放在动态路由之前） ==========

@router.get("/contracts/payment-summary", summary="合同回款汇总列表", response_model=dict)
def list_contract_payment_summary(
    contract_no: Optional[str] = Query(None, description="合同编号筛选"),
    smelter_name: Optional[str] = Query(None, description="冶炼厂名称筛选"),
    status: Optional[int] = Query(None, ge=0, le=3, description="状态筛选"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取合同回款汇总列表（按合同编号分组统计）
    
    统计每个合同：
    - 应收总额：合同应回款总金额
    - 已收总额：已录入的回款金额
    - 未收总额：剩余未回款金额
    - 回款率：已收/应收
    - 回款状态分布
    
    用于财务快速查看各合同的整体回款情况
    """
    check_finance_permission(current_user)
    
    try:
        result = PaymentService.get_contract_payment_summary(
            contract_no=contract_no,
            smelter_name=smelter_name,
            status=status,
            page=page,
            size=size
        )
        return {
            "msg": "查询成功",
            "data": result
        }
    except Exception as e:
        logger.exception("查询合同回款汇总异常")
        raise HTTPException(status_code=500, detail="查询失败")


# ========== 合同回款明细接口（动态路由放在静态路由之后） ==========

@router.get("/contracts/{contract_no}/payment-details", summary="合同回款明细", response_model=dict)
def get_contract_payment_details(
    contract_no: str,
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取单个合同的回款明细
    
    展示内容：
    - 合同基本信息（应收、已收、未收、回款率）
    - 该合同下所有销售订单的收款明细
    - 该合同下的所有回款记录
    
    用于查看单个合同的详细回款情况
    """
    check_finance_permission(current_user)
    
    try:
        result = PaymentService.get_contract_payment_details(
            contract_no=contract_no,
            page=page,
            size=size
        )
        return {
            "msg": "查询成功",
            "data": result
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("查询合同回款明细异常")
        raise HTTPException(status_code=500, detail="查询失败")


# ========== 回款录入接口（核心功能） ==========

@router.post("/records", summary="录入回款记录", response_model=dict)
def record_payment(
    body: RecordPaymentReq,
    current_user: dict = Depends(get_current_user)
):
    """
    录入回款记录（支持分段收款）

    Args:
        body: 回款记录请求体
        current_user: 当前用户信息

    Returns:
        录入结果信息
    """
    check_finance_permission(current_user)

    try:
        result = PaymentService.record_payment(
            payment_detail_id=body.payment_detail_id,
            payment_amount=Decimal(str(body.payment_amount)),
            payment_stage=PaymentStage(body.payment_stage),
            payment_date=body.payment_date,
            payment_method=body.payment_method,
            transaction_no=body.transaction_no,
            remark=body.remark,
            recorded_by=current_user.get("id")
        )
        return {
            "msg": "回款记录录入成功",
            "data": result
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("录入回款记录异常")
        raise HTTPException(status_code=500, detail="录入失败")