import os, glob, json, traceback
import streamlit as st
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import *
from utils.DataUtils import *

def convert_old_files(folder, username, save_paths):
    """
    遍历文件夹下的所有json文件，将文件名中包含用户名的旧文件名转换为不包含用户名的格式。
    例如，将 "xxx_xxx_{username}_xxx.json" 重命名为 "xxx_xxx_xxx.json"。
    """
    files_to_rename = []
    patterns = [
        f"*_{username}_*.json",
        f"{username}_*.json",
        f"*_{username}.json"
    ]
    
    for pattern in patterns:
        files_to_rename.extend(glob.glob(os.path.join(folder, pattern)))
    
    files_to_rename = list(set(files_to_rename))  # 去重
    if not files_to_rename:
        print("未找到需要转换的文件。")

    for old_filename in files_to_rename:
        basename = os.path.basename(old_filename)
        # 移除.json后缀
        name_without_ext = os.path.splitext(basename)[0]
        
        # 直接替换文件名中的用户名部分
        if name_without_ext.endswith(f"_{username}"):
            new_name = name_without_ext[:-len(f"_{username}")]
        elif name_without_ext.startswith(f"{username}_"):
            new_name = name_without_ext[len(f"{username}_"):]
        else:
            new_name = name_without_ext.replace(f"_{username}_", "_")
        
        # 添加回.json后缀
        new_name = f"{new_name}.json"
        new_filename = os.path.join(folder, new_name)
        
        if new_filename != old_filename:
            os.rename(old_filename, new_filename)
            print(f"重命名完成: {basename} -> {new_name}")
        else:
            print(f"跳过文件: {basename} (无需修改)")
    st.success("文件名转换完成！", icon="✅")

    # 修改video_configs文件中的image path
    video_config_file = save_paths['video_config']
    print(video_config_file)
    if not os.path.exists(video_config_file):
        st.error("未找到video_config文件！请检查是否已将完整旧版数据文件复制到新的文件夹！", icon="❌")
        return
    try:
        video_config = load_config(video_config_file)
        main_clips = video_config['main']
        for each in main_clips:
            id = each['id']
            __image_path = os.path.join(save_paths['image_dir'], id + ".png")
            __image_path = os.path.normpath(__image_path)
            each['main_image'] = __image_path
        save_config(video_config_file, video_config)          
        st.success("配置信息转换完成！", icon="✅")
    except Exception as e:
        st.error(f"转换video_config文件时发生错误: {e}", icon="⚠️")

st.header("获取 / 管理 Best50 成绩与存档")

