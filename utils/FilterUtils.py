"""
国服成绩池的规范化、筛选与参数翻译。

纯函数层：只依赖标准库，不 import streamlit / requests / DataUtils，
所以取数链路可以整体打桩、这一层可以脱离网络与界面单独验证。

规范化记录（CANON_KEYS）是谓词层唯一认得的输入：两家 provider 的原始字段
都先 join 一次曲库再落成同一套键，缺失值为 None。
"""

CANON_KEYS = (
    "_id", "_title", "_level_index", "_level", "_ds", "_score", "_rating",
    "_fc", "_chain", "_clear", "_rank", "_over_power",
    "_artist", "_genre", "_bpm", "_version", "_charter", "_aliases",
    "_part", "_raw",
)

PART_BEST = "Best"
PART_NEW = "New"
PART_SELECT = "Select"

# 分组在存档里的固定先后顺序。raw 重建与 clip 编号都必须按这个顺序展开，
# 两者同序才不会出现"Best_1 对上另一条成绩"。
PART_ORDER = (PART_BEST, PART_NEW, PART_SELECT)

# 谓词求值顺序固定：每条成绩只记在第一个把它淘汰的字段上，
# 预览里的"因缺 X 排除 n 条"才是可解释的，而不是各字段各自重复计数。
FILTER_ORDER = (
    "level_index", "ds_range", "score_range", "rating_range",
    "fc", "chain", "clear", "rank", "over_power_range",
    "title_keyword", "artist", "genre", "version", "charter", "bpm_range",
)

FIELD_LABELS = {
    "level_index": "难度",
    "ds_range": "定数",
    "score_range": "分数",
    "rating_range": "单曲 Rating",
    "fc": "全连状态",
    "chain": "链条状态",
    "clear": "达成状态",
    "rank": "评级",
    "over_power_range": "Over Power",
    "title_keyword": "曲名关键字",
    "artist": "曲师",
    "genre": "曲风",
    "version": "版本",
    "charter": "谱师",
    "bpm_range": "BPM",
}

# spec 里的区间字段 -> 规范化记录的字段
RANGE_FIELDS = {
    "ds_range": "_ds",
    "score_range": "_score",
    "rating_range": "_rating",
    "over_power_range": "_over_power",
    "bpm_range": "_bpm",
}

# spec 里的集合字段 -> 规范化记录的字段
SET_FIELDS = {
    "level_index": "_level_index",
    "artist": "_artist",
    "genre": "_genre",
    "version": "_version",
    "charter": "_charter",
    "rank": "_rank",
    "clear": "_clear",
}

# 达成状态里 None 是一个真实取值（"未达成"），不参与"缺信息"统计
OPTIONAL_VALUE_FIELDS = {"fc": "_fc", "chain": "_chain"}


class EmptyFilterResult(Exception):
    """筛选后一条成绩都不剩。抛得越早越干净 —— 调用方必须在写任何文件之前接住它。"""


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _loose_eq(left, right):
    """数值相等优先，否则忽略大小写比字符串 —— 版本在水鱼是 'CHUNITHM VERSE'、在落雪是 23000。"""
    if left is None or right is None:
        return False
    ln, rn = _num(left), _num(right)
    if ln is not None and rn is not None:
        return ln == rn
    return str(left).strip().lower() == str(right).strip().lower()


def _in_any(value, options):
    return any(_loose_eq(value, option) for option in options)


def _in_range(value, bounds):
    lo, hi = bounds
    number = _num(value)
    if number is None:
        return None
    if lo is not None and number < _num(lo):
        return False
    if hi is not None and number > _num(hi):
        return False
    return True


def canon(**values):
    record = {key: None for key in CANON_KEYS}
    record["_aliases"] = []
    record.update({k: v for k, v in values.items() if k in CANON_KEYS})
    return record


