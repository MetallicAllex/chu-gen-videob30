import time
import os, traceback
import streamlit as st
from datetime import datetime
from utils.ImageUtils import render_all_images
from utils.Variables import font_path, image_root_path
from utils.PathUtils import read_global_config, save_config, load_config, get_data_paths, get_user_versions

st.header("Step 4-2: 片头/片尾内容编辑")

G_config = read_global_config()

### Savefile Management - Start ###
if "username" in st.session_state:
    st.session_state.username = st.session_state.username

if "save_id" in st.session_state:
    st.session_state.save_id = st.session_state.save_id

username = st.session_state.get("username", None)
save_id = st.session_state.get("save_id", None)
current_paths = None
data_loaded = False

@st.fragment
def edit_context_widget(name, config, config_file_path):
    # 创建一个container来容纳所有组件
    container = st.container(border=True)
    
    # 在session_state中存储当前配置列表
    if f"{name}_items" not in st.session_state:
        st.session_state[f"{name}_items"] = config[name]
    
    items = st.session_state[f"{name}_items"]
    
    with container:
        # 为每个元素创建编辑组件
        for idx, item in enumerate(items):
            with st.expander(f"{name} 展示：第 {idx + 1} 页", expanded=True, icon="⏮️" if name == "intro" else "⏭️"):
                # 添加版本选择器
                # list_versions = G_config.get("AVAILABLE_VERSION", [])
                # sel_version = st.radio(
                #     "选择背景播放的游戏版本",
                #     options=list_versions,
                #     index=list_versions.index(item["version"]) if item["version"] in list_versions else 0,
                #     key=f"{item['id']}_version",
                #     horizontal=True
                # )
                # 文本编辑框
                bg_col1, bg_col2, bg_col3 = st.columns(3)
                with bg_col1:
                    bg_page = st.checkbox("此页为背景板", help="可在此页展示您需要额外编辑的内容", key=f"{item['id']}_bg_page", value=item["bg_page"])
                with bg_col2:
                    no_overlay = st.checkbox("不需要底图", key=f"{item['id']}_overlay", help="此页非背景板时选项不可用" if not bg_page else "用于框定文本区域，若手动添加文字可自行决定是否保留", disabled=not bg_page, value=item["no_overlay"])
                with bg_col3:
                    no_sound = st.checkbox("不需要 BGM", key=f"{item['id']}_sound", help="在生成片段时不对此片段放入 bgm（如果您想使用自己的音乐作为 bgm，请勾选此项）", value=item["no_sound"])
                new_text = st.text_area(
                    "文本内容", item["text"],
                    key=f"{item['id']}_text",
                    help="若要添加其他内容请多留空白区域",
                    placeholder="输入要展示的文本（若作为背景板展示则不可输入）",
                    disabled=bg_page
                )
                # items[idx]["text"] = new_text
                # items[idx]["bg_page"] = info_page
                # items[idx]['version'] = sel_version

                scol1, scol2 = st.columns(2, vertical_alignment="bottom")
                with scol1:
                    st.subheader("时长(s)")
                with scol2:
                    new_duration = st.number_input("秒", min_value=0, max_value=30, value=item["duration"], step=1, key=f"{item['id']}_duration", label_visibility="collapsed")
                # 持续时间滑动条
                # new_duration = st.slider(
                #     "持续时间（秒）",
                #     min_value=5,
                #     max_value=30,
                #     value=item["duration"],
                #     key=f"{item['id']}_duration"
                # )
                items[idx]["text"] = new_text
                items[idx]["bg_page"] = bg_page
                items[idx]['no_overlay'] = no_overlay
                items[idx]['no_sound'] = no_sound
                items[idx]["duration"] = new_duration
                
        # 删除按钮（只有当列表长度大于 1 时才显示）
        if len(items) > 1:
            if st.button(f"删除第 {idx + 1} 页", key=f"delete_{name}", icon="🗑️", width='stretch'):
                items.pop()
                st.session_state[f"{name}_items"] = items
                st.rerun(scope="fragment")

        st.divider()

        col1, col2 = st.columns(2, vertical_alignment="bottom")
        with col1:
            # 添加新元素的按钮
            if st.button(f"添加一页", key=f"add_{name}", icon="➕", width='stretch'):
                new_item = {
                    "id": f"{name}_{len(items) + 1}",
                    "duration": 10,
                    "text": "",
                    "bg_page": False,
                    "no_overlay": False,
                    "no_sound": False
                    # "version": "LUMINOUS"
                }
                items.append(new_item)
                st.session_state[f"{name}_items"] = items
                st.rerun(scope="fragment")

        with col2:
            # 保存按钮
            if st.button("保存", key=f"save_{name}", icon="💾", width='stretch'):
                try:
                    # 更新配置
                    config[name] = items
                    ## 保存当前配置
                    save_config(config_file_path, config)
                    st.toast("配置已保存！", icon="✅")
                except Exception as e:
                    st.toast(f"保存失败：{str(e)}", icon="❌")
                    st.error(f"详细错误信息（请将这部分内容拷贝或截图发给开发者）：{traceback.format_exc()}", icon="❗")

