"""CSV 批量导入/导出自定义成绩：读表、列映射、逐行校验与三服定数补全。

只做「表格 <-> 本项目记录」的转换，不碰 Streamlit 与存档文件。界面层负责让用户
确认列映射、预览结果，再用现有的 save_song_data 落盘；导出侧只把记录写成 CSV。

只支持 .csv：Excel 用「另存为 CSV UTF-8（逗号分隔）」导出即可。读取时依次尝试
UTF-8（含 BOM）与 GB18030，导出固定写 UTF-8 BOM，Excel 双击打开不会乱码。
"""
from __future__ import annotations

import csv
import io
import math
import re
import unicodedata
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Final

from utils.PageUtils import (build_song_indexes, calculate_rating, lookup_song_fields,
                             record_levels)
from utils.Variables import LEVEL_LABELS, REVERSE_LEVEL_LABELS

MAX_FILE_BYTES: Final = 10 * 1024 * 1024
MAX_ROWS: Final = 5000
MAX_COLUMNS: Final = 64
# 与 utils.Variables 的 LEVEL_LABELS 保持单一来源，避免两处难度名表漂移
LEVEL_NAMES: Final[list[str]] = [name for name, _ in sorted(LEVEL_LABELS.items(), key=lambda item: item[1])]
CSV_ENCODINGS: Final[tuple[str, ...]] = ("utf-8-sig", "gb18030")
CSV_DELIMITERS: Final[str] = ",;\t"

ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "song_name": ("曲名", "歌曲名称", "歌曲名", "title", "song", "song title"),
    "artist": ("曲师", "作曲家", "作曲", "作者", "artist", "composer"),
    "song_id": ("歌曲ID", "曲目ID", "来源ID", "song id", "id"),
    "level_index": ("难度", "难度等级", "谱面难度", "等级索引", "level index", "level label"),
    "difficulty": ("定数", "谱面定数", "等级", "等级值", "ds", "constant", "level value"),
    "level_cn": ("国服定数", "CN定数", "level cn"),
    "level_jp": ("日服定数", "JP定数", "level jp"),
    "level_int": ("国际服定数", "INT定数", "level int"),
    "score": ("分数", "成绩", "得分", "score", "achievement"),
    "rating": ("Rating", "单曲Rating", "单曲RA", "ra", "chuni rating"),
    "full_combo": ("Combo", "FC", "全连", "全连状态", "full combo"),
    "full_chain": ("Chain", "链条", "链条状态", "full chain", "FS"),
    "play_count": ("游玩次数", "次数", "play count", "playcount"),
}

FIELD_LABELS: Final[dict[str, str]] = {
    "song_name": "曲名",
    "artist": "曲师",
    "song_id": "曲目 ID",
    "level_index": "难度",
    "difficulty": "定数",
    "level_cn": "国服定数",
    "level_jp": "日服定数",
    "level_int": "国际服定数",
    "score": "分数",
    "rating": "Rating",
    "full_combo": "Combo",
    "full_chain": "Chain",
    "play_count": "游玩次数",
}


