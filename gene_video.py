import datetime
import os, threading, subprocess, time
from queue import Queue, Empty
from typing import Any, Dict, List, Tuple
import numpy as np
from PIL import Image, ImageFilter
from moviepy import ColorClip, VideoFileClip, ImageClip, TextClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
from moviepy import vfx, afx
from utils.Utils import format_time_difference
from utils.chuni_extension import REVERSE_LEVEL_LABELS

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


def blur_image(image_path, blur_radius=5):
    """
    对图片进行高斯模糊处理
    
    Args:
        image_path (str): 图片路径
        blur_radius (int): 模糊半径，默认为10
        
    Returns:
        numpy.ndarray: 模糊处理后的图片数组
    """
    try:
        pil_image = Image.open(image_path)
        blurred_image = pil_image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        # 将模糊后的图片转换为 numpy 数组
        return np.array(blurred_image)
    except Exception as e:
        print(f"Warning: 图片模糊处理失败 - {str(e)}")
        return np.array(Image.open(image_path))


def create_blank_image(width, height, color=(0, 0, 0, 0)):
    """
    创建一个透明的图片
    """
    # 创建一个RGBA模式的空白图片
    image = Image.new('RGBA', (width, height), color)
    # 转换为numpy数组，moviepy需要这种格式
    return np.array(image)


def normalize_audio_volume(clip, target_dbfs=-20):
    """均衡化音频响度到指定的分贝值"""
    if clip.audio is None:
        return clip
    
    try:
        # 获取音频数据
        audio = clip.audio
        
        # 采样音频的多个点来计算平均音量
        sample_times = np.linspace(0, clip.duration, num=100)
        samples = []
        
        for t in sample_times:
            frame = audio.get_frame(t)
            if isinstance(frame, (list, tuple, np.ndarray)):
                samples.append(np.array(frame))
        
        if not samples:
            return clip
            
        # 将样本堆叠成数组
        audio_array = np.stack(samples)
        
        # 计算当前音频的均方根值
        current_rms = np.sqrt(np.mean(audio_array**2))
        
        # 计算需要的增益
        target_rms = 10**(target_dbfs/20)
        gain = target_rms / (current_rms + 1e-8)  # 添加小值避免除零
        
        # 限制增益范围，避免过度放大或减弱
        gain = np.clip(gain, 0.1, 3.0)
        
        # print(f"Applying volume gain: {gain:.2f}")
        
        # 应用音量调整
        return clip.with_volume_scaled(gain)
    except Exception as e:
        print(f"警告: 音频均衡化失败 - {str(e)}")
        return clip


def create_info_segment(clip_config, resolution, font_path, text_size=44, inline_max_len=40):
    # print(f"正在合成视频片段: {clip_config['id']}")
    bg_image = ImageClip("./images/IntroBase.png").with_duration(clip_config['duration'])
    bg_image = bg_image.with_effects([vfx.Resize(width=resolution[0])])

    # bg_video = VideoFileClip("./images/BgClips/bg.mp4")
    bg_video = VideoFileClip(f"./images/BgClips/bg_xverse.mp4")
    bg_video = bg_video.with_effects([vfx.Loop(duration=clip_config['duration']), 
                                      vfx.MultiplyColor(0.5),
                                      vfx.Resize(width=resolution[0])])

    # 创建文字
    text_list = get_splited_text(clip_config['text'], text_max_bytes=inline_max_len)
    txt_clip = TextClip(font=font_path, text="\n".join(text_list),
                        method = "label",
                        font_size=text_size,
                        margin=(20, 20),
                        interline=6.5,
                        vertical_align="top",
                        color="white",
                        duration=clip_config['duration'])
    
    addtional_text = "【本视频由基于 mai-genVb50 修改的 chu-gen-Vb30(测试版本) 生成，使用时请标记原作者与修改作者】"
    addtional_txt_clip = TextClip(font=font_path, text=addtional_text,
                        method = "label",
                        font_size=20,
                        vertical_align="bottom",
                        color="white",
                        duration=clip_config['duration']
    )
    
    text_pos = (int(0.16 * resolution[0]), int(0.18 * resolution[1]))
    addtional_text_pos = (int(0.2 * resolution[0]), int(0.88 * resolution[1]))
    composite_clip = CompositeVideoClip([
            bg_video.with_position((0, 0)),
            bg_image.with_position((0, 0)),
            txt_clip.with_position((text_pos[0], text_pos[1])),
            addtional_txt_clip.with_position((addtional_text_pos[0], addtional_text_pos[1]))
        ],
        size=resolution,
        use_bgclip=True
    )

    # 为整个composite_clip添加bgm
    # bg_audio = AudioFileClip("./images/Audioes/intro_bgm.mp3")
    bg_audio = AudioFileClip(f"./images/Audioes/bgm_verse.mp3")
    bg_audio = bg_audio.with_effects([afx.AudioLoop(duration=clip_config['duration'])])
    composite_clip = composite_clip.with_audio(bg_audio)

    return composite_clip.with_duration(clip_config['duration'])


# def create_video_segment(clip_config, resolution, font_path, text_size=None, inline_max_len=21):
#     """
#     创建自适应分辨率的视频片段
    
#     Args:
#         clip_config: 片段配置字典
#         resolution: 目标分辨率 (width, height)
#         font_path: 字体文件路径
#         text_size: 文字大小(可选，默认根据分辨率计算)
#         inline_max_len: 每行最大字符数
#     """
#     print(f"正在合成视频片段: {clip_config['id']}")
    
#     # 计算相对于1080p的缩放比例
#     scale_factor = resolution[1] / 1080  # 基于高度缩放
    
#     # 自动计算文字大小（如果未指定）
#     if text_size is None:
#         text_size = int(32 * scale_factor)  # 1080p下默认32px
    
#     # 1. 背景层（纯黑）
#     bg_video = VideoFileClip("./images/BgClips/black_bg.mp4")
#     bg_video = bg_video.with_effects([
#         vfx.Loop(duration=clip_config['duration']), 
#         vfx.Resize(resolution)  # 完整适配目标分辨率
#     ])
    
#     # 2. 主图片层
#     if 'main_image' in clip_config and os.path.exists(clip_config['main_image']):
#         main_image = ImageClip(clip_config['main_image']).with_duration(clip_config['duration'])
#         main_image = main_image.with_effects([vfx.Resize(resolution)])  # 全屏覆盖
#     else:
#         print(f"警告: {clip_config['id']} 缺少主图片")
#         main_image = ImageClip(create_blank_image(*resolution)).with_duration(clip_config['duration'])
    
