"""
常量定义模块
"""

# 全局配置变量
asset_paths = {}
root_path = "./assets"
font_path = f"{root_path}/fonts"
image_root_path = f"{root_path}/images"
comment_font_path = f"{font_path}/FOT_NewRodin_Pro_EB.otf"
ui_font_path = f"{font_path}/SOURCEHANSANSSC-BOLD.OTF"
title_font_path = f"{font_path}/SweiBellLegCJKsc-Black.ttf"
level_font_path = f"{font_path}/NimbusSanL-Bol.otf"

# 难度等级映射关系
REVERSE_LEVEL_LABELS = {
    0: "BASIC",
    1: "ADVANCED",
    2: "EXPERT",
    3: "MASTER",
    4: "ULTIMA",
}

LEVEL_LABELS = {
    "BASIC": 0,
    "ADVANCED": 1,
    "EXPERT": 2,
    "MASTER": 3,
    "ULTIMA": 4,
}

# 连击达成类型
CHUNI_COMBO_TYPES = [
    None,        # 未达成
    "fullcombo",   # FC
    "alljustice"   # AJ
]

# 连锁达成类型（None表示未达成）
CHUNI_CHAIN_TYPES = [
    None,
    "fullchain",   # FC
    "fullchain2"   # FC+
]

# 获取数据类型
CHUNI_DATA_TYPE = {
    "lxns": {
        "全都要": ["data.bests", "data.new_bests"],
        "仅旧曲": "data.bests",
        "仅新曲": "data.new_bests"
    },
    "fish": {
        "全都要": ["records.b30", "records.n20"],
        "仅旧曲": "records.b30",
        "仅新曲": "records.n20"
    }
}

# 旧版本兼容（部分旧存档可能使用的字段名）
LEGACY_LEVEL_LABELS = ["BASIC", "ADVANCED", "EXPERT", "MASTER"]

HARD_RENDER_METHOD = {
    "NVIDIA": {
        "hwaccel": "cuda",
        "codec": "nvenc"
    },
    "AMD": {
        "hwaccel": "amf", 
        "codec": "amf"
    },
    "Intel": {
        "hwaccel": "qsv",
        "codec": "qsv"
    }
}