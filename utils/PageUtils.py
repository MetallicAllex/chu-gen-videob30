import re, subprocess

def escape_markdown_text(text: str) -> str:
    # 更全面的转义，包括 Streamlit 可能需要的额外字符
    special_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(special_chars)}])', r'\\\1', text)

def remove_html_tags_and_invalid_chars(text: str) -> str:
    """去除字符串中的HTML标记和非法字符"""
    # 去除HTML标记
    clean = re.compile('<.*?>')
    text = re.sub(clean, ' ', text)
    
    # 去除非法字符
    invalid_chars = r'[<>:"/\\|?*【】]'  # 定义非法字符
    text = re.sub(invalid_chars, ' ', text)  # 替换为' '

    return text.strip()  # 去除首尾空白字符

def get_ffmpeg_version():
    try:
        # 调用 ffmpeg -version 命令
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              text=True, 
                              check=True)
        
        # 从输出中提取版本号
        version_match = re.search(r'ffmpeg version (\S+)', result.stdout)
        if version_match:
            return version_match.group(1)
        else:
            return "未找到版本信息"
            
    except FileNotFoundError:
        return "FFmpeg 未安装或不在 PATH 中"
    except subprocess.CalledProcessError as e:
        return f"命令执行错误: {e}"

def format_time_difference(seconds):
    """
    格式化时间差，隐藏为 0 的单位
    """
    if seconds < 1:
        return f"{seconds*1000:.1f}ms"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds_remaining = seconds % 60
    
    parts = []
    
    if hours > 0:
        parts.append(f" {hours} 小时")
    if minutes > 0:
        parts.append(f" {minutes} 分")
    if seconds_remaining > 0 or not parts:  # 如果没有其他单位，至少显示秒
        # 如果有更高级单位，秒取整；否则显示小数
        if parts:
            parts.append(f" {int(seconds_remaining)} 秒")
        else:
            parts.append(f" {seconds_remaining:.2f} 秒")
    
    return "".join(parts)