# 在 edit_context_widget 函数后面添加这个新函数
@st.fragment
def video_settings_widget(config_file_path):
    """视频参数设置组件"""
    config = load_config(config_file_path)
    with st.expander("文本渲染参数", expanded=True, icon="📺"):
        setting_area = st.selectbox("选择要修改的区域", ["intro", "content"],
                    key="video_setting_area", help="intro 为开头片尾，content 为谱面确认")
        style_config = config['styleConfig'][setting_area]
        with st.expander("文本样式", icon="🔧", expanded=True):
            setting_col1, setting_col2, setting_col3 = st.columns(3)
            with setting_col1:
                # 设置 UI
                font_options = os.listdir(font_path)
                new_font = st.selectbox("字体", font_options, key="font_select", index=font_options.index(style_config['font']), 
                                        help=f"字体文件名，将其放在 {os.path.abspath(font_path)} 目录下")
                style_config['font'] = new_font
                
            with setting_col2:
                # 字体大小
                new_font_size = st.number_input(
                    "字体大小", min_value=1, step=1,
                    value=style_config["size"]
                )
                style_config["size"] = new_font_size

            with setting_col3:            
                # 颜色选择（RGB转Hex）
                current_color = style_config["color"]
                hex_color = f"#{current_color[0]:02x}{current_color[1]:02x}{current_color[2]:02x}"
                new_color = st.color_picker("文本颜色", hex_color)
                style_config["color"] = [
                    int(new_color[1:3], 16),
                    int(new_color[3:5], 16),
                    int(new_color[5:7], 16)
                ]
            
            stroke_settings = style_config['stroke']
            with st.expander("描边设置", icon="🖼️"):
                stroke_col1, stroke_col2, stroke_col3 = st.columns(3, vertical_alignment="center")
                with stroke_col1:
                    stroke_status = st.checkbox("启用文字描边", key="stroke_status", value=stroke_settings["enable"])
                    stroke_settings["enable"] = stroke_status
                with stroke_col2:
                    # 颜色选择（RGB转Hex）
                    stroke_current_color = stroke_settings["color"]
                    hex_color = f"#{stroke_current_color[0]:02x}{stroke_current_color[1]:02x}{stroke_current_color[2]:02x}"
                    stroke_new_color = st.color_picker("描边颜色", hex_color)
                    stroke_settings["color"] = [
                        int(stroke_new_color[1:3], 16),
                        int(stroke_new_color[3:5], 16),
                        int(stroke_new_color[5:7], 16)
                    ]
                with stroke_col3:
                    # 线宽
                    stroke_new_width = st.number_input(
                        "描边线宽", min_value=0, step=1,
                        value=stroke_settings["width"],
                        help="px（0 则不显示）"
                    )
                    stroke_settings["width"] = stroke_new_width
                    
        layout_config = config['layoutConfig'][setting_area]
        with st.expander(f"文本布局", icon="🔧", expanded=True):
            # st.write(layout_config)
            layout_col1, layout_col2 = st.columns(2)
            with layout_col1:
                col1, col2 = st.columns(2, vertical_alignment="center")
                with col1:
                    # 文本位置
                    new_width = st.number_input(
                        "宽度(px)", min_value=1, step=1,
                        value=layout_config["width"]
                    )
                    layout_config["width"] = new_width
                
                with col2:
                    new_line_spacing = st.number_input(
                        "行间距(px)", min_value=1, step=1,
                        value=layout_config["lineSpacing"]
                    )
                    layout_config["lineSpacing"] = new_line_spacing
                
                with st.expander("内边距"):
                    top, right, bottom, left = layout_config["padding"]
                    col1, col2 = st.columns(2, vertical_alignment="center")
                    with col1:
                        new_top = st.number_input("上(px)", min_value=0, step=1, value=top)
                        new_right = st.number_input("右(px)", min_value=0, step=1, value=right)
                    with col2:
                        new_bottom = st.number_input("下(px)", min_value=0, step=1, value=bottom)
                        new_left = st.number_input("左(px)", min_value=0, step=1, value=left)
                    layout_config["padding"] = (new_top, new_right, new_bottom, new_left)
                
            with layout_col2:
                col1, col2 = st.columns(2, vertical_alignment="center")
                with col1:
                    # 高度
                    auto_height = st.checkbox("自动计算高度", key="auto_height", 
                                            value=layout_config["autoHeight"], 
                                            help="若启用，则高度将自动适配内容")
                    layout_config["autoHeight"] = auto_height
                
                with col2:
                    # 文本位置
                    new_height = st.number_input(
                        "高度(px)", min_value=1, step=1,
                        value=layout_config["height"], disabled=auto_height
                    )
                    layout_config["height"] = new_height
                
                align_settings = layout_config['AlignConfig']
                with st.expander(f"对齐设置"):
                    horizontal_align = align_settings['horizontal']
                    new_horizontal_align = st.selectbox(
                        "水平对齐", ["left", "center", "right"],
                        key="horizontal_align", index=horizontal_align.index(horizontal_align)
                    )
                    align_settings['horizontal'] = new_horizontal_align
                    
                    vertical_align = align_settings['vertical']
                    new_vertical_align = st.selectbox(
                        "垂直对齐", ["top", "center", "bottom"],
                        key="vertical_align", index=vertical_align.index(vertical_align)
                    )
                    align_settings['vertical'] = new_vertical_align
                    
        # 保存按钮
        if st.button("保存到文件", key="save_video_config", icon="💾", use_container_width=True):
            try:
                save_config(config_file_path, config)
                st.toast("已保存到文件！", icon="✅")
            except Exception as e:
                st.toast(f"保存失败：{str(e)}", icon="❌")
                st.error(traceback.format_exc())
    
