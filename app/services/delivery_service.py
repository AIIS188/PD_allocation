"""
销售台账/报货订单服务
"""
import logging
import os
import re
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from app.services.contract_service import get_conn
from app.services.customer_service import CustomerService

logger = logging.getLogger(__name__)

from app.core.paths import UPLOADS_DIR

# 使用绝对路径，避免工作目录变化导致的问题
UPLOAD_DIR = UPLOADS_DIR / "delivery_orders"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class DeliveryService:
    """报货订单服务"""

    def _get_upload_status(self, image_path: Optional[str]) -> str:
        if image_path and os.path.exists(image_path):
            return "联单已上传"
        return "联单未上传"

    def _determine_source_type(self, has_order: str, uploaded_by: str = None) -> str:
        """
        确定来源类型
        - 有联单 -> 司机
        - 无联单 -> 公司
        - 公司人员上传有联单 -> 可指定为公司
        """
        if has_order == '有':
            if uploaded_by == '公司':
                return '公司'
            return '司机'
        else:
            return '公司'

    def _calculate_service_fee(self, has_delivery_order: str) -> Decimal:
        """
        计算联单费
        - 无联单：150元
        - 有联单：0元
        """
        if has_delivery_order == '无':
            return Decimal('150')
        return Decimal('0')

    def _calculate_price(self, factory_name: str, product_name: str, quantity: Decimal) -> tuple:
        """
        关联合同计算价格
        返回: (contract_no, unit_price, total_amount)
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM pd_customers WHERE smelter_name = %s",
                        (factory_name,)
                    )
                    customer = cur.fetchone()
                    if not customer:
                        return None, None, None

                    cur.execute("""
                        SELECT contract_no, unit_price 
                        FROM pd_contracts 
                        WHERE smelter_company = %s 
                        AND status = '生效中'
                        AND contract_date <= CURDATE()
                        AND (end_date IS NULL OR end_date >= CURDATE())
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, (factory_name,))

                    contract = cur.fetchone()
                    if not contract:
                        return None, None, None

                    contract_no, unit_price = contract
                    if unit_price and quantity:
                        total = Decimal(str(unit_price)) * Decimal(str(quantity))
                    else:
                        total = None

                    return contract_no, float(unit_price) if unit_price else None, float(total) if total else None

        except Exception as e:
            logger.error(f"计算价格失败: {e}")
            return None, None, None

    def _get_contract_price_by_product(self, contract_no: str, product_name: str) -> Optional[float]:
        """
        根据合同编号和品种获取单价
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT p.unit_price 
                        FROM pd_contract_products p
                        JOIN pd_contracts c ON p.contract_id = c.id
                        WHERE c.contract_no = %s 
                        AND p.product_name = %s
                        AND p.unit_price IS NOT NULL
                        LIMIT 1
                    """, (contract_no, product_name))

                    row = cur.fetchone()
                    if row and row[0]:
                        return float(row[0])
                    return None
        except Exception as e:
            logger.error(f"获取品种单价失败: {e}")
            return None

    def _create_pending_weighbills(self, delivery_id: int, contract_no: str,
                                   products: List[str], vehicle_no: str,
                                   uploader_id: int, uploader_name: str) -> bool:
        """
        为每个品种创建待上传磅单记录
        一个品种一条记录，状态为"待上传磅单"
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    created_count = 0
                    for product_name in products:
                        # 检查是否已存在（防重复）
                        cur.execute("""
                            SELECT id FROM pd_weighbills 
                            WHERE delivery_id = %s AND product_name = %s
                        """, (delivery_id, product_name))

                        if cur.fetchone():
                            logger.warning(f"品种 {product_name} 的磅单已存在，跳过")
                            continue

                        # 获取该品种的合同单价
                        unit_price = self._get_contract_price_by_product(contract_no, product_name)

                        cur.execute("""
                            INSERT INTO pd_weighbills 
                            (delivery_id, contract_no, vehicle_no, product_name, 
                             unit_price, upload_status, ocr_status, 
                             uploader_id, uploader_name, uploaded_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        """, (
                            delivery_id,
                            contract_no,
                            vehicle_no,
                            product_name,
                            unit_price,
                            '待上传',
                            '待上传磅单',
                            uploader_id,
                            uploader_name
                        ))
                        created_count += 1

                    logger.info(f"为报单 {delivery_id} 创建了 {created_count} 条待上传磅单记录")
                    return True

        except Exception as e:
            logger.error(f"创建待上传磅单记录失败: {e}")
            return False

    def check_duplicate_in_24h(self, driver_phone: str, driver_id_card: str, exclude_id: int = None) -> Dict[str, Any]:
        """
        检查同一司机24小时内是否已报单
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    conditions = ["created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)"]
                    params = []

                    if driver_phone:
                        conditions.append("(driver_phone = %s OR driver_id_card = %s)")
                        params.extend([driver_phone, driver_phone])
                    if driver_id_card:
                        conditions.append("(driver_phone = %s OR driver_id_card = %s)")
                        params.extend([driver_id_card, driver_id_card])

                    if exclude_id:
                        conditions.append("id != %s")
                        params.append(exclude_id)

                    where_sql = "(" + " OR ".join(conditions[1:]) + ")" if len(conditions) > 1 else "1=1"
                    where_sql = f"{conditions[0]} AND ({where_sql})"

                    cur.execute(f"""
                        SELECT id, contract_no, report_date, vehicle_no, driver_name, 
                               driver_phone, driver_id_card, created_at
                        FROM pd_deliveries
                        WHERE {where_sql}
                        ORDER BY created_at DESC
                    """, tuple(params))

                    columns = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()

                    existing_orders = []
                    for row in rows:
                        order = dict(zip(columns, row))
                        for key in ['report_date', 'created_at']:
                            if order.get(key):
                                order[key] = str(order[key])
                        existing_orders.append(order)

                    return {
                        "is_duplicate": len(existing_orders) > 0,
                        "existing_orders": existing_orders,
                        "duplicate_count": len(existing_orders)
                    }

        except Exception as e:
            logger.error(f"检查重复报单失败: {e}")
            return {"is_duplicate": False, "existing_orders": [], "duplicate_count": 0, "error": str(e)}

    def _build_operations(self, has_delivery_order: str, upload_status: str, image_path: Optional[str]) -> Dict[str, bool]:
        """
        构建操作权限标记
        """
        has_image = image_path and os.path.exists(image_path)
        is_uploaded = upload_status == '已上传' or has_image

        return {
            "can_upload": not is_uploaded,
            "can_modify": is_uploaded,
            "can_view": is_uploaded
        }

    def create_delivery(self, data: Dict, image_file: bytes = None,
                        current_user: dict = None, confirm_flag: bool = False) -> Dict[str, Any]:
        """创建报货订单"""
        image_path = None
        temp_file_path = None

        try:
            driver_phone = data.get('driver_phone') if data else None
            driver_id_card = data.get('driver_id_card') if data else None
            # 参数防御性检查
            if data is None:
                return {"success": False, "error": "请求数据不能为空"}

            logger.info(f"【DEBUG】create_delivery 开始，data={data}, current_user={current_user}")

            # 处理来源类型
            has_order = data.get('has_delivery_order', '无')
            uploaded_by = data.get('uploaded_by')
            source_type = self._determine_source_type(has_order, uploaded_by)
            data['source_type'] = source_type
            logger.info(f"【DEBUG】source_type={source_type}")

            # 处理操作人信息
            uploader_id = None
            uploader_name = "system"
            if current_user:
                uploader_id = current_user.get("id")
                uploader_name = current_user.get("name") or current_user.get("account") or "system"
            logger.info(f"【DEBUG】uploader_id={uploader_id}, uploader_name={uploader_name}")

            # 处理报单人信息
            reporter_id = data.get('reporter_id') or uploader_id
            reporter_name = data.get('reporter_name') or data.get('shipper') or uploader_name

            if not data.get('shipper'):
                data['shipper'] = reporter_name

            # 计算联单费
            service_fee = self._calculate_service_fee(has_order)
            logger.info(f"【DEBUG】service_fee={service_fee}")

            # 24小时重复校验 - 关键修复点
            if not confirm_flag:
                driver_phone = data.get('driver_phone')
                driver_id_card = data.get('driver_id_card')

                logger.info(f"【DEBUG】检查重复，driver_phone={driver_phone}, driver_id_card={driver_id_card}")

                # 防御：确保有值才检查
                if driver_phone or driver_id_card:
                    duplicate_check = self.check_duplicate_in_24h(driver_phone, driver_id_card)

                    # 防御：确保返回字典
                    if duplicate_check is None:
                        duplicate_check = {"is_duplicate": False, "existing_orders": [], "duplicate_count": 0}

                    logger.info(f"【DEBUG】duplicate_check={duplicate_check}")

                    if duplicate_check.get("is_duplicate"):
                        return {
                            "success": False,
                            "need_confirm": True,
                            "error": f"该司机24小时内已有 {duplicate_check.get('duplicate_count', 0)} 笔报单，是否继续提交？",
                            "existing_orders": duplicate_check.get("existing_orders", [])
                        }

            # 处理品种列表 - 关键修复点
            products = data.get('products', [])
            logger.info(f"【DEBUG】原始 products={products}, type={type(products)}")

            # 防御：确保是列表
            if products is None:
                products = []
            elif isinstance(products, str):
                products = [p.strip() for p in products.split(',') if p.strip()]
            elif not isinstance(products, (list, tuple)):
                products = []

            # 去重，最多4个
            products = list(dict.fromkeys(products))[:4]
            logger.info(f"【DEBUG】处理后 products={products}")

            if not products:
                main_product = data.get('product_name')
                if main_product:
                    products = [main_product]
                    logger.info(f"【DEBUG】使用主品种={main_product}")

            # 确保有品种
            if not products:
                return {"success": False, "error": "货物品种不能为空"}

            # 计算价格
            contract_no = None
            unit_price = None
            total_amount = None

            target_factory = data.get('target_factory_name')
            quantity = data.get('quantity')

            if target_factory and products and quantity:
                logger.info(f"【DEBUG】计算价格: factory={target_factory}, product={products[0]}, quantity={quantity}")
                try:
                    contract_no, unit_price, total_amount = self._calculate_price(
                        target_factory,
                        products[0],
                        Decimal(str(quantity))
                    )
                    logger.info(
                        f"【DEBUG】价格结果: contract_no={contract_no}, unit_price={unit_price}, total_amount={total_amount}")
                except Exception as price_err:
                    logger.error(f"【DEBUG】计算价格失败: {price_err}")
                    # 价格计算失败不阻断流程

            # 处理联单图片
            upload_status = '待上传'
            if image_file and has_order == '有':
                try:
                    file_ext = ".jpg"
                    safe_name = re.sub(r'[^\w\-]', '_', str(data.get('vehicle_no', 'unknown')))
                    filename = f"order_{safe_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}{file_ext}"
                    file_path = UPLOAD_DIR / filename

                    temp_file_path = file_path
                    with open(file_path, "wb") as f:
                        f.write(image_file)
                    image_path = str(file_path)
                    upload_status = '已上传'
                    logger.info(f"【DEBUG】图片保存成功: {image_path}")
                except Exception as img_err:
                    logger.error(f"【DEBUG】保存图片失败: {img_err}")
                    return {"success": False, "error": f"保存联单图片失败: {img_err}"}

            # 数据库插入
            logger.info(f"【DEBUG】准备插入数据库...")

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # 构建插入字段
                    insert_fields = [
                        'report_date', 'warehouse', 'target_factory_id', 'target_factory_name',
                        'product_name', 'products', 'quantity', 'vehicle_no', 'driver_name',
                        'driver_phone', 'driver_id_card', 'has_delivery_order', 'delivery_order_image',
                        'upload_status', 'source_type', 'shipper', 'payee', 'service_fee',
                        'contract_no', 'contract_unit_price', 'total_amount', 'status',
                        'uploader_id', 'uploader_name', 'reporter_id', 'reporter_name'
                    ]

                    # 准备值列表
                    values = [
                        data.get('report_date'),
                        data.get('warehouse'),
                        data.get('target_factory_id'),
                        data.get('target_factory_name'),
                        products[0] if products else data.get('product_name'),  # 主品种
                        ','.join(products) if products else None,  # 品种列表
                        quantity,
                        data.get('vehicle_no'),
                        data.get('driver_name'),
                        driver_phone,
                        driver_id_card,
                        has_order,
                        image_path,
                        upload_status,
                        source_type,
                        data.get('shipper'),
                        data.get('payee'),
                        service_fee,
                        contract_no,
                        unit_price,
                        total_amount,
                        data.get('status', '待确认'),
                        uploader_id,
                        uploader_name,
                        reporter_id,
                        reporter_name,
                    ]

                    # 构建 SQL
                    placeholders = ','.join(['%s'] * len(values))
                    fields_str = ','.join(insert_fields)

                    sql = f"""
                        INSERT INTO pd_deliveries 
                        ({fields_str}, uploaded_at)
                        VALUES ({placeholders}, NOW())
                    """

                    logger.info(f"【DEBUG】SQL: {sql[:100]}...")
                    logger.info(f"【DEBUG】Values: {values[:5]}...")

                    cur.execute(sql, tuple(values))
                    delivery_id = cur.lastrowid
                    logger.info(f"【DEBUG】插入成功, delivery_id={delivery_id}")

                    # 创建待上传磅单记录
                    if products and contract_no:
                        logger.info(f"【DEBUG】创建磅单记录...")
                        self._create_pending_weighbills(
                            delivery_id, contract_no, products,
                            data.get('vehicle_no'), uploader_id, uploader_name
                        )

                    temp_file_path = None

                    operations = self._build_operations(has_order, upload_status, image_path)

                    return {
                        "success": True,
                        "message": "报货订单创建成功",
                        "data": {
                            "id": delivery_id,
                            "contract_no": contract_no,
                            "products": products,
                            "contract_unit_price": unit_price,
                            "total_amount": total_amount,
                            "source_type": source_type,
                            "upload_status": upload_status,
                            "service_fee": float(service_fee) if service_fee else 0,
                            "uploader_id": uploader_id,
                            "uploader_name": uploader_name,
                            "reporter_id": reporter_id,
                            "reporter_name": reporter_name,
                            "operations": operations
                        }
                    }

        except Exception as e:
            # 清理临时文件
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except:
                    pass
            logger.exception(f"【DEBUG】创建报货订单异常: {e}")
            return {"success": False, "error": str(e)}
    def update_delivery(self, delivery_id: int, data: Dict,
                        image_file: bytes = None, delete_image: bool = False,
                        uploaded_by: str = None) -> Dict[str, Any]:
        """更新报货订单"""
        temp_new_file = None
        old_image_to_delete = None

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT has_delivery_order, delivery_order_image, upload_status, driver_phone, driver_id_card FROM pd_deliveries WHERE id = %s",
                        (delivery_id,)
                    )
                    old = cur.fetchone()
                    if not old:
                        return {"success": False, "error": f"订单ID {delivery_id} 不存在"}

                    old_has_order, old_image_path, old_upload_status, old_driver_phone, old_driver_id_card = old

                    has_order = data.get('has_delivery_order', old_has_order)
                    if 'has_delivery_order' in data or uploaded_by:
                        data['uploaded_by'] = uploaded_by
                        data['source_type'] = self._determine_source_type(has_order, uploaded_by)

                    if 'has_delivery_order' in data and data['has_delivery_order'] != old_has_order:
                        data['service_fee'] = self._calculate_service_fee(data['has_delivery_order'])

                    if 'reporter_id' in data or 'reporter_name' in data:
                        if data.get('reporter_name'):
                            data['shipper'] = data['reporter_name']

                    new_image_path = old_image_path
                    upload_status = old_upload_status

                    if delete_image and old_image_path:
                        old_image_to_delete = old_image_path
                        new_image_path = None
                        upload_status = '待上传'
                        if has_order == '有':
                            data['service_fee'] = Decimal('0')

                    if image_file:
                        safe_name = re.sub(r'[^\w\-]', '_', str(delivery_id))
                        filename = f"delivery_{safe_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
                        file_path = UPLOAD_DIR / filename

                        with open(file_path, "wb") as f:
                            f.write(image_file)

                        temp_new_file = str(file_path)
                        new_image_path = temp_new_file
                        upload_status = '已上传'

                        if old_image_path:
                            old_image_to_delete = old_image_path

                    data['delivery_order_image'] = new_image_path
                    data['upload_status'] = upload_status

                    fields = [
                        'report_date', 'warehouse', 'target_factory_id', 'target_factory_name',
                        'product_name', 'products', 'quantity', 'vehicle_no', 'driver_name', 'driver_phone', 'driver_id_card',
                        'has_delivery_order', 'delivery_order_image', 'upload_status', 'source_type',
                        'shipper', 'payee', 'service_fee', 'contract_no', 'contract_unit_price', 'total_amount',
                        'status', 'reporter_id', 'reporter_name'
                    ]

                    update_fields = []
                    params = []
                    for f in fields:
                        if f in data:
                            update_fields.append(f"{f} = %s")
                            params.append(data[f])

                    if not update_fields and not delete_image and not image_file:
                        return {"success": False, "error": "没有要更新的字段"}

                    params.append(delivery_id)
                    sql = f"UPDATE pd_deliveries SET {', '.join(update_fields)} WHERE id = %s"
                    cur.execute(sql, tuple(params))

                    if old_image_to_delete and os.path.exists(old_image_to_delete):
                        try:
                            os.remove(old_image_to_delete)
                        except Exception as e:
                            logger.warning(f"删除旧图片失败: {e}")

                    operations = self._build_operations(has_order, upload_status, new_image_path)

                    return {
                        "success": True,
                        "message": "更新成功",
                        "data": {
                            "id": delivery_id,
                            "has_delivery_order": has_order,
                            "upload_status": upload_status,
                            "delivery_order_image": new_image_path,
                            "service_fee": float(data.get('service_fee', Decimal('0'))),
                            "reporter_id": data.get('reporter_id'),
                            "reporter_name": data.get('reporter_name'),
                            "operations": operations
                        }
                    }

        except Exception as e:
            if temp_new_file and os.path.exists(temp_new_file):
                try:
                    os.remove(temp_new_file)
                except:
                    pass
            logger.error(f"更新报货订单失败: {e}")
            return {"success": False, "error": str(e)}

    def get_delivery(self, delivery_id: int) -> Optional[Dict]:
        """获取订单详情"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM pd_deliveries WHERE id = %s", (delivery_id,))
                    row = cur.fetchone()
                    if not row:
                        return None

                    columns = [desc[0] for desc in cur.description]
                    data = dict(zip(columns, row))

                    for key in ['report_date', 'created_at', 'updated_at', 'uploaded_at']:
                        if data.get(key):
                            data[key] = str(data[key])

                    # 解析品种列表
                    if data.get('products'):
                        data['products'] = [p.strip() for p in data['products'].split(',') if p.strip()]
                    else:
                        data['products'] = [data.get('product_name')] if data.get('product_name') else []

                    data["has_delivery_order_display"] = '是' if data.get('has_delivery_order') == '有' else '否'
                    data["upload_status_display"] = '是' if data.get('upload_status') == '已上传' else '否'

                    if data.get('service_fee'):
                        data['service_fee'] = float(data['service_fee'])

                    data['operations'] = self._build_operations(
                        data.get('has_delivery_order'),
                        data.get('upload_status'),
                        data.get('delivery_order_image')
                    )

                    return data

        except Exception as e:
            logger.error(f"查询订单失败: {e}")
            return None

    def list_deliveries(
            self,
            exact_shipper: str = None,
            exact_contract_no: str = None,
            exact_report_date: str = None,
            exact_driver_name: str = None,
            exact_vehicle_no: str = None,
            exact_has_delivery_order: str = None,
            exact_upload_status: str = None,
            exact_reporter_name: str = None,
            exact_reporter_id: int = None,
            exact_factory_name: str = None,
            exact_status: str = None,
            exact_driver_phone: str = None,
            fuzzy_keywords: str = None,
            date_from: str = None,
            date_to: str = None,
            page: int = 1,
            page_size: int = 20
    ) -> Dict[str, Any]:
        """查询订单列表"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    where_clauses = []
                    params = []

                    if exact_shipper:
                        where_clauses.append("shipper = %s")
                        params.append(exact_shipper)

                    if exact_contract_no:
                        where_clauses.append("contract_no = %s")
                        params.append(exact_contract_no)

                    if exact_report_date:
                        where_clauses.append("report_date = %s")
                        params.append(exact_report_date)

                    if exact_driver_name:
                        where_clauses.append("driver_name = %s")
                        params.append(exact_driver_name)

                    if exact_vehicle_no:
                        where_clauses.append("vehicle_no = %s")
                        params.append(exact_vehicle_no)

                    if exact_has_delivery_order:
                        where_clauses.append("has_delivery_order = %s")
                        params.append(exact_has_delivery_order)

                    if exact_upload_status:
                        where_clauses.append("upload_status = %s")
                        params.append(exact_upload_status)

                    if exact_reporter_name:
                        where_clauses.append("reporter_name = %s")
                        params.append(exact_reporter_name)

                    if exact_reporter_id:
                        where_clauses.append("reporter_id = %s")
                        params.append(exact_reporter_id)

                    if exact_factory_name:
                        where_clauses.append("target_factory_name = %s")
                        params.append(exact_factory_name)

                    if exact_status:
                        where_clauses.append("status = %s")
                        params.append(exact_status)

                    if exact_driver_phone:
                        where_clauses.append("driver_phone = %s")
                        params.append(exact_driver_phone)

                    if fuzzy_keywords:
                        tokens = [t for t in fuzzy_keywords.split() if t]
                        or_clauses = []
                        for token in tokens:
                            like = f"%{token}%"
                            or_clauses.append(
                                "(vehicle_no LIKE %s OR driver_name LIKE %s OR driver_phone LIKE %s "
                                "OR target_factory_name LIKE %s OR product_name LIKE %s OR contract_no LIKE %s "
                                "OR reporter_name LIKE %s OR shipper LIKE %s)")
                            params.extend([like, like, like, like, like, like, like, like])
                        if or_clauses:
                            where_clauses.append("(" + " OR ".join(or_clauses) + ")")

                    if date_from:
                        where_clauses.append("report_date >= %s")
                        params.append(date_from)

                    if date_to:
                        where_clauses.append("report_date <= %s")
                        params.append(date_to)

                    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

                    cur.execute(f"SELECT COUNT(*) FROM pd_deliveries {where_sql}", tuple(params))
                    total = cur.fetchone()[0]

                    offset = (page - 1) * page_size
                    cur.execute(f"""
                        SELECT * FROM pd_deliveries 
                        {where_sql}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s
                    """, tuple(params + [page_size, offset]))

                    columns = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()
                    data = []
                    for row in rows:
                        item = dict(zip(columns, row))
                        for key in ['report_date', 'created_at', 'updated_at', 'uploaded_at']:
                            if item.get(key):
                                item[key] = str(item[key])

                        # 解析品种列表
                        # 在 list_deliveries 方法中，返回前解析
                        if item.get('products'):
                            item['products'] = [p.strip() for p in item['products'].split(',') if p.strip()]
                            item['product_count'] = len(item['products'])  # ← 品种数量
                        else:
                            item['products'] = [item.get('product_name')] if item.get('product_name') else []
                            item['product_count'] = 1

                        item["has_delivery_order_display"] = '是' if item.get('has_delivery_order') == '有' else '否'
                        item["upload_status_display"] = '是' if item.get('upload_status') == '已上传' else '否'

                        if item.get('service_fee'):
                            item['service_fee'] = float(item['service_fee'])

                        item['operations'] = self._build_operations(
                            item.get('has_delivery_order'),
                            item.get('upload_status'),
                            item.get('delivery_order_image')
                        )

                        data.append(item)

                    return {
                        "success": True,
                        "data": data,
                        "total": total,
                        "page": page,
                        "page_size": page_size
                    }

        except Exception as e:
            logger.error(f"查询列表失败: {e}")
            return {"success": False, "error": str(e), "data": [], "total": 0}

    def delete_delivery(self, delivery_id: int) -> Dict[str, Any]:
        """删除订单（级联删除关联磅单）"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # 先删除关联磅单图片
                    cur.execute("SELECT weighbill_image FROM pd_weighbills WHERE delivery_id = %s", (delivery_id,))
                    for row in cur.fetchall():
                        image_path = row[0]
                        if image_path and os.path.exists(image_path):
                            try:
                                os.remove(image_path)
                            except:
                                pass

                    # 获取联单图片路径
                    cur.execute("SELECT delivery_order_image FROM pd_deliveries WHERE id = %s", (delivery_id,))
                    row = cur.fetchone()

                    if row and row[0]:
                        image_path = row[0]
                        # 级联删除由外键约束处理
                        cur.execute("DELETE FROM pd_deliveries WHERE id = %s", (delivery_id,))

                        if os.path.exists(image_path):
                            try:
                                os.remove(image_path)
                            except Exception as e:
                                logger.warning(f"删除图片文件失败: {e}")
                    else:
                        cur.execute("DELETE FROM pd_deliveries WHERE id = %s", (delivery_id,))

                    return {"success": True, "message": "删除成功"}

        except Exception as e:
            logger.error(f"删除订单失败: {e}")
            return {"success": False, "error": str(e)}


_delivery_service = None


def get_delivery_service():
    global _delivery_service
    if _delivery_service is None:
        _delivery_service = DeliveryService()
    return _delivery_service