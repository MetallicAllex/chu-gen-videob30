"""
常量定义模块
"""

# 全局配置变量
asset_paths = {}
root_path = "./assets"
font_path = f"{root_path}/fonts"
bgclips_path = f"{root_path}/BgClips"
audios_path = f"{root_path}/Audios"
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
    },
    # 国际服字段（待补充）
    "intr": {
        "全都要": ["best", "new"],
        "仅旧曲": "best",
        "仅新曲": "new"
    }
}

# 旧版本兼容（部分旧存档可能使用的字段名）
LEGACY_LEVEL_LABELS = ["BASIC", "ADVANCED", "EXPERT", "MASTER"]

# ffmpeg xfade 滤镜支持的转场效果列表
XFADE_TRANSITIONS = [
    "fade",           # 0  渐变过渡（默认）
    "wipeleft",       # 1  从左向右擦除
    "wiperight",      # 2  从右向左擦除
    "wipeup",         # 3  从下向上擦除
    "wipedown",       # 4  从上向下擦除
    "slideleft",      # 5  向左滑动
    "slideright",     # 6  向右滑动
    "slideup",        # 7  向上滑动
    "slidedown",      # 8  向下滑动
    "circlecrop",     # 9  圆形裁剪过渡
    "rectcrop",       # 10 矩形裁剪过渡
    "distance",       # 11 距离过渡
    "fadeblack",      # 12 黑色渐变
    "fadewhite",      # 13 白色渐变
    "radial",         # 14 径向过渡
    "smoothleft",     # 15 平滑向左滑动
    "smoothright",    # 16 平滑向右滑动
    "smoothup",       # 17 平滑向上滑动
    "smoothdown",     # 18 平滑向下滑动
    "circleopen",     # 19 圆形打开
    "circleclose",    # 20 圆形关闭
    "vertopen",       # 21 垂直打开
    "vertclose",      # 22 垂直关闭
    "horzopen",       # 23 水平打开
    "horzclose",      # 24 水平关闭
    "dissolve",       # 25 溶解效果
    "pixelize",       # 26 像素化过渡
    "diagtl",         # 27 左上到右下对角线
    "diagtr",         # 28 右上到左下对角线
    "diagbl",         # 29 左下到右上对角线
    "diagbr",         # 30 右下到左上对角线
    "hlslice",        # 31 水平向左切片
    "hrslice",        # 32 水平向右切片
    "vuslice",        # 33 垂直向上切片
    "vdslice",        # 34 垂直向下切片
    "hblur",          # 35 水平模糊
    "fadegrays",      # 36 灰度渐变
    "wipetl",         # 37 从左上到右下擦除
    "wipetr",         # 38 从右上到左下擦除
    "wipebl",         # 39 从左下到右上擦除
    "wipebr",         # 40 从右下到左上擦除
    "squeezeh",       # 41 水平挤压
    "squeezev",       # 42 垂直挤压
    "zoomin",         # 43 放大过渡
    "fadefast",       # 44 快速渐变
    "fadeslow",       # 45 慢速渐变
    "hlwind",         # 46 水平左风效果
    "hrwind",         # 47 水平右风效果
    "vuwind",         # 48 垂直上风效果
    "vdwind",         # 49 垂直下风效果
    "coverleft",      # 50 从左侧覆盖
    "coverright",     # 51 从右侧覆盖
    "coverup",        # 52 从上方覆盖
    "coverdown",      # 53 从下方覆盖
    "revealleft",     # 54 向左侧显示
    "revealright",    # 55 向右侧显示
    "revealup",       # 56 向上方显示
    "revealdown",     # 57 向下方显示
]

# xfade 滤镜前缀
XFADE_TRANSITIONS_PREFIX = [
    "wipe",           # 1  从左向右（右向左、下向上、上向下）擦除
    "slide",          # 5  向左（右、上、下）滑动
    "fadeblack",      # 12 黑（白）色渐变
    "smoothleft",     # 15 平滑向左滑动
    "circleopen",     # 19 圆形打开（关闭）
    "vertopen",       # 21 垂直打开（关闭）
    "horzopen",       # 23 水平打开（关闭）
    "diagtl",         # 27 左上到右下（右上到左下、左下到右上、右下到左上）对角线
    "wipetl",         # 37 从左上到右下擦除
    "squeezeh",       # 41 水平（垂直）挤压
    "fadefast",       # 44 快（慢）速渐变
    "coverleft",      # 50 从左（右）侧覆盖
    "revealleft",     # 54 向左（右）侧显示
]

# xfade 滤镜后缀
XFADE_TRANSITIONS_SUFFIX = [
    "fade",           # 0  渐变过渡（默认）
    "circlecrop",     # 9  圆（矩）形裁剪过渡
    "distance",       # 11 距离过渡
    "radial",         # 14 径向过渡
    "dissolve",       # 25 溶解效果
    "pixelize",       # 26 像素化过渡
    "hlslice",        # 31 水平向左（水平向右、垂直向上、垂直向下）切片
    "hblur",          # 35 水平模糊
    "fadegrays",      # 36 灰度渐变
    "zoomin",         # 43 放大过渡
    "hlwind",         # 46 水平左风（水平右、垂直上、垂直下风）效果
    "custom"          # 57 自定义（高级） 
]

HARD_RENDER_METHOD = {
    "NVIDIA": { "codec": "nvenc" },
    "AMD": { "codec": "amf" },
    "Intel": { "codec": "qsv" },
    "d3d12va": { "codec": "d3d12va" }
}

HARDWARE_ENCODER = ["h264", "hevc"]
SOFTWARE_ENCODER = ["libx264", "libx265"]

ACCEL_BRAND = ["d3d12va", "NVIDIA", "AMD", "Intel"]
# ACCEL_BRAND_CAPTIONS = ["自动选择(可能不准确)", "NVENCoder(NVENC)", "AMFramework(含集显)", "QSyncVideo(含集显)"]