def normalize(value: object) -> str:
    return re.sub(r"[\s_:\-/（）()]+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


# 0–4 都能导入（底图内容框 0/1 由 2.png 换色生成）；5 是 WORLD'S END，素材与渲染都不支持。
LEVEL_ALIASES: dict[str, int] = {}
for _index, _name in enumerate(LEVEL_NAMES):
    LEVEL_ALIASES[normalize(_name)] = _index
for _index, _names in {
    0: ("绿", "basic", "bas"),
    1: ("黄", "advanced", "adv"),
    2: ("红", "expert", "exp"),
    3: ("紫", "master", "mas"),
    4: ("黑", "ultima", "ult"),
}.items():
    for _name in _names:
        LEVEL_ALIASES[normalize(_name)] = _index

_COMBO_ALIASES: Final[dict[str, str | None]] = {
    "": None, "无": None, "none": None, "0": None,
    "fc": "fullcombo", "fullcombo": "fullcombo", "全连": "fullcombo",
    "aj": "alljustice", "ajc": "alljustice", "alljustice": "alljustice", "理论": "alljustice",
}
_CHAIN_ALIASES: Final[dict[str, str | None]] = {
    "": None, "无": None, "none": None, "0": None,
    "fs": "fullchain", "fullchain": "fullchain", "全链条": "fullchain",
    "fsc": "fullchain2", "fs+": "fullchain2", "fullchain2": "fullchain2", "链+": "fullchain2",
}


@dataclass
class CsvTable:
    """解析后的表格：表头、数据行（行号从 2 开始）、实际编码与分隔符。"""

    headers: list[str]
    rows: list[tuple[int, list[str]]]
    encoding: str
    delimiter: str


def _decode(data: bytes) -> tuple[str, str]:
    for encoding in CSV_ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请另存为 UTF-8 CSV 后重试。")


def _delimiter(text: str) -> str:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        return ","


def read_csv(data: bytes) -> CsvTable:
    """读取 CSV；限制文件体积、行列数与空行，表头取第一行。"""
    if not data:
        raise ValueError("CSV 文件为空。")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"CSV 文件超过 {MAX_FILE_BYTES // (1024 * 1024)} MiB。")
    text, encoding = _decode(data)
    delimiter = _delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    headers: list[str] = []
    rows: list[tuple[int, list[str]]] = []
    for number, cells in enumerate(reader, start=1):
        if number == 1:
            headers = [str(cell or "").strip() for cell in cells]
            if not any(headers):
                raise ValueError("首行需要填写表头。")
            if len(headers) > MAX_COLUMNS:
                raise ValueError(f"首期支持最多 {MAX_COLUMNS} 列。")
            continue
        if len(rows) >= MAX_ROWS:
            raise ValueError(f"首期支持最多 {MAX_ROWS} 条记录。")
        if len(cells) > MAX_COLUMNS:
            raise ValueError(f"首期支持最多 {MAX_COLUMNS} 列。")
        if not any(str(cell).strip() for cell in cells):
            continue
        rows.append((number, cells))
    if not headers:
        raise ValueError("工作表为空。")
    return CsvTable(headers, rows, encoding, delimiter)


def suggest_mapping(headers: Sequence[str]) -> tuple[dict[int, str | None], dict[int, list[str]]]:
    """按表头猜字段；重复/模糊只给候选，最终由用户确认。"""
    names = {
        field: {normalize(field), *(normalize(alias) for alias in aliases)}
        for field, aliases in ALIASES.items()
    }
    mapping: dict[int, str | None] = {}
    suggestions: dict[int, list[str]] = {}
    for index, header in enumerate(headers):
        value = normalize(header)
        exact = [field for field, words in names.items() if value and value in words]
        if value:
            scored = sorted(
                ((max(SequenceMatcher(None, value, word).ratio() for word in words), field)
                 for field, words in names.items()),
                reverse=True,
            )
            fuzzy = [field for score, field in scored[:3] if score >= 0.65]
        else:
            fuzzy = []
        mapping[index] = exact[0] if len(exact) == 1 else None
        suggestions[index] = exact or fuzzy
    counts: dict[str, int] = {}
    for field in mapping.values():
        if field:
            counts[field] = counts.get(field, 0) + 1
    for index, field in list(mapping.items()):
        if field and counts[field] > 1:
            mapping[index] = None
    return mapping, suggestions


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", "").replace("，", "")
        try:
            number = float(text)
        except ValueError:
            return None
    return number if math.isfinite(number) else None


def _score(value: object) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer() or not 0 <= number <= 1_010_000:
        return None
    return int(number)


def _count(value: object) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer() or number < 0:
        return None
    return int(number)


def _difficulty(value: object) -> float | None:
    number = _number(value)
    if number is None or not 0 < number <= 20:
        return None
    return round(number, 1)


def _level_index(value: object) -> int | None:
    number = _number(value)
    if number is not None and number.is_integer() and 0 <= number <= 4:
        return int(number)
    return LEVEL_ALIASES.get(normalize(value))


def _choice(value: object, aliases: Mapping[str, str | None]) -> str | None:
    text = normalize(value)
    return aliases.get(text)


def _next_clip_index(existing_rows: Sequence[Mapping[str, Any]] | None, prefix: str) -> int:
    max_number = 0
    for row in existing_rows or ():
        head, _, tail = str(row.get("clip_id") or "").rpartition("_")
        if head == prefix and tail.isdigit():
            max_number = max(max_number, int(tail))
    return max_number + 1