# def render_all_images(video_config_file, style_config_file_path, save_paths, force_regen=False):
#     """
#     一键生成所有图片（文字图 + 完整背景图）
    
#     Args:
#         video_config_file: 视频配置文件路径
#         style_config_file_path: 样式配置文件路径
#         save_paths: 保存路径配置
#         force_regen: 是否强制重新生成已存在的文件
#     """
#     from PIL import Image
    
#     def rgb_to_hex(rgb):
#         return '#{:02x}{:02x}{:02x}'.format(*[max(0, min(255, x)) for x in rgb])
    
#     def get_render_params(style, layout):
#         """提取渲染参数"""
#         return {
#             'font_path': os.path.join(font_path, style['font']),
#             'font_size': style['size'],
#             'color': rgb_to_hex(style['color']),
#             'stroke_color': rgb_to_hex(style['stroke']['color']) if style['stroke']['enable'] else None,
#             'stroke_width': style['stroke']['width'],
#             'width': layout['width'],
#             'padding': tuple(layout['padding']),
#             'line_spacing': layout['lineSpacing'],
#             'horizontal_align': layout['AlignConfig']['horizontal'],
#             'vertical_align': layout['AlignConfig']['vertical'],
#             'auto_height': layout['autoHeight'],
#         }
    
#     def merge_text_with_background(text_path, bg_path, output_path, position_ratio, bg_size=(1920, 1080)):
#         """合并单张文字图与背景图"""
#         background = Image.open(bg_path, 'r').convert("RGBA")
#         text_img = Image.open(text_path, 'r').convert("RGBA")
        
#         text_width, text_height = text_img.size
#         bg_width, bg_height = bg_size
        
#         x = int(bg_width * position_ratio[0])
#         y = int(bg_height * position_ratio[1])
#         x = max(0, min(x, bg_width - text_width))
#         y = max(0, min(y, bg_height - text_height))
        
#         background.paste(text_img, (x, y), text_img)
#         background.save(output_path, "PNG")
#         return output_path
    
#     try:
#         # 加载配置
#         style_data = load_config(style_config_file_path)
#         video_data = load_config(video_config_file)
        
#         if not style_data or not video_data:
#             st.error("配置文件加载失败！", icon="❌")
#             return [], []
        
#         styles = style_data['styleConfig']
#         layouts = style_data['layoutConfig']
#         theme = style_data['themes']
#         video_position = style_data['position']['video']
#         intro_position = video_position['intro']
#         content_position = video_position['content']
        
