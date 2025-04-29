import os
from queue import Queue
import threading
from typing import Any, Dict, List, Tuple
import numpy as np
import subprocess
from PIL import Image, ImageFilter
from moviepy import VideoFileClip, ImageClip, TextClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips
from moviepy import vfx, afx

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
    print(f"正在合成视频片段: {clip_config['id']}")
    bg_image = ImageClip("./images/IntroBase.png").with_duration(clip_config['duration'])
    bg_image = bg_image.with_effects([vfx.Resize(width=resolution[0])])

    bg_video = VideoFileClip("./images/BgClips/bg.mp4")
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
    
    addtional_text = "【本视频由 mai-genVb50 修改的 chu-gen-Vb30 生成】"
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
    bg_audio = AudioFileClip("./images/Audioes/intro_bgm.mp3")
    bg_audio = bg_audio.with_effects([afx.AudioLoop(duration=clip_config['duration'])])
    composite_clip = composite_clip.with_audio(bg_audio)

    return composite_clip.with_duration(clip_config['duration'])


def create_video_segment(clip_config, resolution, font_path, text_size=None, inline_max_len=21):
    """
    创建自适应分辨率的视频片段
    
    Args:
        clip_config: 片段配置字典
        resolution: 目标分辨率 (width, height)
        font_path: 字体文件路径
        text_size: 文字大小(可选，默认根据分辨率计算)
        inline_max_len: 每行最大字符数
    """
    print(f"正在合成视频片段: {clip_config['id']}")
    
    # 计算相对于1080p的缩放比例
    scale_factor = resolution[1] / 1080  # 基于高度缩放
    
    # 自动计算文字大小（如果未指定）
    if text_size is None:
        text_size = int(32 * scale_factor)  # 1080p下默认32px
    
    # 1. 背景层（纯黑）
    bg_video = VideoFileClip("./images/BgClips/black_bg.mp4")
    bg_video = bg_video.with_effects([
        vfx.Loop(duration=clip_config['duration']), 
        vfx.Resize(resolution)  # 完整适配目标分辨率
    ])
    
    # 2. 主图片层
    if 'main_image' in clip_config and os.path.exists(clip_config['main_image']):
        main_image = ImageClip(clip_config['main_image']).with_duration(clip_config['duration'])
        main_image = main_image.with_effects([vfx.Resize(resolution)])  # 全屏覆盖
    else:
        print(f"警告: {clip_config['id']} 缺少主图片")
        main_image = ImageClip(create_blank_image(*resolution)).with_duration(clip_config['duration'])
    
    # 3. 视频片段层
    if 'video' in clip_config and os.path.exists(clip_config['video']):
        video_clip = VideoFileClip(clip_config['video'])
        
        # 时间范围校验
        if clip_config['start'] < 0 or clip_config['start'] >= video_clip.duration:
            raise ValueError(f"开始时间 {clip_config['start']} 超出视频长度")
        if clip_config['end'] <= clip_config['start'] or clip_config['end'] > video_clip.duration:
            raise ValueError(f"结束时间 {clip_config['end']} 无效")
        
        video_clip = video_clip.subclipped(clip_config['start'], clip_config['end'])
        
        # 动态计算视频显示区域 (保持16:9比例中的核心区域)
        video_height = int(0.667 * resolution[1])  # 原1080p下716px的逻辑
        video_clip = video_clip.with_effects([vfx.Resize(height=video_height)])
    else:
        print(f"警告: {clip_config['id']} 缺少视频文件")
        blank_size = int(540 * scale_factor)  # 原1080p下540px的逻辑
        video_clip = ImageClip(create_blank_image(blank_size, blank_size))
        video_clip = video_clip.with_duration(clip_config['duration'])
    
    # 4. 文字层
    text_list = get_splited_text(clip_config['text'], text_max_bytes=inline_max_len)
    txt_clip = TextClip(
        font=font_path,
        text="\n".join(text_list),
        method="label",
        font_size=text_size,
        margin=(int(20 * scale_factor), int(20 * scale_factor)),  # 边距缩放
        interline=6.5 * scale_factor,  # 行距缩放
        color="white",
        duration=clip_config['duration']
    )
    
    # 动态计算位置 (基于比例而非固定像素)
    video_pos = (
        int(0.039 * resolution[0]),  # 水平3.9%
        int(0.069 * resolution[1])   # 垂直6.9%
    )
    text_pos = (
        int(0.748 * resolution[0]),  # 水平74.8%
        int(0.069 * resolution[1])   # 垂直6.9%
    )
    
    # 合成所有图层
    composite_clip = CompositeVideoClip([
        bg_video.with_position((0, 0)),
        video_clip.with_position(video_pos),
        main_image.with_position((0, 0)),
        txt_clip.with_position(text_pos)
    ], size=resolution, use_bgclip=True)
    
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


