"""
货主品种 -> 冶炼厂品种 映射（与合同、报单、磅单统一）
"""
# 货主/OCR常用名称 -> 冶炼厂合同品种名称
OWNER_TO_MILL_MAPPING = {
    "电动": "电动车",
    "黑皮": "黑皮",
    "EFB": "黑皮",
    "电轿": "新能源",
    "AGM": "新能源",
    "电信": "通信",
    "摩托车": "摩托车",
    "小四斤": "摩托车",
    "大白": "大白",
    "管式": "牵引",
}


def convert_to_mill_product(owner_product: str) -> str:
    """将货主品种转换为冶炼厂品种（用于合同匹配、磅单存储）"""
    if not owner_product:
        return owner_product
    s = str(owner_product).strip()
    return OWNER_TO_MILL_MAPPING.get(s, s)
