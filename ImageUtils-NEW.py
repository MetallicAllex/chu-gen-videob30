class ChuniImageGenerater:
    def __init__(self, style_config=None):
        self.asset_paths = style_config.get("asset_paths", {})
        self.image_root_path = self.asset_paths.get("score_image_assets_path", "./static/assets/images/Chunithm")
        self.ui_font_path = self.asset_paths.get("ui_font", "./static/assets/fonts/SOURCEHANSANSSC-BOLD.OTF")
        self.title_font_path = "./static/assets/fonts/SweiBellLegCJKsc-Black.ttf"
        self.level_font_path = "./static/assets/fonts/NimbusSanL-Bol.otf"

    def FrameLoader(self, level_index: int = 0):
        with Image.open(f"{self.image_root_path}/Frames/{level_index}.png") as _frame:
            return _frame.copy()

    def LevelLoader(self, ds_cur: float, ds_next: float = 0.0):
        # TODO: FLAG依据判断以哪个版本的定数为准
        ds = ds_cur if ds_cur > 1 else ds_next
        # 根据小数点拆分字符串
        __ds = str(ds)
        if '.' in __ds:
            level, decimal = __ds.split('.')
        else:
            level, decimal = __ds, '0'
        level_number_img = Image.new('RGBA', (108, 88), (0, 0, 0, 0))

        # 绘制数字
        level_number_img = self.TextDraw(level_number_img, level, (54, 46), 
                                         font_path=self.level_font_path,
                                         font_size=60, font_color=(255, 255, 255), h_align="center")

        if int(decimal) >= 6:
            # 绘制加号
            level_number_img = self.TextDraw(level_number_img, '+', (92, 8), 
                                             font_path=self.level_font_path,
                                             font_size=42, font_color=(255, 255, 255), h_align="center")

        return level_number_img
        
    def ScoreLoader(self, score: int = 0):
        if score < 0 or score > 1010000:
            raise ValueError("分数无效")
        
        score_str_formatted = f"{score:,}"   
        score_number_img = Image.new('RGBA', (420, 100), (0, 0, 0, 0))

        # 计算总宽度以实现右对齐
        total_width = 0
        digit_size = (50, 80)  # 每个数字的宽度和高度
        comma_size = (50, 72)  # 逗号的宽度和高度
        for char in score_str_formatted:
            if char == ',':
                total_width += comma_size[0]  // 2 # 逗号宽度视为数字宽度的一半，以实现更紧凑的排列
            else:
                total_width += digit_size[0]
        
        # 从右侧开始绘制
        current_x = 420 - total_width
        
        for char in score_str_formatted:
            if char == ',':
                image_path = f"{self.image_root_path}/Numbers/AchievementNumber/comma.png"
                char_width = comma_size[0] // 2
            else:
                image_path = f"{self.image_root_path}/Numbers/AchievementNumber/{char}.png"
                char_width = digit_size[0]
            
            with Image.open(image_path) as char_img:
                # 将图片缩放到指定大小
                if char == ',':
                    char_img = char_img.resize(comma_size, Image.LANCZOS)
                else:
                    char_img = char_img.resize(digit_size, Image.LANCZOS)
                
                char_y = 28 if char == ',' else 8  # 逗号的垂直方向在数字的下方
                score_number_img.paste(char_img, (current_x, char_y), char_img)
                current_x += char_width
                
        return score_number_img
    
    def RatingLoader(self, rating: float):
        if rating < 0:
            raise ValueError("Rating值无效")
        
        # 按照rating数值选择数字图片的样式
        match rating:
            case _ if rating >= 17:
                digit_style = "ex_rainbow"
            case _ if rating >= 16:
                digit_style = "rainbow"
            case _ if rating < 16:
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
                image_path = f"{self.image_root_path}/Numbers/RatingNumber/{digit_style}/dot.png"
                char_width = dot_size[0] // 2
                char_y = 8  # 小数点位置靠下
            else:   
                image_path = f"{self.image_root_path}/Numbers/RatingNumber/{digit_style}/{char}.png"
                char_width = digit_size[0]
                char_y = 0
            with Image.open(image_path) as char_img:
                if char == '.':
                    char_img = char_img.resize(dot_size, Image.LANCZOS)
                else:
                    char_img = char_img.resize(digit_size, Image.LANCZOS)
                ra_number_img.paste(char_img, (current_x, char_y), char_img)
                current_x += char_width

        return ra_number_img

    def ComboStatusLoader(self, combo_status: str = ""):
        match combo_status:
            case _ if combo_status == '' or combo_status is None:
                return Image.new('RGBA', (80, 80), (0, 0, 0, 0))
            case _ if combo_status == 'fc':
                with Image.open(f"{self.image_root_path}/ComboStatus/11.png") as _comboStatus:
                    return _comboStatus.copy()
            case _ if combo_status == 'aj':
                with Image.open(f"{self.image_root_path}/ComboStatus/12.png") as _comboStatus:
                    return _comboStatus.copy()
            case _ if combo_status == 'ajc':
                with Image.open(f"{self.image_root_path}/ComboStatus/13.png") as _comboStatus:
                    return _comboStatus.copy()
                
    def ChainStatusLoader(self, chain_status: str = ""):
        match chain_status:
            case _ if chain_status == '' or chain_status is None:
                return Image.new('RGBA', (80, 80), (0, 0, 0, 0))
            case _ if chain_status == 'fc':
                with Image.open(f"{self.image_root_path}/ComboStatus/21.png") as _chainStatus:
                    return _chainStatus.copy()
            case _ if chain_status == 'fcr':
                with Image.open(f"{self.image_root_path}/ComboStatus/22.png") as _chainStatus:
                    return _chainStatus.copy()
        
    def TextDraw(self, image, text: str = "", pos: tuple = (0, 0), max_width: int = 2000,
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
            font_path = self.ui_font_path

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
    
    
    def GenerateOneAchievement(self, record_detail: dict):
        """
        生成单个Chunithm成绩记录。

        Args:
            record_detail (dict): 成绩记录详情，包含以下字段：
                - title (str): 乐曲标题
                - artist (str): 艺术家
                - ds_cur (float): 定数（当前版本）
                - ds_next (float): 定数（下版本，可留空）
                - level_index (int): 难度颜色
                - score (int): 分数
                - combo_type (str): FC状态，可选值：空字符串、'fc'、'aj'、'ajc'
                - chain_type (str): 连锁状态，可选值：空字符串、'fc'、'fcr'
                - ra (float): Rating值

        Returns:
            Background (Image.Image): 处理后的成绩记录图片
        """

        # Initialize Background as None outside the try block
        background = None
        
        try:
            assert record_detail['level_index'] in range(0, 5)
            image_base_path = os.path.join(os.getcwd(),
                                            f"{self.image_root_path}/content_base_chunithm_verse.png")
            with Image.open(image_base_path) as background:

                # background size: 1920x1080
                background = background.convert("RGBA")
                assert background.size == (1920, 1080)

                # 载入图片元素
                _temp_img = Image.new('RGBA', background.size, (0, 0, 0, 0))

                # 加载边框
                frame = self.FrameLoader(record_detail["level_index"])
                _temp_img.paste(frame, (65, 32), frame)

                # 加载等级
                level_pos = (102, 884)
                level = self.LevelLoader(record_detail["ds_cur"], record_detail["ds_next"])
                _temp_img.paste(level, level_pos, level)

                # 加载定数（当前版本和下一版本）
                ds_cur_pos = (1562, 1018)
                ds_next_pos = (1756, 1018)
                ds_cur = record_detail["ds_cur"]
                ds_next = record_detail["ds_next"]
                ds_cur_text = str(ds_cur)
                if ds_cur <= 0.0:  # 不在当前版本的谱面，使用0来标记无定数
                    ds_cur_text = "--"
                _temp_img = self.TextDraw(_temp_img, ds_cur_text , ds_cur_pos,
                                          font_path=self.title_font_path, 
                                          font_size=45, font_color=(77, 77, 77), h_align="center")
                if ds_cur <= 0.0: 
                    ds_next_text = str(ds_next)
                elif ds_next > ds_cur:
                    ds_next_text = str(ds_next) + "↑" 
                elif ds_next < ds_cur:
                    ds_next_text = str(ds_next) + "↓"
                else:
                    ds_next_text = str(ds_next) + "→"
                _temp_img = self.TextDraw(_temp_img, ds_next_text , ds_next_pos,
                                          font_path=self.title_font_path, 
                                          font_size=45, font_color=(77, 77, 77), h_align="center")

                # 加载分数
                score_pos = (706, 958)
                score = self.ScoreLoader(record_detail["score"])
                _temp_img.paste(score, score_pos, score)
                
                # 加载Rating值
                rating_pos = (1216, 980)
                rating = self.RatingLoader(record_detail['ra'])
                _temp_img.paste(rating, rating_pos, rating)

                # 加载Combo状态
                combo_status_pos = (426, 975)
                combo_status = self.ComboStatusLoader(record_detail["combo_type"])
                combo_status = combo_status.resize((236, 38), Image.LANCZOS)
                _temp_img.paste(combo_status, combo_status_pos, combo_status)

                # 加载Chain状态
                chain_status_pos = (426, 1020)
                chain_status = self.ChainStatusLoader(record_detail["chain_type"])
                chain_status = chain_status.resize((236, 38), Image.LANCZOS)
                _temp_img.paste(chain_status, chain_status_pos, chain_status)

                # 标题
                text_title_pos = (234, 876)
                title = record_detail['title']
                _temp_img = self.TextDraw(_temp_img, title, text_title_pos, max_width=900,
                                          font_path=self.title_font_path, 
                                          font_size=48, font_color=(26, 0, 84), h_align="left")
                # 艺术家
                text_artist_pos = (234, 936)
                artist = record_detail['artist']
                _temp_img = self.TextDraw(_temp_img, artist, text_artist_pos, max_width=420,
                                          font_path=self.title_font_path, 
                                          font_size=36, font_color=(26, 0, 84), h_align="left")
                
                # 游玩次数（暂无获取方式，b50data中若有手动填写即可显示）
                if "playCount" in record_detail:
                    play_count = int(record_detail["playCount"])
                else:
                    play_count = 0
                if play_count >= 1:
                    with Image.open(f"{self.image_root_path}/Playcount/PlayCountBase.png") as PlayCountBase:
                        _temp_img.paste(PlayCountBase, (1177, 846), PlayCountBase)
                    text_center_pos = (1359, 865)
                    _temp_img = self.TextDraw(_temp_img, str(play_count), text_center_pos,
                                              font_path=self.title_font_path,
                                              font_size=30, font_color=(248, 34, 117), h_align="center")
                    
                background = Image.alpha_composite(background, _temp_img)                           
        except Exception as e:
            print(f"Error generating achievement: {e}")
            print(traceback.format_exc())
            background = Image.new('RGBA', (1520, 500), (0, 0, 0, 255))
        return background