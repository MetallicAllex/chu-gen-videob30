from datetime import datetime
import numpy as np
from queue import Queue, Empty
from typing import Any, Dict, List, Tuple
from utils.Utils import format_time_difference
import os, traceback, threading, subprocess, time
from utils.ImageUtils import create_blank_image, get_splited_text
from utils.Variables import HARD_RENDER_METHOD, root_path, ui_font_path, REVERSE_LEVEL_LABELS
from moviepy import ColorClip, VideoFileClip, ImageClip, TextClip, AudioFileClip, CompositeVideoClip, vfx, afx, concatenate_videoclips

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
    
    # 创建统一的背景（整个片段共用）
    bg_image = ImageClip(f"{root_path}/IntroBase.png").with_duration(clip_config['duration'])
    bg_image = bg_image.with_effects([vfx.Resize(width=resolution[0])])

    bg_video = VideoFileClip(f"{root_path}/BgClips/bg_xverse.mp4")
    bg_video = bg_video.with_effects([
        vfx.Loop(duration=clip_config['duration']), 
        vfx.MultiplyColor(0.5),
        vfx.Resize(width=resolution[0])
    ])

    # 文本分页处理
    text_list = get_splited_text(clip_config['text'], text_max_bytes=inline_max_len)
    
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
    addtional_text = "【本视频由基于 mai-genVb50 修改的 chu-gen-Vb30 生成，使用时请标记原作者与修改作者】"
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
            vertical_align="top", color="black",
            duration=clip_config['duration']
        )
        
        composite_clip = CompositeVideoClip([
            bg_video.with_position((0, 0)),
            bg_image.with_position((0, 0)),
            txt_clip.with_position((text_pos[0], text_pos[1])),
            addtional_txt_clip.with_position((addtional_text_pos[0], addtional_text_pos[1]))
        ], size=resolution, use_bgclip=True)
        
        # 添加音频
        bg_audio = AudioFileClip(f"{root_path}/Audioes/bgm.mp3")
        bg_audio = bg_audio.with_effects([afx.AudioLoop(duration=clip_config['duration'])])
        composite_clip = composite_clip.with_audio(bg_audio)
        
        return composite_clip.with_duration(clip_config['duration'])
    
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
                vertical_align="top", color="black",  # 固定白色，不变色
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
        bg_audio = AudioFileClip(f"{root_path}/Audioes/bgm.mp3")
        bg_audio = bg_audio.with_effects([afx.AudioLoop(duration=clip_config['duration'])])
        composite_clip = composite_clip.with_audio(bg_audio)
        
        return composite_clip.with_duration(clip_config['duration'])