def build_fish_chart_index(music_data):
    """水鱼 /music_data -> {mid: 曲目条目}。ds / level / cids / charts 按 level_index 下标对齐。"""
    index = {}
    for entry in music_data or []:
        song_id = entry.get("id", entry.get("music_id"))
        if song_id is not None:
            index[song_id] = entry
    return index


def build_alias_index(songs):
    """本地 all_music_infos -> {id: 别名列表}。水鱼返回体里没有别名字段，曲名关键字要靠它补。"""
    return {entry["id"]: list(entry.get("aliases") or [])
            for entry in songs or [] if entry.get("id") is not None}


def build_lxns_song_index(songs):
    """本地 all_music_infos -> {id: 曲目条目}，同时把 difficulties 摊成 level_index 序。"""
    index = {}
    for entry in songs or []:
        song_id = entry.get("id")
        if song_id is None:
            continue
        charts = {}
        for chart in entry.get("difficulties", []) or []:
            level_index = chart.get("difficulty")
            if level_index is not None:
                charts[int(level_index)] = chart
        enriched = dict(entry)
        enriched["_charts"] = charts
        index[song_id] = enriched
    return index


def _fish_meta(chart_index, mid, level_index):
    """水鱼记录里 artist/genre/bpm/version/charter 只用于服务端过滤、不在返回体里，全部靠曲库补。"""
    if not chart_index:
        return {}
    entry = chart_index.get(mid) or chart_index.get(str(mid))
    if not entry:
        return {}
    basic = entry.get("basic_info") or {}
    charts = entry.get("charts") or []
    chart = charts[level_index] if isinstance(level_index, int) and 0 <= level_index < len(charts) else {}
    return {
        "_artist": basic.get("artist"),
        "_genre": basic.get("genre"),
        "_bpm": basic.get("bpm"),
        "_version": basic.get("from"),
        "_charter": chart.get("charter") if chart else None,
    }


def _fish_score_fields(song, part):
    return canon(
        _id=song.get("mid"),
        _title=song.get("title"),
        _level_index=song.get("level_index"),
        _level=song.get("level"),
        _ds=song.get("ds"),
        _score=song.get("score"),
        _rating=song.get("ra"),
        _fc=(song.get("fc") or None),
        _part=part,
        _raw=song,
    )


def _fish_item(song, part, chart_index, alias_index):
    item = _fish_score_fields(song, part)
    item.update(_fish_meta(chart_index, item["_id"], item["_level_index"]))
    if alias_index:
        item["_aliases"] = list(alias_index.get(item["_id"]) or alias_index.get(str(item["_id"])) or [])
    return item


def normalize_fish_b50(raw, chart_index=None, alias_index=None):
    """水鱼 /query/player：records.b30 / records.n20 已由服务端切好。"""
    records = (raw or {}).get("records") or {}
    items = []
    for part, key in ((PART_BEST, "b30"), (PART_NEW, "n20")):
        for song in records.get(key) or []:
            items.append(_fish_item(song, part, chart_index, alias_index))
    return items


def normalize_fish_records(raw, chart_index=None, latest_versions=None, alias_index=None):
    """水鱼 /player/records：records.best 是每谱面一条历史最佳，新旧归属由曲库版本判定。"""
    records = (raw or {}).get("records") if isinstance(raw, dict) else raw
    if isinstance(records, dict):
        records = records.get("best") or []
    latest = set(latest_versions or [])
    items = []
    for song in records or []:
        item = _fish_item(song, PART_BEST, chart_index, alias_index)
        # 水鱼完整历史返回体里没有版本字段，新旧只能由曲库的 basic_info.from 判
        item["_part"] = PART_NEW if latest and item["_version"] in latest else PART_BEST
        items.append(item)
    return items


def _lxns_score_fields(song, part):
    return canon(
        _id=song.get("id"),
        _title=song.get("song_name"),
        _level_index=song.get("level_index"),
        _level=song.get("level"),
        _score=song.get("score"),
        _rating=song.get("rating"),
        _over_power=song.get("over_power"),
        _fc=song.get("full_combo"),
        _chain=song.get("full_chain"),
        _clear=song.get("clear"),
        _rank=song.get("rank"),
        _part=part,
        _raw=song,
    )


