import os, subprocess, time
from datetime import datetime
from dataclasses import dataclass
from utils.ImageUtils import get_splited_text
from utils.PageUtils import format_time_difference
from typing import Dict, List, Tuple, Optional, Any
from moviepy import ColorClip, VideoFileClip, ImageClip, TextClip, AudioFileClip, CompositeVideoClip, vfx, afx
from utils.Variables import HARD_RENDER_METHOD, bgclips_path, image_root_path, audios_path, REVERSE_LEVEL_LABELS

@dataclass
class SegmentConfig:
    """视频片段配置数据类"""
    id: str
    song_name: str
    duration: float
    text: str
    level_index: int
    start: float = 0.0
    end: float = 0.0
    video: Optional[str] = None
    main_image: Optional[str] = None
    bg_page: bool = False


class SegmentGenerator:
    """视频片段生成器类"""
    def __init__(
        self,
        style_config: Dict[str, Any],
        resolution: Tuple[int, int] = (1920, 1080),
        font_path: str = "",
        bitrate: int = 5000,
        encoder_param: Optional[Dict[str, Any]] = None,
        output_path: str = './videos/temp_generated'
    ):
        """
        初始化视频生成器
        
        Args:
            resolution: 输出分辨率 (width, height)
            font_path: 字体文件路径
            bitrate: 视频码率 (kbps)
            encoder_param: 编码器参数
            output_path: 输出路径
        """
        self.resolution = resolution
        self.font_path = font_path
        self.bitrate = bitrate
        self.encoder_param = encoder_param or {
            "hwaccel": None,
            "brand": "software",
            "encoder": "libx264",
            "preset": "fast",
            "cq": 33
        }
        self.output_path = output_path
        self.style_config = style_config
        
        # 预计算坐标和缩放因子
        self._update_coordinates()
    
    def _update_coordinates(self, style_config: Dict[str, Any]):
        """更新坐标和缩放因子（基于分辨率）"""
        width, height = self.resolution
        self.scale_factor = height / 1080
        
        # 文字相关坐标
        self.text_size = int(32 * self.scale_factor)
        self.text_x = int(0.7594 * width)
        self.text_first_y = int(0.224 * height)
        self.line_height = self.text_size + 10
        
        # 视频内框坐标
        self.inner_box_left = int(135 * width / 1920)
        self.inner_box_top = int(83 * height / 1080)
        self.inner_box_height = int(668 * height / 1080)
        
        # 视频位置
        self.video_pos = (int(0.0641 * width), int(0.075 * height))
        
        # 信息片段坐标
        self.info_text_pos = (int(0.15 * width), int(0.17 * height))
        self.additional_text_pos = (int(0.2 * width), int(0.89 * height))
    
    def set_resolution(self, resolution: Tuple[int, int]):
        """动态设置分辨率"""
        self.resolution = resolution
        self._update_coordinates()
    
    def create_info_segment(
        self,
        clip_config: SegmentConfig,
        text_size: int = 32,
        inline_max_len: int = 75,
        max_lines_per_page: int = 12
    ) -> CompositeVideoClip:
        """
        创建信息片段
        
        Args:
            clip_config: 片段配置
            text_size: 文字大小
            inline_max_len: 每行最大长度
            max_lines_per_page: 每页最大行数
            
        Returns:
            合成的视频片段
        """
        # 检查必要字段
        if clip_config.duration <= 0:
            raise ValueError(f"无效的片段时长: {clip_config.duration}")
        
        if not clip_config.text:
            clip_config.text = "【无文本内容】"
            print(f"警告: 片段 {clip_config.id} 没有填写内容，将填充占位符")
        
        # 创建背景
        bg_video = self._create_background_video(clip_config.duration)
        bg_image = self._create_background_image(clip_config.duration)
        
        # 文本分页
        pages = self._split_text_into_pages(
            clip_config.text,
            inline_max_len,
            max_lines_per_page,
            clip_config.bg_page
        )
        
        # 创建文字片段
        text_clips = self._create_text_clips_for_pages(
            pages,
            clip_config.duration,
            self.info_text_pos,
            clip_config.bg_page
        )
        
        # 创建底部文字
        additional_clip = self._create_additional_text_clip(clip_config.duration)
        
        # 合成
        composite_clip = CompositeVideoClip(
            [
                bg_video.with_position((0, 0)),
                bg_image.with_position((0, 0)),
                additional_clip.with_position(self.additional_text_pos)
            ] + text_clips,
            size=self.resolution,
            use_bgclip=True
        )
        
        # 添加音频
        composite_clip = self._add_background_audio(composite_clip, clip_config.duration)
        
        return composite_clip.with_duration(clip_config.duration)
    
    def create_video_segment(
        self,
        clip_config: SegmentConfig,
        use_hardware_acceleration: bool = False,
        acceleration_method: str = "NVIDIA"
    ) -> VideoFileClip:
        """
        使用 FFmpeg 创建视频片段（硬件加速模式）
        
        Args:
            clip_config: 片段配置
            use_hardware_acceleration: 是否使用硬件加速
            acceleration_method: 加速方法 (NVIDIA/AMD/Intel)
            
        Returns:
            生成的视频片段
        """
        start_time_generation = time.time()
        
        # 构建 FFmpeg 命令
        cmd = self._build_ffmpeg_command(
            clip_config,
            use_hardware_acceleration,
            acceleration_method
        )
        
        # 生成输出路径
        output_path = self._get_output_path(clip_config)
        
        print(f"正在为您生成【{clip_config.song_name} - {REVERSE_LEVEL_LABELS.get(clip_config.level_index)}】的片段")
        print("正在执行 FFmpeg 生成命令。")
        
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
            print(f"已生成您的视频片段，名称为: {output_path}")
            print(f"片段生成用时{format_time_difference(time.time() - start_time_generation)}")
            return VideoFileClip(output_path)
            
        except subprocess.CalledProcessError as e:
            self._handle_ffmpeg_error(e, clip_config, cmd, output_path)
            print("将使用快速模式为您重新生成；")
            return self.create_video_segment_classic(clip_config)
    
    def create_video_segment_classic(
        self,
        clip_config: SegmentConfig,
        text_size: Optional[int] = None
    ) -> CompositeVideoClip:
        """
        标准渲染模式（moviepy 实现）
        
        Args:
            clip_config: 片段配置
            text_size: 文字大小
            
        Returns:
            合成的视频片段
        """
        print(f"正在为您生成【{clip_config.song_name} - {REVERSE_LEVEL_LABELS.get(clip_config.level_index)}】的片段")
        
        # 设置文字大小
        if text_size is None:
            text_size = self.text_size
        
        # 创建各图层
        bg_video = self._create_background_video(clip_config.duration)
        main_image = self._create_main_image(clip_config)
        video_clip = self._create_video_clip(clip_config)
        
        # 创建分页文字
        text_clips = self._create_paginated_text_clips(
            clip_config.text,
            clip_config.duration,
            text_size
        )
        
        # 合成所有图层
        all_clips = [
            bg_video.with_position((0, 0)),
            main_image.with_position((0, 0)),
            video_clip.with_position(self.video_pos)
        ]
        all_clips.extend(text_clips)
        
        composite_clip = CompositeVideoClip(all_clips, size=self.resolution, use_bgclip=True)
        
        return composite_clip.with_duration(clip_config.duration)
    
    # ==================== 私有辅助方法 ====================
    
    def _create_background_video(self, duration: float) -> VideoFileClip:
        """创建背景视频"""
        bg_video = VideoFileClip(f"{bgclips_path}/bg.mp4")
        return bg_video.with_effects([
            vfx.Loop(duration=duration),
            vfx.MultiplyColor(0.5),
            vfx.Resize(width=self.resolution[0])
        ])
    
    def _create_background_image(self, duration: float) -> ImageClip:
        """创建背景图片"""
        bg_image = ImageClip(f"{image_root_path}\\Base\\intro\\IntroBase.png")
        return bg_image.with_duration(duration).with_effects([
            vfx.Resize(width=self.resolution[0])
        ])
    
    def _split_text_into_pages(
        self,
        text: str,
        inline_max_len: int,
        max_lines_per_page: int,
        is_bg_page: bool
    ) -> List[List[str]]:
        """将文本分割成多页"""
        text_list = get_splited_text(text, text_max_bytes=inline_max_len)
        
        if not text_list or is_bg_page:
            text_list = ["【无文本内容或背景页】"]
        
        pages = []
        current_page = []
        
        for line in text_list:
            if len(current_page) >= max_lines_per_page:
                pages.append(current_page)
                current_page = [line]
            else:
                current_page.append(line)
        
        if current_page:
            pages.append(current_page)
        
        return pages
    
    def _create_text_clips_for_pages(
        self,
        pages: List[List[str]],
        duration: float,
        position: Tuple[int, int],
        is_bg_page: bool
    ) -> List[TextClip]:
        """为多页文本创建文字片段"""
        if len(pages) <= 1:
            # 单页情况
            txt_clip = TextClip(
                font=self.font_path,
                text="\n".join(pages[0]),
                method="label",
                font_size=self.text_size,
                margin=(20, 5),
                interline=6.5,
                vertical_align="top",
                color="black" if not is_bg_page else "#FFFFFF00",
                duration=duration,
                transparent=is_bg_page
            )
            return [txt_clip.with_position(position)]
        
        # 多页情况
        page_duration = duration / len(pages)
        text_clips = []
        
        for i, page_lines in enumerate(pages):
            page_text = "\n".join(page_lines)
            start_time = i * page_duration
            
            txt_clip = TextClip(
                font=self.font_path,
                text=page_text,
                method="label",
                font_size=self.text_size,
                margin=(20, 5),
                interline=6.5,
                vertical_align="top",
                color="black" if not is_bg_page else "white",
                duration=page_duration
            ).with_start(start_time)
            
            text_clips.append(txt_clip.with_position(position))
        
        return text_clips
    
    def _create_additional_text_clip(self, duration: float) -> TextClip:
        """创建底部附加文字"""
        addtional_text = "【本视频由 chu-gen-videob30 生成，版本 v0.6】"
        return TextClip(
            font=self.font_path,
            text=addtional_text,
            method="label",
            font_size=20,
            vertical_align="bottom",
            color="white",
            duration=duration
        )
    
    def _add_background_audio(self, clip: CompositeVideoClip, duration: float) -> CompositeVideoClip:
        """添加背景音乐"""
        bg_audio = AudioFileClip(f"{audios_path}/bgm.mp3")
        bg_audio = bg_audio.with_effects([afx.AudioLoop(duration=duration)])
        return clip.with_audio(bg_audio)
    
    def _create_main_image(self, clip_config: SegmentConfig) -> ImageClip:
        """创建主图片层"""
        if clip_config.main_image and os.path.exists(clip_config.main_image):
            main_image = ImageClip(clip_config.main_image)
            return main_image.with_duration(clip_config.duration).with_effects([
                vfx.Resize(self.resolution)
            ])
        else:
            print(f"警告: {clip_config.id} 缺少主图片")
            return ColorClip(size=self.resolution, color=(0, 0, 0)).with_duration(clip_config.duration)
    
    def _create_video_clip(self, clip_config: SegmentConfig) -> VideoFileClip:
        """创建视频片段层"""
        if clip_config.video and os.path.exists(clip_config.video):
            try:
                video_clip = VideoFileClip(clip_config.video).subclipped(
                    clip_config.start, clip_config.end
                )
                return video_clip.with_effects([
                    vfx.Resize(height=self.inner_box_height)
                ])
            except Exception as e:
                print(f"视频处理错误: {e}")
        
        print(f"警告: {clip_config.id} 缺少视频文件")
        return ColorClip(
            size=(self.inner_box_height * 16 // 9, self.inner_box_height),
            color=(0, 0, 0)
        ).with_duration(clip_config.duration)
    
    def _create_paginated_text_clips(
        self,
        text: str,
        duration: float,
        text_size: int
    ) -> List[TextClip]:
        """创建分页文字剪辑"""
        MAX_LINES_PER_PAGE = 12
        line_height = text_size + 10
        
        # 分割文本
        text_list = get_splited_text(text, text_max_bytes=20)
        
        # 分页
        text_pages = []
        for i in range(0, len(text_list), MAX_LINES_PER_PAGE):
            text_pages.append(text_list[i:i + MAX_LINES_PER_PAGE])
        
        total_pages = len(text_pages)
        page_duration = duration / total_pages if total_pages > 0 else duration
        
        text_clips = []
        
        for page_index, page_lines in enumerate(text_pages):
            page_start_time = page_index * page_duration
            
            for line_index, line in enumerate(page_lines):
                y_offset = self.text_first_y + line_index * line_height
                
                try:
                    txt_clip = TextClip(
                        text=line,
                        font=self.font_path,
                        font_size=text_size,
                        color="rgb(120,65,14)",
                        method="pango" if hasattr(TextClip, 'PANGO') else "label",
                    ).with_duration(page_duration)
                    
                    txt_clip = txt_clip.with_start(page_start_time)
                    text_clips.append(txt_clip.with_position((self.text_x, y_offset)))
                    
                except Exception as e:
                    print(f"创建文字剪辑失败: {e}")
        
        return text_clips
    
    def _build_ffmpeg_command(
        self,
        clip_config: SegmentConfig,
        use_hardware_acceleration: bool,
        acceleration_method: str
    ) -> List[str]:
        """构建 FFmpeg 命令"""
        input_args = []
        filter_complex_parts = []
        
        # 背景视频路径
        bg_video_path = os.path.abspath(f"{bgclips_path}/bg.mp4").replace('\\', '/')
        input_args.extend(['-i', bg_video_path])
        
        # 背景处理
        base_stream = self._build_background_filter(
            clip_config,
            input_args,
            filter_complex_parts
        )
        
        # 添加文本
        base_stream = self._add_text_filters(
            clip_config,
            filter_complex_parts,
            base_stream
        )
        
        # 添加视频片段
        audio_stream = self._add_video_overlay(
            clip_config,
            input_args,
            filter_complex_parts,
            base_stream
        )
        
        # 最终输出
        filter_complex_parts.append(f'[{base_stream}]trim=duration={clip_config.duration}[v_out];')
        
        if audio_stream:
            filter_complex_parts.append(audio_stream)
        else:
            filter_complex_parts.append(f'aevalsrc=0::d={clip_config.duration}[a_out]')
        
        filter_complex = ''.join(filter_complex_parts)
        
        # 编码参数
        encoding_args = self._get_encoding_args(use_hardware_acceleration, acceleration_method)
        
        # 输出路径
        output_path = self._get_output_path(clip_config)
        
        # 构建完整命令
        return [
            'ffmpeg', '-y',
            *input_args,
            '-hide_banner',
            '-filter_complex', filter_complex,
            '-map', '[v_out]',
            '-map', '[a_out]',
            *encoding_args,
            '-preset', self.encoder_param.get("preset", "fast"),
            '-cq', str(self.encoder_param.get("cq", '33')),
            '-r', '60',
            '-threads', '0',
            '-thread_type', 'frame',
            '-b:v', f'{self.bitrate}k',
            '-maxrate', f'{int(self.bitrate) * 2}k',
            '-bufsize', f'{int(self.bitrate) * 4}k',
            '-pix_fmt', 'yuv420p',
            '-acodec', 'aac',
            '-b:a', '320k',
            '-max_muxing_queue_size', '4096',
            '-t', str(clip_config.duration),
            output_path
        ]
    
    def _build_background_filter(
        self,
        clip_config: SegmentConfig,
        input_args: List[str],
        filter_complex_parts: List[str]
    ) -> str:
        """构建背景滤镜"""
        duration = clip_config.duration
        resolution = self.resolution
        
        if clip_config.main_image and os.path.exists(clip_config.main_image):
            main_image_path = os.path.abspath(clip_config.main_image).replace('\\', '/')
            input_args.extend(['-i', main_image_path])
            
            filter_complex_parts.append(f'[1:v]scale={resolution[0]}:{resolution[1]}[img];')
            filter_complex_parts.append(
                f'[0:v]loop=loop=-1:size=1000:start=0,trim=duration={duration},'
                f'scale={resolution[0]}:{resolution[1]},eq=brightness=-0.25[bg_processed];'
            )
            filter_complex_parts.append('[bg_processed][img]overlay=0:0[bg_img];')
            return 'bg_img'
        else:
            filter_complex_parts.append(
                f'[0:v]loop=loop=-1:size=1000:start=0,trim=duration={duration},'
                f'scale={resolution[0]}:{resolution[1]},eq=brightness=-0.25[bg_img];'
            )
            return 'bg_img'
    
    def _add_text_filters(
        self,
        clip_config: SegmentConfig,
        filter_complex_parts: List[str],
        base_stream: str
    ) -> str:
        """添加文字滤镜"""
        duration = clip_config.duration
        text_lines = get_splited_text(clip_config.text, text_max_bytes=20)
        lines_per_page = 12
        
        pages = []
        for i in range(0, len(text_lines), lines_per_page):
            pages.append(text_lines[i:i + lines_per_page])
        
        total_pages = len(pages)
        page_duration = duration / total_pages if total_pages > 0 else duration
        
        print(f"分页信息: 总行数 = {len(text_lines)}, 总页数 = {total_pages}, 每页显示时间 = {page_duration:.2f} 秒")
        
        for page_num, page_lines in enumerate(pages):
            page_start = page_num * page_duration
            page_end = (page_num + 1) * page_duration
            
            for line_num, line in enumerate(page_lines):
                y_offset = self.text_first_y + line_num * self.line_height
                
                filter_complex_parts.append(
                    f'[{base_stream}]drawtext=text=\"{line}\":fontfile={self.font_path}:'
                    f'fontsize={self.text_size}:fontcolor=78410E:'
                    f'x={self.text_x}:y={y_offset}:'
                    f'enable=\'between(t,{page_start},{page_end})\''
                )
                
                current_label = f'page{page_num}_line{line_num}'
                filter_complex_parts.append(f'[{current_label}];')
                base_stream = current_label
        
        return base_stream
    
    def _add_video_overlay(
        self,
        clip_config: SegmentConfig,
        input_args: List[str],
        filter_complex_parts: List[str],
        base_stream: str
    ) -> Optional[str]:
        """添加视频叠加层"""
        if clip_config.video and os.path.exists(clip_config.video):
            video_path = os.path.abspath(clip_config.video).replace('\\', '/')
            input_args.extend(['-i', video_path])
            video_idx = 2 + (1 if clip_config.main_image and os.path.exists(clip_config.main_image) else 0)
            
            filter_complex_parts.append(
                f'[{video_idx}:v]scale=-1:{self.inner_box_height},'
                f'trim=start={clip_config.start}:duration={clip_config.duration},'
                f'setpts=PTS-STARTPTS[overlay_vid];'
            )
            filter_complex_parts.append(
                f'[{base_stream}][overlay_vid]overlay={self.inner_box_left}:{self.inner_box_top}[final_video];'
            )
            
            audio_stream = f'[{video_idx}:a]atrim=start={clip_config.start}:duration={clip_config.duration},asetpts=PTS-STARTPTS[a_out]'
            filter_complex_parts[-1] = filter_complex_parts[-1].replace('[final_video];', '[final_video];')
            return audio_stream
        
        return None
    
    def _get_encoding_args(
        self,
        use_hardware_acceleration: bool,
        acceleration_method: str
    ) -> List[str]:
        """获取编码参数"""
        encoding_args = []
        
        if use_hardware_acceleration and acceleration_method in HARD_RENDER_METHOD:
            encoder_prefix = self.encoder_param.get("encoder", "h264")
            hardware_suffix = HARD_RENDER_METHOD[acceleration_method]["codec"]
            final_encoder = f"{encoder_prefix}_{hardware_suffix}"
            encoding_args.extend(['-vcodec', final_encoder])
        else:
            final_encoder = self.encoder_param.get("encoder", "libx264")
            encoding_args.extend(['-vcodec', final_encoder])
        
        return encoding_args
    
    def _get_output_path(self, clip_config: SegmentConfig) -> str:
        """获取输出路径"""
        if os.path.isdir(self.output_path):
            return os.path.join(
                self.output_path,
                f"{clip_config.id}-{REVERSE_LEVEL_LABELS.get(clip_config.level_index)}.mp4"
            )
        return self.output_path
    
    def _handle_ffmpeg_error(
        self,
        error: subprocess.CalledProcessError,
        clip_config: SegmentConfig,
        cmd: List[str],
        output_path: str
    ):
        """处理 FFmpeg 错误"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_content = f"""
========================== FFmpeg 生成失败！============================
生成时间：{timestamp}，
视频 ID: {clip_config.id}，
歌曲名称: {clip_config.song_name}，
输出路径: {output_path}，
持续时间: {clip_config.duration} 秒，
分辨率: {self.resolution}

FFmpeg 命令:
{" ".join(cmd)}

错误输出:
{error.stderr}

配置信息:
{clip_config}
============================ 错误日志结束 ============================"""
        
        log_path = f'./videos/error_logs/generation_error_report_{timestamp}.log'
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(log_content)
        
        print("FFmpeg 生成失败！详细错误报告已保存为文件；")
        print(f"路径：{os.path.abspath(log_path)}")
        print("============================ 这里是分隔符 ============================")


# 使用示例
# if __name__ == "__main__":
#     # 创建生成器实例
#     generator = VideoSegmentGenerator(
#         resolution=(1920, 1080),
#         font_path="path/to/font.ttf",
#         bitrate=5000,
#         output_path="./output"
#     )
    
#     # 创建配置
#     config = SegmentConfig(
#         id="test_001",
#         song_name="测试歌曲",
#         duration=10.0,
#         text="这是一段测试文本",
#         level_index=0
#     )
    
    # 生成片段
    # clip = generator.create_info_segment(config)
    # clip = generator.create_video_segment_classic(config)
    # clip = generator.create_video_segment(config, use_hardware_acceleration=True)