def create_video_segment(clip_config, resolution, font_path, bitrate, encoder_param,
                                       use_hardware_acceleration, acceleration_method="libx264",
                                       output_path='./videos/temp_generated'):
    """分页显示评论文字 - 修复版本"""
    start_time_generation = time.time()
    
    # 坐标计算
    inner_box_left = int(135 * resolution[0] / 1920)
    inner_box_top = int(83 * resolution[1] / 1080)
    inner_box_height = int(665 * resolution[1] / 1080)
    scale_factor = resolution[1] / 1080
    text_size = int(32 * scale_factor)
    
    text = clip_config['text']
    duration = clip_config['duration']
    start_time = clip_config['start']
    
    # 文件路径
    bg_video_path = os.path.abspath(f"{root_path}/BgClips/bg_xverse.mp4").replace('\\', '/')
    main_image_path = os.path.abspath(clip_config.get('main_image', '')).replace('\\', '/') if clip_config.get('main_image') else ''
    video_path = os.path.abspath(clip_config.get('video', '')).replace('\\', '/') if clip_config.get('video') else ''
    
    input_args = []
    filter_complex_parts = []
    
    # 硬件加速
    if use_hardware_acceleration and acceleration_method in HARD_RENDER_METHOD:
        try:
            method_config = HARD_RENDER_METHOD[acceleration_method]
            hwaccel = method_config.get("hwaccel")
            if hwaccel:
                input_args.extend(['-hwaccel', hwaccel])
        except Exception as e:
            print(f"硬件加速配置出错: {e}")
    
    # 输入1: 背景视频
    input_args.extend(['-i', bg_video_path])
    
    # 基础背景处理
    if main_image_path and os.path.exists(main_image_path):
        input_args.extend(['-i', main_image_path])
        filter_complex_parts.append(f'[1:v]scale={resolution[0]}:{resolution[1]}[img];')
        filter_complex_parts.append('[0:v][img]overlay=0:0[bg_img];')
        base_stream = 'bg_img'
    else:
        filter_complex_parts.append(f'[0:v]loop=loop=-1:size=1000:start=0,trim=duration={duration},scale={resolution[0]}:{resolution[1]}[bg_img];')
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
                f'[{base_stream}]drawtext=text=\'{line}\':fontfile={font_path}:'
                f'fontsize={text_size}:fontcolor=78410E:'
                f'x={text_x}:y={y_offset}:'
                f'enable=\'between(t,{page_start},{page_end})\''
            )
            
            # 设置输出标签
            current_label = f'page{page_num}_line{line_num}'
            filter_complex_parts.append(f'[{current_label}];')
            base_stream = current_label
    
    # 视频片段处理
    audio_stream = None
    if video_path and os.path.exists(video_path):
        input_args.extend(['-i', video_path])
        video_idx = 2  # 第三个输入
        
        filter_complex_parts.append(f'[{video_idx}:v]scale=-1:{inner_box_height},trim=start={start_time}:duration={duration},setpts=PTS-STARTPTS[overlay_vid];')
        filter_complex_parts.append(f'[{base_stream}][overlay_vid]overlay={inner_box_left}:{inner_box_top}[final_video];')
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
    encoding_args = []
    if use_hardware_acceleration and acceleration_method in HARD_RENDER_METHOD:
        encoder_prefix = encoder_param.get("encoder", "h264")
        hardware_suffix = HARD_RENDER_METHOD[acceleration_method]["codec"]
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
        '-preset', encoder_param.get("preset_type", "fast"),
        '-cq', str(encoder_param.get("cq_set", '33')),
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
    # print(" ".join(cmd))

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"已生成您的视频片段，名称为: {output_path}")
        print(f"片段生成用时{format_time_difference(time.time() - start_time_generation)}")
        return VideoFileClip(output_path)
    except subprocess.CalledProcessError as e:
        error_cmd = " ".join(cmd)
        # 准备日志内容
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_content = f"""========================== FFmpeg 生成失败！============================
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

错误详情:
{str(e)}

配置信息:
{clip_config}
============================ 错误日志结束 ======================================="""
        
        # 写入错误日志文件
        log_path = f'./videos/error_logs/video_generation_error_report_{timestamp}.log'
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(log_content)
        
        print("========================== FFmpeg 生成失败！====================================")
        print(f"详细错误报告已保存，请将此错误报告文件发送给 chu-gen 开发者。")
        print(f"路径：{os.path.abspath(log_path)}") # 额外提示日志位置
        # print(f"视频生成命令：\n{str(error_cmd)}\n")
        # print(f"生成输出日志: \n{e.stderr}")
        print("============================ 这里是分隔符 ======================================")
        print("将使用快速模式为您重新生成；")
        print(" -> 生成器不会检查片段完整性，别忘了将失败的片段删除；")
        print(" -> 如果仍要使用极速模式，请至少等待您报告的问题解决。\n")
        return create_video_segment_classic(clip_config, resolution, font_path)

