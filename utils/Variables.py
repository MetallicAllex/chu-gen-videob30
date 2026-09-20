"""
常量定义模块
"""

import os

# 全局配置变量
asset_paths = {}
root_path = "./assets"
font_path = f"{root_path}/fonts"
bgclips_path = f"{root_path}/BgClips"
audios_path = f"{root_path}/Audios"
image_root_path = f"{root_path}/images"
thumbnails_dir = f"{root_path}/thumbnails"
combo_img_path = f"{image_root_path}/ComboStatus"
comment_font_path = f"{font_path}/FOT_NewRodin_Pro_EB.otf"
ui_font_path = f"{font_path}/SOURCEHANSANSSC-BOLD.OTF"
title_font_path = f"{font_path}/SweiBellLegCJKsc-Black.ttf"
level_font_path = f"{font_path}/NimbusSanL-Bol.otf"
# 曲目列表
music_info_path = './music_datasets/all_music_infos.json'
jp_music_info_path = './music_datasets/jp_songs_info.json'
intl_music_info_path = './music_datasets/intl_songs_info.json'
# --- 日服 / 国际服曲库的 R2 镜像（cloudflare/music-db 那个 Worker 定时写入）---
# 两家不一样：国际服的源在 GitHub raw 上、还要清洗过才能用，多数人直连不到，
# 对这个包来说更新能力就等于这个镜像的可用性 —— URL 为空时只能停在包里那份快照。
# 日服就算没配 URL 也能直连 chunirec，但 Worker 那份是 chunirec × otoge join 过的：
# meta 里多带 version（直连的原始导出没有），所以这里也默认走镜像，直连只剩兜底。
# 产物键名固定在 chunithm/ 前缀下；要指到别处用环境变量 INTL_MUSIC_URL / JP_MUSIC_URL 覆盖。
_R2_BASE = "https://hk-proxy.cm-tea.top/chunithm"
# 记账不放进球库那一层（打包容易漏带，`.meta.json` 也容易被误认成又一份曲库）。
# status 下只有两份，按"谁在写"切：sources.json 是各源的条件请求记账（取数时逐源写），
# local.json 是本机这一轮的结果（云端状态 + 退避记录，轮次收尾时写）。
# 合成一份就得让不同时刻的写者去读改写同一个文件，那是自己给自己造"覆盖别人刚写的那段"。
music_status_dir = './music_datasets/status'
jp_music_info_url = os.environ.get("JP_MUSIC_URL", f"{_R2_BASE}/jp_songs_info.json")
intl_music_info_url = os.environ.get("INTL_MUSIC_URL", f"{_R2_BASE}/intl_songs_info.json")
# 取曲库时发的客户端标识：自报身份，便于在对端（镜像、落雪、水鱼）的日志里认出是谁在拉，
# 也比默认的 python-requests/* 好归因。改它不牵涉任何放行规则 —— 实测三种 UA 都能取到，
# 这条链路真正的问题是偶发连接重置/读超时，那由 DataUtils._get_with_retry 处理。
MUSIC_DATA_USER_AGENT = os.environ.get(
    "CHU_MUSIC_UA",
    "chu-gen-videob30-music-sync (+https://github.com/MetallicAllex/chu-gen-videob30)")
# 国服建存档的筛选项要靠曲库补齐（水鱼返回体里没有 artist/genre/bpm/version/charter）
fish_music_info_path = './music_datasets/fish_music_data.json'
fish_latest_version_path = './music_datasets/fish_latest_version.json'
# 国服 song/list 的 versions/genres 两张表，取数时被 transformer 丢掉过，单独落盘。
# 这份是筛选层要读的数据（不是记账），所以留在库那一层。
cn_song_meta_path = './music_datasets/cn_songs_meta.json'

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

# --- 以下枚举是筛选项的取值域，值与说明逐条照抄 lxns-chunithm-api-docs.md「数据模型」---
# 上面两个列表服务渲染层（按下标取图），这两份服务筛选层（按取值匹配），不要合并

CHUNI_FULL_COMBO_TYPES = {
    "fullcombo": "FULL COMBO",
    "alljustice": "ALL JUSTICE",
    "alljusticecritical": "AJC",
}

CHUNI_FULL_CHAIN_TYPES = {
    "fullchain": "铂 FULL CHAIN",
    "fullchain2": "金 FULL CHAIN",
}

CHUNI_CLEAR_TYPES = {
    "clear": "CLEAR",
    "hard": "HARD",
    "brave": "BRAVE",
    "absolute": "ABSOLUTE",
    "catastrophy": "CATASTROPHY",
    "failed": "FAILED",
}

CHUNI_RANK_TYPES = {
    "sssp": "SSS+",
    "sss": "SSS",
    "ssp": "SS+",
    "ss": "SS",
    "sp": "S+",
    "s": "S",
    "aaa": "AAA",
    "aa": "AA",
    "a": "A",
    "bbb": "BBB",
    "bb": "BB",
    "b": "B",
    "c": "C",
    "d": "D",
}

# 难度下标 -> 中文名。5 是 WORLD'S END，素材与渲染都不支持，筛选项里不放开
CHUNI_LEVEL_NAMES = {
    0: "BASIC",
    1: "ADVANCED",
    2: "EXPERT",
    3: "MASTER",
    4: "ULTIMA",
}

