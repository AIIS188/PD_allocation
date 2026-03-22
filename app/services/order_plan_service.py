"""
订货计划：录入、列表筛选、仅修改车数（与报货计划关联并带入冶炼厂）
"""
import logging
from datetime import date, datetime
from typing import Any, Dict, Optional

from pymysql.cursors import DictCursor

from app.services.contract_service import get_conn
from app.services.delivery_plan_service import (
    apply_increment_confirmed_trucks,
    get_delivery_plan_service,
)

logger = logging.getLogger(__name__)

_ORDER_PLAN_REMARK_ENSURED = False

AUDIT_STATUS_PENDING = "待审核"
AUDIT_STATUS_APPROVED = "审核通过"
AUDIT_STATUS_REJECTED = "审核未通过"
VALID_AUDIT_STATUSES = frozenset(
    {AUDIT_STATUS_PENDING, AUDIT_STATUS_APPROVED, AUDIT_STATUS_REJECTED}
)


def _ensure_order_plan_remark_column() -> None:
    """旧库补全订货计划审核备注字段（仅执行一次）。"""
    global _ORDER_PLAN_REMARK_ENSURED
    if _ORDER_PLAN_REMARK_ENSURED:
        return
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pd_order_plans'
                    """
                )
                existing = {row[0] for row in (cur.fetchall() or [])}
                if "audit_remark" not in existing:
                    cur.execute(
                        """
                        ALTER TABLE pd_order_plans
                        ADD COLUMN audit_remark TEXT DEFAULT NULL COMMENT '审核备注/原因'
                        """
                    )
            conn.commit()
        _ORDER_PLAN_REMARK_ENSURED = True
    except Exception as e:
        logger.warning("ensure_order_plan_remark_column skipped/failed: %s", e)


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for key, val in out.items():
        if isinstance(val, datetime):
            out[key] = val.isoformat(sep=" ", timespec="seconds")
        elif isinstance(val, date):
            out[key] = val.isoformat()
    return out


class OrderPlanService:
    _SELECT = """
        id, delivery_plan_id, plan_no, smelter_name, truck_count, audit_status, audit_remark,
        created_by, created_by_name, updated_by, updated_by_name,
        created_at, updated_at
    """

    def _lookup_delivery_plan(
        self, cur, plan_no: str
    ) -> Optional[Dict[str, Any]]:
        cur.execute(
            """
            SELECT id, plan_no, smelter_name
            FROM pd_delivery_plans
            WHERE plan_no = %s
            LIMIT 1
            """,
            (plan_no,),
        )
        return cur.fetchone()

    def create(
        self,
        plan_no: str,
        truck_count: int,
        *,
        operator_id: Optional[int] = None,
        operator_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        _ensure_order_plan_remark_column()
        plan_no = (plan_no or "").strip()
        if not plan_no:
            return {"success": False, "error": "报货计划编号不能为空"}
        if truck_count < 0:
            return {"success": False, "error": "车数不能为负"}

        try:
            with get_conn() as conn:
                with conn.cursor(DictCursor) as cur:
                    dp = self._lookup_delivery_plan(cur, plan_no)
                    if not dp:
                        return {
                            "success": False,
                            "error": f"报货计划编号不存在: {plan_no}",
                        }
                    delivery_plan_id = int(dp["id"])
                    plan_no_db = (dp.get("plan_no") or plan_no).strip()
                    smelter = dp.get("smelter_name")

                    cur.execute(
                        """
                        INSERT INTO pd_order_plans (
                            delivery_plan_id, plan_no, smelter_name, truck_count, audit_status,
                            created_by, created_by_name, updated_by, updated_by_name
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            delivery_plan_id,
                            plan_no_db,
                            smelter,
                            truck_count,
                            AUDIT_STATUS_PENDING,
                            operator_id,
                            operator_name,
                            operator_id,
                            operator_name,
                        ),
                    )
                    new_id = cur.lastrowid
                    conn.commit()

                    cur.execute(
                        f"SELECT {self._SELECT.strip()} FROM pd_order_plans WHERE id = %s",
                        (new_id,),
                    )
                    row = cur.fetchone()
                    return {
                        "success": True,
                        "message": "订货计划录入成功",
                        "data": _serialize_row(row) if row else {"id": new_id},
                    }
        except Exception as e:
            logger.error("create order plan failed: %s", e)
            return {"success": False, "error": str(e)}

    def get(self, order_plan_id: int) -> Dict[str, Any]:
        _ensure_order_plan_remark_column()
        try:
            with get_conn() as conn:
                with conn.cursor(DictCursor) as cur:
                    cur.execute(
                        f"SELECT {self._SELECT.strip()} FROM pd_order_plans WHERE id = %s",
                        (order_plan_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return {
                            "success": False,
                            "error": f"订货计划 ID {order_plan_id} 不存在",
                        }
                    return {"success": True, "data": _serialize_row(row)}
        except Exception as e:
            logger.error("get order plan failed: %s", e)
            return {"success": False, "error": str(e)}

    def list_plans(
        self,
        *,
        audit_status: Optional[str] = None,
        plan_no: Optional[str] = None,
        smelter_name: Optional[str] = None,
        operator_name: Optional[str] = None,
        updated_from: Optional[str] = None,
        updated_to: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        _ensure_order_plan_remark_column()
        try:
            with get_conn() as conn:
                with conn.cursor(DictCursor) as cur:
                    where_clauses: list[str] = []
                    params: list[Any] = []

                    if audit_status:
                        if audit_status not in VALID_AUDIT_STATUSES:
                            return {
                                "success": False,
                                "error": f"无效的状态，允许值：{', '.join(sorted(VALID_AUDIT_STATUSES))}",
                            }
                        where_clauses.append("audit_status = %s")
                        params.append(audit_status)
                    if plan_no:
                        where_clauses.append("plan_no LIKE %s")
                        params.append(f"%{plan_no.strip()}%")
                    if smelter_name:
                        where_clauses.append("smelter_name LIKE %s")
                        params.append(f"%{smelter_name.strip()}%")
                    if operator_name:
                        q = f"%{operator_name.strip()}%"
                        where_clauses.append(
                            "(created_by_name LIKE %s OR updated_by_name LIKE %s)"
                        )
                        params.extend([q, q])
                    if updated_from:
                        uf = updated_from.strip()
                        if len(uf) == 10 and uf[4] == "-" and uf[7] == "-":
                            uf = uf + " 00:00:00"
                        where_clauses.append("updated_at >= %s")
                        params.append(uf)
                    if updated_to:
                        ut = updated_to.strip()
                        if len(ut) == 10 and ut[4] == "-" and ut[7] == "-":
                            ut = ut + " 23:59:59"
                        where_clauses.append("updated_at <= %s")
                        params.append(ut)

                    where_sql = (
                        "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
                    )

                    cur.execute(
                        f"SELECT COUNT(*) AS total FROM pd_order_plans {where_sql}",
                        tuple(params),
                    )
                    tr = cur.fetchone()
                    total = int(tr["total"]) if tr else 0

                    offset = (page - 1) * page_size
                    cur.execute(
                        f"""
                        SELECT {self._SELECT.strip()}
                        FROM pd_order_plans
                        {where_sql}
                        ORDER BY updated_at DESC, id DESC
                        LIMIT %s OFFSET %s
                        """,
                        tuple(params + [page_size, offset]),
                    )
                    rows = [_serialize_row(dict(r)) for r in (cur.fetchall() or [])]
                    return {
                        "success": True,
                        "data": rows,
                        "total": total,
                        "page": page,
                        "page_size": page_size,
                    }
        except Exception as e:
            logger.error("list order plans failed: %s", e)
            return {"success": False, "error": str(e)}

    def update_truck_count_only(
        self,
        order_plan_id: int,
        truck_count: int,
        *,
        operator_id: Optional[int] = None,
        operator_name: Optional[str] = None,
        is_accounting_role: bool = False,
    ) -> Dict[str, Any]:
        if truck_count < 0:
            return {"success": False, "error": "车数不能为负"}

        _ensure_order_plan_remark_column()
        try:
            with get_conn() as conn:
                with conn.cursor(DictCursor) as cur:
                    cur.execute(
                        "SELECT id, audit_status FROM pd_order_plans WHERE id = %s",
                        (order_plan_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return {
                            "success": False,
                            "error": f"订货计划 ID {order_plan_id} 不存在",
                        }

                    if is_accounting_role:
                        cur.execute(
                            """
                            UPDATE pd_order_plans
                            SET truck_count = %s,
                                updated_by = %s,
                                updated_by_name = %s
                            WHERE id = %s
                            """,
                            (truck_count, operator_id, operator_name, order_plan_id),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE pd_order_plans
                            SET truck_count = %s,
                                audit_status = %s,
                                updated_by = %s,
                                updated_by_name = %s
                            WHERE id = %s
                            """,
                            (
                                truck_count,
                                AUDIT_STATUS_PENDING,
                                operator_id,
                                operator_name,
                                order_plan_id,
                            ),
                        )
                    conn.commit()

                    cur.execute(
                        f"SELECT {self._SELECT.strip()} FROM pd_order_plans WHERE id = %s",
                        (order_plan_id,),
                    )
                    out = cur.fetchone()
                    return {
                        "success": True,
                        "message": "车数已更新",
                        "data": _serialize_row(out) if out else {},
                    }
        except Exception as e:
            logger.error("update order plan truck_count failed: %s", e)
            return {"success": False, "error": str(e)}

    def audit(
        self,
        order_plan_id: int,
        audit_result: str,
        remark: Optional[str],
        *,
        operator_id: Optional[int] = None,
        operator_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        if audit_result not in (AUDIT_STATUS_APPROVED, AUDIT_STATUS_REJECTED):
            return {
                "success": False,
                "error": f"audit_result 须为「{AUDIT_STATUS_APPROVED}」或「{AUDIT_STATUS_REJECTED}」",
            }

        _ensure_order_plan_remark_column()
        rmk = (remark or "").strip()
        if audit_result == AUDIT_STATUS_REJECTED and not rmk:
            return {
                "success": False,
                "error": "审核未通过时必须填写审核备注，请写明原因",
            }
        rmk_val: Optional[str] = rmk if rmk else None

        try:
            with get_conn() as conn:
                prev_ac = conn.get_autocommit()
                conn.autocommit(False)
                delivery_plan_id: Optional[int] = None
                try:
                    with conn.cursor(DictCursor) as cur:
                        cur.execute(
                            f"""
                            SELECT {self._SELECT.strip()}
                            FROM pd_order_plans
                            WHERE id = %s
                            FOR UPDATE
                            """,
                            (order_plan_id,),
                        )
                        row = cur.fetchone()
                        if not row:
                            conn.rollback()
                            return {
                                "success": False,
                                "error": f"订货计划 ID {order_plan_id} 不存在",
                            }
                        if row.get("audit_status") != AUDIT_STATUS_PENDING:
                            conn.rollback()
                            return {"success": False, "error": "仅「待审核」状态可审核"}

                        plan_no = (row.get("plan_no") or "").strip()
                        truck_count = int(row.get("truck_count") or 0)
                        delivery_plan_id = int(row["delivery_plan_id"])

                        if audit_result == AUDIT_STATUS_APPROVED:
                            try:
                                apply_increment_confirmed_trucks(
                                    cur,
                                    plan_no,
                                    truck_count,
                                    operator_id=operator_id,
                                    operator_name=operator_name,
                                )
                            except ValueError as e:
                                conn.rollback()
                                return {"success": False, "error": str(e)}

                        cur.execute(
                            """
                            UPDATE pd_order_plans
                            SET audit_status = %s,
                                audit_remark = %s,
                                updated_by = %s,
                                updated_by_name = %s
                            WHERE id = %s
                            """,
                            (
                                audit_result,
                                rmk_val,
                                operator_id,
                                operator_name,
                                order_plan_id,
                            ),
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.autocommit(prev_ac)
        except Exception as e:
            logger.error("audit order plan failed: %s", e)
            return {"success": False, "error": str(e)}

        op_msg = (
            "审核已通过"
            if audit_result == AUDIT_STATUS_APPROVED
            else "审核已驳回"
        )
        payload: Dict[str, Any] = {
            "order_plan": self.get(order_plan_id).get("data") or {},
        }
        if audit_result == AUDIT_STATUS_APPROVED and delivery_plan_id is not None:
            dp = get_delivery_plan_service().get_plan(delivery_plan_id)
            if dp.get("success"):
                payload["delivery_plan"] = dp.get("data")
            else:
                payload["delivery_plan"] = None
        else:
            payload["delivery_plan"] = None

        return {
            "success": True,
            "message": op_msg,
            "data": payload,
        }


_order_plan_service: Optional[OrderPlanService] = None


def get_order_plan_service() -> OrderPlanService:
    global _order_plan_service
    if _order_plan_service is None:
        _order_plan_service = OrderPlanService()
    return _order_plan_service