#     # 3. 视频片段层
#     if 'video' in clip_config and os.path.exists(clip_config['video']):
#         video_clip = VideoFileClip(clip_config['video'])
        
#         # 时间范围校验
#         if clip_config['start'] < 0 or clip_config['start'] >= video_clip.duration:
#             raise ValueError(f"开始时间 {clip_config['start']} 超出视频长度")
#         if clip_config['end'] <= clip_config['start'] or clip_config['end'] > video_clip.duration:
#             raise ValueError(f"结束时间 {clip_config['end']} 无效")
        
#         video_clip = video_clip.subclipped(clip_config['start'], clip_config['end'])
        
#         # 动态计算视频显示区域 (保持16:9比例中的核心区域)
#         video_height = int(0.667 * resolution[1])  # 原1080p下716px的逻辑
#         video_clip = video_clip.with_effects([vfx.Resize(height=video_height)])
#     else:
#         print(f"警告: {clip_config['id']} 缺少视频文件")
#         blank_size = int(540 * scale_factor)  # 原1080p下540px的逻辑
#         video_clip = ImageClip(create_blank_image(blank_size, blank_size))
#         video_clip = video_clip.with_duration(clip_config['duration'])
    
#     # 4. 文字层
#     text_list = get_splited_text(clip_config['text'], text_max_bytes=inline_max_len)
#     txt_clip = TextClip(
#         font=font_path,
#         text="\n".join(text_list),
#         method="label",
#         font_size=text_size,
#         margin=(int(20 * scale_factor), int(20 * scale_factor)),  # 边距缩放
#         interline=6.5 * scale_factor,  # 行距缩放
#         color="white",
#         duration=clip_config['duration']
#     )
    
#     # 动态计算位置 (基于比例而非固定像素)
#     video_pos = (
#         int(0.039 * resolution[0]),  # 水平3.9%
#         int(0.069 * resolution[1])   # 垂直6.9%
#     )
#     text_pos = (
#         int(0.748 * resolution[0]),  # 水平74.8%
#         int(0.069 * resolution[1])   # 垂直6.9%
#     )
    
#     # 合成所有图层
#     composite_clip = CompositeVideoClip([
#         bg_video.with_position((0, 0)),
#         video_clip.with_position(video_pos),
#         main_image.with_position((0, 0)),
#         txt_clip.with_position(text_pos)
#     ], size=resolution, use_bgclip=True)
    
#     return composite_clip.with_duration(clip_config['duration'])

# 全局缓存字典
_position_cache = {}
_scaling_cache = {}

def get_cached_position(resolution, element_type):
    """缓存位置计算"""
    cache_key = f"{resolution[0]}_{resolution[1]}_{element_type}"
    if cache_key not in _position_cache:
        if element_type == "video":
            pos = (int(0.039 * resolution[0]), int(0.069 * resolution[1]))
        elif element_type == "text":
            pos = (int(0.748 * resolution[0]), int(0.069 * resolution[1]))
        else:
            pos = (0, 0)
        _position_cache[cache_key] = pos
    return _position_cache[cache_key]

def get_cached_scaling(resolution):
    """缓存缩放计算"""
    cache_key = f"{resolution[0]}_{resolution[1]}"
    if cache_key not in _scaling_cache:
        scale_factor = resolution[1] / 1080
        video_height = int(0.667 * resolution[1])
        text_size = int(32 * scale_factor)
        _scaling_cache[cache_key] = (scale_factor, video_height, text_size)
    return _scaling_cache[cache_key]

# def create_video_segment(clip_config, resolution, font_path, bitrate, output_path='./videos/temp_generated'):
#     """修正音频问题的FFmpeg命令"""
#     scale_factor = resolution[1] / 1080
#     video_height = int(0.667 * resolution[1])
#     text_size = int(32 * scale_factor)
    
#     text = clip_config['text']
    
#     # 确保所有输入文件存在
#     bg_video_path = os.path.abspath("./images/BgClips/bg_xverse.mp4").replace('\\', '/')
#     main_image_path = os.path.abspath(clip_config.get('main_image', '')).replace('\\', '/') if clip_config.get('main_image') else ''
#     video_path = os.path.abspath(clip_config.get('video', '')).replace('\\', '/') if clip_config.get('video') else ''
    
#     # 构建输入参数
#     input_args = [
#         '-i', bg_video_path,
#         '-init_hw_device', 'cuda=cu:0', # 指定初始化 GPU 设备
#         '-filter_hw_device', 'cu',  # 指定滤镜渲染 GPU 设备
#         '-hwaccel', 'cuda',  # 启用硬件加速
#         # '-hwaccel_output_format', 'cuda'
#     ]
#     filter_complex_parts = []
    
#     # 确定每个输入的索引
#     input_count = 1  # 背景视频是第一个输入
    
#     # 主图片处理
#     if main_image_path and os.path.exists(main_image_path):
#         input_args.extend(['-i', main_image_path])
#         input_count += 1
#         filter_complex_parts.append('[1:v]scale=1920:1080[img];')
#         filter_complex_parts.append('[0:v][img]overlay=0:0[bg_img];')
#         base_stream = 'bg_img'
#     else:
#         filter_complex_parts.append('[0:v]scale=1920:1080[bg_img];')
#         base_stream = 'bg_img'
    
#     # 视频片段处理
#     audio_stream = None
#     if video_path and os.path.exists(video_path):
#         input_args.extend([
#             '-i', video_path
#         ])
#         input_count += 1
#         video_idx = input_count - 1
        
#         # 添加视频处理
#         filter_complex_parts.append(f'[{video_idx}:v]scale=-1:{video_height}[vid];')
#         filter_complex_parts.append(f'[{base_stream}][vid]overlay={int(0.039*resolution[0])}:{int(0.069*resolution[1])}[base];')
#         base_stream = 'base'
        
#         # 设置音频流（从源视频提取）
#         audio_stream = f'[{video_idx}:a]'
    
#     # 文本处理
#     text_lines = get_splited_text(text, text_max_bytes=23)

#     for i, line in enumerate(text_lines):
#         # y_offset = int(0.069 * resolution[1]) + i * (text_size + 10)
#         y_offset = int(0.255 * resolution[1]) + i * (text_size + 10)
#         filter_complex_parts.append(
#             f'[{base_stream}]drawtext=text=\'{line}\':fontfile={font_path}:'
#             # f'fontsize={text_size}:fontcolor=white:x={int(0.748*resolution[0])}:'
#             f'fontsize={text_size}:fontcolor=black:x={int(0.7594*resolution[0])}:'
#             f'y={y_offset}[text{i}];'
#         )
#         base_stream = f'text{i}'
    
