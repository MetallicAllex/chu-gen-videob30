from PIL import Image
import numpy as np
from datetime import datetime
from queue import Queue, Empty
import os, threading, subprocess, time
from typing import Any, Dict, List, Tuple
from utils.DataUtils import sort_video_files
from utils.PageUtils import format_time_difference
from utils.ImageUtils import create_blank_image, get_splited_text
from utils.Variables import HARD_RENDER_METHOD, bgclips_path, image_root_path, audios_path, REVERSE_LEVEL_LABELS
from moviepy import ColorClip, VideoFileClip, ImageClip, TextClip, AudioFileClip, CompositeVideoClip, vfx, afx

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

def create_info_segment(clip_config, resolution, font_path, text_size=32, inline_max_len=75, max_lines_per_page=12):
    # 基础设置
    scale_factor = resolution[1] / 1080
    text_scale = int(text_size * scale_factor)
    
    # 检查必要字段
    if 'duration' not in clip_config:
        raise ValueError(f"缺少 duration 字段: {clip_config}")
    
    if 'text' not in clip_config or not clip_config['text']:
        # 如果没有文本，使用默认文本
        clip_config['text'] = "【无文本内容】"
        print(f"警告: 片段 {clip_config.get('id', 'unknown')} 没有填写内容，将填充占位符")
        print("如果您反复填写保存无效果，请尝试手动编辑配置文件中的 intro 和 outro 部分。")
    
    # 创建统一的背景（整个片段共用）
    bg_image = ImageClip(f"{image_root_path}/Base/intro/IntroBase.png").with_duration(clip_config['duration'])
    bg_image = bg_image.with_effects([vfx.Resize(width=resolution[0])])

    bg_video = VideoFileClip(f"{bgclips_path}/bg.mp4")
    bg_video = bg_video.with_effects([
        vfx.Loop(duration=clip_config['duration']), 
        vfx.MultiplyColor(0.5),
        vfx.Resize(width=resolution[0]),
        vfx.LumContrast(lum=0.5)
    ])

    # 文本分页处理
    text_list = get_splited_text(clip_config['text'], text_max_bytes=inline_max_len)
    
    # 如果文本列表为空，添加一个占位符
    if not text_list or clip_config["bg_page"] == True:
        text_list = ["【无文本内容或背景页】"]
    
    # 分页逻辑
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
    
    # 底部文字
    addtional_text = "【本视频由 chu-gen-videob30 生成，版本 v1.1-fix3】"
    addtional_txt_clip = TextClip(
        font=font_path, text=addtional_text,
        method="label", font_size=20,
        vertical_align="bottom", color="white",
        duration=clip_config['duration']
    )
    
    text_pos = (int(0.15 * resolution[0]), int(0.17 * resolution[1]))
    addtional_text_pos = (int(0.2 * resolution[0]), int(0.89 * resolution[1]))
    
    # 单页情况
    if len(pages) <= 1:
        txt_clip = TextClip(
            font=font_path, text="\n".join(pages[0]),
            method="label", font_size=text_scale,
            margin=(20, 5), interline=6.5,
            vertical_align="top", color="black" if clip_config["bg_page"] == False else "#FFFFFF00",
        #     duration=clip_config['duration'], transparent=False if clip_config["bg_page"] == True else True
            duration=clip_config['duration']
        )
        
        composite_clip = CompositeVideoClip([
            bg_video.with_position((0, 0)),
            bg_image.with_position((0, 0)),
            txt_clip.with_position((text_pos[0], text_pos[1])),
            addtional_txt_clip.with_position((addtional_text_pos[0], addtional_text_pos[1]))
        ], size=resolution, use_bgclip=True)
    
    # 多页情况 - 简单切换版本：无过渡效果，直接切换
    else:
        page_duration = clip_config['duration'] / len(pages)
        
        # 创建所有文字片段，分别控制显示时间
        text_clips = []
        
        for i, page_lines in enumerate(pages):
            # 添加页码指示
            page_text = "\n".join(page_lines)
            #  + f"\n\n第 {i+1}/{len(pages)} 页"
            # 计算当前页的开始时间
            start_time = i * page_duration
            
            # 创建文字Clip，设置实际显示时长
            txt_clip = TextClip(
                font=font_path, text=page_text,
                method="label", font_size=text_scale,
                margin=(20, 5), interline=6.5,
                vertical_align="top", color="black" if clip_config["bg_page"] == False else "white",  # 固定黑色，不变色
                duration=page_duration
            ).with_start(start_time)  # 设置开始时间
            
            text_clips.append(txt_clip.with_position((text_pos[0], text_pos[1])))
        
        # 创建单个复合片段
        composite_clip = CompositeVideoClip([
            bg_video.with_position((0, 0)),
            bg_image.with_position((0, 0)),
            addtional_txt_clip.with_position((addtional_text_pos[0], addtional_text_pos[1]))
        ] + text_clips, 
        size=resolution, use_bgclip=True)
        
    # 添加音频
    bg_audio = AudioFileClip(f"{audios_path}/bgm.mp3")
    bg_audio = bg_audio.with_effects([afx.AudioLoop(duration=clip_config['duration'])])
    composite_clip = composite_clip.with_audio(bg_audio)
    
    return composite_clip.with_duration(clip_config['duration'])

