"""
异常上报服务 - 异常审核模块
"""
import logging
from typing import Any, Dict, List, Optional

from core.database import get_conn

logger = logging.getLogger(__name__)

STATUS_CHOICES = ("待处理", "已处理")


class ExceptionReportService:
    """异常上报管理服务"""

    def list_reports(
        self,
        status: Optional[str] = None,
        driver_name: Optional[str] = None,
        vehicle_no: Optional[str] = None,
        exception_type_id: Optional[int] = None,
        reporter: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询异常上报列表"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    conditions = []
                    params: List[Any] = []

                    if status:
                        conditions.append("r.status = %s")
                        params.append(status)
                    if driver_name:
                        conditions.append("r.driver_name LIKE %s")
                        params.append(f"%{driver_name}%")
                    if vehicle_no:
                        conditions.append("r.vehicle_no LIKE %s")
                        params.append(f"%{vehicle_no}%")
                    if exception_type_id:
                        conditions.append("r.exception_type_id = %s")
                        params.append(exception_type_id)
                    if reporter:
                        conditions.append("r.reporter LIKE %s")
                        params.append(f"%{reporter}%")

                    where_clause = " AND ".join(conditions) if conditions else "1=1"
                    count_sql = f"SELECT COUNT(*) as total FROM pd_exception_reports r WHERE {where_clause}"
                    cur.execute(count_sql, params)
                    total = cur.fetchone()["total"]

                    offset = (page - 1) * page_size
                    list_sql = f"""
                        SELECT r.id, r.status, r.driver_name, r.vehicle_no, r.phone,
                               r.exception_type_id, r.exception_type_name, r.description,
                               r.reporter, r.reported_at, r.created_at, r.updated_at
                        FROM pd_exception_reports r
                        WHERE {where_clause}
                        ORDER BY r.reported_at DESC, r.id DESC
                        LIMIT %s OFFSET %s
                    """
                    cur.execute(list_sql, params + [page_size, offset])
                    rows = cur.fetchall()

                    items = []
                    for r in rows:
                        items.append({
                            "id": r["id"],
                            "status": r["status"],
                            "driver_name": r["driver_name"],
                            "vehicle_no": r["vehicle_no"],
                            "phone": r["phone"],
                            "exception_type_id": r["exception_type_id"],
                            "exception_type_name": r["exception_type_name"],
                            "description": r["description"],
                            "reporter": r["reporter"],
                            "reported_at": str(r["reported_at"]) if r.get("reported_at") else None,
                            "created_at": str(r["created_at"]) if r.get("created_at") else None,
                            "updated_at": str(r["updated_at"]) if r.get("updated_at") else None,
                        })

                    return {
                        "success": True,
                        "data": {
                            "items": items,
                            "total": total,
                            "page": page,
                            "page_size": page_size,
                        },
                    }
        except Exception as e:
            logger.error(f"查询异常上报列表失败: {e}")
            return {"success": False, "error": str(e)}

    def get_report(self, report_id: int) -> Optional[Dict[str, Any]]:
        """获取单条异常上报详情"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, status, driver_name, vehicle_no, phone,
                               exception_type_id, exception_type_name, description,
                               reporter, reported_at, created_at, updated_at
                        FROM pd_exception_reports
                        WHERE id = %s
                        """,
                        (report_id,),
                    )
                    r = cur.fetchone()
                    if not r:
                        return None
                    return {
                        "id": r["id"],
                        "status": r["status"],
                        "driver_name": r["driver_name"],
                        "vehicle_no": r["vehicle_no"],
                        "phone": r["phone"],
                        "exception_type_id": r["exception_type_id"],
                        "exception_type_name": r["exception_type_name"],
                        "description": r["description"],
                        "reporter": r["reporter"],
                        "reported_at": str(r["reported_at"]) if r.get("reported_at") else None,
                        "created_at": str(r["created_at"]) if r.get("created_at") else None,
                        "updated_at": str(r["updated_at"]) if r.get("updated_at") else None,
                    }
        except Exception as e:
            logger.error(f"获取异常上报详情失败: {e}")
            return None

    def create_report(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """新增异常上报"""
        status = (data.get("status") or "待处理").strip()
        if status not in STATUS_CHOICES:
            return {"success": False, "error": f"异常状态必须是 {'/'.join(STATUS_CHOICES)} 之一"}

        driver_name = (data.get("driver_name") or "").strip() or None
        vehicle_no = (data.get("vehicle_no") or "").strip() or None
        phone = (data.get("phone") or "").strip() or None
        exception_type_id = data.get("exception_type_id")
        description = (data.get("description") or "").strip() or None
        reporter = (data.get("reporter") or "").strip() or None
        reported_at = data.get("reported_at")  # 可选，不传则用当前时间

        exception_type_name = None
        if exception_type_id:
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT type_name FROM pd_exception_types WHERE id = %s",
                            (exception_type_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            exception_type_name = row["type_name"]
                        else:
                            return {"success": False, "error": f"异常类型 ID {exception_type_id} 不存在"}
            except Exception as e:
                logger.error(f"查询异常类型失败: {e}")
                return {"success": False, "error": str(e)}

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if reported_at:
                        if isinstance(reported_at, str):
                            reported_at_val = reported_at
                        else:
                            reported_at_val = str(reported_at)
                        cur.execute(
                            """
                            INSERT INTO pd_exception_reports
                            (status, driver_name, vehicle_no, phone, exception_type_id, exception_type_name,
                             description, reporter, reported_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                status,
                                driver_name,
                                vehicle_no,
                                phone,
                                exception_type_id,
                                exception_type_name,
                                description,
                                reporter,
                                reported_at_val,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO pd_exception_reports
                            (status, driver_name, vehicle_no, phone, exception_type_id, exception_type_name,
                             description, reporter)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                status,
                                driver_name,
                                vehicle_no,
                                phone,
                                exception_type_id,
                                exception_type_name,
                                description,
                                reporter,
                            ),
                        )
                    report_id = cur.lastrowid
                    return {
                        "success": True,
                        "message": "异常上报成功",
                        "data": {"id": report_id},
                    }
        except Exception as e:
            logger.error(f"新增异常上报失败: {e}")
            return {"success": False, "error": str(e)}

    def update_report(self, report_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """修改异常上报"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM pd_exception_reports WHERE id = %s", (report_id,))
                    if not cur.fetchone():
                        return {"success": False, "error": f"异常上报 ID {report_id} 不存在"}

                    allowed_fields = [
                        "status",
                        "driver_name",
                        "vehicle_no",
                        "phone",
                        "exception_type_id",
                        "description",
                        "reporter",
                        "reported_at",
                    ]
                    update_parts = []
                    params: List[Any] = []

                    if "status" in data and data["status"] is not None:
                        status = str(data["status"]).strip()
                        if status not in STATUS_CHOICES:
                            return {"success": False, "error": f"异常状态必须是 {'/'.join(STATUS_CHOICES)} 之一"}
                        update_parts.append("status = %s")
                        params.append(status)

                    if "driver_name" in data:
                        update_parts.append("driver_name = %s")
                        params.append((data["driver_name"] or "").strip() or None)
                    if "vehicle_no" in data:
                        update_parts.append("vehicle_no = %s")
                        params.append((data["vehicle_no"] or "").strip() or None)
                    if "phone" in data:
                        update_parts.append("phone = %s")
                        params.append((data["phone"] or "").strip() or None)
                    if "exception_type_id" in data:
                        exception_type_id = data["exception_type_id"]
                        exception_type_name = None
                        if exception_type_id:
                            cur.execute(
                                "SELECT type_name FROM pd_exception_types WHERE id = %s",
                                (exception_type_id,),
                            )
                            row = cur.fetchone()
                            if not row:
                                return {"success": False, "error": f"异常类型 ID {exception_type_id} 不存在"}
                            exception_type_name = row["type_name"]
                        update_parts.append("exception_type_id = %s")
                        params.append(exception_type_id)
                        update_parts.append("exception_type_name = %s")
                        params.append(exception_type_name)
                    if "description" in data:
                        update_parts.append("description = %s")
                        params.append((data["description"] or "").strip() or None)
                    if "reporter" in data:
                        update_parts.append("reporter = %s")
                        params.append((data["reporter"] or "").strip() or None)
                    if "reported_at" in data:
                        update_parts.append("reported_at = %s")
                        params.append(data["reported_at"])

                    if not update_parts:
                        return {"success": False, "error": "没有要更新的字段"}

                    params.append(report_id)
                    cur.execute(
                        f"UPDATE pd_exception_reports SET {', '.join(update_parts)} WHERE id = %s",
                        tuple(params),
                    )
                    return {
                        "success": True,
                        "message": "异常上报修改成功",
                        "data": {"id": report_id},
                    }
        except Exception as e:
            logger.error(f"修改异常上报失败: {e}")
            return {"success": False, "error": str(e)}

    def delete_report(self, report_id: int) -> Dict[str, Any]:
        """删除异常上报"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM pd_exception_reports WHERE id = %s", (report_id,))
                    if not cur.fetchone():
                        return {"success": False, "error": f"异常上报 ID {report_id} 不存在"}

                    cur.execute("DELETE FROM pd_exception_reports WHERE id = %s", (report_id,))
                    return {
                        "success": True,
                        "message": "异常上报删除成功",
                        "data": {"id": report_id},
                    }
        except Exception as e:
            logger.error(f"删除异常上报失败: {e}")
            return {"success": False, "error": str(e)}


_exception_report_service = None


def get_exception_report_service() -> ExceptionReportService:
    global _exception_report_service
    if _exception_report_service is None:
        _exception_report_service = ExceptionReportService()
    return _exception_report_service