def create_video_segment_classic(clip_config, resolution, font_path, text_size=None):
    """优化后的视频片段创建函数，支持文本分页显示"""
    print(f"正在为您生成【{clip_config['song_name']} - {REVERSE_LEVEL_LABELS.get(clip_config['level_index'])}】的片段")
    
    # 根据上级函数计算新的位置参数
    video_pos = (int(0.0641  * resolution[0]), int(0.075 * resolution[1]))
    text_x = int(0.7594 * resolution[0])
    text_first_y = int(0.224 * resolution[1])
    
    try:
        if not isinstance(resolution, (tuple, list)) or len(resolution) != 2:
            raise ValueError(f"无效的 resolution 格式: {resolution}")
        width, height = int(resolution[0]), int(resolution[1])
        resolution = (width, height)
    except (TypeError, ValueError) as e:
        print(f"resolution 参数错误: {e}，使用默认分辨率 1920x1080")
        resolution = (1920, 1080)
    
    # 使用计算出的文字大小
    if text_size is None:
        base_text_size = 32
        text_size = int(base_text_size * resolution[1] / 1080)
    
    # 1. 背景层
    bg_video = VideoFileClip(f"{root_path}/BgClips/bg_xverse.mp4")
    bg_video = bg_video.with_effects([
        vfx.Loop(duration=clip_config['duration']), 
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
                    print(f"回退方法也失败: {e2}")
    
    # 5. 添加页码指示器（可选）
    # if total_pages > 1:
    #     try:
    #         # 在右下角显示页码
    #         page_indicator_x = int(0.85 * resolution[0])
    #         page_indicator_y = int(0.95 * resolution[1])
            
    #         for page_index in range(total_pages):
    #             page_start_time = page_index * page_duration
    #             indicator_text = f"{page_index + 1}/{total_pages}"
                
    #             indicator_clip = TextClip(
    #                 text=indicator_text,
    #                 font=font_path,
    #                 font_size=int(text_size * 0.8),  # 稍小一点的字号
    #                 color="rgb(120,65,14)",
    #                 method="pango" if hasattr(TextClip, 'PANGO') else "label",
    #             ).with_duration(page_duration)
                
    #             indicator_clip = indicator_clip.with_start(page_start_time)
    #             text_clips.append(indicator_clip.with_position((page_indicator_x, page_indicator_y)))
                
    #     except Exception as e:
    #         print(f"添加页码指示器失败: {e}")
    
    # 6. 合成所有图层
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

def create_full_video_streaming(resources, resolution, font_path, bitrate, 
                               auto_add_transition=True, trans_time=1, full_last_clip=False,
                               temp_dir="./videos/temp_streaming"):
    """流式处理完整视频，避免内存爆炸"""
    import os
    os.makedirs(temp_dir, exist_ok=True)
    
    temp_files = []
    
    try:
        # 1. 分段渲染并保存到临时文件
        current_time = 0
        segment_files = []
        
        # 处理开场片段
        if 'intro' in resources:
            for clip_config in resources['intro']:
                clip = create_info_segment(clip_config, resolution, font_path)
                clip = normalize_audio_volume(clip)
                
                segment_file = os.path.join(temp_dir, f"intro_{len(segment_files)}.mp4")
                clip.write_videofile(segment_file, fps=60, logger=None)
                segment_files.append(segment_file)
                clip.close()
                current_time += clip.duration
        
        # 处理主要视频片段
        if 'main' in resources:
            for i, clip_config in enumerate(resources['main']):
                print(f"处理主片段 {i+1}/{len(resources['main'])}")
                
                if clip_config['id'] == resources['main'][-1]['id'] and full_last_clip:
                    # 最后一个片段特殊处理
                    start_time = clip_config['start']
                    full_clip_duration = VideoFileClip(clip_config['video']).duration - 5
                    clip_config['duration'] = full_clip_duration - start_time
                    clip_config['end'] = full_clip_duration
                
                clip = create_video_segment_classic(clip_config, resolution, font_path)
                clip = normalize_audio_volume(clip)
                
                segment_file = os.path.join(temp_dir, f"main_{i}.mp4")
                clip.write_videofile(segment_file, fps=60, logger=None)
                segment_files.append(segment_file)
                clip.close()
                
                # 每处理几个片段就垃圾回收
                if i % 5 == 0:
                    import gc
                    gc.collect()
        
        # 处理结尾片段
        if 'ending' in resources:
            for i, clip_config in enumerate(resources['ending']):
                clip = create_info_segment(clip_config, resolution, font_path)
                clip = normalize_audio_volume(clip)
                
                segment_file = os.path.join(temp_dir, f"ending_{i}.mp4")
                clip.write_videofile(segment_file, fps=60, verbose=False, logger=None)
                segment_files.append(segment_file)
                clip.close()
        
        # 2. 使用FFmpeg拼接所有分段（无转场）
        if segment_files:
            return concatenate_videoclips([VideoFileClip(f) for f in segment_files])
        else:
            raise ValueError("没有生成任何视频片段")
            
    except Exception as e:
        # 清理临时文件
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
        raise e

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

            clip = create_video_segment_classic(clip_config, resolution, font_path)  
            clip = normalize_audio_volume(clip)

            combined_start_time = clips[-1].end - trans_time
            ending_clips.append(clip)     
        else:
            clip = create_video_segment_classic(clip_config, resolution, font_path)  
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

def sort_video_files(files):
    """
    严格检查：只允许完全符合 '数字_描述.mp4' 格式的文件
    不合格的文件会被跳过并记录警告
    """
    sorted_files = []
    encountered_numbers = set()
    skipped_files = []
    
    # print(f"开始严格检查文件列表: {files}")
    
    for filename in files:
        # print(f"检查文件: '{filename}'")
        
        try:
            # 1. 检查文件扩展名
            if not filename.endswith('.mp4'):
                raise ValueError(f"文件扩展名不是 .mp4")
            
            # 2. 分离基础名称和扩展名
            base_name = os.path.splitext(filename)[0]
            
            # 3. 检查是否包含下划线
            if '_' not in base_name:
                raise ValueError(f"文件名缺少下划线分隔符")
            
            # 4. 提取数字部分
            parts = base_name.split('_')
            number_str = parts[0]
            
            # 5. 检查数字部分是否纯数字
            if not number_str.isdigit():
                raise ValueError(f"数字部分包含非数字字符")
            
            # 6. 转换为数字
            number = int(number_str)
            
            # 7. 检查描述部分是否合法（不能包含空格、副本等）
            description = '_'.join(parts[1:])  # 剩余部分作为描述
            if any(char in description for char in [' ', '-', '副本', 'copy']):
                raise ValueError(f"描述部分包含非法字符")
            
            # 8. 检查数字是否重复
            if number in encountered_numbers:
                raise ValueError(f"发现重复的片段编号 {number}")
            
            # 9. 所有检查通过，添加到列表
            sorted_files.append((number, filename))
            encountered_numbers.add(number)
            # print(f"文件通过检查: {filename} -> 编号 {number}")
            
        except (ValueError, IndexError) as e:
            # print(f"跳过: {filename} - {e}")
            skipped_files.append((filename, str(e)))
    
    # 如果没有找到任何合格文件
    if not sorted_files:
        raise ValueError(f"没有找到任何符合格式的视频文件！跳过的文件: {skipped_files}")
    
    # 报告跳过的文件
    if skipped_files:
        print(f"警告: 跳过了 {len(skipped_files)} 个不符合格式的文件:")
        for filename, reason in skipped_files:
            print(f"  - {filename}: {reason}")
    
    # 按数字排序
    sorted_files.sort(key=lambda x: x[0])
    # print(f"排序后的合格文件: {sorted_files}")
    
    # 检查数字序列是否连续
    numbers = [num for num, _ in sorted_files]
    expected_sequence = list(range(numbers[0], numbers[0] + len(numbers)))
    
    if numbers != expected_sequence:
        missing_numbers = set(expected_sequence) - set(numbers)
        if missing_numbers:
            raise ValueError(f"片段编号不连续！缺失的编号: {sorted(missing_numbers)}。当前合格文件: {[f for _, f in sorted_files]}")
        else:
            raise ValueError(f"片段编号序列异常！当前: {numbers}，期望: {expected_sequence}")
    
    result = [filename for _, filename in sorted_files]
    # print(f"最终通过的文件 ({len(result)} 个): {result}")
    return result

# def combine_full_video_from_existing_clips(video_clip_path, resolution, trans_time=1):
#     clips = []

#     video_files = [f for f in os.listdir(video_clip_path) if f.endswith(".mp4")]
#     sorted_files = sort_video_files(video_files)
    
#     print(f"Sorted files: {sorted_files}")

#     if not sorted_files:
#         raise ValueError("Error: 没有有效的视频片段文件！(Best_1-30)")

#     for file in sorted_files:
#         clip = VideoFileClip(os.path.join(video_clip_path, file))
#         clip = normalize_audio_volume(clip)
        
#         if len(clips) == 0:
#             clips.append(clip)
#         else:
#             # 为前一个片段添加音频渐出效果
#             clips[-1] = clips[-1].with_audio_fadeout(trans_time)
#             # 为当前片段添加音频渐入效果和视频渐入效果
#             current_clip = clip.with_audio_fadein(trans_time).with_crossfadein(trans_time)
#             # 设置片段开始时间
#             clips.append(current_clip.with_start(clips[-1].end - trans_time))

#     final_video = CompositeVideoClip(clips, size=resolution)
#     return final_video


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

def render_all_video_clips(
    resources, 
    video_output_path, 
    resolution: tuple, 
    v_bitrate_kbps, 
    font_path,
    encoder_param: dict,
    auto_add_transition=True, 
    trans_time=1, 
    force_render=False,
    classic_fast_render=False,
    use_hardware_acceleration=False,
    acceleration_method="libx264",
    clips_only=False
):
    """生成所有视频片段的函数

    Args:
        resources (JSON): 视频配置数据
        video_output_path (str): 输出目录
        resolution (tuple): 视频分辨率
        v_bitrate_kbps (int, 或 str?): 视频码率
        font_path (str): 评论使用的字体路径
        encoder_param (dict): 编码器参数
        auto_add_transition (bool, 可选): 自动在片段间添加过渡。 默认为 True。
        trans_time (int, 可选): 过渡时间，单位秒。 默认为 1 秒。
        force_render (bool, 可选): 强制渲染。 默认为 False。
        classic_fast_render (bool, 可选): 使用之前的渲染模式。 Defaults to False。
        use_hardware_acceleration (bool, 可选): 使用硬件加速。 默认为 False。
        acceleration_method (str, 可选): 硬件加速方案。 默认为 "libx264"。
    """
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
                    if classic_fast_render:
                        print(f"开始处理[快速]: {current_prefix}_{config['id']}({config['song_name']}).mp4")
                        clip = create_video_segment_classic(config, resolution, font_path)
                    else:
                        print(f"开始处理[FFmpeg]: {current_prefix}_{config['id']}({config['song_name']}).mp4")
                        clip = create_video_segment(
                            config, 
                            resolution, 
                            font_path, 
                            v_bitrate_kbps,  # 第4个参数：bitrate
                            encoder_param,    # 第5个参数：encoder_param
                            use_hardware_acceleration,  # 第6个参数：use_hardware_acceleration
                            acceleration_method  # 第7个参数：acceleration_method
                        )
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
                if use_hardware_acceleration and acceleration_method is not None:
                    # 硬件加速模式
                    encoder_prefix = encoder_param.get('encoder', 'h264')
                    
                    # 如果是 Intel 且选择了不支持的编码器，强制使用 h264
                    if acceleration_method == "Intel" and encoder_prefix == "vp9":
                        encoder_prefix = "h264"  # Intel 不支持 vp9 添加过渡，强制回退到 h264
                    
                    hardware_suffix = HARD_RENDER_METHOD[acceleration_method]['codec']
                    final_codec = f"{encoder_prefix}_{hardware_suffix}"
                    
                else:
                    # 软件编码模式
                    final_codec = acceleration_method if acceleration_method else "libx264"
                    
                clip.write_videofile(
                    output_file,
                    fps=60,
                    threads=8,
                    # codec="h264_nvenc",          # GPU H.264
                    codec=final_codec,
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

        # 3. 拼接TS文件并输出为MP4
        output_path = os.path.join(video_clip_path, f"{username}_Best50_{'fast' if classic_fast_render else 'ffmpeg'}.mp4")
        
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

# def combine_full_video_ffmpeg_concat_gl(video_clip_path, resolution, trans_name="fade", trans_time=1):
#     video_files = [f for f in os.listdir(video_clip_path) if f.endswith(".mp4")]
#     sorted_files = sort_video_files(video_files)
    
#     if not sorted_files:
#         raise ValueError("Error: 没有有效的视频片段文件！")
    
#     output_path = os.path.join(video_clip_path, "final_output.mp4")
    
#     # 创建MP4文件列表
#     mp4_list_file = os.path.join(video_clip_path, "mp4_files.txt")
#     with open(mp4_list_file, 'w', encoding='utf-8') as f:
#         for file in sorted_files:
#             # 使用正斜杠替换反斜杠，并使用相对路径
#             full_path = os.path.join(video_clip_path, file).replace('\\', '/')
#             f.write(f"file '{full_path}'\n")


#     # 使用nodejs脚本拼接视频
#     node_script_path = os.path.join(os.path.dirname(__file__), "external_scripts", "concat_videos_ffmpeg.js")

#     cmd = f'node {node_script_path} -o {output_path} -v {mp4_list_file} -t {trans_name} -d {int(trans_time * 1000)}'
#     print(f"执行命令: {cmd}")

#     os.system(cmd)

#     return output_path

    # 渲染失败: generate_complete_video() got an unexpected keyword argument 'encoder_type'
def generate_complete_video(configs, username, video_output_path, video_res, video_bitrate,
                            video_trans_enable, video_trans_time, full_last_clip, encoder_param,
                            acceleration_method="libx264", use_hardware_acceleration=False, font_path=ui_font_path):
    """生成完整视频的函数

    Args:
        configs (JSON): 视频配置数据
        username (str): 用户名
        video_output_path (str): 视频输出目录
        video_res (tuple): 视频分辨率
        video_bitrate (int): 视频码率
        video_trans_enable (bool): 视频是否已启用过渡效果
        video_trans_time (float): 过渡效果时长
        full_last_clip (bool): 最后一个片段是否需要拉长播放时间
        use_hardware_acceleration (bool, 可选): 是否使用硬件加速（可能没有效果但也试试看（，默认为否）
        acceleration_method (str, 可选): 硬件加速方法([h264_nvenc/amf/qsv]/libx264)，默认为软编 libx264
        font_path (str, 可选): 使用的字体，默认为 UI 字体.

    Returns:
        Message: 视频生成结果
        
    Raises:
        Message: 生成失败原因
    """
    print(f"正在合成完整视频")
    try:
        final_video = create_full_video_streaming(configs, resolution=video_res, font_path=font_path, 
                                        auto_add_transition=video_trans_enable, 
                                        trans_time=video_trans_time, 
                                        full_last_clip=full_last_clip,
                                        bitrate=video_bitrate)
        if use_hardware_acceleration and acceleration_method is not None:
            final_codec = f"{encoder_param.get('encoder', 'h264')}_{HARD_RENDER_METHOD[acceleration_method]['codec'] if use_hardware_acceleration else acceleration_method}"
        else:
            final_codec = "libx264"
        final_video.write_videofile(os.path.join(video_output_path, f"{username}_Best50.mp4"), codec=final_codec,
                                    fps=60, threads=8, preset=encoder_param.get('preset_type', 'fast'), bitrate=video_bitrate)
        final_video.close()
        return {"status": "success", "info": f"合成完整视频成功"}
    except Exception as e:
        print(f"Error: 合成完整视频时发生异常: {traceback.print_exc()}")
        return {"status": "error", "info": f"合成完整视频时发生错误：{traceback.print_exc()}"}