def convert_rows(table: CsvTable, mapping: Mapping[int, str | None],
                 indexes: Mapping[str, Any], *, prefix: str = "PickUp",
                 existing_rows: Sequence[Mapping[str, Any]] | None = None
                 ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把表格行转成本项目记录；返回 (可导入记录, 逐行预览)。"""
    records: list[dict[str, Any]] = []
    preview: list[dict[str, Any]] = []
    next_number = _next_clip_index(existing_rows, prefix)
    for row_number, cells in table.rows:
        raw: dict[str, object] = {}
        warnings: list[str] = []
        for index, field in mapping.items():
            if field and index < len(cells):
                raw[field] = cells[index]
        errors: list[str] = []

        title = _text(raw.get("song_name"))
        if not title:
            errors.append("缺少曲名")
        level_index = _level_index(raw.get("level_index"))
        if level_index is None or level_index < 0 or level_index > 4:
            errors.append("难度需为 BASIC / ADVANCED / EXPERT / MASTER / ULTIMA（或 0–4）")
        score = _score(raw.get("score"))
        if score is None:
            errors.append("分数需为 0–1010000 的整数")

        difficulty = _difficulty(raw.get("difficulty"))
        given_levels: dict[str, float | None] = {
            "CN": _difficulty(raw.get("level_cn")),
            "JP": _difficulty(raw.get("level_jp")),
            "INT": _difficulty(raw.get("level_int")),
        }
        song_id: int | None = None
        id_value = _number(raw.get("song_id"))
        if id_value is not None and id_value.is_integer() and id_value > 0:
            song_id = int(id_value)

        artist = _text(raw.get("artist")) or None
        levels: dict[str, float | None] = {"CN": None, "JP": None, "INT": None}
        if title and level_index is not None:
            matched_id: int | None = song_id
            if matched_id is None:
                cn_song = indexes["CN_TITLE"].get(title)
                intl_song = indexes["INT"].get(title)
                matched = (cn_song or {}).get("id") or (intl_song or {}).get("id")
                matched_id = int(matched) if matched is not None else None
            found_artist, found_levels = lookup_song_fields(
                matched_id, title, level_index, indexes, cn_by_title=True)
            artist = artist or found_artist
            for server, value in (found_levels or {}).items():
                if server in levels and value is not None:
                    # 日服曲库的 const 是字符串（"15.1"），国服/国际服是数字，这里统一转 float
                    try:
                        levels[server] = float(value)
                    except (TypeError, ValueError):
                        pass
            if not any(found_levels.values()) and difficulty is None and not any(given_levels.values()):
                warnings.append("曲库未匹配，且表内没有定数，无法计算 Rating")
            elif not any(found_levels.values()) and (difficulty is not None or any(given_levels.values())):
                warnings.append("曲库未匹配，按表内曲师 / 定数导入")
        # 表里单独填的「定数」按国服定数理解（用户一般只知道自己所在服的定数），
        # 逐服的「国服/日服/国际服定数」列优先级更高，稍后再覆盖。
        if difficulty is not None:
            levels["CN"] = difficulty
        for server, value in given_levels.items():
            if value is not None:
                levels[server] = value
        constant = difficulty or levels["CN"] or levels["JP"] or levels["INT"]
        if constant is None and not errors:
            errors.append("缺少定数（曲库也查不到）")
        if artist is None:
            warnings.append("缺少曲师（底图会显示空曲师）")
        combo = _choice(raw.get("full_combo"), _COMBO_ALIASES)
        if _text(raw.get("full_combo")) and combo is None:
            warnings.append("Combo 无法识别，已留空")
        chain = _choice(raw.get("full_chain"), _CHAIN_ALIASES)
        if _text(raw.get("full_chain")) and chain is None:
            warnings.append("Chain 无法识别，已留空")
        play_count = _count(raw.get("play_count"))
        if _text(raw.get("play_count")) and play_count is None:
            warnings.append("游玩次数无效，已留空")

        rating = _number(raw.get("rating"))
        if rating is not None and (rating < 0 or rating > 20):
            rating = None
            warnings.append("Rating 超出 0–20，已按分数和定数重算")
        if rating is None and constant is not None and score is not None:
            rating = calculate_rating(score, constant)

        level_label = REVERSE_LEVEL_LABELS.get(level_index, "") if level_index is not None else ""
        if errors:
            preview.append({
                "CSV行": row_number, "曲名": title, "难度": level_label,
                "定数": constant, "分数": score, "Rating": rating,
                "Combo": combo or "", "Chain": chain or "", "曲目ID": song_id,
                "状态": "无法导入", "提示": "；".join(errors),
            })
            continue

        if song_id is None:
            song_id = zlib.crc32(f"{title}|{level_index}".encode("utf-8")) % 9000 + 1000
        record: dict[str, Any] = {
            "id": song_id,
            "song_name": title,
            "artist": artist or "",
            "level": constant,
            "level_cn": levels["CN"],
            "level_jp": levels["JP"],
            "level_int": levels["INT"],
            "level_index": level_index,
            "level_next": levels["JP"] or levels["CN"] or constant,
            "score": score,
            "rating": round(rating, 2) if rating is not None else 0.0,
            "full_combo": combo,
            "full_chain": chain,
            "clip_id": f"{prefix}_{next_number}",
            "play_count": play_count,
        }
        next_number += 1
        records.append(record)
        preview.append({
            "CSV行": row_number, "曲名": title, "难度": level_label,
            "定数": constant, "分数": score, "Rating": record["rating"],
            "Combo": combo or "", "Chain": chain or "", "曲目ID": song_id,
            "状态": "可导入", "提示": "；".join(warnings),
        })
    return records, preview


# 导出沿用导入的表头（含三服定数与曲目 ID），保证导出的文件能原样回导；
# 「剪辑ID」只作参考列，导入时会被忽略（ALIASES 里没有它）。
EXPORT_HEADERS: Final[list[str]] = [
    "曲名", "曲师", "难度", "定数", "国服定数", "日服定数", "国际服定数",
    "分数", "Rating", "Combo", "Chain", "游玩次数", "曲目ID", "剪辑ID",
]

# 空白模板只放「结算页一定看得到」的四列：曲名 / 难度 / 分数 / Rating。
# 定数、游玩次数、曲师、曲目 ID 都由曲库与成绩补全，不写也能导入（写了也能识别）。
TEMPLATE_HEADERS: Final[list[str]] = ["曲名", "难度", "分数", "Rating"]


def _format_level(value: object) -> str:
    number = _number(value)
    return f"{number:.1f}" if number is not None and number > 0 else ""


def _format_int(value: object) -> str:
    number = _number(value)
    return str(int(number)) if number is not None and number.is_integer() else ""


def _render_csv(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def build_template() -> bytes:
    """空白模板：曲名 / 难度 / 分数 / Rating 四列（定数与游玩次数等可自行加列）。"""
    return _render_csv(TEMPLATE_HEADERS, [])


def build_csv(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """把当前存档记录导出成 UTF-8 BOM 的 CSV，表头与导入约定一致，可直接回导。"""
    rendered: list[list[str]] = []
    for row in rows:
        levels = record_levels(dict(row))
        level_index = _number(row.get("level_index"))
        difficulty = _format_level(row.get("level")) or _format_level(levels.get("CN")) \
            or _format_level(levels.get("JP")) or _format_level(levels.get("INT"))
        rendered.append([
            str(row.get("song_name") or ""),
            str(row.get("artist") or ""),
            REVERSE_LEVEL_LABELS.get(int(level_index), "")
            if level_index is not None and level_index.is_integer() else "",
            difficulty,
            _format_level(row.get("level_cn")) or _format_level(levels.get("CN")),
            _format_level(row.get("level_jp")) or _format_level(levels.get("JP")),
            _format_level(row.get("level_int")) or _format_level(levels.get("INT")),
            _format_int(row.get("score")),
            f"{_number(row.get('rating')):.2f}" if _number(row.get("rating")) is not None else "",
            str(row.get("full_combo") or ""),
            str(row.get("full_chain") or ""),
            _format_int(row.get("play_count")),
            _format_int(row.get("id")),
            str(row.get("clip_id") or ""),
        ])
    return _render_csv(EXPORT_HEADERS, rendered)


def build_indexes(song_db: Sequence[Mapping[str, Any]], jp_song_db: Sequence[Mapping[str, Any]],
                  intl_song_db: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return build_song_indexes(song_db, jp_song_db, intl_song_db)