def normalize_lxns(raw, song_index=None, new_versions=None, include_selections=False):
    """
    落雪：既吃 /player/bests 的 {data: {bests, new_bests, selections}}，也吃
    /player/scores 的扁平 Score[]（完整历史）。扁平输入没有现成的新旧标记，
    只能按 new_versions（本地曲库最高的两个 version）判定，判不出来就全归旧曲。
    """
    # data 既可能是 {bests,...} 分层字典，也可能是 Score[] 扁平列表，两种都要剥掉外层包裹
    payload = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
    items = []

    if isinstance(payload, list):
        for song in payload:
            items.append(_lxns_song(song, None, song_index, new_versions))
        return items

    payload = payload or {}
    groups = [(PART_BEST, "bests"), (PART_NEW, "new_bests")]
    if include_selections:
        groups.append((PART_SELECT, "selections"))
    for part, key in groups:
        for song in payload.get(key) or []:
            items.append(_lxns_song(song, part, song_index, new_versions))
    return items


def _lxns_song(song, part, song_index, new_versions):
    item = _lxns_score_fields(song, part)
    entry = (song_index or {}).get(item["_id"]) or (song_index or {}).get(str(item["_id"]))
    if entry:
        charts = entry.get("_charts") or {}
        chart = charts.get(item["_level_index"]) or {}
        item["_ds"] = chart.get("level_value")
        item["_level"] = item["_level"] or chart.get("level")
        item["_artist"] = entry.get("artist")
        item["_genre"] = entry.get("genre")
        item["_bpm"] = entry.get("bpm")
        item["_version"] = entry.get("version")
        item["_charter"] = chart.get("note_designer")
        item["_aliases"] = list(entry.get("aliases") or [])
    if part is None:
        new_versions = set(new_versions or [])
        item["_part"] = (PART_NEW if new_versions and item["_version"] in new_versions else PART_BEST)
    return item


def spec_is_active(spec, key):
    value = (spec or {}).get(key)
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _range_bounds(value):
    lo, hi = (list(value) + [None, None])[:2]
    return lo, hi


def apply_filters(items, spec, unsupported=()):
    """
    跨字段 AND、同字段取值 OR。

    生效字段值为 None 时该条不计入命中，并记进 stats["missing"] —— 落雪本地曲库
    实测缺 3 首歌，不报出来就是静默丢数据。
    unsupported 里的 spec 键不参与判定，只记进 stats["ignored"]：provider 压根没有
    这个字段时，把它当"未达成"筛会得到全 0 且理由误导人的结果。
    """
    spec = spec or {}
    stats = {
        "total": len(items),
        "hits": 0,
        "excluded_by": {},
        "missing": {},
        "applied": [],
        "ignored": [],
    }

    active = [key for key in FILTER_ORDER if spec_is_active(spec, key)]
    usable = []
    for key in active:
        if key in unsupported:
            stats["ignored"].append((key, "该数据源不提供此信息"))
        else:
            usable.append(key)
    stats["applied"] = usable

    hits = []
    for item in items:
        blocked = None
        for key in usable:
            matched, known = _match(item, key, spec[key])
            if matched:
                continue
            blocked = (key, known)
            break
        if blocked is None:
            hits.append(item)
            continue
        key, known = blocked
        stats["excluded_by"][key] = stats["excluded_by"].get(key, 0) + 1
        if not known:
            stats["missing"][key] = stats["missing"].get(key, 0) + 1

    stats["hits"] = len(hits)
    return hits, stats


