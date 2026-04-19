import numpy as np
import os, traceback
import streamlit as st
from PIL.Image import Resampling
from PIL import Image, ImageDraw, ImageFont
from utils.PageUtils import calculate_rating
from utils.PathUtils import load_config, save_config
from utils.TextRenderer import render_text_to_image
from utils.Variables import image_root_path, ui_font_path, title_font_path, level_font_path, combo_img_path, font_path, REVERSE_LEVEL_LABELS

def get_splited_text(text, text_max_bytes=70):
    """
    将说明文本按照最大字节数限制切割成多行
    
    Args:
        text (str): 输入文本
        text_max_bytes (int): 每行最大字节数限制（utf-8编码）
        
    Returns:
        str: 按规则切割并用换行符连接的文本
    """
    lines = []
    current_line = ""
    
    # 按现有换行符先分割
    for line in text.split('\n'):
        current_length = 0
        current_line = ""
        
        for char in line:
            # 计算字符长度：中日文为2，其他为1
            if '\u4e00' <= char <= '\u9fff' or '\u3040' <= char <= '\u30ff':
                char_length = 2
            else:
                char_length = 1
            
            # 如果添加这个字符会超出限制，保存当前行并重新开始
            if current_length + char_length > text_max_bytes:
                lines.append(current_line)
                current_line = char
                current_length = char_length
            else:
                current_line += char
                current_length += char_length
        
        # 处理剩余的字符
        if current_line:
            lines.append(current_line)
    
    return lines

def create_blank_image(width, height, color=(0, 0, 0, 0)):
    """
    创建一张透明图
    """
    # 创建一个RGBA模式的空白图片
    # image = Image.new('RGBA', (width, height), color)
    # 创建一个RGBA模式的空白图片，转换为numpy数组并返回（moviepy 需要这种格式）
    return np.array(Image.new('RGBA', (width, height), color))
    # return np.array(image)

def FrameLoader(level_index: int = 0):
    with Image.open(f"{image_root_path}/Frames/{level_index}.png") as _frame:
        return _frame.copy()

def LevelLoader(level: float, level_next: float = 0.0):
    # print(f"DEBUG: level={level}, type={type(level)}")
    # print(f"DEBUG: level_next={level_next}, type={type(level_next)}")
    lv = level if level > 1.0 else level_next
    __lv = str(lv)
    if '.' in __lv:
        level, decimai = __lv.split('.')
    else:
        level, decimai = __lv, '0'
    level_number_img = Image.new('RGBA', (108, 88), (0, 0, 0, 0))
    
    # 绘制数字
    level_number_img = TextDraw(level_number_img, level, (54, 46), 
                                font_path=level_font_path,
                                font_size=60, font_color=(255, 255, 255))

    if int(decimai) >= 5:
        # 绘制加号
        level_number_img = TextDraw(level_number_img, '+', (92, 8),
                                    font_path=level_font_path,
                                    font_size=42, font_color=(255, 255, 255))

    return level_number_img

def ScoreLoader(score: int = 0):
    if score < 0 or score > 1010000:
        raise ValueError("分数无效")
 
    score_str_formatted = f"{score:,}"
    score_number_img = Image.new('RGBA', (420, 100), (0, 0, 0, 0))
    
    # 计算总宽度实现右对齐
    total_width = 0
    digit_size = (50, 80)
    comma_size = (50, 72)
    for char in score_str_formatted:
        if char == ',':
            total_width += comma_size[0] // 2
        else:
            total_width += digit_size[0]

    # 从右侧开始绘制
    current_x = 420 - total_width
    for char in score_str_formatted:
        if char == ',':
            image_path = f"{image_root_path}/Numbers/AchievementNumber/comma.png"
            char_width = comma_size[0] // 2
        else:
            image_path = f"{image_root_path}/Numbers/AchievementNumber/{char}.png"
            char_width = digit_size[0]

        try:
            with Image.open(image_path) as char_img:
                # 确保图像是 RGBA 模式
                if char_img.mode != 'RGBA':
                    char_img = char_img.convert('RGBA')
                
                # 将图片缩放到指定大小
                if char == ',':
                    char_img = char_img.resize(comma_size, Resampling.LANCZOS)
                else:
                    char_img = char_img.resize(digit_size, Resampling.LANCZOS)
                
                char_y = 28 if char == ',' else 4
                # 正确使用 paste：第三个参数是蒙版（alpha通道）
                score_number_img.paste(char_img, (current_x, char_y), char_img)
                current_x += char_width
        except Exception as e:
            print(f"加载字符 '{char}' 失败: {e}")
            continue
            
    return score_number_img