# 区间滑块的取值域 (min, max, step)。取的是两家实测范围的超集（水鱼完整历史
# ds 3.0~15.7 / ra 3.73~16.54，落雪 rating 16.35~17.07、over_power 81~87），
# 两端必须留白：滑到 min / max 表示该侧不限，否则"没动过的默认全区间"会被
# 当成一条真条件，把缺该字段的记录悄悄剔掉。
CN_FILTER_RANGES = {
    "ds_range": (1.0, 16.0, 0.1),
    "score_range": (500000, 1010000, 500),
    "rating_range": (0.0, 18.0, 0.1),
    "over_power_range": (0.0, 120.0, 0.5),
    "bpm_range": (30, 300, 1),
}

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

# 更新曲目数据所使用的难度映射
DIFFICULTY_MAP = {
    "BAS": "BASIC",
    "ADV": "ADVANCED",
    "EXP": "EXPERT",
    "MAS": "MASTER",
    "ULT": "ULTIMA"
}

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

ACCEL_BRAND = ["NVIDIA", "AMD", "Intel"]
# ACCEL_BRAND_CAPTIONS = ["NVENCoder(NVENC)", "AMFramework(含集显)", "QSyncVideo(含集显)"]

# 预设视频列表/合集源
# 格式: {平台: {作者: [(ID, 标题), ...]}}
VIDEO_LISTS = {
    "bilibili": {
        "中二熊与迪拉企鹅": [
            (2869420, "彩谱"),
            (8009176, "16"),
            (5972048, "15+"),
            (1476789, "15"),
            (1474948, "14+"),
            (2869059, "14"),
            (6469785, "10 ~ 13+")
        ],
        "Mr_Circle": [
            ("BV1CXT46TEVU", "Mate"),
            ("BV17em1BCEE6", "X-VERSE-X"),
            ("BV1ctu4zHEmx", "X-VERSE"),
            ("BV1RwkPYjEAP", "VERSE"),
            ("BV1pw4m1a7Ak", "LUMINOUS+"),
            ("BV1nC4y1Q75i", "LUMINOUS"),
            ("BV1rg4y1G7H6", "SUN+"),
            ("BV1U44y1f7am", "SUN"),
            ("BV1BY4y1h7DF", "NEW!!+"),
            ("BV1gL4y1q7kz", "NEW!!"),
            ("BV1aA411G7yc", "PARADISE LOST"),
            ("BV1dz4y1S7cm", "PARADISE"),
            ("BV1bz411v7qR", "CRYSTAL+"),
            ("BV1yE411y723", "CRYSTAL"),
            ("BV1kb411M7tX", "AMAZON+"),
            ("BV1mb411P7ou", "AMAZON"),
            ("BV1JW411C7p9", "AIR+"),
            ("BV1EW411C73Q", "AIR"),
            ("BV1EW411C7Wc", "STAR+"),
            ("BV1EW411C7r4", "STAR"),
            ("BV1xW411d7c4", "初代+"),
            ("BV1xW411d7dw", "初代(2)"),
            ("BV1sW411d7ho", "初代")
        ]
    },
    "youtube": {
        "チュウニズム譜面保管所(8.0)": [
            ("PLo8aaA3Hh3kSLDGp_RR34jji9e_KdD-kk", "所有黑谱[ULTIMA]"),
            ("PLo8aaA3Hh3kSKcupe925RI7cE9crb6mnU", "15+ 紫谱[MASTER]"),
            ("PLo8aaA3Hh3kQfRcFGLEf0B5GlWphqBqKp", "15 紫谱[MASTER]"),
            ("PLo8aaA3Hh3kTrkuqQhNSRLIrg80oL7lV9", "14+ 紫谱[MASTER]"),
            ("PLo8aaA3Hh3kT0MPGsJrGo-roBTgXCdiW0", "14 紫谱[MASTER]"),
        ],
        "チュウニズム譜面保管所(9.0)": [
            ("PLo8aaA3Hh3kQz17E5V_N-r907co0iRutH", "所有黑谱[ULTIMA]"),
            ("PLo8aaA3Hh3kQCw7_vRUQcOJIMB5maNIMr", "15+ 紫谱[MASTER]"),
            ("PLo8aaA3Hh3kQMmR0AGbMJuiLunlVs8OAF", "15 紫谱[MASTER]"),
            ("PLo8aaA3Hh3kTsEZZ1uy5-XuXa5_L_zWI2", "14+ 紫谱[MASTER]"),
            ("PLo8aaA3Hh3kT4wO7GE_5_c1myTw1iVSEc", "14 紫谱[MASTER]"),
            ("PLo8aaA3Hh3kTN2ShcX0IyWIZVJvCnT4Fd", "彩谱[WORLD'S END]")
        ],
        "チュウニズム譜面保管所(8.0+9.0)": [
            ("PLo8aaA3Hh3kQ6LPDo8vqa-yuHQtgt7AfE", "14 红谱[EXPERT]"),
            ("PLo8aaA3Hh3kTt3xnXv5fgMRUyxToagESQ", "14+ 红谱[EXPERT]")
        ]
        # "Uploader": [
        #     ("PLxxx", "CHUNITHM 譜面確認 MASTER"),
        # ],
    },
}