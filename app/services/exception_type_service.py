"""
异常类型服务 - 异常审核模块
"""
import logging
from typing import Any, Dict, List, Optional

from core.database import get_conn

logger = logging.getLogger(__name__)


class ExceptionTypeService:
    """异常类型管理服务"""

    def list_types(self) -> Dict[str, Any]:
        """查询所有异常类型列表（用于下拉选择）"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, type_name, created_at, updated_at
                        FROM pd_exception_types
                        ORDER BY id ASC
                        """
                    )
                    rows = cur.fetchall()
                    items = []
                    for r in rows:
                        items.append({
                            "id": r["id"],
                            "type_name": r["type_name"],
                            "created_at": str(r["created_at"]) if r.get("created_at") else None,
                            "updated_at": str(r["updated_at"]) if r.get("updated_at") else None,
                        })
                    return {
                        "success": True,
                        "data": items,
                    }
        except Exception as e:
            logger.error(f"查询异常类型列表失败: {e}")
            return {"success": False, "error": str(e)}

    def create_type(self, type_name: str) -> Dict[str, Any]:
        """新增异常类型"""
        normalized = (type_name or "").strip()
        if not normalized:
            return {"success": False, "error": "异常类型名称不能为空"}
        if len(normalized) > 64:
            return {"success": False, "error": "异常类型名称不能超过64个字符"}

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM pd_exception_types WHERE type_name = %s",
                        (normalized,),
                    )
                    if cur.fetchone():
                        return {"success": False, "error": f"异常类型 '{normalized}' 已存在"}

                    cur.execute(
                        "INSERT INTO pd_exception_types (type_name) VALUES (%s)",
                        (normalized,),
                    )
                    type_id = cur.lastrowid
                    return {
                        "success": True,
                        "message": "异常类型新增成功",
                        "data": {"id": type_id, "type_name": normalized},
                    }
        except Exception as e:
            logger.error(f"新增异常类型失败: {e}")
            return {"success": False, "error": str(e)}

    def update_type(self, type_id: int, type_name: str) -> Dict[str, Any]:
        """修改异常类型"""
        normalized = (type_name or "").strip()
        if not normalized:
            return {"success": False, "error": "异常类型名称不能为空"}
        if len(normalized) > 64:
            return {"success": False, "error": "异常类型名称不能超过64个字符"}

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM pd_exception_types WHERE id = %s", (type_id,))
                    if not cur.fetchone():
                        return {"success": False, "error": f"异常类型 ID {type_id} 不存在"}

                    cur.execute(
                        "SELECT id FROM pd_exception_types WHERE type_name = %s AND id != %s",
                        (normalized, type_id),
                    )
                    if cur.fetchone():
                        return {"success": False, "error": f"异常类型 '{normalized}' 已存在"}

                    cur.execute(
                        "UPDATE pd_exception_types SET type_name = %s WHERE id = %s",
                        (normalized, type_id),
                    )
                    # 同步更新异常上报表中的冗余字段
                    cur.execute(
                        "UPDATE pd_exception_reports SET exception_type_name = %s WHERE exception_type_id = %s",
                        (normalized, type_id),
                    )
                    return {
                        "success": True,
                        "message": "异常类型修改成功",
                        "data": {"id": type_id, "type_name": normalized},
                    }
        except Exception as e:
            logger.error(f"修改异常类型失败: {e}")
            return {"success": False, "error": str(e)}

    def delete_type(self, type_id: int) -> Dict[str, Any]:
        """删除异常类型"""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, type_name FROM pd_exception_types WHERE id = %s", (type_id,))
                    row = cur.fetchone()
                    if not row:
                        return {"success": False, "error": f"异常类型 ID {type_id} 不存在"}

                    cur.execute("DELETE FROM pd_exception_types WHERE id = %s", (type_id,))
                    # pd_exception_reports 外键 ON DELETE SET NULL，会自动置空 exception_type_id
                    return {
                        "success": True,
                        "message": "异常类型删除成功",
                        "data": {"id": type_id},
                    }
        except Exception as e:
            logger.error(f"删除异常类型失败: {e}")
            return {"success": False, "error": str(e)}


_exception_type_service = None


def get_exception_type_service() -> ExceptionTypeService:
    global _exception_type_service
    if _exception_type_service is None:
        _exception_type_service = ExceptionTypeService()
    return _exception_type_service