def RatingLoader(rating: float):
    if rating < 0:
        raise ValueError("Rating 无效")
    
    # 按数值选择图像样式
    if rating >= 17:
        digit_style = "ex_rainbow"
    elif rating >= 16:
        digit_style = "rainbow"
    else:
        digit_style = "gold"
    
    ra_number_formatted = f"{rating:.2f}"
    ra_number_img = Image.new('RGBA', (160, 50), (0, 0, 0, 0))
    
    # 计算总宽度实现居中对齐
    total_width = 0
    digit_size = (35, 48)
    dot_size = (33, 45)

    for char in ra_number_formatted:
        if char == '.':
            total_width += dot_size[0] // 2
        else:
            total_width += digit_size[0]
    
    current_x = (160 - total_width) // 2
    for char in ra_number_formatted:
        if char == '.':
            image_path = f"{image_root_path}/Numbers/RatingNumber/{digit_style}/dot.png"
            char_width = dot_size[0] // 2
            char_y = 8
        else:   
            image_path = f"{image_root_path}/Numbers/RatingNumber/{digit_style}/{char}.png"
            char_width = digit_size[0]
            char_y = 0
        
        try:
            with Image.open(image_path) as char_img:
                # 确保图像是 RGBA 模式
                if char_img.mode != 'RGBA':
                    char_img = char_img.convert('RGBA')
                
                if char == '.':
                    char_img = char_img.resize(dot_size, Resampling.LANCZOS)
                else:
                    char_img = char_img.resize(digit_size, Resampling.LANCZOS)
                
                # 正确使用 paste
                ra_number_img.paste(char_img, (current_x, char_y), char_img)
                current_x += char_width
        except Exception as e:
            print(f"加载字符 '{char}' 失败: {e}")
            continue

    return ra_number_img  # 修正：在循环结束后返回
        
def ComboStatusLoader(combo_status: str = "", score: int = 0):
    match combo_status:
        case _ if combo_status == '' or combo_status is None:
            return Image.new('RGBA', (80, 80), (0, 0, 0, 0))
        case _ if combo_status == 'alljustice' and score == 1010000:
            with Image.open(f"{combo_img_path}/13.png") as _comboStatus:
                return _comboStatus.copy()
        case _ if combo_status == 'alljustice':
            with Image.open(f"{combo_img_path}/12.png") as _comboStatus:
                return _comboStatus.copy()
        case _ if combo_status == 'fullcombo' :
            with Image.open(f"{combo_img_path}/11.png") as _comboStatus:
                return _comboStatus.copy()


def ChainStatusLoader(chain_status: str = ""):
    match chain_status:
        case _ if chain_status == '' or chain_status is None:
            return Image.new('RGBA', (80, 80), (0, 0, 0, 0))
        case _ if chain_status == 'fullchain2':
            with Image.open(f"{combo_img_path}/22.png") as _chainStatus:
                return _chainStatus.copy()
        case _ if chain_status == 'fullchain':
            with Image.open(f"{combo_img_path}/21.png") as _chainStatus:
                return _chainStatus.copy()


