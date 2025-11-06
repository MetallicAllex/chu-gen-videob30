import json, os
from PIL import Image, ImageDraw, ImageFont
from utils.Utils import TextAnchor, diff_bg_change

VERSE_INFO_PATH = './music_datasets/jp_songs_info.json'
# BASE_FONT_NAME = "msyh"
# CORNER_IMG_PATH = "images/CornerMark.png"

# 加载谱面数据 & 扁平化 (曲名, 难度) -> 定数
with open(VERSE_INFO_PATH, 'r', encoding='utf-8') as f:
    verse_db_raw = json.load(f)

flat_const_map = {
    (item['meta']['title'], diff): item['data'][diff]['const']
    for item in verse_db_raw for diff in item['data']
}

def load_fonts(style_config=None):
    asset_paths = style_config.get("asset_paths", {}) if style_config else {}
    image_root_path = asset_paths.get("score_image_assets_path", "./static/assets/images/Chunithm")
    ui_font_path = asset_paths.get("ui_font", "./static/assets/fonts/SOURCEHANSANSSC-BOLD.OTF")
    title_font_path = "./static/assets/fonts/SweiBellLegCJKsc-Black.ttf"
    level_font_path = "./static/assets/fonts/NimbusSanL-Bol.otf"
    
    config = {
        'ui': (ui_font_path, 32),
        'title': (title_font_path, 32),
        'level': (level_font_path, 36)
    }
    
    return {
        key: ImageFont.truetype(path, size)
        for key, (path, size) in config.items()
    }

def render_corner_logo(fonts, prefix, clip_id):
    corner = Image.open(CORNER_IMG_PATH).resize((125, 125))
    text_layer = Image.new("RGBA", corner.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    anchor = TextAnchor(corner.width // 2, corner.height // 2)

    draw.text(anchor.get_pos(draw, prefix, fonts['title'], -3, -52), prefix, fill=(0, 0, 0), font=fonts['title'])
    draw.text(anchor.get_pos(draw, clip_id.split("_")[1], fonts['number'], -1, -6), clip_id.split("_")[1], fill=(255, 255, 255), font=fonts['number'])

    return Image.alpha_composite(corner, text_layer)

def generate_single_image(background_path, record_detail, output_path, prefix, index, verse_mode=False):
    fonts = load_fonts()
    with Image.open(background_path) as background:
        bg = background.copy()

        # 角标
        combined_logo = render_corner_logo(fonts, prefix, record_detail['clip_id'])

        # 曲名图层
        name_layer = Image.new("RGBA", (1308, 143))
        name_draw = ImageDraw.Draw(name_layer)
        anchor = TextAnchor(name_layer.width // 2, name_layer.height // 2)
        name_draw.text(anchor.get_pos(name_draw, record_detail['song_name'], fonts['song_name'], y_offset=-10), record_detail['song_name'], fill=(0, 0, 0), font=fonts['song_name'])

        # 等级图层
        level_layer = Image.new("RGBA", (1308, 83))
        level_draw = ImageDraw.Draw(level_layer)
        anchor = TextAnchor(level_layer.width // 2, level_layer.height // 2)

        difficulty_name = diff_bg_change(record_detail['level_index'])
        old_const = record_detail['level']
        new_const = flat_const_map.get((record_detail['song_name'], difficulty_name), old_const)

        if verse_mode:
            if new_const == old_const:
                level_text = f"{difficulty_name}[{old_const}(X-VERSE)]"
            else:
                level_text = f"{difficulty_name}[{old_const} → {new_const:.1f}(X-VERSE)]"
        else:
            level_text = f"{difficulty_name} {old_const}"

        level_draw.text(anchor.get_pos(level_draw, level_text, fonts['level'], y_offset=-20), level_text, fill=(0, 0, 0), font=fonts['level'])

        # 分数图层
        score_layer = Image.new("RGBA", (437, 143))
        score_draw = ImageDraw.Draw(score_layer)
        anchor = TextAnchor(score_layer.width // 2, score_layer.height // 2)
        # score_text = str(record_detail['score']) + special_mark(record_detail['full_combo'])
        score_text = f"{record_detail['score']}{dict(fullcombo='(FC)', alljustice='(AJ)').get(record_detail['full_combo'], '')}"
        score_draw.text(anchor.get_pos(score_draw, score_text, fonts['score'], y_offset=-17), score_text, fill=(0, 0, 0), font=fonts['score'])

        # Rating图层
        rating_layer = Image.new("RGBA", (437, 83))
        rating_draw = ImageDraw.Draw(rating_layer)
        anchor = TextAnchor(rating_layer.width // 2, rating_layer.height // 2)
        base_rating = record_detail["rating"]
        new_rating = base_rating + (new_const - old_const)

        if verse_mode:
            rating_text = f'{base_rating:.2f}(verse)' if new_const == old_const else f'{base_rating:.2f} → {new_rating:.2f}(verse)'
        else:
            rating_text = f'{base_rating:.2f}'

        rating_draw.text(anchor.get_pos(rating_draw, rating_text, fonts['rating'], y_offset=-15), rating_text, fill=(0, 0, 0), font=fonts['rating'])

        # 合成图层
        layers = [
            (name_layer, (59, 860)),
            (level_layer, (59, 1013)),
            (score_layer, (1420, 864)),
            (rating_layer, (1420, 1008)),
            (combined_logo, (60, 875))
        ]

        for layer, position in layers:
            bg.paste(layer, position, layer)

        bg.save(os.path.join(output_path, f"{prefix}_{index + 1}.png"))