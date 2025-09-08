"""
CHUNITHM 扩展工具模块
包含游戏相关常量定义
"""

# 难度等级映射关系
CHUNI_LEVELS = {
    0: "BASIC",
    1: "ADVANCED",
    2: "EXPERT", 
    3: "MASTER",
    4: "ULTIMA"  # 仅部分曲目存在
}

# 连击达成类型
CHUNI_COMBO_TYPES = [
    "none",        # 未达成
    "fullcombo",   # FC
    "alljustice"   # AJ
]

# 连锁达成类型（None表示未达成）
CHUNI_CHAIN_TYPES = [
    None,
    "fullchain",   # FC
    "fullchain+"   # FC+
]

# 旧版本兼容（部分旧存档可能使用的字段名）
LEGACY_LEVEL_LABELS = ["BASIC", "ADVANCED", "EXPERT", "MASTER"]