def TextDraw(image, text: str = "", pos: tuple = (0, 0), offset: tuple = (0, 0), max_width: int = 2000,
                 font_path=None, font_size=32, font_color=(255, 255, 255), h_align: str = "center"):
        """
        绘制文本，若超出最大宽度则缩小字体直至适配

        Args:
            image (PIL.Image): 目标图像
            text (str): 要绘制的文本
            pos (tuple): 基准位置 (x, y)。水平含义由 h_align 决定:
                         h_align = 'left'  -> pos 作为文本左边界
                         h_align = 'center'-> pos 作为文本水平中心
                         h_align = 'right' -> pos 作为文本右边界
                         垂直方向始终居中
            offset (tuple): 相对于基准位置的偏移量 (x_offset, y_offset)
            max_width (int): 最大允许宽度
            font_path (str): 字体文件路径
            font_size (int): 初始字体大小
            font_color (tuple): 字体颜色 (R, G, B)
            h_align (str): 水平对齐方式: 'left' | 'center' | 'right'
        """

        # 转换 font_color 为元组
        if isinstance(font_color, list):
            font_color = tuple(font_color)

        # 载入文字元素
        Draw = ImageDraw.Draw(image)
        if not font_path:
            font_path = ui_font_path

        # 校验对齐
        if h_align not in ("left", "center", "right"):
            raise ValueError(f"h_align 必须为 'left' | 'center' | 'right', 当前: {h_align}")

        # 动态调整字体大小以适配最大宽度
        Font = ImageFont.truetype(font_path, font_size)
        Bbox = Draw.textbbox((0, 0), text, font=Font)
        text_width = Bbox[2] - Bbox[0]

        while text_width > max_width and font_size > 10:
            font_size -= 1
            Font = ImageFont.truetype(font_path, font_size)
            Bbox = Draw.textbbox((0, 0), text, font=Font)
            text_width = Bbox[2] - Bbox[0]
        text_height = Bbox[3] - Bbox[1]
        # 计算水平起点
        if h_align == "left":
            x = pos[0] + offset[0]
        elif h_align == "center":
            x = pos[0] - text_width // 2 + offset[0]
        else:  # right
            x = pos[0] - text_width + offset[0]
        # 垂直始终居中
        y = pos[1] - text_height // 2 + offset[1]
        text_pos = (x, y)
        Draw.text(text_pos, text, fill=font_color, font=Font)
        return image

