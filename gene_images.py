import json
import os
from PIL import Image, ImageDraw, ImageFont
from utils.Utils import TextAnchor, diff_bg_change

VERSE_INFO_PATH = './music_datasets/jp_songs_info.json'
BASE_FONT_NAME = "msyh"
CORNER_IMG_PATH = "images/CornerMark.png"

# 加载谱面数据 & 扁平化 (曲名, 难度) -> 定数
with open(VERSE_INFO_PATH, 'r', encoding='utf-8') as f:
    verse_db_raw = json.load(f)

flat_const_map = {
    (item['meta']['title'], diff): item['data'][diff]['const']
    for item in verse_db_raw for diff in item['data']
}

def load_fonts(base_font=BASE_FONT_NAME):
    config = {
        'title': ('bd', 32), 'number': ('', 72), 'song_name': ('l', 60),
        'level': ('l', 36), 'score': ('l', 64), 'rating': ('l', 36)
    }
    return {
        key: ImageFont.truetype(f"{base_font}{suffix}.ttc", size)
        for key, (suffix, size) in config.items()
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
                level_text = f"{difficulty_name}[{old_const}(verse)]"
            else:
                level_text = f"{difficulty_name}[{old_const} → {new_const}(verse)]"
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


# verse_info_path = './music_datasets/jp_songs_info.json'

# # 加速用缓存：曲名 -> 谱面信息
# with open(verse_info_path, 'r', encoding='utf-8') as f:
#     verse_db_raw = json.load(f)
# verse_db = {item['meta']['title']: item for item in verse_db_raw}

# def generate_single_image(background_path, record_detail, output_path, prefix, index):
#     """完整锚点定位方案。

#     Args:
#         background_path(path): 背景图路径
#         record_detail(list): Best 曲目数据
#         output_path(path): 输出路径
#         prefix(str): 前缀（默认 Best）
#         index(int): Best 曲目序号
    
#     Returns:
#         bg (Image): 生成的成绩底图
#     """
#     # 基础字体配置（可扩展）
#     FONT_CONFIG = {
#         'title':       ('bd', 32),
#         'number':      ('',  72),  # 无后缀
#         'song_name':   ('l', 60),
#         'level':       ('l', 36),
#         'score':      ('l', 64),
#         'rating':     ('l', 36)
#     }

#     BASE_FONT_NAME = "msyh"

#     fonts = {
#         key: ImageFont.truetype(
#             f"{BASE_FONT_NAME}{suffix}.ttc",  # 自动拼接后缀
#             size
#         ) for key, (suffix, size) in FONT_CONFIG.items()
#     }

#     with Image.open(background_path) as background:
#         # ========== Best角标处理 ==========
#         best_corner = Image.open("images/CornerMark.png").resize((125, 125))
#         text_corner_layer = Image.new("RGBA", best_corner.size, (0, 0, 0, 0))
#         corner_draw = ImageDraw.Draw(text_corner_layer)
        
#         # 创建角标锚点（中心点）
#         corner_anchor = TextAnchor(best_corner.width // 2, best_corner.height // 2)
        
#         # 绘制"Best"文字
#         title_pos = corner_anchor.get_pos(corner_draw, "Best", fonts['title'], -3, -52)
#         corner_draw.text(title_pos, "Best", fill=(0, 0, 0), font=fonts['title'])
        
#         # 绘制数字
#         num_text = record_detail["clip_id"].split("_")[1]
#         num_pos = corner_anchor.get_pos(corner_draw, num_text, fonts['number'], -1, -6)
#         corner_draw.text(num_pos, num_text, fill=(255, 255, 255), font=fonts['number'])
        
#         # 合并角标图层
#         combined_logo = Image.alpha_composite(best_corner, text_corner_layer)

#         # ========== 曲名图层 ==========
#         name_layer = Image.new("RGBA", (1308, 143))
#         name_draw = ImageDraw.Draw(name_layer)
#         name_anchor = TextAnchor(name_layer.width // 2, name_layer.height // 2)
        
#         song_name_pos = name_anchor.get_pos(
#             name_draw, 
#             record_detail["song_name"], 
#             fonts['song_name'],
#             y_offset=-10
#         )
#         name_draw.text(song_name_pos, record_detail["song_name"], fill=(0, 0, 0), font=fonts['song_name'])

#         # ========== 等级图层 ==========
#         level_layer = Image.new("RGBA", (1308, 83))
#         level_draw = ImageDraw.Draw(level_layer)
#         level_anchor = TextAnchor(level_layer.width // 2, level_layer.height // 2)
        
#         level_text = f"{diff_bg_change(record_detail['level_index'])} {record_detail['level']}"
#         level_pos = level_anchor.get_pos(
#             level_draw,
#             level_text,
#             fonts['level'],
#             y_offset=-20
#         )
#         level_draw.text(level_pos, level_text, fill=(0, 0, 0), font=fonts['level'])

#         # ========== 分数图层 ==========
#         score_layer = Image.new("RGBA", (437, 143))
#         score_draw = ImageDraw.Draw(score_layer)
#         score_anchor = TextAnchor(score_layer.width // 2, score_layer.height // 2)
        
#         score_text = str(record_detail['score']) + special_mark(record_detail['full_combo'])
#         score_pos = score_anchor.get_pos(
#             score_draw,
#             score_text,
#             fonts['score'],
#             y_offset=-17
#         )
#         score_draw.text(score_pos, score_text, fill=(0, 0, 0), font=fonts['score'])

#         # ========== Rating图层 ==========
#         rating_layer = Image.new("RGBA", (437, 83))
#         rating_draw = ImageDraw.Draw(rating_layer)
#         rating_anchor = TextAnchor(rating_layer.width // 2, rating_layer.height // 2)
        
#         rating_text = f'{record_detail["rating"]:.2f}'
#         rating_pos = rating_anchor.get_pos(
#             rating_draw,
#             rating_text,
#             fonts['rating'],
#             y_offset=-15
#         )
#         rating_draw.text(rating_pos, rating_text, fill=(0, 0, 0), font=fonts['rating'])

#         # ========== 最终合成 ==========
#         bg = background.copy()
#         layers = [
#             (name_layer, (59, 860)),    # 曲名位置
#             (level_layer, (59, 1013)),  # 等级位置
#             (score_layer, (1420, 864)), # 分数位置
#             (rating_layer, (1420, 1008)),# Rating位置
#             (combined_logo, (60, 875))  # 角标位置
#         ]
        
#         for layer, position in layers:
#             bg.paste(layer, position, layer)
        
#         # 保存结果
#         bg.save(os.path.join(output_path, f"{prefix}_{index + 1}.png"))

# def generate_single_image_verse(background_path, record_detail, output_path, prefix, index):
#     """完整锚点定位方案。

#     Args:
#         background_path(path): 背景图路径
#         record_detail(list): Best 曲目数据
#         output_path(path): 输出路径
#         prefix(str): 前缀（默认 Best）
#         index(int): Best 曲目序号
    
#     Returns:
#         bg (Image): 生成的成绩底图
#     """
#     # 基础字体配置（可扩展）
#     FONT_CONFIG = {
#         'title':       ('bd', 32),
#         'number':      ('',  72),  # 无后缀
#         'song_name':   ('l', 60),
#         'level':       ('l', 36),
#         'score':      ('l', 64),
#         'rating':     ('l', 36)
#     }

#     BASE_FONT_NAME = "msyh"

#     fonts = {
#         key: ImageFont.truetype(
#             f"{BASE_FONT_NAME}{suffix}.ttc",  # 自动拼接后缀
#             size
#         ) for key, (suffix, size) in FONT_CONFIG.items()
#     }

#     with Image.open(background_path) as background:
#         # ========== Best角标处理 ==========
#         best_corner = Image.open("images/CornerMark.png").resize((125, 125))
#         text_corner_layer = Image.new("RGBA", best_corner.size, (0, 0, 0, 0))
#         corner_draw = ImageDraw.Draw(text_corner_layer)
        
#         # 创建角标锚点（中心点）
#         corner_anchor = TextAnchor(best_corner.width // 2, best_corner.height // 2)
        
#         # 绘制"Best"文字
#         title_pos = corner_anchor.get_pos(corner_draw, "Best", fonts['title'], -3, -52)
#         corner_draw.text(title_pos, "Best", fill=(0, 0, 0), font=fonts['title'])
        
#         # 绘制数字
#         num_text = record_detail["clip_id"].split("_")[1]
#         num_pos = corner_anchor.get_pos(corner_draw, num_text, fonts['number'], -1, -6)
#         corner_draw.text(num_pos, num_text, fill=(255, 255, 255), font=fonts['number'])
        
#         # 合并角标图层
#         combined_logo = Image.alpha_composite(best_corner, text_corner_layer)

#         # ========== 曲名图层 ==========
#         name_layer = Image.new("RGBA", (1308, 143))
#         name_draw = ImageDraw.Draw(name_layer)
#         name_anchor = TextAnchor(name_layer.width // 2, name_layer.height // 2)
        
#         song_name_pos = name_anchor.get_pos(
#             name_draw, 
#             record_detail["song_name"], 
#             fonts['song_name'],
#             y_offset=-10
#         )
#         name_draw.text(song_name_pos, record_detail["song_name"], fill=(0, 0, 0), font=fonts['song_name'])

#         # ========== 等级图层 ==========
#         level_layer = Image.new("RGBA", (1308, 83))
#         level_draw = ImageDraw.Draw(level_layer)
#         level_anchor = TextAnchor(level_layer.width // 2, level_layer.height // 2)

#         # 将 level_index 转为难度名
#         difficulty_name = diff_bg_change(record_detail['level_index'])  # e.g. "MASTER"

#         # 寻找匹配的谱面信息
#         matched_chart = verse_db.get(record_detail['song_name'])

#         if matched_chart:
#             new_const = matched_chart['data'][difficulty_name]['const']
#             old_const = record_detail['level']
#             if new_const == old_const:
#                 level_text = f"{difficulty_name}[{old_const}(verse)]"
#             else:
#                 level_text = f"{difficulty_name}[{old_const} → {new_const}(verse)]"
#         else:
#             # 如果没匹配到曲目不处理
#             level_text = f"{difficulty_name} {record_detail['level']}"

#         level_pos = level_anchor.get_pos(
#             level_draw,
#             level_text,
#             fonts['level'],
#             y_offset=-20
#         )
#         level_draw.text(level_pos, level_text, fill=(0, 0, 0), font=fonts['level'])

#         # ========== 分数图层 ==========
#         score_layer = Image.new("RGBA", (437, 143))
#         score_draw = ImageDraw.Draw(score_layer)
#         score_anchor = TextAnchor(score_layer.width // 2, score_layer.height // 2)
        
#         score_text = str(record_detail['score']) + special_mark(record_detail['full_combo'])
#         score_pos = score_anchor.get_pos(
#             score_draw,
#             score_text,
#             fonts['score'],
#             y_offset=-17
#         )
#         score_draw.text(score_pos, score_text, fill=(0, 0, 0), font=fonts['score'])

#         # ========== Rating图层 ==========
#         rating_layer = Image.new("RGBA", (437, 83))
#         rating_draw = ImageDraw.Draw(rating_layer)
#         rating_anchor = TextAnchor(rating_layer.width // 2, rating_layer.height // 2)
        
#         new_rating = record_detail["rating"] + (new_const - old_const)

#         if record_detail["rating"] == new_rating:
#             rating_text = f'{record_detail["rating"]:.2f}(verse)'
#         else:
#             rating_text = f'{record_detail["rating"]:.2f} → {new_rating:.2f}(verse)'
#         rating_pos = rating_anchor.get_pos(
#             rating_draw,
#             rating_text,
#             fonts['rating'],
#             y_offset=-15
#         )
#         rating_draw.text(rating_pos, rating_text, fill=(0, 0, 0), font=fonts['rating'])

#         # ========== 最终合成 ==========
#         bg = background.copy()
#         layers = [
#             (name_layer, (59, 860)),    # 曲名位置
#             (level_layer, (59, 1013)),  # 等级位置
#             (score_layer, (1420, 864)), # 分数位置
#             (rating_layer, (1420, 1008)),# Rating位置
#             (combined_logo, (60, 875))  # 角标位置
#         ]
        
#         for layer, position in layers:
#             bg.paste(layer, position, layer)
        
#         # 保存结果
#         bg.save(os.path.join(output_path, f"{prefix}_{index + 1}.png"))



def generate_b30_images(UserID, b35_data, output_dir):
    print("生成B30图片中...")
    os.makedirs(output_dir, exist_ok=True)
    # 生成最佳图片
    # gene_images_batch(b35_data, UserID, "Best")

    print(f"已生成 {UserID} 的 B30 图片，请在 b30_images/{UserID} 文件夹中查看。")