#     # 最终输出流
#     filter_complex_parts.append(f'[{base_stream}]copy[v_out];')
    
#     # 如果有音频流，添加到滤镜链
#     if audio_stream:
#         filter_complex_parts.append(f'{audio_stream}acopy[a_out]')
#     else:
#         # 如果没有音频，创建静音音频
#         filter_complex_parts.append(f'aevalsrc=0::d={clip_config["duration"]}[a_out]')
    
#     # 合并滤镜链
#     filter_complex = ''.join(filter_complex_parts)
    
#     # 确保输出路径是文件而不是目录
#     if os.path.isdir(output_path):
#         output_path = os.path.join(output_path, f"{clip_config['id']}.mp4")
    
#     # 构建FFmpeg命令
#     cmd = [
#         'ffmpeg',
#         '-y',
#         *input_args,
#         '-filter_complex', filter_complex,
#         # '-ss', str(clip_config['start']),
#         # '-t', str(clip_config['end'] - clip_config['start']),
#         '-map', '[v_out]',  # 映射视频输出流
#         '-map', '[a_out]',  # 映射音频输出流
#         '-preset', 'fast',
#         '-vcodec', 'h264_nvenc',
#         '-r', '60',
#         '-threads', '8',
#         '-thread_type', 'frame',  # 使用帧级多线程
#         '-b:v', f'{bitrate}k',
#         '-maxrate', f'{int(bitrate)*2}k',
#         '-pix_fmt', 'yuv420p',
#         '-acodec', 'aac',  # 指定音频编码器
#         '-b:a', '320k',    # 音频比特率
#         '-max_muxing_queue_size', '512',  # 防止muxing队列过大
#         output_path
#     ]
    
#     # 打印命令以便调试
#     # print("执行FFmpeg命令:")
#     # print(" ".join(cmd))

#     print(f"正在为您生成【{clip_config['song_name']}】的片段")
#     print("执行FFmpeg命令:")
#     print(" ".join(cmd))

#     # 执行命令
#     try:
#         subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
#         print(f"已生成您的视频片段，名称为: {output_path}")
#         return VideoFileClip(output_path)
#     except subprocess.CalledProcessError as e:
#         error_cmd = " ".join(cmd)  # 这就是您要的变量
#         print("========================== FFmpeg 生成失败！====================================")
#         print("哎呀！生成您的视频片段时出现了问题xwx！")
#         print("如果您不知道如何处理，请将此部分[等于号(=)划定的所有内容]截图发送给 chu-gen 开发者。")
#         print(f"视频生成命令：\n{str(error_cmd)}\n")
#         print(f"生成输出日志: \n{e.stderr}")
#         print("============================ 这里是结尾 ========================================")
#         print("因为您的视频片段使用此模式生成时出现了问题，我们将使用快速模式重新生成；")
#         print(" -> 生成器不会检查您的视频片段文件完整性，别忘了将您生成失败的片段删除掉；")
#         print(" -> 如果您仍要使用极速模式生成，请等待您报告的问题解决后，重新启动生成器。\n")
#         return create_video_segment_classic(clip_config, resolution, font_path)  # 回退到旧方法