def create_video_segment(clip_config, resolution, font_path, bitrate, encoder_param, output_path='./videos/temp_generated'):
    """FFmpeg 渲染模式（分页显示评论修复）
    Args:
        clip_config(JSON): 视频配置数据
        resolution(tuple[int, int]): 输出分辨率
        font_path(str): （调用）评论文字路径
        bitrate(int): 输出码率
        encoder_param(dict[str, int | str | None]): 编码器参数
        output_path(str): 输出路径

    Raises:
        subprocess.CalledProcessError: 输出失败，跳回标准渲染
    
    Returns:
        VideoFileClip: 生成的视频文件
    """
    start_time_generation = time.time()
    
    # 坐标计算
    inner_box_left = int(135 * resolution[0] / 1920)
    inner_box_top = int(83 * resolution[1] / 1080)
    inner_box_height = int(668 * resolution[1] / 1080)
    scale_factor = resolution[1] / 1080
    text_size = int(32 * scale_factor)
    
    video_pos = (int(0.0641  * resolution[0]), int(0.075 * resolution[1]))
    text_x = int(0.7594 * resolution[0])
    text_first_y = int(0.224 * resolution[1])
    
    text = clip_config['text']
    duration = clip_config['duration']
    start_time = clip_config['start']
    
    # 文件路径
    bg_video_path = os.path.abspath(f"{bgclips_path}/bg.mp4").replace('\\', '/')
    main_image_path = os.path.abspath(clip_config.get('main_image', '')).replace('\\', '/') if clip_config.get('main_image') else ''
    video_path = os.path.abspath(clip_config.get('video', '')).replace('\\', '/') if clip_config.get('video') else ''
    
    input_args = []
    filter_complex_parts = []
    
    # # 硬件加速（经多方测试后停用）
    # if use_hardware_acceleration and acceleration_method in HARD_RENDER_METHOD:
    #     try:
    #         method_config = HARD_RENDER_METHOD[acceleration_method]
    #         hwaccel = method_config.get("hwaccel")
    #         if hwaccel and hwaccel != HARD_RENDER_METHOD["AMD"]:
    #             input_args.extend(['-hwaccel', hwaccel])
    #     except Exception as e:
    #         print(f"硬件加速配置出错: {e}")
    
    # 输入1: 背景视频
    input_args.extend(['-i', bg_video_path])
    
    # 基础背景处理
    # if main_image_path and os.path.exists(main_image_path):
    #     input_args.extend(['-i', main_image_path])
    #     filter_complex_parts.append(f'[1:v]scale={resolution[0]}:{resolution[1]}[img];')
    #     filter_complex_parts.append('[0:v][img]overlay=0:0[bg_img];')
    #     base_stream = 'bg_img'
    # else:
    #     filter_complex_parts.append(f'[0:v]loop=loop=-1:size=1000:start=0,trim=duration={duration},scale={resolution[0]}:{resolution[1]}[bg_img];')
    #     base_stream = 'bg_img'
    
    # 基础背景处理
    if main_image_path and os.path.exists(main_image_path):
        input_args.extend(['-i', main_image_path])
        filter_complex_parts.append(f'[1:v]scale={resolution[0]}:{resolution[1]}[img];')
        # 背景视频：循环、裁剪、缩放、调整亮度
        filter_complex_parts.append(f'[0:v]loop=loop=-1:size=1000:start=0,trim=duration={duration},scale={resolution[0]}:{resolution[1]},eq=brightness=-0.25[bg_processed];')
        # 叠加背景视频和主图片（主图片亮度不变）
        filter_complex_parts.append('[bg_processed][img]overlay=0:0[bg_img];')
        base_stream = 'bg_img'
    else:
        # 只有背景视频：循环、裁剪、缩放、调整亮度
        filter_complex_parts.append(f'[0:v]loop=loop=-1:size=1000:start=0,trim=duration={duration},scale={resolution[0]}:{resolution[1]},eq=brightness=-0.25[bg_img];')
        base_stream = 'bg_img'
    
    # 文本分页处理
    text_lines = get_splited_text(text, text_max_bytes=20)
    lines_per_page = 12  # 每页12行
    pages = []
    
    # 将文本分页
    for i in range(0, len(text_lines), lines_per_page):
        page_lines = text_lines[i:i + lines_per_page]
        pages.append(page_lines)
    
    total_pages = len(pages)
    
    # 计算每页显示时间（平均分配）
    page_duration = duration / total_pages
    
    print(f"分页信息: 总行数 = {len(text_lines)}, 总页数 = {total_pages}, 每页显示时间 = {page_duration:.2f} 秒")
    
    text_x = int(0.7594 * resolution[0])
    base_y = int(0.224 * resolution[1])
    line_height = text_size + 10
    
    # 为每一页创建文字叠加（使用enable控制显示时间）
    for page_num, page_lines in enumerate(pages):
        # 计算当前页的时间段
        page_start = page_num * page_duration
        page_end = (page_num + 1) * page_duration
        
        print(f"第 {page_num + 1} 页: {page_start:.1f} - {page_end:.1f} s, 行数 = {len(page_lines)}")
        
        # 为当前页的每一行添加文字
        for line_num, line in enumerate(page_lines):
            y_offset = base_y + line_num * line_height
            
            # 使用enable控制显示时间，避免复杂的透明度表达式
            filter_complex_parts.append(
                f'[{base_stream}]drawtext=text=\"{line}\":fontfile={font_path}:'
                f'fontsize={text_size}:fontcolor=78410E:'
                f'x={text_x}:y={y_offset}:'
                f'enable=\'between(t,{page_start},{page_end})\''
            )
            
            # 设置输出标签
            current_label = f'page{page_num}_line{line_num}'
            filter_complex_parts.append(f'[{current_label}];')
            base_stream = current_label
    
    # 视频片段处理（全屏→默认位置的缓动动画）
    audio_stream = None
    # 视频片段处理部分
    if video_path and os.path.exists(video_path):
        input_args.extend(['-i', video_path])
        video_idx = 2
        
        # # 精确判断：只对 id=9191 且 level_index=3 的曲目添加动画
        # video_id = str(clip_config.get('id', ''))
        # level = clip_config.get('level_index')
        
        # if video_id == '9191' and level == 3:
        #     print(f"✓ 为目标曲目添加动画效果：ID={video_id}, 难度=MASTER")
            
        #     # 动画参数
        #     anim_start_time = 1.5
        #     anim_duration = 1.75
        #     anim_end_time = anim_start_time + anim_duration
            
        #     # 起始位置：全屏
        #     start_x, start_y = 0, 0
        #     start_width = resolution[0]
        #     start_height = resolution[1]
            
        #     # 结束位置：默认内框
        #     end_x = inner_box_left
        #     end_y = inner_box_top
        #     end_height = inner_box_height
        #     # 保持宽高比计算结束宽度
        #     aspect = start_width / start_height  # 视频原始宽高比（假设与分辨率相同）
        #     end_width = end_height * aspect
            
        #     print(f"动画参数:")
        #     print(f"  位置: ({start_x}, {start_y}) → ({end_x}, {end_y})")
        #     print(f"  尺寸: ({start_width}, {start_height}) → ({end_width:.1f}, {end_height})")
            
        #     # 缓动函数：progress = (t - start)/duration, ease = 0.5 - 0.5*cos(pi * progress)
        #     progress = f'((t-{anim_start_time})/{anim_duration})'
        #     ease = f'(0.5 - 0.5*cos(PI * {progress}))'
            
        #     # 缩放表达式（宽度保持宽高比）
        #     scale_filter = f"scale=" \
        #                 f"'if(lt(t,{anim_start_time}), {start_width}, " \
        #                 f"if(gt(t,{anim_end_time}), {end_width}, " \
        #                 f"({start_height} + ({end_height}-{start_height})*{ease})*{aspect}" \
        #                 f"))' : " \
        #                 f"'if(lt(t,{anim_start_time}), {start_height}, " \
        #                 f"if(gt(t,{anim_end_time}), {end_height}, " \
        #                 f"{start_height} + ({end_height}-{start_height})*{ease}" \
        #                 f"))' : eval=frame"
            
        #     # 位置表达式
        #     overlay_filter = f"overlay=" \
        #                     f"'if(lt(t,{anim_start_time}), {start_x}, " \
        #                     f"if(gt(t,{anim_end_time}), {end_x}, " \
        #                     f"{start_x} + ({end_x}-{start_x})*{ease}" \
        #                     f"))' : " \
        #                     f"'if(lt(t,{anim_start_time}), {start_y}, " \
        #                     f"if(gt(t,{anim_end_time}), {end_y}, " \
        #                     f"{start_y} + ({end_y}-{start_y})*{ease}" \
        #                     f"))' : eval=frame"
            
        #     # 应用滤镜
        #     filter_complex_parts.append(
        #         f'[{video_idx}:v]trim=start={start_time}:duration={duration},'
        #         f'setpts=PTS-STARTPTS,'
        #         f'{scale_filter}[overlay_vid];'
        #     )
            
        #     filter_complex_parts.append(
        #         f'[{base_stream}][overlay_vid]{overlay_filter}[final_video];'
        #     )
        
    #     else:
        # 其他曲目：使用默认静态效果
        filter_complex_parts.append(
            f'[{video_idx}:v]scale=-1:{inner_box_height},trim=start={start_time}:duration={duration},setpts=PTS-STARTPTS[overlay_vid];'
        )
        filter_complex_parts.append(
            f'[{base_stream}][overlay_vid]overlay={inner_box_left}:{inner_box_top}[final_video];'
        )
        
        base_stream = 'final_video'
        audio_stream = f'[{video_idx}:a]atrim=start={start_time}:duration={duration},asetpts=PTS-STARTPTS[a_out]'
        
    # 最终输出
    filter_complex_parts.append(f'[{base_stream}]trim=duration={duration}[v_out];')
    
    if audio_stream:
        filter_complex_parts.append(audio_stream)
    else:
        filter_complex_parts.append(f'aevalsrc=0::d={duration}[a_out]')
    
    filter_complex = ''.join(filter_complex_parts)
    
    # print("调试信息 - 分页显示滤镜链:")
    # print(filter_complex)
    
    # 编码参数
    hwaccel = encoder_param["hwaccel"]
    accel_type = encoder_param["brand"]
    encoding_args = []
    if  hwaccel and accel_type in HARD_RENDER_METHOD:
        encoder_prefix = encoder_param.get("encoder", "h264")
        hardware_suffix = HARD_RENDER_METHOD[accel_type]["codec"]
        final_encoder = f"{encoder_prefix}_{hardware_suffix}"
        encoding_args.extend(['-vcodec', final_encoder])
    else:
        final_encoder = encoder_param.get("encoder", "libx264")
        encoding_args.extend(['-vcodec', final_encoder])
    
    # 输出路径
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
        *encoding_args,
        '-preset', encoder_param.get("preset", "fast"),
        '-cq', str(encoder_param.get("cq", '33')),
        '-r', '60',
        '-threads', '0',
        '-thread_type', 'frame',
        '-b:v', f'{bitrate}k',
        '-maxrate', f'{int(bitrate)*2}k',
        '-bufsize', f'{int(bitrate)*4}k',
        '-pix_fmt', 'yuv420p',
        '-acodec', 'aac',
        '-b:a', '320k',
        '-max_muxing_queue_size', '4096',
        '-t', str(duration),
        output_path
    ]
    
    print(f"正在为您生成【{clip_config['song_name']} - {REVERSE_LEVEL_LABELS.get(clip_config['level_index'])}】的片段")
    print("正在执行 FFmpeg 生成命令。")
    print(" ".join(cmd))

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"已生成您的视频片段，名称为: {output_path}")
        print(f"片段生成用时{format_time_difference(time.time() - start_time_generation)}")
        return VideoFileClip(output_path)
    except subprocess.CalledProcessError as e:
        error_cmd = " ".join(cmd)
        # 准备日志内容
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_content = f"""
========================== FFmpeg 生成失败！============================
生成时间：{timestamp}，
视频 ID: {clip_config['id']}，
歌曲名称: {clip_config['song_name']}，
输出路径: {output_path}，
持续时间: {duration} 秒，
分辨率: {resolution}

FFmpeg 命令:
{str(error_cmd)}

错误输出:
{e.stderr}

配置信息:s
{clip_config}
============================ 错误日志结束 ============================"""
        
        # 写入错误日志文件
        log_path = f'./videos/error_logs/generation_error_report_{timestamp}.log'
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(log_content)
        
        print("FFmpeg 生成失败！详细错误报告已保存为文件；")
        print("请将此文件发送给 chu-gen 开发者，而不是这个画面的截图。")
        print(f"路径：{os.path.abspath(log_path)}") # 额外提示日志位置
        # print(f"视频生成命令：\n{str(error_cmd)}\n")
        # print(f"生成输出日志: \n{e.stderr}")
        print("============================ 这里是分隔符 ============================")
        print("将使用快速模式为您重新生成；")
        print(" -> 生成器不会检查片段完整性，别忘了将失败的片段删除；")
        print(" -> 如果仍要使用极速模式，请至少等待您报告的问题解决。\n")
        return create_video_segment_classic(clip_config, resolution, font_path)

