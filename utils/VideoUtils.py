import numpy as np
from datetime import datetime
from queue import Queue, Empty
import os, threading, subprocess, time
from typing import Any, Dict, List, Tuple
from utils.DataUtils import sort_video_files
from utils.ImageUtils import create_blank_image
from utils.PageUtils import format_time_difference
from moviepy import VideoFileClip, ImageClip, vfx, afx
from utils.Variables import HARD_RENDER_METHOD, bgclips_path, audios_path, REVERSE_LEVEL_LABELS

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

def create_info_segment(clip_config, encoder_param, style_config, output_path='./videos/temp_generated'):
    """
    使用 FFmpeg 生成信息片段（背景板/说明页）
    
    Args:
        clip_config: 片段配置
        encoder_param: 编码参数
        style_config: 样式配置（包含位置等）
        output_path: 输出路径（文件或目录）
    
    Returns:
        VideoFileClip 对象（需要手动关闭）
    """
    start_time_generation = time.time()
    
    # 基础设置
    bitrate = encoder_param['bitrate']
    resolution = encoder_param['resolution']
    
    # 获取样式位置
    darkness = style_config['darkness']
    bg_page = clip_config['bg_page']
    no_overlay = clip_config['no_overlay']
    no_sound = clip_config['no_sound']
    duration = clip_config['duration']
    
    # 检查必要字段
    if 'duration' not in clip_config:
        raise ValueError(f"缺少 duration 字段: {clip_config}")
    
    # 确定背景图片路径
    if bg_page == False:
        # 正常页面：始终使用完整图片
        bg_image_path = os.path.abspath(clip_config['full_image']).replace('\\', '/')
        if no_overlay:
            print(f"提示: 片段 {clip_config['id']} 的【禁用叠加层】设置将被忽略")
    else:  # bg_page == True
        # 背景板页
        if no_overlay == True:
            print(f"警告: 片段 {clip_config['id']} 已设置【禁用叠加层】")
            bg_image_path = None
        else:
            bg_image_path = os.path.abspath(clip_config['full_image']).replace('\\', '/')
    
    
    # 文件路径
    bg_video_path = os.path.abspath(f"{bgclips_path}/bg.mp4").replace('\\', '/')
    if not no_sound:
        bg_audio_path = os.path.abspath(f"{audios_path}/bgm.mp3").replace('\\', '/')
    else:
        bg_audio_path = None
    # 输入参数和滤镜链
    input_args = []
    filter_complex_parts = []
    
    # 输入0: 背景视频
    if os.path.exists(bg_video_path):
        input_args.extend(['-i', bg_video_path])
    else:
        raise FileNotFoundError(f"背景视频不存在: {bg_video_path}")
    
    if bg_image_path is not None:
        input_args.extend(['-i', bg_image_path])
        
        # 背景视频：循环、裁剪、调暗（不缩放，不转格式）
        filter_complex_parts.append(
            f'[0:v]loop=loop=-1:size=1000:start=0,'
            f'trim=duration={duration},'
            f'eq=brightness={darkness}[bg_processed];'
        )
        
        # 背景图片：只叠加，不处理
        filter_complex_parts.append(
            f'[bg_processed][1:v]overlay=0:0[bg_combined];'
        )
        base_stream = 'bg_combined'
    else:
        if no_overlay and bg_page:
            print(f"信息: 片段 {clip_config['id']} 已禁用底板图像")
        
        # 背景视频：循环、裁剪、调暗
        filter_complex_parts.append(
            f'[0:v]loop=loop=-1:size=1000:start=0,'
            f'trim=duration={duration},'
            f'eq=brightness={darkness}[bg_processed];'
        )
        base_stream = 'bg_processed'
    
    # ⭐ 最后统一缩放
    filter_complex_parts.append(
        f'[{base_stream}]scale={resolution[0]}:{resolution[1]},'
        f'trim=duration={duration},'
        f'setpts=PTS-STARTPTS[v_out];'
    )
    
    # 音频处理
    audio_stream = None
    if bg_audio_path is not None:
        input_args.extend(['-i', bg_audio_path])
        audio_idx = 2
        
        # 先获取音频时长，计算需要循环的次数
        # 或者使用流循环 + 精确裁剪
        filter_complex_parts.append(
            f'[{audio_idx}:a]atrim=duration={duration},asetpts=PTS-STARTPTS[a_out]'
        )
        audio_stream = 'a_out'
    
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
        output_path = os.path.join(output_path, f"{clip_config['id']}.mp4")
    
        # 构建FFmpeg命令
    cmd = [
        'ffmpeg',
        '-y',
        *input_args,
        '-hide_banner',
        '-filter_complex', filter_complex,
        '-map', '[v_out]',
        '-map', f'[{audio_stream}]',
        *encoding_args,
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
        # '-t', str(duration),
        output_path
    ]
    
    print(f"正在为您生成【{clip_config['id']}】的片段")
    print("正在执行 FFmpeg 生成命令。")
    print(" ".join(cmd))

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"已生成您的视频片段，名称为：{output_path}")
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