def create_full_video(resources, resolution, font_path, auto_add_transition=True, trans_time=1, full_last_clip=False):
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

            clip = create_video_segment(clip_config, resolution, font_path)  
            clip = normalize_audio_volume(clip)

            combined_start_time = clips[-1].end - trans_time
            ending_clips.append(clip)     
        else:
            clip = create_video_segment(clip_config, resolution, font_path)  
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
    多线程检测已渲染的视频片段
    
    Args:
        video_configs(dict): 视频配置字典(包含intro/main/ending)
        output_dir(path): 输出目录
        force_render(bool): 是否强制重新渲染
        max_workers(int): 最大工作线程数
        
    Returns:
        tuple([List[Dict[str, Any]], List[Dict[str, Any]]]): 需要渲染的配置列表, 已存在的配置列表
    """
    # 准备所有需要检查的文件任务
    task_queue = Queue()
    result_queue = Queue()
    
    # 准备所有待检查的配置
    vfile_prefix = 0
    all_configs = []
    
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

    # 工作线程函数
    def check_worker():
        while True:
            try:
                prefix, config = task_queue.get_nowait()
            except:
                break
                
            output_file = os.path.join(output_dir, f"{prefix}_{config['id']}.mp4")
            exists = os.path.exists(output_file) and not force_render
            result_queue.put((prefix, config, exists))
            task_queue.task_done()

    # 创建并启动工作线程
    threads = []
    for _ in range(min(max_workers, task_queue.qsize())):
        t = threading.Thread(target=check_worker)
        t.start()
        threads.append(t)
    
    # 等待所有检查完成
    for t in threads:
        t.join()
    
    # 处理结果
    to_render = []
    existing = []
    
    while not result_queue.empty():
        prefix, config, exists = result_queue.get()
        if exists:
            existing.append(config)
            print(f"检测到已存在片段: {prefix}_{config['id']}.mp4")
        else:
            to_render.append(config)
    
    return to_render, existing

def render_all_video_clips(
    resources, 
    video_output_path, 
    resolution: tuple, 
    v_bitrate_kbps, 
    font_path,
    auto_add_transition=True, 
    trans_time=1, 
    force_render=False
):
    # 第一步: 多线程检测已渲染片段
    to_render, existing = check_rendered_clips_multithreaded(
        resources,
        video_output_path,
        force_render,
        max_workers=4
    )
    
    print(f"需要渲染 {len(to_render)} 个新片段，跳过 {len(existing)} 个已存在片段")
    
    # 第二步: 只渲染需要的新片段(单线程)
    vfile_prefix = 0
    if not 'main' in resources:
        print("Error: 没有找到主视频片段的配置！请检查配置文件！")
        return

    # 重构渲染逻辑，只处理to_render中的配置
    def render_selected_clips(clip_configs, segment_type):
        nonlocal vfile_prefix
        for config in clip_configs:
            if config in to_render:  # 只渲染需要的新片段
                if segment_type == 'info':
                    clip = create_info_segment(config, resolution, font_path)
                else:
                    clip = create_video_segment(config, resolution, font_path)
                
                output_file = os.path.join(video_output_path, f"{vfile_prefix}_{config['id']}.mp4")
                print(f"正在合成视频片段: {vfile_prefix}_{config['id']}.mp4")
                
                clip = normalize_audio_volume(clip)
                if auto_add_transition:
                    clip = clip.with_effects([
                        vfx.FadeIn(duration=trans_time),
                        vfx.FadeOut(duration=trans_time),
                        afx.AudioFadeIn(duration=trans_time),
                        afx.AudioFadeOut(duration=trans_time)
                    ])
                
                clip.write_videofile(output_file, fps=60, threads=2, preset='fast', bitrate=v_bitrate_kbps)
                clip.close()
                del clip
            
            vfile_prefix += 1  # 无论是否渲染，索引都要增加

    # 渲染各个部分
    if 'intro' in resources:
        render_selected_clips(resources['intro'], 'info')

    render_selected_clips(resources['main'], 'video')

    if 'ending' in resources:
        render_selected_clips(resources['ending'], 'info')


def combine_full_video_direct(video_clip_path, username):
    print("[Info] --------------------开始拼接视频-------------------")
    video_files = [f for f in os.listdir(video_clip_path) if f.endswith(".mp4")]
    sorted_files = sort_video_files(video_files)
    
    if not sorted_files:
        raise ValueError("Error: 没有有效的视频片段文件！")

    # 创建临时目录存放 ts 文件
    temp_dir = os.path.join(video_clip_path, "temp_ts")
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # 1. 创建MP4文件列表
        mp4_list_file = os.path.join(video_clip_path, "mp4_files.txt")
        with open(mp4_list_file, 'w', encoding='utf-8') as f:
            for file in sorted_files:
                # 使用正斜杠替换反斜杠，并使用相对路径
                full_path = os.path.join(video_clip_path, file).replace('\\', '/')
                f.write(f"file '{full_path}'\n")

        # 2. 创建TS文件列表并转换视频
        ts_list_file = os.path.join(video_clip_path, "ts_files.txt")
        with open(ts_list_file, 'w', encoding='utf-8') as f:
            for i, file in enumerate(sorted_files):
                ts_name = f"{i:04d}.ts"
                ts_path = os.path.join(temp_dir, ts_name)
                
                # 转换MP4为TS
                cmd = [
                    'ffmpeg', '-y', '-loglevel', 'warning',
                    '-i', os.path.join(video_clip_path, file),
                    '-c', 'copy',
                    '-bsf:v', 'h264_mp4toannexb',
                    '-f', 'mpegts',
                    '-threads', '0',
                    ts_path
                ]
                subprocess.run(cmd, check=True)
                
                # 写入TS文件相对路径，使用正斜杠
                # relative_ts_path = os.path.join('temp_ts', ts_name).replace('\\', '/')
                # f.write(f"file '{relative_ts_path}'\n")

                # 写入TS文件绝对路径，使用正斜杠
                absolute_ts_path = os.path.abspath(os.path.join(video_clip_path, 'temp_ts', ts_name)) 
                f.write(f"file '{absolute_ts_path}'\n")

        # 3. 拼接TS文件并输出为MP4
        output_path = os.path.join(video_clip_path, "final_output.mp4")
        
        # 执行拼接命令
        real_path = os.path.abspath(video_clip_path)
        # current_dir = os.getcwd()
        # os.chdir(video_clip_path)
        
        cmd = [
            'ffmpeg', '-y', '-loglevel', 'warning',
            '-f', 'concat',
            '-safe', '0',
            '-i', f'{real_path}\\ts_files.txt',  # 使用绝对路径
            '-c', 'copy',
            f'{real_path}\\{username}_Best30_fast.mp4',  # 使用绝对路径
            '-threads', '0',
        ]
        
        subprocess.run(cmd, check=True)
        print("视频拼接完成，已清理临时转换的 ts 片段文件")
        
    finally:
        # 清理临时文件
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, file))
            os.rmdir(temp_dir)

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