def create_video_segment(clip_config, resolution, font_path, bitrate, output_path='./videos/temp_generated'):
    start_time_generation = time.time()
    """修正视频叠加层剪辑时长的FFmpeg命令"""
    scale_factor = resolution[1] / 1080
    video_height = int(0.667 * resolution[1])
    text_size = int(32 * scale_factor)
    
    text = clip_config['text']
    duration = clip_config['duration']
    start_time = clip_config['start']  # 开始时间
    # end_time = clip_config['end']      # 结束时间
    
    # 确保所有输入文件存在
    bg_video_path = os.path.abspath("./images/BgClips/bg_xverse.mp4").replace('\\', '/')
    main_image_path = os.path.abspath(clip_config.get('main_image', '')).replace('\\', '/') if clip_config.get('main_image') else ''
    video_path = os.path.abspath(clip_config.get('video', '')).replace('\\', '/') if clip_config.get('video') else ''
    
    # 构建输入参数
    input_args = [
        '-i', bg_video_path,
        '-init_hw_device', 'cuda=cu:0',
        '-filter_hw_device', 'cu',
        '-hwaccel', 'cuda',
    ]
    filter_complex_parts = []
    
    # 确定每个输入的索引
    input_count = 1  # 背景视频是第一个输入
    
    # 主图片处理
    if main_image_path and os.path.exists(main_image_path):
        input_args.extend(['-i', main_image_path])
        input_count += 1
        filter_complex_parts.append('[1:v]scale=1920:1080[img];')
        filter_complex_parts.append('[0:v][img]overlay=0:0[bg_img];')
        base_stream = 'bg_img'
    else:
        # 背景视频循环并设置时长
        filter_complex_parts.append(f'[0:v]loop=loop=-1:size=1000:start=0,trim=duration={duration}[bg_loop];')
        filter_complex_parts.append('[bg_loop]scale=1920:1080[bg_img];')
        base_stream = 'bg_img'
    
    # 视频片段处理 - 关键修正部分
    audio_stream = None
    if video_path and os.path.exists(video_path):
        input_args.extend(['-i', video_path])
        input_count += 1
        video_idx = input_count - 1
        
        # 修正：确保叠加视频流被正确处理
        # 先缩放再剪辑
        filter_complex_parts.append(f'[{video_idx}:v]scale=-1:{video_height},trim=start={start_time}:duration={duration},setpts=PTS-STARTPTS[overlay_vid];')
        filter_complex_parts.append(f'[{base_stream}][overlay_vid]overlay={int(0.0422*resolution[0])}:{int(0.0583*resolution[1])}[base];')
        base_stream = 'base'
        
        # 音频流单独处理，不合并到滤镜链中
        audio_stream = f'[{video_idx}:a]atrim=start={start_time}:duration={duration},asetpts=PTS-STARTPTS[a_out]'
    
    # 文本处理
    text_lines = get_splited_text(text, text_max_bytes=18)

    for i, line in enumerate(text_lines):
        y_offset = int(0.227 * resolution[1]) + i * (text_size + 10)
        filter_complex_parts.append(
            f'[{base_stream}]drawtext=text=\'{line}\':fontfile={font_path}:'
            f'fontsize={text_size}:fontcolor=black:x={int(0.7594*resolution[0])}:'
            f'y={y_offset}[text{i}];'
        )
        base_stream = f'text{i}'
    
    # 最终输出流 - 确保总时长
    filter_complex_parts.append(f'[{base_stream}]trim=duration={duration}[v_out];')
    
    # 音频处理 - 修正部分
    if audio_stream:
        # 将音频流添加到滤镜链中
        filter_complex_parts.append(audio_stream)
    else:
        # 如果没有音频，创建指定时长的静音音频
        filter_complex_parts.append(f'aevalsrc=0::d={duration}[a_out]')
    
    # 合并滤镜链
    filter_complex = ''.join(filter_complex_parts)
    
    # 确保输出路径是文件而不是目录
    if os.path.isdir(output_path):
        output_path = os.path.join(output_path, f"{clip_config['id']}-{REVERSE_LEVEL_LABELS.get(clip_config['level_index'])}.mp4")
    
    # 构建FFmpeg命令
    cmd = [
        'ffmpeg',
        '-y',
        *input_args,
        '-hide_banner',
        '-filter_complex', filter_complex,
        '-map', '[v_out]',
        '-map', '[a_out]',
        '-vcodec', 'h264_nvenc',
        '-preset', 'p6',           # 高压缩率
        '-cq', '28',
        '-r', '60',
        '-threads', '0',
        '-thread_type', 'frame',
        '-b:v', f'{bitrate}k',
        '-maxrate', f'{int(bitrate)*2}k',
        '-bufsize', f'{int(bitrate)*4}k', # 缓冲区大小设置为四倍码率
        '-pix_fmt', 'yuv420p',
        '-acodec', 'aac',
        '-b:a', '320k',
        '-max_muxing_queue_size', '4096',
        # 双重时长保险
        '-t', str(duration),
        output_path
    ]
    
    print(f"正在为您生成【{clip_config['song_name']} - {REVERSE_LEVEL_LABELS.get(clip_config['level_index'])}】的片段")
    # print(f"视频剪辑参数: 从 {start_time}秒 开始，持续 {duration} 秒")
    print("执行FFmpeg命令:")
    print(" ".join(cmd))

    # 执行命令
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"已生成您的视频片段，名称为: {output_path}")
        print(f"片段生成用时 {format_time_difference(time.time() - start_time_generation)}")
        return VideoFileClip(output_path)
    except subprocess.CalledProcessError as e:
        error_cmd = " ".join(cmd)
        print("========================== FFmpeg 生成失败！====================================")
        print(f"视频生成命令：\n{str(error_cmd)}\n")
        print(f"生成输出日志: \n{e.stderr}")
        print("============================ 这里是结尾 ========================================")
        print("因为您的视频片段使用此模式生成时出现了问题，我们将使用快速模式重新生成；")
        print(" -> 生成器不会检查您的视频片段文件完整性，别忘了将您生成失败的片段删除掉；")
        print(" -> 如果您仍要使用极速模式生成，请等待您报告的问题解决后，重新启动生成器。\n")
        return create_video_segment_classic(clip_config, resolution, font_path)

def create_video_segment_classic(clip_config, resolution, font_path, text_size=None):
    """优化后的视频片段创建函数"""
    # print(f"正在合成视频片段: {clip_config['id']}")
    print(f"正在为您生成【{clip_config['song_name']} - {REVERSE_LEVEL_LABELS.get(clip_config['level_index'])}】的片段")
    # 使用缓存获取缩放和位置信息
    scale_factor, video_height, calculated_text_size = get_cached_scaling(resolution)
    
    # 根据上级函数计算新的位置参数
    video_pos = (int(0.0422 * resolution[0]), int(0.0583 * resolution[1]))
    text_x = int(0.7594 * resolution[0])
    text_first_y = int(0.227 * resolution[1])
    
    # 使用计算出的文字大小（如果未提供）
    if text_size is None:
        text_size = calculated_text_size
    
    # 1. 背景层
    bg_video = VideoFileClip("./images/BgClips/bg_xverse.mp4")
    bg_video = bg_video.with_effects([
        vfx.Loop(duration=clip_config['duration']), 
        vfx.Resize(resolution)
    ])
    
    # 2. 主图片层 - 使用更高效的加载方式
    if 'main_image' in clip_config and os.path.exists(clip_config['main_image']):
        # 直接使用 FFmpeg 加载图片，避免 PIL 开销
        main_image = ImageClip(clip_config['main_image']).with_duration(clip_config['duration'])
        main_image = main_image.with_effects([vfx.Resize(resolution)])
    else:
        print(f"警告: {clip_config['id']} 缺少主图片")
        # 创建纯色背景而不是加载图片
        main_image = ColorClip(size=resolution, color=(0, 0, 0)).with_duration(clip_config['duration'])
    
    # 3. 视频片段层 - 优化加载和裁剪
    if 'video' in clip_config and os.path.exists(clip_config['video']):
        # 使用更高效的子剪辑方法
        try:
            # 直接使用FFmpeg提取所需片段，避免完全加载整个视频
            video_clip = VideoFileClip(clip_config['video']).subclipped(
                clip_config['start'], clip_config['end']
            )
            video_clip = video_clip.with_effects([vfx.Resize(height=video_height)])
        except Exception as e:
            print(f"视频处理错误: {e}")
            # 创建备用视频片段
            blank_size = int(540 * scale_factor)
            video_clip = ColorClip(size=(blank_size, blank_size), color=(0, 0, 0))
            video_clip = video_clip.with_duration(clip_config['duration'])
    else:
        print(f"警告: {clip_config['id']} 缺少视频文件")
        blank_size = int(540 * scale_factor)
        video_clip = ColorClip(size=(blank_size, blank_size), color=(0, 0, 0))
        video_clip = video_clip.with_duration(clip_config['duration'])
    
    # 4. 文字层 - 根据上级函数调整文本布局
    text_list = get_splited_text(clip_config['text'], text_max_bytes=18)  # 改为18字节
    
    # 创建多个文本层，每行单独定位
    text_clips = []
    for i, line in enumerate(text_list):
        y_offset = text_first_y + i * (text_size + 10)
        try:
            txt_clip = TextClip(
                text=line,
                font=font_path,
                font_size=text_size,
                color="black",  # 改为黑色
                method="pango" if hasattr(TextClip, 'PANGO') else "label",
            ).with_duration(clip_config['duration'])
            
            text_clips.append(txt_clip.with_position((text_x, y_offset)))
        except:
            # 回退到原始方法
            txt_clip = TextClip(
                font=font_path,
                text=line,
                method="label",
                font_size=text_size,
                color="black",  # 改为黑色
                duration=clip_config['duration']
            )
            text_clips.append(txt_clip.with_position((text_x, y_offset)))
    
    # 5. 优化合成过程
    # 使用更高效的图层合成顺序
    all_clips = [
        bg_video.with_position((0, 0)),
        main_image.with_position((0, 0)),
        video_clip.with_position(video_pos)
    ]
    all_clips.extend(text_clips)
    
    composite_clip = CompositeVideoClip(all_clips, size=resolution, use_bgclip=True)
    
    return composite_clip.with_duration(clip_config['duration'])


