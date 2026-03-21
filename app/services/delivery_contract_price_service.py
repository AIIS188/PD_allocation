"""
报单关联合同的品类单价：从合同品种表同步、按报单维度查询与改价
"""
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pymysql.cursors import DictCursor

from app.services.contract_service import get_conn

logger = logging.getLogger(__name__)

_TABLE_ENSURED = False


def _ensure_table() -> None:
    global _TABLE_ENSURED
    if _TABLE_ENSURED:
        return
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pd_delivery_contract_product_prices (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
                        delivery_id BIGINT NOT NULL COMMENT '报单ID（pd_deliveries.id）',
                        contract_id BIGINT NOT NULL COMMENT '合同ID（同步自报单关联合同）',
                        product_name VARCHAR(64) NOT NULL COMMENT '品类名称',
                        unit_price DECIMAL(12, 2) NOT NULL COMMENT '单价（元）',
                        sort_order INT NOT NULL DEFAULT 0 COMMENT '排序',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
                        UNIQUE KEY uk_delivery_product (delivery_id, product_name),
                        INDEX idx_delivery_id (delivery_id),
                        INDEX idx_contract_id (contract_id),
                        CONSTRAINT fk_dcpp_delivery FOREIGN KEY (delivery_id)
                            REFERENCES pd_deliveries(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='报单关联合同品类单价表';
                    """
                )
            conn.commit()
        _TABLE_ENSURED = True
    except Exception as e:
        logger.warning("ensure pd_delivery_contract_product_prices: %s", e)


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for key, val in out.items():
        if isinstance(val, datetime):
            out[key] = val.isoformat(sep=" ", timespec="seconds")
        elif isinstance(val, date):
            out[key] = val.isoformat()
        elif isinstance(val, Decimal):
            out[key] = float(val)
    return out


class DeliveryContractPriceService:
    def _get_delivery_contract_id(self, cur, delivery_id: int) -> tuple[Optional[int], Optional[str]]:
        cur.execute(
            """
            SELECT contract_id, contract_no FROM pd_deliveries WHERE id = %s
            """,
            (delivery_id,),
        )
        row = cur.fetchone()
        if not row:
            return None, "报单不存在"
        cid = row.get("contract_id") if isinstance(row, dict) else row[0]
        cno = row.get("contract_no") if isinstance(row, dict) else row[1]
        if cid:
            try:
                return int(cid), None
            except (TypeError, ValueError):
                cid = None
        if cno:
            cur.execute("SELECT id FROM pd_contracts WHERE contract_no = %s LIMIT 1", (cno,))
            r2 = cur.fetchone()
            if r2:
                rid = r2.get("id") if isinstance(r2, dict) else r2[0]
                return int(rid), None
        return None, "报单未关联合同，无法同步品类单价"

    def list_by_delivery(self, delivery_id: int) -> Dict[str, Any]:
        _ensure_table()
        try:
            with get_conn() as conn:
                with conn.cursor(DictCursor) as cur:
                    cur.execute("SELECT id FROM pd_deliveries WHERE id = %s", (delivery_id,))
                    if not cur.fetchone():
                        return {"success": False, "error": f"报单 ID {delivery_id} 不存在"}
                    cur.execute(
                        """
                        SELECT id, delivery_id, contract_id, product_name, unit_price, sort_order,
                               created_at, updated_at
                        FROM pd_delivery_contract_product_prices
                        WHERE delivery_id = %s
                        ORDER BY sort_order, id
                        """,
                        (delivery_id,),
                    )
                    rows = [_serialize_row(dict(r)) for r in (cur.fetchall() or [])]
                    return {"success": True, "data": rows}
        except Exception as e:
            logger.error("list delivery contract prices: %s", e)
            return {"success": False, "error": str(e)}

    def fetch_prices_by_delivery_ids(
        self, delivery_ids: List[int]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """批量查询多个报单下的合同品类单价，供列表接口拼接。"""
        _ensure_table()
        if not delivery_ids:
            return {}
        try:
            uniq = list({int(i) for i in delivery_ids})
            placeholders = ",".join(["%s"] * len(uniq))
            with get_conn() as conn:
                with conn.cursor(DictCursor) as cur:
                    cur.execute(
                        f"""
                        SELECT id, delivery_id, contract_id, product_name, unit_price, sort_order,
                               created_at, updated_at
                        FROM pd_delivery_contract_product_prices
                        WHERE delivery_id IN ({placeholders})
                        ORDER BY delivery_id, sort_order, id
                        """,
                        tuple(uniq),
                    )
                    rows = cur.fetchall() or []
            out: Dict[int, List[Dict[str, Any]]] = {}
            for r in rows:
                d = _serialize_row(dict(r))
                did = int(d["delivery_id"])
                out.setdefault(did, []).append(d)
            return out
        except Exception as e:
            logger.warning("fetch_prices_by_delivery_ids: %s", e)
            return {}

    def sync_from_contract(self, delivery_id: int) -> Dict[str, Any]:
        _ensure_table()
        try:
            with get_conn() as conn:
                prev_ac = conn.get_autocommit()
                conn.autocommit(False)
                try:
                    with conn.cursor(DictCursor) as cur:
                        cur.execute("SELECT id FROM pd_deliveries WHERE id = %s", (delivery_id,))
                        if not cur.fetchone():
                            conn.rollback()
                            return {"success": False, "error": f"报单 ID {delivery_id} 不存在"}

                        contract_id, err = self._get_delivery_contract_id(cur, delivery_id)
                        if contract_id is None:
                            conn.rollback()
                            return {"success": False, "error": err or "无法解析合同"}

                        cur.execute(
                            """
                            SELECT product_name, unit_price, sort_order
                            FROM pd_contract_products
                            WHERE contract_id = %s
                            ORDER BY sort_order, id
                            """,
                            (contract_id,),
                        )
                        products = cur.fetchall() or []
                        if not products:
                            conn.rollback()
                            return {
                                "success": False,
                                "error": "该合同下没有品种明细，无法同步",
                            }

                        cur.execute(
                            "DELETE FROM pd_delivery_contract_product_prices WHERE delivery_id = %s",
                            (delivery_id,),
                        )
                        for idx, p in enumerate(products):
                            name = (p.get("product_name") or "").strip()
                            if not name:
                                continue
                            up = p.get("unit_price")
                            if up is None:
                                up = Decimal("0")
                            else:
                                up = Decimal(str(up))
                            so = int(p.get("sort_order") or idx)
                            cur.execute(
                                """
                                INSERT INTO pd_delivery_contract_product_prices
                                (delivery_id, contract_id, product_name, unit_price, sort_order)
                                VALUES (%s, %s, %s, %s, %s)
                                """,
                                (delivery_id, contract_id, name, up, so),
                            )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.autocommit(prev_ac)
            result = self.list_by_delivery(delivery_id)
            result["message"] = "已从合同品种表同步"
            return result
        except Exception as e:
            logger.error("sync delivery contract prices: %s", e)
            err = str(e)
            if "Duplicate entry" in err and "uk_delivery_product" in err:
                return {"success": False, "error": "品类名称在同一报单下重复"}
            return {"success": False, "error": err}

    def update_unit_prices(
        self,
        delivery_id: int,
        items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        _ensure_table()
        if not items:
            return {"success": False, "error": "items 不能为空"}
        try:
            with get_conn() as conn:
                prev_ac = conn.get_autocommit()
                conn.autocommit(False)
                try:
                    with conn.cursor(DictCursor) as cur:
                        cur.execute("SELECT id FROM pd_deliveries WHERE id = %s", (delivery_id,))
                        if not cur.fetchone():
                            conn.rollback()
                            return {"success": False, "error": f"报单 ID {delivery_id} 不存在"}

                        for it in items:
                            row_id = it.get("id")
                            pname = (it.get("product_name") or "").strip() if it.get("product_name") else None
                            if row_id is None and not pname:
                                conn.rollback()
                                return {
                                    "success": False,
                                    "error": "每项须提供 id 或 product_name",
                                }
                            try:
                                price = Decimal(str(it.get("unit_price")))
                            except Exception:
                                conn.rollback()
                                return {"success": False, "error": "unit_price 无效"}
                            if price < 0:
                                conn.rollback()
                                return {"success": False, "error": "单价不能为负"}

                            if row_id is not None:
                                cur.execute(
                                    """
                                    UPDATE pd_delivery_contract_product_prices
                                    SET unit_price = %s
                                    WHERE id = %s AND delivery_id = %s
                                    """,
                                    (price, int(row_id), delivery_id),
                                )
                                if cur.rowcount == 0:
                                    conn.rollback()
                                    return {
                                        "success": False,
                                        "error": f"记录 id={row_id} 不属于该报单或不存在",
                                    }
                            else:
                                cur.execute(
                                    """
                                    UPDATE pd_delivery_contract_product_prices
                                    SET unit_price = %s
                                    WHERE delivery_id = %s AND product_name = %s
                                    """,
                                    (price, delivery_id, pname),
                                )
                                if cur.rowcount == 0:
                                    conn.rollback()
                                    return {
                                        "success": False,
                                        "error": f"品类「{pname}」在该报单下不存在",
                                    }
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.autocommit(prev_ac)
            out = self.list_by_delivery(delivery_id)
            out["message"] = "单价已更新"
            return out
        except Exception as e:
            logger.error("update delivery contract prices: %s", e)
            return {"success": False, "error": str(e)}


_service: Optional[DeliveryContractPriceService] = None


def get_delivery_contract_price_service() -> DeliveryContractPriceService:
    global _service
    if _service is None:
        _service = DeliveryContractPriceService()
    return _service