#         # 创建目录
#         image_root = save_paths['image_dir']
#         text_dir = os.path.join(image_root, 'text')
#         fullbg_dir = os.path.join(image_root, 'fullbg')
#         os.makedirs(text_dir, exist_ok=True)
#         os.makedirs(fullbg_dir, exist_ok=True)
        
#         # 准备背景路径
#         intro_bg_path = f"{image_root_path}/Base/intro/{theme}/IntroBase.png"
#         content_bg_dir = f"{image_root}/background"
        
#         # 渲染配置
#         render_configs = [
#             (video_data.get('intro', []), 'intro', get_render_params(styles['intro'], layouts['intro'])),
#             (video_data.get('ending', []), 'ending', get_render_params(styles['intro'], layouts['intro'])),
#             (video_data.get('main', []), 'main', get_render_params(styles['content'], layouts['content']))
#         ]
        
#         text_files = []
#         fullbg_files = []
#         skipped_count = 0
        
#         # 遍历渲染
#         for segments, seg_type, params in render_configs:
#             for seg in segments:
#                 text = seg.get('text', '')
#                 if not text or not text.strip():
#                     continue
                
#                 file_name = f"{seg['clip_id'] if seg_type == 'main' else seg['id']}.png"
                
#                 # 生成文件名和路径
#                 # if seg_type == 'main':
#                 #     file_name = f"{seg['clip_id']}.png"
#                 # else:
#                 #     file_name = f"{seg['id']}.png"
                
#                 text_path = os.path.join(text_dir, file_name)
#                 fullbg_path = os.path.join(fullbg_dir, file_name)
                
#                 # 检查是否需要跳过
#                 if not force_regen and os.path.exists(text_path) and os.path.exists(fullbg_path):
#                     skipped_count += 1
#                     text_files.append(text_path)
#                     fullbg_files.append(fullbg_path)
#                     continue
                
#                 # 生成文字图
#                 _, saved_text_path = render_text_to_image(
#                     text=text.strip(),
#                     output_path=text_path,
#                     **params
#                 )
#                 text_files.append(saved_text_path)
                
#                 # 合并背景图
#                 if seg_type == 'main':
#                     bg_path = os.path.join(content_bg_dir, file_name)
#                     if os.path.exists(bg_path):
#                         merge_text_with_background(
#                             saved_text_path,
#                             bg_path,
#                             fullbg_path,
#                             content_position
#                         )
#                         fullbg_files.append(fullbg_path)
#                     else:
#                         st.warning(f"背景图不存在，跳过合并: {file_name}")
#                 else:
#                     if os.path.exists(intro_bg_path):
#                         merge_text_with_background(
#                             saved_text_path,
#                             intro_bg_path,
#                             fullbg_path,
#                             intro_position
#                         )
#                         fullbg_files.append(fullbg_path)
#                     else:
#                         st.warning(f"Intro 背景图不存在，跳过合并: {file_name}", icon="⚠️")
        
#         # 显示结果
#         new_count = len(text_files) - skipped_count
#         if new_count > 0:
#             st.success(f"成功生成 {new_count} 张文字图 + {new_count} 张完整背景图", icon="✅")
#         if skipped_count > 0:
#             st.info(f"跳过已存在的 {skipped_count} 组图片", icon="⏭️")
        
#         return text_files, fullbg_files
        
#     except Exception as e:
#         st.error(f"生成失败：{str(e)}", icon="❌")
#         st.error(traceback.format_exc(), icon="❌")
#         return [], []

if not username:
    st.error("请先获取 Best50 存档！", icon="❌")
    st.stop()
    