def add_clip_with_transition(clips, new_clip, set_start=False, trans_time=1):
    """
    添加新片段到片段列表中，并处理转场效果
    
    Args:
        clips (list): 现有片段列表
        new_clip: 要添加的新片段
        trans_time (float): 转场时长
        set_start (bool): 是否设置开始时间（用于主要视频片段）
    """
    if len(clips) == 0:
        clips.append(new_clip)
        return
    
    # 对主要视频片段设置开始时间
    if set_start:
        new_clip = new_clip.with_start(clips[-1].end - trans_time)

    # 为前一个片段添加渐出效果
    clips[-1] = clips[-1].with_effects([
            vfx.CrossFadeOut(duration=trans_time),
            afx.AudioFadeOut(duration=trans_time)
        ])

    # 为新片段添加渐入效果
    new_clip = new_clip.with_effects([
            vfx.CrossFadeIn(duration=trans_time),
            afx.AudioFadeIn(duration=trans_time)
        ])
    
    clips.append(new_clip)


def create_full_video(resources, resolution, font_path, bitrate, auto_add_transition=True, trans_time=1, full_last_clip=False):
    clips = []
    ending_clips = []

    # 处理开场片段
    if 'intro' in resources:
        for clip_config in resources['intro']:
            clip = create_info_segment(clip_config, resolution, font_path)
            clip = normalize_audio_volume(clip)
            add_clip_with_transition(clips, clip, set_start=True, trans_time=trans_time)

    combined_start_time = 0
    if not 'main' in resources:
        print("Error: 没有找到主视频片段的合成！请检查配置文件！")
        return
    
    # 处理主要视频片段
    for clip_config in resources['main']:
        # 判断是否是最后一个片段
        if clip_config['id'] == resources['main'][-1]['id'] and full_last_clip:
            start_time = clip_config['start']
            # 获取原始视频的长度（不是配置文件中配置的duration）
            full_clip_duration = VideoFileClip(clip_config['video']).duration - 5
            # 修改配置文件中的duration，因此下面创建视频片段时，会使用加长版duration
            clip_config['duration'] = full_clip_duration - start_time
            clip_config['end'] = full_clip_duration

            clip = create_video_segment(clip_config, resolution, font_path, bitrate=bitrate)  
            clip = normalize_audio_volume(clip)

            combined_start_time = clips[-1].end - trans_time
            ending_clips.append(clip)     
        else:
            clip = create_video_segment(clip_config, resolution, font_path, bitrate=bitrate)  
            clip = normalize_audio_volume(clip)

            add_clip_with_transition(clips, clip, set_start=True, trans_time=trans_time)

    # 处理结尾片段
    if 'ending' in resources:
        for clip_config in resources['ending']:
            clip = create_info_segment(clip_config, resolution, font_path)
            clip = normalize_audio_volume(clip)
            if full_last_clip:
                ending_clips.append(clip)
            else:
                add_clip_with_transition(clips, clip, 
                                        set_start=True, 
                                        trans_time=trans_time)

    if full_last_clip and len(ending_clips) > 0:
        clips.append(get_combined_ending_clip(ending_clips, combined_start_time, trans_time))

    if auto_add_transition:
        return CompositeVideoClip(clips)
    else:
        return concatenate_videoclips(clips)  # 该方法不会添加转场效果，即使设置了trans_time


# def sort_video_files(files):
#     """
#     对视频文件按照文件名开头的数字索引进行排序
#     例如: "0_xxx.mp4", "1_xxx.mp4", "2_xxx.mp4" 等
#     """
#     def get_sort_key(filename):
#         try:
#             # 获取文件名（不含扩展名）中第一个下划线前的数字
#             number = int(os.path.splitext(filename)[0].split('_')[0])
#             return number
#         except (ValueError, IndexError):
#             print(f"Error: 无法从文件名解析索引: {filename}")
#             return float('inf')  # 将无效文件排到最后
    
#     # 直接按照数字索引排序
#     return sorted(files, key=get_sort_key)

def sort_video_files(files):
    """
    对视频文件按照文件名开头的数字索引进行排序，
    遇到第一个非数字开头的文件时停止（如 final_output.mp4）
    """
    sorted_files = []
    
    for filename in files:
        try:
            # 获取文件名中第一个下划线前的数字
            number = int(os.path.splitext(filename)[0].split('_')[0])
            sorted_files.append((number, filename))
        except (ValueError, IndexError):
            # 遇到非数字开头的文件（如 final_output.mp4），直接停止收集
            break
    
    # 按数字排序后返回文件名（不带数字）
    return [filename for _, filename in sorted(sorted_files, key=lambda x: x[0])]


def combine_full_video_from_existing_clips(video_clip_path, resolution, trans_time=1):
    clips = []

    video_files = [f for f in os.listdir(video_clip_path) if f.endswith(".mp4")]
    sorted_files = sort_video_files(video_files)
    
    print(f"Sorted files: {sorted_files}")

    if not sorted_files:
        raise ValueError("Error: 没有有效的视频片段文件！(Best_1-30)")

    for file in sorted_files:
        clip = VideoFileClip(os.path.join(video_clip_path, file))
        clip = normalize_audio_volume(clip)
        
        if len(clips) == 0:
            clips.append(clip)
        else:
            # 为前一个片段添加音频渐出效果
            clips[-1] = clips[-1].with_audio_fadeout(trans_time)
            # 为当前片段添加音频渐入效果和视频渐入效果
            current_clip = clip.with_audio_fadein(trans_time).with_crossfadein(trans_time)
            # 设置片段开始时间
            clips.append(current_clip.with_start(clips[-1].end - trans_time))

    final_video = CompositeVideoClip(clips, size=resolution)
    return final_video