def _match(item, key, value):
    """返回 (是否命中, 该条记录在这个字段上是否有值)。"""
    if key in RANGE_FIELDS:
        field = RANGE_FIELDS[key]
        raw = item.get(field)
        result = _in_range(raw, _range_bounds(value))
        if result is None:
            return False, raw is not None
        return result, True

    if key in SET_FIELDS:
        field = SET_FIELDS[key]
        raw = item.get(field)
        options = [v for v in _as_list(value) if v is not None and v != ""]
        if raw is None:
            return False, False
        return _in_any(raw, options), True

    if key in OPTIONAL_VALUE_FIELDS:
        field = OPTIONAL_VALUE_FIELDS[key]
        tokens = [str(v).strip().lower() for v in _as_list(value)]
        raw = item.get(field)
        normalized = None if raw is None else str(raw).strip().lower()
        if normalized:
            return normalized in tokens, True
        return ("none" in tokens), True

    if key == "title_keyword":
        keywords = [str(v).strip().lower() for v in _as_list(value) if str(v).strip()]
        haystacks = [str(item.get("_title") or "").strip().lower()]
        haystacks += [str(a).strip().lower() for a in (item.get("_aliases") or [])]
        return any(keyword in text for keyword in keywords for text in haystacks), True

    return True, True


def _as_list(value):
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


# --- 服务端参数翻译 -------------------------------------------------------------
# 只有能"精确表达"的条件才值得发出去：服务端少筛一条都不会错（本地精筛会补），
# 翻译错却会静默丢数据。所以拿不准的一律留在本地，并回报被放弃的原因。

def to_fish_params(spec):
    """把 spec 翻译成水鱼 /player/records 的查询参数，返回 (params, dropped)。"""
    spec = spec or {}
    params, dropped = {}, []

    def give_up(key, reason):
        dropped.append((key, reason))

    if spec_is_active(spec, "level_index"):
        values = [_num(v) for v in _as_list(spec["level_index"])]
        if any(v is None or v != int(v) for v in values):
            give_up("level_index", "取值非整数")
        else:
            params["level_index"] = ",".join(str(int(v)) for v in values)

    for key, name in (("ds_range", "ds"), ("score_range", "score"),
                      ("rating_range", "ra"), ("bpm_range", "bpm")):
        if not spec_is_active(spec, key):
            continue
        lo, hi = _range_bounds(spec[key])
        lo_num, hi_num = _num(lo), _num(hi)
        if lo is not None and lo_num is None:
            give_up(key, "下界不是数值")
            continue
        if hi is not None and hi_num is None:
            give_up(key, "上界不是数值")
            continue
        # 单边开区间必须留空（ds=14..），写 0 或 9999 会把该字段缺值的行为变成不可控的比较
        params[name] = f"{'' if lo is None else _trim_number(lo_num)}..{'' if hi is None else _trim_number(hi_num)}"

    if spec_is_active(spec, "fc"):
        tokens = [str(v).strip().lower() for v in _as_list(spec["fc"]) if str(v).strip()]
        if "none" in tokens and len(tokens) > 1:
            # ?fc=&fc=fullcombo 的混合语义没法离线证实，交给本地那一步
            give_up("fc", "同时包含未达成与已达成，服务端语义未证实")
        elif "none" in tokens:
            params["fc"] = ""
        else:
            unknown = [t for t in tokens if t not in ("fullcombo", "alljustice", "alljusticecritical")]
            if unknown:
                give_up("fc", f"未知取值 {'/'.join(unknown)}")
            else:
                params["fc"] = ",".join(tokens)

    for key, name in (("artist", "artist"), ("genre", "genre"),
                      ("version", "version"), ("charter", "charter")):
        if not spec_is_active(spec, key):
            continue
        values = [str(v).strip() for v in _as_list(spec[key]) if str(v).strip()]
        if any("," in v for v in values):
            # 服务端按逗号拆多值，曲师/谱师名里带逗号就会被拆错
            give_up(key, "取值含逗号，服务端会按多值拆分")
            continue
        params[name] = ",".join(values)

    for key in ("title_keyword", "clear", "chain", "rank", "over_power_range"):
        if spec_is_active(spec, key):
            reason = ("曲名是关键字子串匹配，服务端 title 为精确匹配" if key == "title_keyword"
                      else "水鱼不提供该字段")
            give_up(key, reason)

    return params, dropped