def create_video_segment_classic(clip_config, resolution, font_path, text_size=None):
    """标准渲染（优化后），支持文本分页显示
    
    Args:
        clip_config(JSON): 视频配置数据
        resolution(tuple[int, int]): 输出分辨率
        font_path(str): （调用）评论文字路径
        text_size(None): 文字大小，默认 None
    
    Returns:
        CompositeVideoClip: 输出的视频文件
    """
    print(f"正在为您生成【{clip_config['song_name']} - {REVERSE_LEVEL_LABELS.get(clip_config['level_index'])}】的片段")
    
    # 根据上级函数计算新的位置参数
    video_pos = (int(0.0641  * resolution[0]), int(0.075 * resolution[1]))
    text_x = int(0.7594 * resolution[0])
    text_first_y = int(0.224 * resolution[1])
    
    try:
        if not isinstance(resolution, (tuple, list)) or len(resolution) != 2:
            raise ValueError(f"无效分辨率格式: {resolution}")
        width, height = int(resolution[0]), int(resolution[1])
        resolution = (width, height)
    except (TypeError, ValueError) as e:
        print(f"分辨率参数错误: {e}，使用默认分辨率 1080p。")
        resolution = (1920, 1080)
    
    # 使用计算出的文字大小
    if text_size is None:
        base_text_size = 32
        text_size = int(base_text_size * resolution[1] / 1080)
    
    # 1. 背景层
    bg_video = VideoFileClip(f"{bgclips_path}/bg.mp4")
    bg_video = bg_video.with_effects([
        vfx.Loop(duration=clip_config['duration']), 
        vfx.MultiplyColor(0.5),
        vfx.Resize(resolution)
    ])
    
    # 2. 主图片层
    if 'main_image' in clip_config and os.path.exists(clip_config['main_image']):
        main_image = ImageClip(clip_config['main_image']).with_duration(clip_config['duration'])
        main_image = main_image.with_effects([vfx.Resize(resolution)])
    else:
        print(f"警告: {clip_config['id']} 缺少主图片")
        main_image = ColorClip(size=resolution, color=(0, 0, 0)).with_duration(clip_config['duration'])
    
    # 3. 视频片段层
    if 'video' in clip_config and os.path.exists(clip_config['video']):
        try:
            inner_box_height = int(665 * resolution[1] / 1080)
            video_clip = VideoFileClip(clip_config['video']).subclipped(
                clip_config['start'], clip_config['end']
            )
            video_clip = video_clip.with_effects([vfx.Resize(height=inner_box_height)])
        except Exception as e:
            print(f"视频处理错误: {e}")
            inner_box_height = int(665 * resolution[1] / 1080)
            video_clip = ColorClip(size=(inner_box_height*16//9, inner_box_height), color=(0, 0, 0))
            video_clip = video_clip.with_duration(clip_config['duration'])
    else:
        print(f"警告: {clip_config['id']} 缺少视频文件")
        inner_box_height = int(665 * resolution[1] / 1080)
        video_clip = ColorClip(size=(inner_box_height*16//9, inner_box_height), color=(0, 0, 0))
        video_clip = video_clip.with_duration(clip_config['duration'])
    
    # 4. 文字层 - 新增分页功能
    MAX_LINES_PER_PAGE = 12  # 每页最多12行
    line_height = text_size + 10  # 行高
    
    # 分割文本并分页
    text_list = get_splited_text(clip_config['text'], text_max_bytes=20)
    text_pages = []
    
    # 将文本分成多页，每页最多MAX_LINES_PER_PAGE行
    for i in range(0, len(text_list), MAX_LINES_PER_PAGE):
        page_lines = text_list[i:i + MAX_LINES_PER_PAGE]
        text_pages.append(page_lines)
    
    # 计算每页的显示时长
    total_pages = len(text_pages)
    if total_pages > 0:
        page_duration = clip_config['duration'] / total_pages
    else:
        page_duration = clip_config['duration']
    
    # 创建分页文字剪辑
    text_clips = []
    
    for page_index, page_lines in enumerate(text_pages):
        page_start_time = page_index * page_duration
        # page_end_time = (page_index + 1) * page_duration
        
        for line_index, line in enumerate(page_lines):
            y_offset = text_first_y + line_index * line_height
            
            try:
                txt_clip = TextClip(
                    text=line,
                    font=font_path,
                    font_size=text_size,
                    color="rgb(120,65,14)",
                    method="pango" if hasattr(TextClip, 'PANGO') else "label",
                ).with_duration(page_duration)  # 每页文字只显示对应的时长
                
                # 设置文字的显示时间段
                txt_clip = txt_clip.with_start(page_start_time)
                text_clips.append(txt_clip.with_position((text_x, y_offset)))
                
            except Exception as e:
                print(f"创建文字剪辑失败: {e}")
                # 回退到原始方法
                try:
                    txt_clip = TextClip(
                        font=font_path,
                        text=line,
                        method="label",
                        font_size=text_size,
                        color="rgb(120,65,14)",
                        duration=page_duration
                    )
                    txt_clip = txt_clip.with_start(page_start_time)
                    text_clips.append(txt_clip.with_position((text_x, y_offset)))
                except Exception as e2:
                    print(f"［文字剪辑］旧方法失败: {e2}")
    
    # 合成所有图层
    all_clips = [
        bg_video.with_position((0, 0)),
        main_image.with_position((0, 0)),
        video_clip.with_position(video_pos)
    ]
    all_clips.extend(text_clips)
    
    composite_clip = CompositeVideoClip(all_clips, size=resolution, use_bgclip=True)
    
    return composite_clip.with_duration(clip_config['duration'])

def get_video_preview_frame(clip_config, style_config, resolution, part="intro") -> Image.Image:
    """ 获取视频片段的预览帧，返回PIL.Image对象 """
    if part == "intro":
        preview_clip = create_info_segment(clip_config, style_config, resolution)
    elif part == "content":
        preview_clip = create_video_segment(clip_config, resolution, style_config)
    
    frame = preview_clip.get_frame(t=1)
    pil_img = Image.fromarray(frame.astype("uint8"))
    return pil_img

def gen_black_video(duration, resolution):
    """
    生成一个纯黑色的底板视频（debug 和默认背景）
    """
    black_frame = create_blank_image(resolution[0], resolution[1], color=(0, 0, 0, 1))
    clip = ImageClip(black_frame).with_duration(duration)
    clip.write_videofile(f"{bgclips_path}/black_bg.mp4", fps=60)

def check_rendered_clips_multithreaded(
    video_configs: Dict[str, List[Dict[str, Any]]],
    output_dir: str,
    force_render: bool = False,
    max_workers: int = 4
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    多线程检测已渲染的视频片段
    
    （统一按顺序编号：intro -> main -> ending, 从0开始）
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

def render_all_video_clips(
    resources, 
    video_output_path, 
    resolution: tuple, 
    v_bitrate_kbps, 
    # trans_params,
    font_path,
    encoder_param: dict,
    force_render=False,
    classic_fast_render=False,
    clips_only=False
):
    """生成所有视频片段的函数

    Args:
        resources (JSON): 视频配置数据
        video_output_path (str): 输出目录
        resolution (tuple): 视频分辨率
        v_bitrate_kbps (int): 视频码率
        font_path (str): 评论使用的字体路径
        encoder_param (dict): 编码器参数
        add_transition (bool?): 在片段间添加过渡。默认为 True。
        trans_time (int?): 过渡时间，单位秒。默认为 1 秒。
        force_render (bool?): 强制渲染。默认为 False。
        classic_fast_render (bool?): 使用标准渲染模式（MoviePy）。默认为 False。
    """
    # 1. 检查已有片段
    to_render, existing = check_rendered_clips_multithreaded(
        resources,
        video_output_path,
        force_render
    )
    
    print(f"需要渲染 {len(to_render)} 个新片段，跳过 {len(existing)} 个已存在片段")
    
    # 如果底板视频不存在则生成一份新的
    if not os.path.exists(f"{bgclips_path}/black_bg.mp4"):
        gen_black_video(5, resolution)
    
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
                    if classic_fast_render:
                        print(f"开始处理[标准]: {current_prefix}_{config['id']}({config['song_name']}).mp4")
                        clip = create_video_segment_classic(config, resolution, font_path)
                    else:
                        print(f"开始处理[FFmpeg 快速]: {current_prefix}_{config['id']}({config['song_name']}).mp4")
                        clip = create_video_segment(
                            config, 
                            resolution, 
                            font_path, 
                            v_bitrate_kbps,  # 第4个参数：bitrate
                            encoder_param    # 第5个参数：encoder_param
                        )
                # print(f"正在处理视频片段: {current_prefix}_{config['id']}.mp4")

                clip = normalize_audio_volume(clip)
                # if trans_params["enabled"] or not clips_only:
                #     duration = trans_params["duration"]
                #     custom = trans_params["enable_custom"]
                #     effect = trans_params["effect"]
                #     fade_range = trans_params["range"]
                    
                #     effects = []
                    
                #     # # 非自定义模式
                #     if custom:
                #         if effect == "fade":
                #             # 普通淡变
                #             if fade_range in ["start", "both"]:
                #                 effects.append(vfx.FadeIn(duration))
                #             if fade_range in ["end", "both"]:
                #                 effects.append(vfx.FadeOut(duration))
                        
                #         elif effect == "slide":
                #             # 滑入滑出效果
                #             direction = trans_params["slide_direction"]
                #             if fade_range in ["start", "both"]:
                #                 effects.append(vfx.SlideIn(duration=duration, side=direction))
                #             if fade_range in ["end", "both"]:
                #                 effects.append(vfx.SlideOut(duration=duration, side=direction))
                #     else:
                #         # 普通淡变
                #         if fade_range in ["start", "both"]:
                #             effects.append(vfx.FadeIn(duration))
                #         if fade_range in ["end", "both"]:
                #             effects.append(vfx.FadeOut(duration))
                    
                # 音频过渡始终添加
                # effects.extend([
                #     afx.AudioFadeIn(duration),
                #     afx.AudioFadeOut(duration)
                # ])
                
                clip = clip.with_effects([
                    vfx.FadeIn(duration=1.5),
                    vfx.FadeOut(duration=1.5),
                    afx.AudioFadeIn(duration=1.5),
                    afx.AudioFadeOut(duration=1.5)
                ])
                    
                clip.write_videofile(
                    output_file,
                    fps=60,
                    threads=8,
                    codec="libx264",          # fallback: 使用 CPU 的 libx264 输出文件（硬件加速会导致 preset 或某些参数异常）
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

def combine_full_video_direct(video_clip_path, username, classic_fast_render=False):
    print("[信息] ==================== 开始拼接视频 ==================")
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

        # 3. 拼接输出为 MP4
        output_path = os.path.join(video_clip_path, f"{username}_Best50{'' if classic_fast_render else '_fast'}.mp4")
        
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
            '-threads', '0',
            output_path,  # 使用绝对路径
        ]
        subprocess.run(cmd, check=True)

        print("[信息] ==================== 视频拼接完成 ==================")
    
    except Exception as e:
        print(f"拼接失败：{str(e)}")
    # finally:
    #     # 清理临时文件
    #     if os.path.exists(temp_dir):
    #         for file in os.listdir(temp_dir):
    #             os.remove(os.path.join(temp_dir, file))
    #         os.rmdir(temp_dir)

    return output_path