def gene_pure_black_video(duration, resolution):
    """
    生成一个纯黑色的视频
    """
    black_frame = create_blank_image(resolution[0], resolution[1], color=(0, 0, 0, 1))
    clip = ImageClip(black_frame).with_duration(duration)
    clip.write_videofile("./videos/black_bg.mp4", fps=60)


def get_combined_ending_clip(ending_clips, combined_start_time, trans_time):
    """合并 Best1 片段与结尾，使用统一音频"""

    if len(ending_clips) < 2:
        print("Warning: 没有足够的结尾片段，将只保留 Best#1")
        return ending_clips[0].with_start(combined_start_time).with_effects([
            vfx.CrossFadeIn(duration=trans_time),
            afx.AudioFadeIn(duration=trans_time),
            vfx.CrossFadeOut(duration=trans_time),
            afx.AudioFadeOut(duration=trans_time)
        ])
    
    # 获得b1片段
    b1_clip = ending_clips[0]
    # 获得结尾片段组
    ending_comment_clips = ending_clips[1:]

    # 取出b1片段的音频
    combined_clip_audio = b1_clip.audio
    b1_clip = b1_clip.without_audio()

    # 计算需要从b1片段结尾截取的时间
    ending_full_duration = sum([clip.duration for clip in ending_comment_clips])

    if ending_full_duration > b1_clip.duration:
        print(f"警告: Best#1 长度不足，FULL_LAST_CLIP 将被忽略。")
        return CompositeVideoClip(ending_clips).with_start(combined_start_time).with_effects([
            vfx.CrossFadeIn(duration=trans_time),
            afx.AudioFadeIn(duration=trans_time),
            vfx.CrossFadeOut(duration=trans_time),
            afx.AudioFadeOut(duration=trans_time)
        ])

    # 将ending_clip的时间提前到b1片段的结尾，并裁剪b1片段
    b1_clip = b1_clip.subclipped(start_time=b1_clip.start, end_time=b1_clip.end - ending_full_duration)
    # 裁剪ending_comment_clips
    for i in range(len(ending_comment_clips)):
        if i == 0:
            ending_comment_clips[i] = ending_comment_clips[i].with_start(b1_clip.end)
        else:
            ending_comment_clips[i] = ending_comment_clips[i].with_start(ending_comment_clips[i-1].end)

    full_list = [b1_clip] + ending_comment_clips
    # for clip in full_list:
    #     print(f"Combined Ending Clip: clip的开始时间：{clip.start}, 结束时间：{clip.end}")

    # 将b1片段与ending_clip合并
    combined_clip = CompositeVideoClip(full_list)
    print(f"[信息]视频生成器: Best#1 音频长度: {combined_clip_audio.duration}, 拼接长度: {combined_clip.duration}")
    # 设置combined_clip的音频为原b1片段的音频（二者长度应该相同）
    combined_clip = combined_clip.with_audio(combined_clip_audio)
    # 设置combined_clip的开始时间
    combined_clip = combined_clip.with_start(combined_start_time)
    # 设置结尾淡出到黑屏
    combined_clip = combined_clip.with_effects([
        vfx.CrossFadeIn(duration=trans_time),
        afx.AudioFadeIn(duration=trans_time),
        vfx.CrossFadeOut(duration=trans_time),
        afx.AudioFadeOut(duration=trans_time)
    ])
    
    return combined_clip


# def render_all_video_clips(resources, video_output_path, resolution, v_bitrate_kbps, font_path,
#                            auto_add_transition=True, trans_time=1, force_render=False):
#     vfile_prefix = 0

#     def modify_and_rend_clip(clip, config, prefix, auto_add_transition, trans_time):
#         output_file = os.path.join(video_output_path, f"{prefix}_{config['id']}.mp4")
        
#         # 检查文件是否已经存在
#         if os.path.exists(output_file) and not force_render:
#             print(f"文件 {output_file} 跳过渲染。勾选 “强制覆盖” 以强制渲染")
#             clip.close()
#             del clip
#             return
        
#         clip = normalize_audio_volume(clip)
#         # 如果启用了自动添加转场效果，则在头尾加入淡入淡出
#         if auto_add_transition:
#             clip = clip.with_effects([
#                 vfx.FadeIn(duration=trans_time),
#                 vfx.FadeOut(duration=trans_time),
#                 afx.AudioFadeIn(duration=trans_time),
#                 afx.AudioFadeOut(duration=trans_time)
#             ])
#         # 直接渲染clip为视频文件
#         print(f"正在合成视频片段: {prefix}_{config['id']}.mp4")
#         clip.write_videofile(output_file, fps=60, threads=8, preset='fast', bitrate=v_bitrate_kbps)
#         clip.close()
#         # 强制垃圾回收
#         del clip

#     if not 'main' in resources:
#         print("Error: 没有找到主视频片段的配置！请检查配置文件！")
#         return

#     if 'intro' in resources:
#         for clip_config in resources['intro']:
#             clip = create_info_segment(clip_config, resolution, font_path)
#             clip = modify_and_rend_clip(clip, clip_config, vfile_prefix, auto_add_transition, trans_time)
#             vfile_prefix += 1

#     for clip_config in resources['main']:
#         clip = create_video_segment(clip_config, resolution, font_path)
#         clip = modify_and_rend_clip(clip, clip_config, vfile_prefix, auto_add_transition, trans_time)

#         vfile_prefix += 1

#     if 'ending' in resources:
#         for clip_config in resources['ending']:
#             clip = create_info_segment(clip_config, resolution, font_path)
#             clip = modify_and_rend_clip(clip, clip_config, vfile_prefix, auto_add_transition, trans_time)
#             vfile_prefix += 1