with st.container(border=True):
    if save_id:
        # load save data
        current_paths = get_data_paths(username, save_id)
        data_loaded = True
        # st.write(f"当前存档【用户名：{username}，存档时间：{save_id}】")
        # 方案2：指标卡片式显示
        info_col1, info_col2 = st.columns([1.15, .85])
        with info_col1:
            st.metric(
                label="👤 当前用户",
                value=username
            )
        with info_col2:
            st.metric(
                label="⏰ 存档时间", 
                value=save_id
            )

        # 为了实现实时的小组件更新，文本框数据存储在session_state中，
        # 因此需要在读取存档的过程中更新
        video_config_file = current_paths['video_config']
        if not os.path.exists(video_config_file):
            st.error(f"未找到 {video_config_file} ，请检查前置步骤是否完成，以及 b50 存档数据完整性！", icon="❌")
            config = None
        else:
            config = load_config(video_config_file)
            for name in ["intro", "ending"]:
                st.session_state[f"{name}_items"] = config[name]
    else:
        st.warning("未索引到存档，请先加载存档数据！", icon="⚠️")

    with st.expander("更换 Best50 存档", icon="💾"):
        st.info("要更换不同用户的存档，请回到存档管理页指定其他用户名。", icon="ℹ️")
        versions = get_user_versions(username)
        if versions:
            save_col1, save_col2 = st.columns([1.25, .75])
            with save_col1:
                selected_save_id = st.selectbox(
                    "选择存档", versions, label_visibility="collapsed",
                    format_func=lambda x: f"{x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
                )
            with save_col2:
                if st.button("使用此存档", help="（只需要点击一次！）", width='stretch', icon="▶️"):
                    if selected_save_id:
                        st.session_state.save_id = selected_save_id
                        st.rerun()
                    else:
                        st.error("存档路径无效！", icon="❌")
        else:
            st.warning("未找到任何存档，请先在存档管理页获取！", icon="⚠️")
            st.stop()
    if not save_id:
        st.stop()
### Savefile Management - End ###

if config:
    st.write("添加想要展示的文字内容，每一页最多可以展示约 250 字")
    st.info("左右两侧填写完毕后，需要分别点击保存才可生效！", icon="ℹ️")

    # 分为两栏，左栏读取intro部分的配置，右栏读取outro部分的配置
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("片头")
        edit_context_widget("intro", config, video_config_file)
    with col2:
        st.subheader("片尾")
        edit_context_widget("ending", config, video_config_file)

# TODO: 在这里添加开头结尾和评论的文字图像预览功能
# 并且支持在此处预先生成需要使用的图像，将其存储在 (存档目录)/images/text 目录下
# 以背景板图像的相同名称保存，减少因命名混乱导致评论所在片段错误
# 同时在一定程度上可以解决无法显示 Emoji 的问题，并且加快渲染速度
# 能将节省下来的时间用于在最终的拼接视频步骤上添加转场过渡效果
    video_settings_widget(current_paths['custom_style'])  # 新增这一行
    # render_widget(video_config_file, current_paths['custom_style'], current_paths)
    with st.expander("图像预览", expanded=False, icon="🖼️"):
        st.info("""
                使用您当前存档的 Best #1 和片头图像作为预览，修改请在上方和上一页进行。
                - 片头/尾若以背景板展示，则下方不会显示片头/尾图像
                """, icon="ℹ️")
        col1, col2 = st.columns(2)
        with col1:
            if os.path.exists(f"{current_paths['image_dir']}/fullbg/Best_1.png"):
                st.image(f"{current_paths['image_dir']}/fullbg/Best_1.png",  caption="Best #1 预览")
            else:
                st.warning("未找到 Best #1 图像，将显示 Best #1 无文字版本！", icon="⚠️")
                st.image(f"{current_paths['image_dir']}/background/Best_1.png",  caption="Best #1（无文字）预览")
        with col2:
            if os.path.exists(f"{current_paths['image_dir']}/fullbg/intro_1.png"):
                st.image(f"{current_paths['image_dir']}/fullbg/intro_1.png",  caption="片头/尾预览")
            else:
                st.warning("未找到片头/尾图像，您是否【作为背景板展示】或【未渲染图像】！", icon="⚠️")
    st.divider()
    render_info, force_render_text, render_btn = st.columns([1, .35, .65])
    with render_info:
        st.write("【可选】预先生成所需的评论文本图像，可减少部分渲染时间。")
    with force_render_text:
        force_render = st.checkbox("强制重新生成", value=False, help="强制重新生成已存在的文件，无论其是否已存在。")
    with render_btn:
        if st.button("生成评论图", width='stretch', icon="🖼️", help="如果上方没有文字版图像预览，也请使用此按钮生成"):
            st.toast("正在生成图像。", icon="⏳")
            # render_text(video_config_file, current_paths['custom_style'], current_paths, force_render)
            render_all_images(video_config_file, current_paths['custom_style'], current_paths, force_render)
            time.sleep(3)
            st.rerun()
    col1, col2 = st.columns(2, vertical_alignment="center")
    with col1:
        st.write("配置完毕后，即可准备生成您的 Best30 视频")
    with col2:
        if st.button("下一步", width='stretch', icon="➡️"):
            st.switch_page("st_pages/6_Compostie_Videos.py")
else:
    st.warning("未找到视频生成生成配置！请检查是否完成了4-1！", icon="⚠️")