def _trim_number(value):
    if value == int(value):
        return str(int(value))
    return str(round(value, 6)).rstrip("0").rstrip(".")


# --- 截断与回显 -----------------------------------------------------------------

def cap_parts(items, caps):
    """
    各组按单曲 Rating 稳定降序取前 k 条，组内截断、组间保持首次出现的顺序。

    排序而非原样输出，是因为下游 clip_id 直接按列表顺序编号：完整历史池截断后
    如果不按 Rating 排，做出来的存档会出现 Best_5 比 Best_1 分高。
    caps 里没有的组原样保留（简略成绩模式不下限，也就不会被重排）。
    """
    if not caps:
        return list(items)

    groups = {}
    for order, item in enumerate(items):
        groups.setdefault(item.get("_part"), []).append((order, item))

    kept = []
    for part, members in groups.items():
        limit = caps.get(part)
        if limit is None:
            kept.extend(members)
            continue
        members.sort(key=lambda pair: (-(_num(pair[1].get("_rating")) or 0.0), pair[0]))
        kept.extend(members[:limit])

    return [item for _, item in kept]


def group_by_part(items):
    """{分组: 条目}，只保留非空分组，组内维持传入顺序（cap_parts 已排好）。"""
    groups = {}
    for item in items:
        groups.setdefault(item.get("_part"), []).append(item)
    return {part: groups[part] for part in PART_ORDER if groups.get(part)}


def ordered_by_part(items):
    """按 PART_ORDER 把各组串平，供 raw 重建与 clip_prefixes 共用同一份顺序。"""
    return [item for group in group_by_part(items).values() for item in group]


# --- 版本"代"：国服的一个版本在数据里占两档 ------------------------------------------
# 落雪每档差 500（22000 CHUNITHM LUMINOUS / 22500 LUMINOUS PLUS），一代就是同一个千位段。
# 不能靠标题后缀认 "PLUS"：CHUNITHM PARADISE 的第二档叫 PARADISE LOST，名字里没有 PLUS。
VERSION_GENERATION = 1000


def version_sort_key(value):
    """落雪是 version 整数（按数值排），水鱼是版本标题字符串。"""
    number = _num(value)
    return (0, number, "") if number is not None else (1, 0, str(value))


def version_generation(value, title_to_generation=None):
    """
    一个版本取值所属的"代"。

    整数按千位段归代；字符串（水鱼那份是版本标题）先经落雪版本表换算，换算不出就自成一代
    —— 宁可多列一项让人自己挑，也不能把两代错并成一代，那会静默多选曲目。
    """
    number = _num(value)
    if number is not None:
        return int(number // VERSION_GENERATION)
    text = str(value).strip()
    if title_to_generation:
        found = title_to_generation.get(text.lower())
        if found is not None:
            return found
    return text


def group_versions(values, title_to_generation=None):
    """{代: [该代的原始取值…]}，代内按 version_sort_key 排。"""
    groups = {}
    for value in values:
        groups.setdefault(version_generation(value, title_to_generation), []).append(value)
    return {gen: sorted(members, key=version_sort_key) for gen, members in groups.items()}


def describe_spec(spec):
    """把生效条件写成一行中文，供报错与预览回显。"""
    spec = spec or {}
    parts = []
    for key in FILTER_ORDER:
        if not spec_is_active(spec, key):
            continue
        label = FIELD_LABELS.get(key, key)
        value = spec[key]
        if key in RANGE_FIELDS:
            lo, hi = _range_bounds(value)
            if lo is None:
                shown = f"≤{hi}"
            elif hi is None:
                shown = f"≥{lo}"
            else:
                shown = f"{lo}~{hi}"
            parts.append(f"{label} {shown}")
        else:
            values = _as_list(value)
            shown = "、".join(str(v) for v in values[:4]) + ("…" if len(values) > 4 else "")
            parts.append(f"{label} {shown}")
    return " · ".join(parts) if parts else "无条件（全量）"