def check_rendered_clips_multithreaded(
    video_configs: Dict[str, List[Dict[str, Any]]],
    output_dir: str,
    force_render: bool = False,
    max_workers: int = 4
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    多线程检测已渲染的视频片段（统一按顺序编号：intro -> main -> ending, 从0开始）
    返回 (to_render_list, existing_list)
    """
    task_queue = Queue()
    result_queue = Queue()

    vfile_prefix = 0
    all_configs = []

    # 按顺序将所有片段加入任务队列（保证 prefix 一致）
    if 'intro' in video_configs:
        for config in video_configs['intro']:
            task_queue.put((vfile_prefix, config))
            all_configs.append((vfile_prefix, config))
            vfile_prefix += 1

    if 'main' in video_configs:
        for config in video_configs['main']:
            task_queue.put((vfile_prefix, config))
            all_configs.append((vfile_prefix, config))
            vfile_prefix += 1

    if 'ending' in video_configs:
        for config in video_configs['ending']:
            task_queue.put((vfile_prefix, config))
            all_configs.append((vfile_prefix, config))
            vfile_prefix += 1

    # worker 检查文件是否存在并把结果放入 result_queue
    def check_worker():
        while True:
            try:
                prefix, config = task_queue.get_nowait()
            except Empty:
                break

            output_file = os.path.join(output_dir, f"{prefix}_{config['id']}.mp4")
            exists = os.path.exists(output_file) and not force_render
            result_queue.put((prefix, config, exists))
            task_queue.task_done()

    # 启动线程
    threads = []
    for _ in range(min(max_workers, max(1, task_queue.qsize()))):
        t = threading.Thread(target=check_worker)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    # 收集结果
    to_render = []
    existing = []
    while not result_queue.empty():
        prefix, config, exists = result_queue.get()
        if exists:
            existing.append(config)
            # print(f"检测到已存在片段: {prefix}_{config['id']}.mp4")
        else:
            to_render.append(config)

    # （可选）调试输出：预期文件 vs 实际存在文件
    # existing_files = sorted([f for f in os.listdir(output_dir) if f.endswith('.mp4')])
    # expected_files = sorted([f"{p}_{c['id']}.mp4" for p,c in all_configs])
    # print("existing_files:", existing_files)
    # print("expected_files:", expected_files)

    return to_render, existing

# def render_all_video_clips(
#     resources, 
#     video_output_path, 
#     resolution: tuple, 
#     v_bitrate_kbps, 
#     font_path,
#     auto_add_transition=True, 
#     trans_time=1, 
#     force_render=False
# ):
#     # 第一步: 多线程检测已渲染片段
#     to_render, existing = check_rendered_clips_multithreaded(
#         resources,
#         video_output_path,
#         force_render,
#         max_workers=4
#     )
    
#     print(f"需要渲染 {len(to_render)} 个新片段，跳过 {len(existing)} 个已存在片段")
    
#     # 第二步: 只渲染需要的新片段(单线程)
#     vfile_prefix = 0
#     if not 'main' in resources:
#         print("Error: 没有找到主视频片段的配置！请检查配置文件！")
#         return

#     # 重构渲染逻辑，只处理to_render中的配置
#     def render_selected_clips(clip_configs, segment_type):
#         nonlocal vfile_prefix
#         for config in clip_configs:
#             current_prefix = vfile_prefix  # 与检测使用相同的编号规则

#             if config in to_render:  # 仅渲染需要的
#                 if segment_type == 'info':
#                     clip = create_info_segment(config, resolution, font_path)
#                 else:
#                     clip = create_video_segment(config, resolution, font_path)

#                 output_file = os.path.join(video_output_path, f"{current_prefix}_{config['id']}.mp4")
#                 print(f"正在合成视频片段: {current_prefix}_{config['id']}.mp4")

#                 clip = normalize_audio_volume(clip)
#                 if auto_add_transition:
#                     clip = clip.with_effects([
#                         vfx.FadeIn(duration=trans_time),
#                         vfx.FadeOut(duration=trans_time),
#                         afx.AudioFadeIn(duration=trans_time),
#                         afx.AudioFadeOut(duration=trans_time)
#                     ])

#                 clip.write_videofile(output_file, fps=60, threads=8, preset='fast', codec='h264_nvenc', bitrate=v_bitrate_kbps)
#                 clip.close()
#                 del clip

#             # 无论是否渲染，prefix 都要前进，保持与检测端一致的编号位置
#             vfile_prefix += 1

def render_all_video_clips(
    resources, 
    video_output_path, 
    resolution: tuple, 
    v_bitrate_kbps, 
    font_path,
    auto_add_transition=True, 
    trans_time=1, 
    force_render=False,
    classic_fast_render=False
):
    # 1. 检查已有片段
    to_render, existing = check_rendered_clips_multithreaded(
        resources,
        video_output_path,
        force_render,
        max_workers=4
    )
    
    print(f"需要渲染 {len(to_render)} 个新片段，跳过 {len(existing)} 个已存在片段")
    
    vfile_prefix = 0
    if "main" not in resources:
        print("错误: 没有找到主视频片段的配置！请检查配置文件！")
        return

    # 2. 渲染函数
    def render_selected_clips(clip_configs, segment_type):
        nonlocal vfile_prefix
        for config in clip_configs:
            current_prefix = vfile_prefix
            output_file = os.path.join(video_output_path, f"{current_prefix}_{config['id']}.mp4")

            if config in to_render:  # 仅渲染需要的
                if segment_type == "info":
                    print(f"开始处理头尾: {current_prefix}_{config['id']}.mp4")
                    clip = create_info_segment(config, resolution, font_path)
                else:
                    if classic_fast_render == True:
                        print(f"开始处理[快速]: {current_prefix}_{config['id']}({config['song_name']}).mp4")
                        clip = create_video_segment_classic(config, resolution, font_path)
                    else:
                        print(f"开始处理[FFmpeg]: {current_prefix}_{config['id']}({config['song_name']}).mp4")
                        clip = create_video_segment(config, resolution, font_path, bitrate=v_bitrate_kbps)
                # print(f"正在处理视频片段: {current_prefix}_{config['id']}.mp4")

                clip = normalize_audio_volume(clip)
                if auto_add_transition:
                    clip = clip.with_effects([
                        vfx.FadeIn(duration=trans_time),
                        vfx.FadeOut(duration=trans_time),
                        afx.AudioFadeIn(duration=trans_time),
                        afx.AudioFadeOut(duration=trans_time)
                    ])

                # 用 GPU 编码器导出（避免 CPU 瓶颈）
                clip.write_videofile(
                    output_file,
                    fps=60,
                    threads=8,
                    codec="h264_nvenc",          # GPU H.264
                    preset="fast",
                    bitrate=f'{v_bitrate_kbps}k'
                )
                clip.close()
                del clip

            vfile_prefix += 1  # 保持编号一致

    # 渲染各个部分
    if 'intro' in resources:
        render_selected_clips(resources['intro'], 'info')

    render_selected_clips(resources['main'], 'video')

    if 'ending' in resources:
        render_selected_clips(resources['ending'], 'info')


def combine_full_video_direct(
    video_clip_path, username,
    video_res, video_bitrate,
    use_overprocess=False,
    classic_fast_render=False
    ):
    print("[Info] ==================== 开始拼接视频 ==================")
    video_files = [f for f in os.listdir(video_clip_path) if f.endswith(".mp4")]
    sorted_files = sort_video_files(video_files)
    
    if not sorted_files:
        raise ValueError("Error: 没有有效的视频片段文件！")

    # 创建临时目录存放 ts 文件
    # temp_dir = os.path.join(video_clip_path, "temp_ts")
    # os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # 1. 创建MP4文件列表
        mp4_list_file = os.path.join(video_clip_path, "mp4_files.txt")
        with open(mp4_list_file, 'w', encoding='utf-8') as f:
            for file in sorted_files:
                # 使用正斜杠替换反斜杠，并使用相对路径
                full_path = os.path.abspath(os.path.join(video_clip_path, file)).replace('\\', '/')
                f.write(f"file '{full_path}'\n")

        # 2. 创建TS文件列表并转换视频
        # ts_list_file = os.path.join(video_clip_path, "ts_files.txt")
        # with open(ts_list_file, 'w', encoding='utf-8') as f:
        #     for i, file in enumerate(sorted_files):
        #         ts_name = f"{i:04d}.ts"
        #         ts_path = os.path.join(temp_dir, ts_name)
                
        #         # 转换MP4为TS
        #         cmd = [
        #             'ffmpeg', '-y', '-loglevel', 'info',
        #             '-init_hw_device', 'cuda=cu:0', # 指定初始化 GPU 设备
        #             '-filter_hw_device', 'cu',  # 指定滤镜渲染 GPU 设备
        #             '-hwaccel', 'cuda',  # 启用硬件加速
        #             '-i', os.path.join(video_clip_path, file),
        #             '-c', 'copy',
        #             '-bsf:v', 'h264_mp4toannexb',
        #             '-f', 'mpegts',
        #             '-threads', '0',
        #             ts_path
        #         ]
        #         subprocess.run(cmd, check=True)
                
        #         # 写入TS文件相对路径，使用正斜杠
        #         # relative_ts_path = os.path.join('temp_ts', ts_name).replace('\\', '/')
        #         # f.write(f"file '{relative_ts_path}'\n")

        #         # 写入TS文件绝对路径，使用正斜杠
        #         absolute_ts_path = os.path.abspath(os.path.join(video_clip_path, 'temp_ts', ts_name)) 
        #         f.write(f"file '{absolute_ts_path}'\n")

        # 3. 拼接TS文件并输出为MP4
        if classic_fast_render == True:
            output_path = os.path.join(video_clip_path, f"{username}_Best30_fast.mp4")
        else:
            output_path = os.path.join(video_clip_path, f"{username}_Best30_ffmpeg.mp4")
        
        # 执行拼接命令
        real_path = os.path.abspath(video_clip_path)
        # current_dir = os.getcwd()
        # os.chdir(video_clip_path)
        
        cmd = [
            'ffmpeg', '-y',
            '-hide_banner',
            '-loglevel', 'info',
            '-f', 'concat',
            '-safe', '0',
            # '-i', f'{real_path}\\ts_files.txt',  # 使用绝对路径
            '-i', f'{real_path}\\mp4_files.txt',  # 使用绝对路径
            # 关键修复：时间戳处理
            '-fflags', '+genpts',            # 生成时间戳
            '-avoid_negative_ts', 'make_zero', # 避免负时间戳
            
            # 编码参数（确保可seek）
            '-max_interleave_delta', '0',   # 减少交错延迟
            
            '-c', 'copy',
            output_path,  # 使用绝对路径
            '-threads', '0',
        ]
        subprocess.run(cmd, check=True)

        if use_overprocess:
            # 后处理
            cmd2 = [
                'ffmpeg',
                '-y', '-hide_banner',
                '-loglevel', 'info',
                '-i', f'{real_path}\\{username}_Best30_fast.mp4',
                
                # 时间戳修复（关键）
                '-fflags', '+genpts',
                '-vsync', 'cfr',
                '-video_track_timescale', '90000',
                
                # 编码参数（通用版）
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-init_hw_device', 'cuda=cu:0', # 指定初始化 GPU 设备
                '-filter_hw_device', 'cu',  # 指定滤镜渲染 GPU 设备
                '-hwaccel', 'cuda',  # 启用硬件加速
                '-g', '30',
                '-keyint_min', '30',
                '-sc_threshold', '0',

                # 替代x264-params的方案
                # '-flags', '+cgop',      # 强制闭合GOP（类似force-cfr效果）
                # '-force_key_frames', 'expr:gte(n,n_forced*30)',  # 每30帧关键帧
                
                # 分辨率/码率
                '-vf', f'scale={video_res[0]}:{video_res[1]}',
                '-b:v', f'{video_bitrate}k',
                
                # 输出
                '-movflags', '+faststart',
                '-threads', '8',
                f'{real_path}\\{username}_Best30_processed.mp4'
            ]
            subprocess.run(cmd2, check=True)

        print("[Info] ==================== 视频拼接完成 ==================")
    
    except Exception as e:
        print(f"拼接失败：{str(e)}")
    # finally:
    #     # 清理临时文件
    #     if os.path.exists(temp_dir):
    #         for file in os.listdir(temp_dir):
    #             os.remove(os.path.join(temp_dir, file))
    #         os.rmdir(temp_dir)

    return output_path

def combine_full_video_ffmpeg_concat_gl(video_clip_path, resolution, trans_name="fade", trans_time=1):
    video_files = [f for f in os.listdir(video_clip_path) if f.endswith(".mp4")]
    sorted_files = sort_video_files(video_files)
    
    if not sorted_files:
        raise ValueError("Error: 没有有效的视频片段文件！")
    
    output_path = os.path.join(video_clip_path, "final_output.mp4")
    
    # 创建MP4文件列表
    mp4_list_file = os.path.join(video_clip_path, "mp4_files.txt")
    with open(mp4_list_file, 'w', encoding='utf-8') as f:
        for file in sorted_files:
            # 使用正斜杠替换反斜杠，并使用相对路径
            full_path = os.path.join(video_clip_path, file).replace('\\', '/')
            f.write(f"file '{full_path}'\n")


    # 使用nodejs脚本拼接视频
    node_script_path = os.path.join(os.path.dirname(__file__), "external_scripts", "concat_videos_ffmpeg.js")

    cmd = f'node {node_script_path} -o {output_path} -v {mp4_list_file} -t {trans_name} -d {int(trans_time * 1000)}'
    print(f"执行命令: {cmd}")

    os.system(cmd)

    return output_path