def check_username(input_username):
    # 检查用户名是否包含非法字符
    if any(char in input_username for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
        return escape_markdown_text(input_username), input_username
    else:
        return input_username, input_username
    
def read_raw_username(username):
    userinfo_file = os.path.join(get_user_base_dir(username), "user_info.json")
    # 优先从新系统读取
    if os.path.exists(userinfo_file):
        with open(userinfo_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("legacy_raw_username", data.get("username", username))

# 初始化会话状态
if 'use_lxns' not in st.session_state:
    st.session_state.use_lxns = False

username = st.session_state.get("username", None)
save_id = st.session_state.get('save_id', None)
friend_code = st.session_state.get("friend_code", None)

with st.container(border=True):
    input_username = st.text_input(
        "用户名 / 绑定 QQ 号（水鱼查分器所需）",
        value=username if username else "", 
        placeholder="建议用户名，便于辨认且方便水鱼查分"
    )
    
    # 添加复选框控制是否显示好友码输入框
    use_lxns = st.checkbox(
        "我使用落雪查分器（更新后请勿再次勾选，避免因反复更新导致好友码丢失）", 
        value=st.session_state.use_lxns,
        help="如果您使用落雪查分器作为数据源，请勾选此项"
    )
    
    # 根据复选框状态决定是否显示好友码输入框
    if use_lxns:
        # st.toast("若已经更新好友码，请勿再次勾选，避免因反复更新导致好友码丢失", icon="❗")
        col1, col2 = st.columns([0.75, 0.2], vertical_alignment='bottom')
        with col1:
            friend_code = st.text_input(
                "好友码（落雪查分器所需）",
                value=friend_code if friend_code else "",
                placeholder="使用落雪查分（首次）必须提供此项，否则查询将失败",
                help="""
                不知道好友码在哪？
                - 访问 [【账号详情】页](https://maimai.lxns.net/user/profile) 查看
                
                为什么我提供了好友码，仍然无法查询数据？
                - 请确保您在 [【账号设置】页](https://maimai.lxns.net/user/settings) 开启了所有读取权限
                """
            )
        with col2:
            if st.session_state.get('config_saved', False):
                # 已保存配置，显示更新按钮
                if st.button("更新好友码", use_container_width=True):
                    if not friend_code.strip():
                        st.toast("请输入好友码", icon="❌")
                    elif int(friend_code[:2]) == 99 or int(friend_code[:2]) != 10:
                        st.toast("请输入对应游戏的好友码", icon="❌")
                    else:
                        username = st.session_state.get("username")
                        if username:
                            userinfo_file = os.path.join(get_user_base_dir(username), "user_info.json")
                            if os.path.exists(userinfo_file):
                                with open(userinfo_file, 'r', encoding='utf-8') as f:
                                    user_info = json.load(f)
                                
                                # 更新好友码
                                user_info["friend_code"] = friend_code.strip()
                                
                                with open(userinfo_file, 'w', encoding='utf-8') as f:
                                    json.dump(user_info, f, indent=2, ensure_ascii=False)
                                
                                st.session_state.friend_code = friend_code.strip()
                                st.toast("好友码已更新！", icon="✅")
                            else:
                                st.toast("未找到用户信息文件", icon="❌")
                        else:
                            st.toast("未找到用户名", icon="❌")
    
    # 显示"确定"按钮（无论是否勾选落雪查分器）
    if st.button("确定", use_container_width=True):
        if not input_username:
            st.error("用户名不能为空！", icon="❌")
            st.session_state.config_saved = False
        else:  
            # 输入的 username 作为文件夹路径，需要去除非法字符；raw_username 为你的好友码，除非包含非法字符，否则与 username 相同
            username, raw_username = check_username(input_username)
            root_save_dir = get_user_base_dir(username)
            if not os.path.exists(root_save_dir):
                os.makedirs(root_save_dir, exist_ok=True)
            
            # 创建或更新 JSON 文件用于保存用户数据
            userinfo_file = os.path.join(root_save_dir, "user_info.json")
            user_info = {}
            
            # 如果用户信息文件已存在，先加载现有数据
            if os.path.exists(userinfo_file):
                with open(userinfo_file, 'r', encoding='utf-8') as f:
                    user_info = json.load(f)
            
            # 更新用户信息
            user_info["username"] = username
            
            # 只有在使用落雪查分器时才保存或更新好友码
            if use_lxns and friend_code[:2] == 10:
                user_info["friend_code"] = friend_code.strip()
            # 如果不使用落雪查分器，但之前有好友码，保留原有好友码
            elif "friend_code" in user_info:
                # 保留原有好友码，不做修改
                pass
            else:
                # 既不使用落雪查分器，也没有原有好友码，设置为空
                user_info["friend_code"] = ""
            
            # 保存用户信息
            with open(userinfo_file, 'w', encoding='utf-8') as f:
                json.dump(user_info, f, indent=2, ensure_ascii=False)
            
            st.toast("用户信息已保存！", icon="✅")
            st.session_state.update({
                "username": username,
                "friend_code": user_info.get("friend_code", ""),
                "use_lxns": use_lxns,
                "config_saved": True
            })

def update_b50(update_function, secret_identifier, save_paths, data_type):
    try:
        # 1. 强制加载用户名（完全隔离好友码）
        def get_safe_display_name():
            """从session_state或文件获取真实用户名，绝不使用传入的secret_identifier"""
            # 优先从session获取
            safe_name = st.session_state.get("username", None)
            if safe_name: 
                return safe_name
                
            # 次之从user_info.json获取
            user_info_path = os.path.join(get_user_base_dir(secret_identifier), "user_info.json")
            if os.path.exists(user_info_path):
                with open(user_info_path, 'r', encoding='utf-8') as f:
                    return json.load(f).get("username", "用户")
                    
            return "用户"  # 最终回退

        safe_name = get_safe_display_name()

        # 2. 执行数据获取（原逻辑不变）
        b50_data = update_function(save_paths['raw_file'], save_paths['data_file'], secret_identifier, data_type)
        
        # 3. 绝对安全显示
        st.success(f"已获取 {safe_name} 的游戏数据：{os.path.dirname(save_paths['data_file'])}")
        st.session_state.data_updated_step1 = True
        return b50_data

    except Exception as e:
        st.session_state.data_updated_step1 = False
        
        # 4. 错误信息核级过滤
        error_msg = str(e)
        filtered_msg = error_msg.replace(secret_identifier, "[已过滤]")  # 暴力替换所有可能泄露
        
        st.error(f"获取数据失败: {filtered_msg}")
        st.expander("详细错误信息（请将这部分内容拷贝或截图发给开发者）：").write(traceback.format_exc())  # 确保traceback也过滤
        return None

@st.dialog("删除存档？", width="medium")
def delete_save_data(username, save_id):
    version_dir = get_user_version_dir(username, save_id)
    st.write(f"您是要删除【{username} - {save_id}】吗？")
    st.warning("将清除所有已生成 Best50 底图和视频，且不可撤销！", icon="⚠️")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("是的！我要删除它！", icon="✔️", use_container_width=True):
            # 迭代地删除文件夹version_dir下的所有文件和子文件夹
            for root, dirs, files in os.walk(version_dir, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(version_dir)
            st.toast(f"已删除存档【{username} - {save_id}】", icon="✅")
            st.rerun()
    with col2:
        if st.button("不了，也许哪天会用？", icon="✖️", use_container_width=True):
            st.rerun()

def load_user_info(username):
    """从 user_info.json 加载用户数据到 session_state"""
    user_info_path = os.path.join(get_user_base_dir(username), "user_info.json")
    if os.path.exists(user_info_path):
        try:
            with open(user_info_path, "r", encoding="utf-8") as f:
                user_info = json.load(f)
                # 更新 session_state
                st.session_state.update({
                    "username": user_info.get("username", username),
                    "friend_code": user_info.get("friend_code", ""),
                    "use_lxns": bool(user_info.get("friend_code", "")),  # 如果有好友码，默认勾选使用落雪查分器
                })
                return True
        except Exception as e:
            st.error(f"加载用户信息失败: {e}", icon="❌")
            return False
    return False

st.divider()
if st.session_state.get('config_saved', False):
    raw_username = read_raw_username(username)

    st_init_cache_pathes()

    st.write("b50 存档读取 / 编辑")
    versions = get_user_versions(username)
    if versions:
        with st.container(border=True):
            st.info(f"新存档可能无法立刻显示，单击其他存档即可刷新。", icon="ℹ️")
            selected_save_id = st.selectbox(
                "选择一份已保存的存档",
                versions,
                format_func=lambda x: f"{username} - {x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y 年 %m 月 %d 日')})"
            )
            col1, col2, col3 = st.columns(3, gap="small")
            with col1:
                if st.button("加载此存档", icon="▶️", use_container_width=True):
                    if selected_save_id:
                        st.session_state.save_id = selected_save_id
                        if load_user_info(username):
                            st.toast("已加载您的存档。", icon="✅")
                            st.session_state.friend_code = friend_code
                            st.toast("同时您的好友码已恢复至生成器内，您现在可以获取落雪查分器数据了。", icon="ℹ️")
                        else:
                            st.warning("存档加载成功，但未找到用户信息（可能需要重新输入好友码）。", icon="⚠️")
                        st.session_state.data_updated_step1 = True
                    else:
                        st.error("未指定有效的存档路径！", icon="❌")
            with col2:
                version_dir = get_user_version_dir(username, selected_save_id)
                if st.button("打开文件夹", icon="📂", help=version_dir, use_container_width=True):
                    if os.path.exists(version_dir):
                        absolute_path = os.path.abspath(version_dir)
                    else:
                        absolute_path = os.path.abspath(os.path.dirname(version_dir))
                    open_file_explorer(absolute_path)
            with col3:
                if st.button("删除存档", icon="🗑️", use_container_width=True):
                    delete_save_data(username, selected_save_id)

    else:
        st.warning(f"{username} 还没有历史存档，请从下方获取新的 Best30 数据。", icon="⚠️")

    st.divider()
    st.write(f"新建 / 获取 b50 数据")
    st.info("""
            从下面选择您使用的查分器获取 Best50 数据，系统将为您创建存档。
            - 【水鱼】需关闭 [（禁止其他人查询我的成绩）](https://www.diving-fish.com/maimaidx/prober/#Profile)以允许用户名查询
            - 【落雪】加载存档后若下方未出现【已保存好友码】提示，请重新加载
            """, icon="ℹ️")
    with st.container(border=True):
        # st.warning("因当前开发分支限制，水鱼查分器数据源获取被禁用。", icon="⚠️")
        metadata_status = os.path.exists(music_info_path) and os.path.exists(jp_music_info_path)
        if not metadata_status:
            st.error("""
                    您的包体未拥有谱面数据，请回到首页下载！
                    - 刚下载的新包体**默认未携带谱面数据**，**已经用过但文件不存在**则可能是被误删
                    - 生成器任何操作**均基于此数据完成**，您*必须*要有这份数据后才能继续
                    """, icon="❗")
        with st.expander("我玩国服", icon="🔴"):
            col1, col2 = st.columns([1.25, .75])
            
            with col1:
                data_type = st.radio("获取数据类型",["全都要", "仅旧曲", "仅新曲"], index=0, disabled=not metadata_status, horizontal=True, key="select_data_type",
                                    help="您的包体未拥有谱面数据，请回到首页下载！" if not metadata_status else "此设置目前只影响国服（外服缺少测试数据）", captions=["Best30 + New20", "Only Best30", "Only New20"])
            
            with col2: 
                # 显示当前好友码状态（如果有）
                if st.session_state.get("friend_code"):
                    st.info(f"【落雪】已存好友码: ******{st.session_state.friend_code[11:]}", icon="ℹ️")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("从落雪查分器获取", help="您的包体未拥有谱面数据，请回到首页下载！" if not metadata_status else "将使用您的好友码作为验证参数向代理请求游戏数据",
                             icon="❄️", use_container_width=True, disabled=not metadata_status):
                    if not st.session_state.get("friend_code"):
                        st.error("未设置好友码！请在上方勾选'我使用落雪查分器'并输入您的好友码。", icon="❌")
                    else:
                        try:
                            current_paths = get_data_paths(username, timestamp=None)
                            save_dir = os.path.dirname(current_paths['data_file'])
                            save_id = os.path.basename(save_dir)
                            if save_id:
                                os.makedirs(save_dir, exist_ok=True)
                                st.session_state.save_id = save_id
                                with st.spinner("正在获取数据。"):
                                    update_b50(
                                        update_b50_data_lxns,
                                        st.session_state.friend_code,
                                        current_paths,
                                        data_type
                                    )
                        except Exception as e:
                            st.error(f"获取数据时发生错误: {e}", icon="❌")
            with col2:
                if st.button("从水鱼查分器获取", help="您的包体未拥有谱面数据，请回到首页下载！" if not metadata_status else "将使用您的用户名作为查询参数",
                             icon="🐟", use_container_width=True, disabled=not metadata_status):
                    current_paths = get_data_paths(username, timestamp=None)
                    save_dir = os.path.dirname(current_paths['data_file'])
                    save_id = os.path.basename(save_dir)
                    if save_id:
                        os.makedirs(save_dir, exist_ok=True)
                        st.session_state.save_id = save_id
                        with st.spinner("正在获取数据。"):
                            update_b50(
                                update_b50_data_fish,
                                raw_username,
                                current_paths,
                                data_type
                            )
        with st.expander("我玩外服（待开发）", icon="🔵"):
            st.info(f"""
                    请按照以下操作放入您的游戏数据：
                    - 将您获取的游戏数据保存为 `b30_raw.json`
                    - 将其放在您的用户目录【{username}】下
                    - 点击 “解析原始数据” 以开始解析
                    """, icon="ℹ️")
            st.warning("目前需要提供测试样本以用于测试，因此此功能仍在重新开发", icon="⚠️")


        col1, col2 = st.columns([.4, 1.6], gap="small", vertical_alignment="center")
        with col1:
            st.markdown("或者，您也可以")
        
        with col2:
            if st.button("新建空白存档", key="int_create_new_save", icon="📄", use_container_width=True, disabled=not metadata_status,
                         help="您的包体（目前）未拥有谱面数据，请回到首页下载！" if not metadata_status else "如果您目前没有可用于生成存档的数据，可生成空白存档（作为占位）"):
                current_paths = get_data_paths(username, timestamp=None)
                save_dir = os.path.dirname(current_paths['data_file'])
                save_id = os.path.basename(save_dir)
                os.makedirs(save_dir, exist_ok=True)
                st.session_state.save_id = save_id
                st.success(f"已新建空白存档！用户名：{username}，存档时间：{save_id}", icon="✅")
        
    if st.session_state.get('data_updated_step1', False):
        st.divider()
        col1, col2 = st.columns(2, gap="small", vertical_alignment="center")
        with col1:
            st.write("确认数据无误后，前往下一步准备生成底图。")
        
        with col2:
            if st.button("下一步", icon="➡️", help="您需要获取谱面数据后才能继续，因为您的存档依靠此数据生成" if not metadata_status else "", use_container_width=True, disabled=not metadata_status):
                st.switch_page("st_pages/Generate_Pic_Resources.py")
else:
    st.warning("请先确定用户名！", icon="⚠️")