def create_video_segment(clip_config, encoder_param, style_config, output_path='./videos/temp_generated'):
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
    resolution = encoder_param['resolution']
    bitrate = encoder_param['bitrate']
    darkness = style_config['darkness']
    postion = style_config['position']['video']
    
    # 坐标计算
    overlay = postion['overlay']
    height = postion['height']
    inner_box_left = int(overlay[0] * resolution[0])
    inner_box_top = int(overlay[1] * resolution[1])
    inner_box_height = int(height * resolution[1] / 1080)
    
    # inner_box_left = int(135 * resolution[0] / 1920)
    # inner_box_top = int(83 * resolution[1] / 1080)
    # inner_box_height = int(668 * resolution[1] / 1080)
    # scale_factor = resolution[1] / 1080
    # text_size = int(32 * scale_factor)
    
    # video_pos = (int(0.0641  * resolution[0]), int(0.075 * resolution[1]))
    # text_x = int(0.7594 * resolution[0])
    # text_first_y = int(0.224 * resolution[1])
    
    text = clip_config['text']
    duration = clip_config['duration']
    start_time = clip_config['start']
    
    # 文件路径
    bg_video_path = os.path.abspath(f"{bgclips_path}/bg.mp4").replace('\\', '/')
    # main_image_path = os.path.abspath(clip_config.get('main_image', '')).replace('\\', '/') if clip_config.get('main_image') else ''
    main_image_path = os.path.abspath(clip_config.get('full_image', '')).replace('\\', '/') if clip_config.get('full_image') else ''
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
        filter_complex_parts.append(f'[0:v]loop=loop=-1:size=1000:start=0,trim=duration={duration},scale={resolution[0]}:{resolution[1]},eq=brightness={darkness}[bg_processed];')
        # 叠加背景视频和主图片（主图片亮度不变）
        filter_complex_parts.append('[bg_processed][img]overlay=0:0[bg_img];')
        base_stream = 'bg_img'
    else:
        # 只有背景视频：循环、裁剪、缩放、调整亮度
        filter_complex_parts.append(f'[0:v]loop=loop=-1:size=1000:start=0,trim=duration={duration},scale={resolution[0]}:{resolution[1]},eq=brightness={darkness}[bg_img];')
        base_stream = 'bg_img'
    
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
        # '-preset', encoder_param.get("preset", "fast"),
        # '-cq', str(encoder_param.get("cq", '33')),
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
        print(f"已生成您的视频片段，名称为：{output_path}")
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


def gen_black_video(duration, resolution: tuple[int, int]):
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
    # resolution: tuple, 
    # v_bitrate_kbps, 
    trans_param: dict,
    encoder_param: dict,
    style_config: dict,
    force_render=False
):
    """生成所有视频片段的函数

    Args:
        resources (JSON): 视频配置数据
        video_output_path (str): 输出目录
        resolution (tuple): 视频分辨率
        v_bitrate_kbps (int): 视频码率
        encoder_param (dict): 编码器参数
        trans_time (int?): 过渡时间，单位秒。默认为 1 秒。
        force_render (bool?): 强制渲染。默认为 False。
        classic_fast_render (bool?): 使用标准渲染模式（MoviePy）。默认为 False。
    """
    resolution = encoder_param['resolution']
    # print(f"视频分辨率: {resolution}")
    bitrate = encoder_param['bitrate']
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
                    # clip = create_info_segment(config, resolution, font_path)
                    # clip = create_info_segment_optimized(config, encoder_param)
                    clip = create_info_segment(config, encoder_param, style_config)
                else:
                    print(f"开始处理[FFmpeg 快速]: {current_prefix}_{config['id']}({config['song_name']}).mp4")
                    # clip = create_video_segment(
                    #     config, 
                    #     resolution, 
                    #     font_path, 
                    #     v_bitrate_kbps,  # 第4个参数：bitrate
                    #     encoder_param    # 第5个参数：encoder_param
                    # )
                    clip = create_video_segment(
                        config, 
                        encoder_param, # 第 2 个参数：encoder_param
                        style_config,  # 第 3 个参数：style_config
                    )
                # print(f"正在处理视频片段: {current_prefix}_{config['id']}.mp4")

                clip = normalize_audio_volume(clip)                
                if trans_param['enabled']:
                    clip = clip.with_effects([
                        vfx.FadeIn(trans_param['duration']),
                        vfx.FadeOut(trans_param['duration']),
                        afx.AudioFadeIn(trans_param['duration']),
                        afx.AudioFadeOut(trans_param['duration'])
                    ])
                
                clip.write_videofile(
                    output_file,
                    fps=60,
                    threads=8,
                    codec="libx264",          # fallback: 使用 CPU 的 libx264 输出文件（硬件加速会导致 preset 或某些参数异常）
                    bitrate=f'{bitrate}k'
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

def combine_full_video_direct(video_clip_path, username):
    print("[信息] ==================== 开始拼接视频 ==================")
    video_files = [f for f in os.listdir(video_clip_path) if f.endswith(".mp4")]
    sorted_files = sort_video_files(video_files)
    
    if not sorted_files:
        raise ValueError("Error: 没有有效的视频片段文件！")
    
    try:
        # 1. 创建MP4文件列表
        mp4_list_file = os.path.join(video_clip_path, "mp4_files.txt")
        with open(mp4_list_file, 'w', encoding='utf-8') as f:
            for file in sorted_files:
                # 使用正斜杠替换反斜杠，并使用相对路径
                full_path = os.path.abspath(os.path.join(video_clip_path, file)).replace('\\', '/')
                f.write(f"file '{full_path}'\n")

        # 3. 拼接输出为 MP4
        output_path = os.path.join(video_clip_path, f"{username}_Best50.mp4")
        
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