# def generate_single_image(record_detail: dict, style_config: dict, output_path, prefix, index: int):
def generate_single_image(record_detail: dict, style_config: dict, output_path):
    """
    生成单个 Best50 成绩记录图。

    Args:
        record_detail (dict): 成绩记录详情，包含以下字段：
            - song_name (str): 乐曲标题
            - level_index (int): 难度索引
            - score (int): 分数
            - rating (float): Rating值
            - full_combo (str): Combo 类型，可选：空、'fullcombo'、'alljustice'
            - full_chain (str): Chain 类型，可选：空、'fullchain'、'fullchain2'
            - play_count (int): 游玩次数，可选：空、（整数）游玩次数
            - clip_id (str): 标识符
            - level (float): 当前定数
            - level_next (float): 下版本定数
        style_config (dict): 元素坐标，用于读取 customization.json 文件
        output_path (str): 输出目录
        prefix (str): 文件名前缀(deprecated)
        index (int): 索引编号(deprecated)

    Returns:
        file: Best50 图像
    """
    background = None
    template = style_config['themes']
    position = style_config['position']['image']
    size = style_config['size']
    color = style_config['color']
    max_width = style_config['maxWidth'] if 'maxWidth' in style_config else None
    align = style_config['align']
    # 只允许一个下划线分隔符（对应 Best_xx 格式）
    prefix, index = record_detail['clip_id'].split('_', 1)
    try:
        if template == ('default' or 'custom_default'):
            assert record_detail['level_index'] in range(0, 5)
            image_base_path = os.path.join(f"{image_root_path}/Base/content", "content_base.png")
            with Image.open(image_base_path) as background:
                background = background.convert("RGBA")
                assert background.size == (1920, 1080)
                
                # 载入元素
                temp_img = Image.new('RGBA', background.size, (0, 0, 0, 0))
                
                # 边框
                # frame_pos = (65, 32)
                frame_pos = position['frame']
                frame = FrameLoader(record_detail['level_index'])
                # 确保frame是RGBA模式
                if frame.mode != 'RGBA':
                    frame = frame.convert('RGBA')
                temp_img.paste(frame, frame_pos, frame)
                
                # 等级
                # level_pos = (100, 884) # x 坐标 + 4（发现已偏移 4px）
                level_pos = position['level']['integer']
                level = LevelLoader(record_detail['level'], record_detail['level_next'])
                if level.mode != 'RGBA':
                    level = level.convert('RGBA')
                temp_img.paste(level, level_pos, level)
                
                # 定数
                # cur_pos = (1562, 1018)
                # next_pos = (1756, 1018)
                cur_pos = position['level']['current']
                next_pos = position['level']['next']
                cur_color = color['level']['current']
                next_color = color['level']['next']
                cur_next_size = size['level']
                cur_next_align = align['level']
                
                # 成绩数据
                cur_level = record_detail['level']
                next_level = record_detail['level_next']
                cur_text = str(cur_level)
                if cur_level <= 0.0:
                    cur_text = "--"
                temp_img = TextDraw(temp_img, cur_text, cur_pos,
                                    font_path=title_font_path,
                                    font_size=cur_next_size, font_color=cur_color, h_align=cur_next_align)
                
                if cur_level <= 0:
                    next_text = str(next_level)
                elif next_level > cur_level:
                    next_text = str(next_level) + "↑" 
                elif next_level < cur_level:
                    next_text = str(next_level) + "↓"
                else:
                    next_text = str(next_level) + "→"
                temp_img = TextDraw(temp_img, next_text, next_pos,
                                    font_path=title_font_path,
                                    font_size=cur_next_size, font_color=next_color, h_align=cur_next_align)
                
                # 分数
                # score_pos = (706, 958)
                score_pos = position['score']
                score = ScoreLoader(record_detail["score"])
                if score.mode != 'RGBA':
                    score = score.convert('RGBA')
                temp_img.paste(score, score_pos, score)

                # Rating
                # rating_pos = (1216, 980)
                rating_pos = position['rating']
                rating = RatingLoader(record_detail["rating"])
                if rating.mode != 'RGBA':
                    rating = rating.convert('RGBA')
                temp_img.paste(rating, rating_pos, rating)

                # Combo
                # combo_pos = (424, 971)
                combo_pos = position['combo']
                combo_status = ComboStatusLoader(record_detail['full_combo'], record_detail['score']).resize([243, 40], Resampling.LANCZOS)
                if combo_status.mode != 'RGBA':
                    combo_status = combo_status.convert('RGBA')
                temp_img.paste(combo_status, combo_pos, combo_status)

                # Chain
                # chain_pos = (423, 1015)
                chain_pos = position['chain']
                chain_status = ChainStatusLoader(record_detail['full_chain']).resize([243, 40], Resampling.LANCZOS)
                if chain_status.mode != 'RGBA':
                    chain_status = chain_status.convert('RGBA')
                temp_img.paste(chain_status, chain_pos, chain_status)

                # 标题
                # title_pos = (234, 876)
                title_pos = position['title']
                title_color = color['title']
                title_size = size['title']
                title_align = align['title']
                title_width = max_width['title']
                temp_img = TextDraw(temp_img, record_detail['song_name'], title_pos, max_width=title_width,
                                    font_path=title_font_path, font_size=title_size,
                                    font_color=title_color, h_align=title_align)
                
                # 曲师
                # artist_pos = (234, 936)
                artist_pos = position['artist']
                artist_color = color['artist']
                artist_size = size['artist']
                artist_align = align['artist']
                artist_width = max_width['artist']
                temp_img = TextDraw(temp_img, record_detail['artist'], artist_pos, max_width=artist_width,
                                    font_path=title_font_path, font_size=artist_size,
                                    font_color=artist_color, h_align=artist_align)
                
                # Best 序号
                # best_pos = (245, 1017)
                best_pos = position['bestNum']
                best_color = color['bestNum']
                best_size = size['bestNum']
                best_align = align['bestNum']
                best_width = max_width['bestNum']
                temp_img = TextDraw(temp_img, f"{prefix} #{index}", best_pos, max_width=best_width,
                                    font_path=title_font_path, font_size=best_size,
                                    font_color=best_color, h_align=best_align)
                
                # 游玩次数
                if record_detail['play_count'] is not None:
                    PlayCount = int(record_detail['play_count'])
                else:
                    PlayCount = 0
                # 只有当游玩次数≥1时才显示
                if PlayCount >= 1:
                    # 载入游玩次数背景图标
                    play_count_base_path = os.path.join(os.getcwd(), f"{image_root_path}/Playcount/PlayCountBase.png")
                    with Image.open(play_count_base_path) as play_count_base:
                        # play_count_base_pos = (1170, 840)
                        play_count_base_pos = position['playCount']['base']
                        if play_count_base.mode != 'RGBA':
                            play_count_base = play_count_base.convert('RGBA')
                        temp_img.paste(play_count_base, play_count_base_pos, play_count_base)
                    
                    # 绘制游玩次数文字
                    # text_central_pos = (1359, 865)
                    text_central_pos = position['playCount']['text']
                    
                    play_count_text = str(PlayCount)
                    play_count_color = color['playCount']
                    play_count_size = size['playCount']
                    play_count_align = align['playCount']
                    temp_img = TextDraw(temp_img, play_count_text, text_central_pos,
                                    font_path=title_font_path, font_size=play_count_size,
                                    font_color=play_count_color, h_align=play_count_align)
                
                # 将temp_img合成到background上
                background = Image.alpha_composite(background, temp_img)
        
        elif template == ('init' or 'custom_init'):
            CORNER_IMG_PATH = f"{image_root_path}/CornerMark.png"

            # （此函数只能调用微软字体库中的字体）
            def load_fonts(base_font: str, size: dict):
                config = {
                    'title': ('bd', size['title']), 'number': ('', size['number']), 'song_name': ('l', size['score']),
                    'level': ('l', size['level']), 'score': ('l', size['score']), 'rating': ('l', size['rating'])
                }
                
                fonts = {}
                for key, (suffix, size) in config.items():
                    font_path = f"{base_font}{suffix}.ttc"
                    fonts[key] = {
                        'path': font_path,
                        'size': size,
                        'font': ImageFont.truetype(font_path, size)
                    }
                
                return fonts

            def render_corner_logo(fonts, clip_id: str, color):
                corner = Image.open(CORNER_IMG_PATH).resize((125, 125))
                text_layer = Image.new("RGBA", corner.size, (0, 0, 0, 0))
                
                # 获取中心点坐标
                center_x = corner.width // 2
                center_y = corner.height // 2
                prefix, clip_number = clip_id.split("_", 1)
                
                # 绘制 prefix 文本（原偏移 -3, -52）
                TextDraw(
                    text_layer,
                    prefix.upper(),
                    pos=(center_x - 3, center_y - 52),  # 应用偏移
                    font_path=fonts['title']['path'],  # 需要从ImageFont对象获取路径
                    font_size=fonts['title']['size'],
                    # font_color=(0, 0, 0),
                    font_color=color['title'],
                    h_align="center"
                )
                
                # 绘制 clip_id 文本（原偏移 -1, -6）
                TextDraw(
                    text_layer,
                    clip_number,
                    pos=(center_x - 1, center_y - 6),
                    font_path=fonts['number']['path'],
                    font_size=fonts['number']['size'],
                    # font_color=(255, 255, 255),
                    font_color=color['number'],
                    h_align="center"
                )
                
                return Image.alpha_composite(corner, text_layer)
            
            fonts = load_fonts("msyh", size)
            background_path = os.path.join(f"{image_root_path}/Base/content", f"{record_detail['level_index']}.png")
            with Image.open(background_path) as background:
                background = background.convert('RGBA')
                
                # 角标
                corner = render_corner_logo(fonts, record_detail['clip_id'], color)
                
                # 曲名图层
                name_layer = Image.new("RGBA", (1308, 143))
                name_center_x = name_layer.width // 2
                name_center_y = name_layer.height // 2
                
                TextDraw(
                    name_layer,
                    record_detail['song_name'],
                    pos=(name_center_x, name_center_y - 10),  # y_offset = -10
                    font_path=fonts['song_name']['path'],
                    font_size=fonts['song_name']['size'],
                    # font_color=(0, 0, 0),
                    font_color=color['title'],
                    h_align="center",
                    max_width=1000
                )
                
                # 等级图层
                level_layer = Image.new("RGBA", (1308, 83))
                level_center_x = level_layer.width // 2
                level_center_y = level_layer.height // 2
                
                difficulty_name = REVERSE_LEVEL_LABELS[record_detail['level_index']]
                old_const = record_detail['level']
                new_const = record_detail['level_next']
                
                if new_const > old_const:
                    level_text = f"{difficulty_name}[{old_const} ↑ {new_const}(NEXT)]"
                elif new_const < old_const:
                    level_text = f"{difficulty_name}[{old_const} ↓ {new_const}(NEXT)]"
                else:
                    level_text = f"{difficulty_name}[{old_const}(NEXT)]"
                
                TextDraw(
                    level_layer,
                    level_text,
                    pos=(level_center_x, level_center_y - 20),  # y_offset = -20
                    font_path=fonts['level']['path'],
                    font_size=fonts['level']['size'],
                    # font_color=(0, 0, 0),
                    font_color=color['level'],
                    h_align="center"
                )
                
                # 分数图层
                score_layer = Image.new("RGBA", (437, 143))
                score_center_x = score_layer.width // 2
                score_center_y = score_layer.height // 2
                
                # score_text = f"{record_detail['score']}{dict(fullcombo='(FC)', alljustice='(AJ)').get(record_detail['full_combo'], '')}"
                
                score = record_detail['score']
                full_combo = record_detail['full_combo']

                # 根据条件确定后缀
                if full_combo == 'alljustice':
                    suffix = '(AJC)' if score == 1010000 else '(AJ)'
                elif full_combo == 'fullcombo':
                    suffix = '(FC)'
                else:
                    suffix = ''

                score_text = f"{score}{suffix}"
                
                TextDraw(
                    score_layer,
                    score_text,
                    pos=(score_center_x, score_center_y - 17),  # y_offset = -17
                    font_path=fonts['score']['path'],
                    font_size=fonts['score']['size'],
                    # font_color=(0, 0, 0),
                    font_color=color['score'],
                    h_align="center"
                )
                
                # Rating图层
                rating_layer = Image.new("RGBA", (437, 83))
                rating_center_x = rating_layer.width // 2
                rating_center_y = rating_layer.height // 2
                
                base_rating = record_detail["rating"]
                new_rating = calculate_rating(record_detail['score'], new_const)
                if new_const != old_const:
                    rating_text = f'{base_rating} → {new_rating}(NEXT)'
                else:
                    rating_text = f'{base_rating}(NEXT)'
                
                TextDraw(
                    rating_layer,
                    rating_text,
                    pos=(rating_center_x, rating_center_y - 15),  # y_offset = -15
                    font_path=fonts['rating']['path'],
                    font_size=fonts['rating']['size'],
                    # font_color=(0, 0, 0),
                    font_color=color['rating'],
                    h_align="center"
                )
                
                # 合成图层
                # layers = [
                #     (name_layer, (59, 860)),
                #     (level_layer, (59, 1013)),
                #     (score_layer, (1420, 864)),
                #     (rating_layer, (1420, 1008)),
                #     (corner, (60, 875))
                # ]
                
                layers = [
                    (name_layer, position['title']),
                    (level_layer, position['level']),
                    (score_layer, position['score']),
                    (rating_layer, position['rating']),
                    (corner, position['combined'])
                ]
                
                for layer, position in layers:
                    background.paste(layer, position, layer)
    except Exception as e:
            print(f"在生成图像时出现错误：{e}")
            print(traceback.format_exc())
            background = Image.new('RGBA', background.size, (0, 0, 0, 255))
            error_text = f"生成图像时出现错误：{e}"
            temp_img = TextDraw(temp_img, error_text, (0, 50), max_width=background.size[0],
                                 font_path=title_font_path, font_size=32,
                                 font_color=(255, 255, 255), h_align="left")
            background = Image.alpha_composite(background, temp_img)
    finally:
        background.save(os.path.join(output_path, f"{prefix}_{index}.png"))

