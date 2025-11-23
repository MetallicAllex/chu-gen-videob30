import os, traceback
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PIL.Image import Resampling
from utils.Variables import image_root_path, ui_font_path, title_font_path, level_font_path
# def blur_image(image_path, blur_radius=5):
#     """
#     对图片进行高斯模糊处理
    
#     Args:
#         image_path (str): 图片路径
#         blur_radius (int): 模糊半径，默认为10
        
#     Returns:
#         numpy.ndarray: 模糊处理后的图片数组
#     """
#     try:
#         pil_image = Image.open(image_path)
#         blurred_image = pil_image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
#         # 将模糊后的图片转换为 numpy 数组
#         return np.array(blurred_image)
#     except Exception as e:
#         print(f"Warning: 图片模糊处理失败 - {str(e)}")
#         return np.array(Image.open(image_path))

def create_blank_image(width, height, color=(0, 0, 0, 0)):
    """
    创建一个透明的图片
    """
    # 创建一个RGBA模式的空白图片
    image = Image.new('RGBA', (width, height), color)
    # 转换为numpy数组，moviepy需要这种格式
    return np.array(image)

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

    if int(decimai) >= 6:
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
            with Image.open(f"{image_root_path}/ComboStatus/13.png") as _comboStatus:
                return _comboStatus.copy()
        case _ if combo_status == 'alljustice':
            with Image.open(f"{image_root_path}/ComboStatus/12.png") as _comboStatus:
                return _comboStatus.copy()
        case _ if combo_status == 'fullcombo' :
            with Image.open(f"{image_root_path}/ComboStatus/11.png") as _comboStatus:
                return _comboStatus.copy()


def ChainStatusLoader(chain_status: str = ""):
    match chain_status:
        case _ if chain_status == '' or chain_status is None:
            return Image.new('RGBA', (80, 80), (0, 0, 0, 0))
        case _ if chain_status == 'fullchain2':
            with Image.open(f"{image_root_path}/ComboStatus/22.png") as _chainStatus:
                return _chainStatus.copy()
        case _ if chain_status == 'fullchain':
            with Image.open(f"{image_root_path}/ComboStatus/21.png") as _chainStatus:
                return _chainStatus.copy()


def TextDraw(image, text: str = "", pos: tuple = (0, 0), max_width: int = 2000,
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
            max_width (int): 最大允许宽度
            font_path (str): 字体文件路径
            font_size (int): 初始字体大小
            font_color (tuple): 字体颜色 (R, G, B)
            h_align (str): 水平对齐方式: 'left' | 'center' | 'right'
        """

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
            x = pos[0]
        elif h_align == "center":
            x = pos[0] - text_width // 2
        else:  # right
            x = pos[0] - text_width
        # 垂直始终居中
        y = pos[1] - text_height // 2
        text_pos = (x, y)
        Draw.text(text_pos, text, fill=font_color, font=Font)
        return image

def generate_single_image(record_detail: dict, output_path, prefix, index):
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
        output_path (str): 输出目录
        prefix (str): 文件名前缀
        index (int): 索引编号
        verse_mode (bool): 是否显示定数变化模式

    Returns:
        None
    """
    background = None
    try:
        assert record_detail['level_index'] in range(0, 5)
        image_base_path = os.path.join(os.getcwd(), f"{image_root_path}/content_base_chunithm_verse.png")
        with Image.open(image_base_path) as background:
            background = background.convert("RGBA")
            assert background.size == (1920, 1080)
            
            # 载入元素
            temp_img = Image.new('RGBA', background.size, (0, 0, 0, 0))
            
            # 边框
            frame = FrameLoader(record_detail['level_index'])
            # 确保frame是RGBA模式
            if frame.mode != 'RGBA':
                frame = frame.convert('RGBA')
            temp_img.paste(frame, (65, 32), frame)
            
            # 等级
            level = LevelLoader(record_detail['level'], record_detail['level_next'])
            if level.mode != 'RGBA':
                level = level.convert('RGBA')
            temp_img.paste(level, (98, 884), level)
            
            # 定数
            cur_pos = (1562, 1018)
            next_pos = (1756, 1018)
            cur_level = record_detail['level']
            next_level = record_detail['level_next']
            cur_text = str(cur_level)
            if cur_level <= 0.0:
                cur_text = "--"
            temp_img = TextDraw(temp_img, cur_text, cur_pos,
                                 font_path=title_font_path,
                                 font_size=45, font_color=(77, 77, 77), h_align="center")
            
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
                                 font_size=45, font_color=(77, 77, 77), h_align="center")
            
            # 分数
            score_pos = (706, 958)
            score = ScoreLoader(record_detail["score"])
            if score.mode != 'RGBA':
                score = score.convert('RGBA')
            temp_img.paste(score, score_pos, score)

            # Rating
            rating_pos = (1216, 980)
            rating = RatingLoader(record_detail["rating"])
            if rating.mode != 'RGBA':
                rating = rating.convert('RGBA')
            temp_img.paste(rating, rating_pos, rating)

            # Combo
            combo_pos = (424, 971)
            combo_status = ComboStatusLoader(record_detail['full_combo'], record_detail['score']).resize([243, 40], Resampling.LANCZOS)
            if combo_status.mode != 'RGBA':
                combo_status = combo_status.convert('RGBA')
            temp_img.paste(combo_status, combo_pos, combo_status)

            # Chain
            chain_pos = (423, 1015)
            chain_status = ChainStatusLoader(record_detail['full_chain']).resize([243, 40], Resampling.LANCZOS)
            if chain_status.mode != 'RGBA':
                chain_status = chain_status.convert('RGBA')
            temp_img.paste(chain_status, chain_pos, chain_status)

            # 标题
            title_pos = (234, 876)
            temp_img = TextDraw(temp_img, record_detail['song_name'], title_pos, max_width=900,
                                 font_path=title_font_path, font_size=48,
                                 font_color=(26, 0, 84), h_align="left")
            
            # 曲师
            artist_pos = (234, 936)
            temp_img = TextDraw(temp_img, record_detail['artist'], artist_pos, max_width=420,
                                 font_path=title_font_path, font_size=36,
                                 font_color=(26, 0, 84), h_align="left")
            
            # Best 序号
            best_pos = (245, 1017)
            temp_img = TextDraw(temp_img, f"{prefix} #{index}", best_pos, max_width=200,
                                font_path=title_font_path, font_size=28,
                                font_color=(255, 255, 255), h_align="center")
            
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
                    if play_count_base.mode != 'RGBA':
                        play_count_base = play_count_base.convert('RGBA')
                    temp_img.paste(play_count_base, (1170, 840), play_count_base)
                
                # 绘制游玩次数文字
                text_central_position = (1350, 860)
                play_count_text = str(PlayCount)
                temp_img = TextDraw(temp_img, play_count_text, text_central_position,
                                   font_path=title_font_path, font_size=24,
                                   font_color=(255, 152, 0), h_align="center")
            
            # 将temp_img合成到background上
            background = Image.alpha_composite(background, temp_img)
    except Exception as e:
            print(f"在生成图像时出现错误：{e}")
            print(traceback.format_exc())
            background = Image.new('RGBA', (1520, 500), (0, 0, 0, 255))
    finally:
        background.save(os.path.join(output_path, f"{prefix}_{index}.png"))