def render_all_images(video_config_file, style_config_file_path, save_paths, force_regen=False):
    """
    一键生成所有图片（文字图 + 完整背景图）
    
    Args:
        video_config_file: 视频配置文件路径
        style_config_file_path: 样式配置文件路径
        save_paths: 保存路径配置
        force_regen: 是否强制重新生成已存在的文件
    """
    from PIL import Image
    
    def rgb_to_hex(rgb):
        return '#{:02x}{:02x}{:02x}'.format(*[max(0, min(255, x)) for x in rgb])
    
    def get_render_params(style, layout):
        """提取渲染参数"""
        return {
            'font_path': os.path.join(font_path, style['font']),
            'font_size': style['size'],
            'color': rgb_to_hex(style['color']),
            'stroke_color': rgb_to_hex(style['stroke']['color']) if style['stroke']['enable'] else None,
            'stroke_width': style['stroke']['width'],
            'width': layout['width'],
            'padding': tuple(layout['padding']),
            'line_spacing': layout['lineSpacing'],
            'horizontal_align': layout['AlignConfig']['horizontal'],
            'vertical_align': layout['AlignConfig']['vertical'],
            'auto_height': layout['autoHeight'],
        }
    
    def merge_text_with_background(text_path, bg_path, output_path, position_ratio, bg_size=(1920, 1080)):
        """合并单张文字图与背景图"""
        background = Image.open(bg_path, 'r').convert("RGBA")
        text_img = Image.open(text_path, 'r').convert("RGBA")
        
        text_width, text_height = text_img.size
        bg_width, bg_height = bg_size
        
        x = int(bg_width * position_ratio[0])
        y = int(bg_height * position_ratio[1])
        x = max(0, min(x, bg_width - text_width))
        y = max(0, min(y, bg_height - text_height))
        
        background.paste(text_img, (x, y), text_img)
        background.save(output_path, "PNG")
        return output_path
    
    def update_config_with_image_paths():
        """更新配置文件中的 full_image 路径"""
        try:
            # 重新加载配置（确保获取最新数据）
            config_to_update = load_config(video_config_file)
            style_cfg = load_config(style_config_file_path)
            
            if not config_to_update or not style_cfg:
                st.warning("无法更新配置：配置文件加载失败", icon="⚠️")
                return
            
            theme = style_cfg['themes']
            image_root = save_paths['image_dir']
            intro_bg_path = f"{image_root_path}/Base/intro/{theme}/IntroBase.png".replace("./", "").replace("/", "\\")
            fullbg_dir = os.path.join(image_root, 'fullbg')
            
            # 统计
            total = 0
            filled = 0
            
            # 处理 intro 和 ending
            for seg_type in ['intro', 'ending']:
                for seg in config_to_update.get(seg_type, []):
                    total += 1
                    file_name = f"{seg['id']}.png"
                    bg_page = seg['bg_page']
                    no_overlay = seg['no_overlay']

                    if bg_page:
                        if no_overlay:  # 勾选 = 不需要背景板底图
                            full_image_path = ""  # 留空
                            filled += 1
                        else:  # 不勾选 = 需要背景板底图
                            full_image_path = intro_bg_path if os.path.exists(intro_bg_path) else ""
                            if full_image_path:
                                filled += 1
                    else:
                        # 普通文本页面
                        full_image_path = os.path.join(fullbg_dir, file_name)
                        filled += 1
                    
                    # if bg_page:
                    #     if no_overlay:
                    #         # 背景板页面 + 保留背景板底图
                    #         full_image_path = intro_bg_path if os.path.exists(intro_bg_path) else ""
                    #         if full_image_path:
                    #             filled += 1
                    #     else:
                    #         # 背景板页面且不保留背景板 → 留空
                    #         full_image_path = ""
                    # else:
                    #     # 普通文本页面，使用生成的完整背景图
                    #     full_image_path = os.path.join(fullbg_dir, file_name)
                    #     # if os.path.exists(full_image_path):
                    #     filled += 1
                    #     # else:
                    #         # full_image_path = ""
                    
                    seg['full_image'] = full_image_path
            
            # 处理 main
            for seg in config_to_update.get('main', []):
                total += 1
                file_name = f"{seg['clip_id']}.png"
                full_image_path = os.path.join(fullbg_dir, file_name)
                seg['full_image'] = full_image_path if os.path.exists(full_image_path) else ""
                if seg['full_image']:
                    filled += 1
            
            # 保存配置
            save_config(video_config_file, config_to_update)
            st.toast(f"已更新 {filled}/{total} 个图像路径到配置文件", icon="✅")
            
        except Exception as e:
            st.warning(f"更新配置失败：{str(e)}", icon="⚠️")
    
    try:
        # 加载配置
        style_data = load_config(style_config_file_path)
        video_data = load_config(video_config_file)
        
        if not style_data or not video_data:
            st.error("配置文件加载失败！", icon="❌")
            return [], []
        
        styles = style_data['styleConfig']
        layouts = style_data['layoutConfig']
        theme = style_data['themes']
        video_position = style_data['position']['video']
        intro_position = video_position['intro']
        content_position = video_position['content']
        
        # 创建目录
        image_root = save_paths['image_dir']
        text_dir = os.path.join(image_root, 'text')
        fullbg_dir = os.path.join(image_root, 'fullbg')
        os.makedirs(text_dir, exist_ok=True)
        os.makedirs(fullbg_dir, exist_ok=True)
        
        # 准备背景路径
        intro_bg_path = f"{image_root_path}/Base/intro/{theme}/IntroBase.png"
        content_bg_dir = f"{image_root}/background"
        
        # 渲染配置
        render_configs = [
            (video_data.get('intro', []), 'intro', get_render_params(styles['intro'], layouts['intro'])),
            (video_data.get('ending', []), 'ending', get_render_params(styles['intro'], layouts['intro'])),
            (video_data.get('main', []), 'main', get_render_params(styles['content'], layouts['content']))
        ]
        
        text_files = []
        fullbg_files = []
        skipped_count = 0
        
        # 遍历渲染
        for segments, seg_type, params in render_configs:
            for seg in segments:
                text = seg.get('text', '')
                if not text or not text.strip():
                    continue
                
                file_name = f"{seg['clip_id'] if seg_type == 'main' else seg['id']}.png"
                
                text_path = os.path.join(text_dir, file_name)
                fullbg_path = os.path.join(fullbg_dir, file_name)
                
                # 检查是否需要跳过
                if not force_regen and os.path.exists(text_path) and os.path.exists(fullbg_path):
                    skipped_count += 1
                    text_files.append(text_path)
                    fullbg_files.append(fullbg_path)
                    continue
                
                # 生成文字图
                _, saved_text_path = render_text_to_image(
                    text=text.strip(),
                    output_path=text_path,
                    **params
                )
                text_files.append(saved_text_path)
                
                # 合并背景图
                if seg_type == 'main':
                    bg_path = os.path.join(content_bg_dir, file_name)
                    if os.path.exists(bg_path):
                        merge_text_with_background(
                            saved_text_path,
                            bg_path,
                            fullbg_path,
                            content_position
                        )
                        fullbg_files.append(fullbg_path)
                    else:
                        st.warning(f"背景图不存在，跳过合并: {file_name}", icon="⚠️")
                else:
                    if os.path.exists(intro_bg_path):
                        merge_text_with_background(
                            saved_text_path,
                            intro_bg_path,
                            fullbg_path,
                            intro_position
                        )
                        fullbg_files.append(fullbg_path)
                    else:
                        st.warning(f"Intro 背景图不存在，跳过合并: {file_name}", icon="⚠️")
        
        # 显示结果
        new_count = len(text_files) - skipped_count
        if new_count > 0:
            st.success(f"成功生成 {new_count} 张文字图 + {new_count} 张完整背景图", icon="✅")
        if skipped_count > 0:
            st.info(f"跳过已存在的 {skipped_count} 组图片", icon="⏭️")
        
        # ========== 关键：更新配置文件中的图像路径 ==========
        update_config_with_image_paths()
        
        return text_files, fullbg_files
        
    except Exception as e:
        st.error(f"生成失败：{str(e)}", icon="❌")
        st.error(traceback.format_exc(), icon="❌")
        return [], []