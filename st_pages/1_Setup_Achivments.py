import os
import glob
import time
import json
import traceback
import streamlit as st
from datetime import datetime
from utils.PageUtils import *
from utils.PathUtils import *
from pre_gen import update_b30_data_lxns, update_b30_data_fish, st_init_cache_pathes

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

st.header("获取 / 管理 Best30 成绩与存档")

def check_username(input_username):
    # 检查用户名是否包含非法字符
    if any(char in input_username for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
        return remove_invalid_chars(input_username), input_username
    else:
        return input_username, input_username
    
def read_raw_username(username):
    userinfo_file = os.path.join(get_user_base_dir(username), "user_info.json")
    # 优先从新系统读取
    if os.path.exists(userinfo_file):
        with open(userinfo_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("legacy_raw_username", data.get("username", username))


username = st.session_state.get("username", None)
save_id = st.session_state.get('save_id', None)
token = st.session_state.get("lxns_token", None)
with st.container(border=True):
    input_username = st.text_input(
        "用户名 / 绑定 QQ 号（水鱼查分器所需）",
        value = username if username else "", placeholder="建议用户名，便于辨认且方便水鱼查分"
    )
    col1, col2 = st.columns([0.75, 0.2], vertical_alignment='bottom')
    with col1:
        input_token = st.text_input(
            "个人 API 密钥（落雪查分器所需）",
            value = token if token else "", type="password", placeholder="使用落雪查分（首次）必须提供此项，否则查询将失败"
        )
    with col2:
        if st.button("不知道在哪？", use_container_width=True, help="访问 [落雪查分器【账号详情 - 第三方应用】页](https://maimai.lxns.net/user/profile)，API 密钥框在本页底部"):
            st.toast("访问 [落雪查分器【账号详情 - 第三方应用】页](https://maimai.lxns.net/user/profile?tab=thirdparty)，API 密钥框在本页底部", icon="ℹ️")

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
            # 创建 JSON 文件用于保存用户数据和 Token
            userinfo_file = os.path.join(root_save_dir, "user_info.json")
            user_info = {
                "username": username,
                "lxns_token": input_token.strip(),  # 去除前后空格
            }
            if not os.path.exists(userinfo_file):
                with open(userinfo_file, 'w', encoding='utf-8') as f:
                    json.dump(user_info, f, indent=2, ensure_ascii=False)
            st.success("用户信息已保存！", icon="✅")
            st.session_state.update({
                "username": username,
                "lxns_token": input_token.strip(),
                "config_saved": True
            })
            st.session_state.config_saved = True  # 添加状态标记

def update_b30(update_function, secret_identifier, save_paths):
    try:
        # 1. 强制加载用户名（完全隔离Token）
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
        b30_data = update_function(save_paths['raw_file'], save_paths['data_file'], secret_identifier)
        
        # 3. 绝对安全显示
        st.success(f"已获取 {safe_name} 的 Best30 数据：{os.path.dirname(save_paths['data_file'])}")
        st.session_state.data_updated_step1 = True
        return b30_data

    except Exception as e:
        st.session_state.data_updated_step1 = False
        
        # 4. 错误信息核级过滤
        error_msg = str(e)
        filtered_msg = error_msg.replace(secret_identifier, "[已过滤]")  # 暴力替换所有可能泄露
        
        st.error(f"获取数据失败: {filtered_msg}")
        st.expander("详细错误信息（请将这部分内容拷贝或截图发给开发者）：").write(traceback.format_exc())  # 确保traceback也过滤
        return None


# def update_b30(update_function, username, save_paths):
#     try:
#         # 使用指定的方法读取B30数据
#         b30_data = update_function(save_paths['raw_file'], save_paths['data_file'], username)
#         st.success(f"已获取 {username} 的 Best30 数据！新的存档时间为：{os.path.dirname(save_paths['data_file'])}")
#         st.session_state.data_updated_step1 = True
#         return b30_data
#     except Exception as e:
#         st.session_state.data_updated_step1 = False
#         st.error(f"获取 Best30 数据时发生错误: {e}")
#         st.expander("错误详情").write(traceback.format_exc())
#         return None

# def check_save_available(username, save_id):
#     if not save_id:
#         return False
#     save_paths = get_data_paths(username, save_id)
#     return os.path.exists(save_paths['data_file'])

@st.dialog("删除存档？", width="medium")
def delete_save_data(username, save_id):
    version_dir = get_user_version_dir(username, save_id)
    st.warning(f"您是要删除存档【{username} - {save_id}】吗？将清除所有已生成 Best30 底图和视频，且不可撤销！", icon="⚠️")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("是的！确定要删除它！", icon="✔️", use_container_width=True):
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

# 仅在配置已保存时显示"开始预生成"按钮
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
                    "token": user_info.get("token", ""),
                })
                return True
        except Exception as e:
            st.error(f"加载用户信息失败: {e}")
            return False
    return False

if st.session_state.get('config_saved', False):
    raw_username = read_raw_username(username)

    st_init_cache_pathes()

    st.write("b30 存档读取 / 编辑")
    versions = get_user_versions(username)
    if versions:
        with st.container(border=True):
            st.write(f"新存档可能无法立刻显示，单击其他存档即可刷新。")
            st.warning("【落雪查分器】需要您的 API 密钥验证身份，因此您需要先加载存档", icon="⚠️")
            selected_save_id = st.selectbox(
                "选择一份已保存的存档",
                versions,
                format_func=lambda x: f"{username} - {x} ({datetime.strptime(x.split('_')[0], '%Y%m%d').strftime('%Y-%m-%d')})"
            )
            col1, col2, col3 = st.columns(3, gap="small")
            # with col1:
            #     if st.button("加载此存档数据"):
            #         if selected_save_id:
            #             print(selected_save_id)
            #             st.session_state.save_id = selected_save_id
            #             # st.success(f"已加载存档！用户名：{username}，存档时间：{selected_save_id}，可使用上方按钮加载和修改数据。")
            #             st.success(f"已加载此存档！用户名：{username}，存档时间：{selected_save_id}")
            #             st.session_state.data_updated_step1 = True                
            #         else:
            #             st.error("未指定有效的存档路径！")
            with col1:
                if st.button("加载此存档", icon="▶️", use_container_width=True):
                    if selected_save_id:
                        st.session_state.save_id = selected_save_id
                        # ✅ 新增：加载用户信息（包括 Token）
                        if load_user_info(username):
                            st.toast("已加载您的存档。", icon="✅")
                            st.toast("同时您的 Token 已恢复至生成器内，您现在可以获取落雪查分器数据了。", icon="ℹ️")
                        else:
                            st.warning("存档加载成功，但未找到用户信息（可能需要重新输入 Token）。")
                        st.session_state.data_updated_step1 = True
                    else:
                        st.error("未指定有效的存档路径！")
            with col2:
                version_dir = get_user_version_dir(username, selected_save_id)
                if st.button("打开文件夹", icon="📂", help=version_dir, use_container_width=True):
                    if os.path.exists(version_dir):
                        absolute_path = os.path.abspath(version_dir)
                    else:
                        absolute_path = os.path.abspath(os.path.dirname(version_dir))
                    open_file_explorer(absolute_path)
            # with col3:
            #     if st.button("查看 / 修改存档", key="edit_b30_data"):
            #         save_id = st.session_state.get('save_id', None)
            #         save_available = check_save_available(username, save_id)
            #         if save_available:
            #             edit_b30_data(username, save_id)
            #         else:
            #             st.error("未找到b30数据，请先读取存档，或生成新存档！")
            with col3:
                if st.button("删除存档", icon="🗑️", use_container_width=True):
                    delete_save_data(username, selected_save_id)

    else:
        st.warning(f"{username} 还没有历史存档，请从下方获取新的 Best30 数据。")

    st.write(f"新建 / 获取 b30 数据")
    with st.container(border=True):
        st.info(f"从下面选择您使用的查分器获取 Best30 数据，系统将为您创建存档。", icon="ℹ️")
        st.warning(f"水鱼需关闭【[禁止其他人查询我的成绩](https://www.diving-fish.com/maimaidx/prober/#Profile)】以允许用户名查询", icon="⚠️")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("从落雪查分器获取", help="将使用您的个人 API 密钥作为验证参数", icon="❄️", use_container_width=True):
                try:
                    current_paths = get_data_paths(username, timestamp=None)  # 获取新的存档路径
                    save_dir = os.path.dirname(current_paths['data_file'])
                    save_id = os.path.basename(save_dir)  # 从存档路径得到新存档的时间戳
                    token = st.session_state.token  # 只传递Token
                    username = st.session_state.username # 仅用于显示
                    if save_id:
                        os.makedirs(save_dir, exist_ok=True) # 新建存档文件夹
                        st.session_state.save_id = save_id
                        with st.spinner("正在获取 b30 数据..."):
                            update_b30(
                                update_b30_data_lxns,
                                token,
                                current_paths,
                            )
                except AttributeError:
                    st.error("未提供 Token，是存档还没加载？", icon="❌")
                    time.sleep(3)
                    st.rerun()
        with col2:
            if st.button("从水鱼查分器获取", help="将使用您的用户名作为查询参数", icon="🐟", use_container_width=True):
                current_paths = get_data_paths(username, timestamp=None)  # 获取新的存档路径
                save_dir = os.path.dirname(current_paths['data_file'])
                save_id = os.path.basename(save_dir)  # 从存档路径得到新存档的时间戳
                if save_id:
                    os.makedirs(save_dir, exist_ok=True) # 新建存档文件夹
                    st.session_state.save_id = save_id
                    with st.spinner("正在获取 b30 数据..."):
                        update_b30(
                            update_b30_data_fish,
                            raw_username,
                            current_paths,
                        )

        st.error("因外服缺少测试样本，且 VERSE [修改了 Best 机制](https://zh.moegirl.org.cn/CHUNITHM#Rating)，我们目前无法支持其导入数据", icon="❌")

        col1, col2 = st.columns(2, gap="small")
        with col1:
            st.markdown("如果您目前没有可用于生成存档的数据，可生成空白存档（作为占位使用）")
        
        with col2:
            if st.button("新建空白存档", key="dx_int_create_new_save", icon="📄", use_container_width=True):
                current_paths = get_data_paths(username, timestamp=None)  # 获取新的存档路径
                save_dir = os.path.dirname(current_paths['data_file'])
                save_id = os.path.basename(save_dir)  # 从存档路径得到新存档的时间戳
                os.makedirs(save_dir, exist_ok=True) # 新建存档文件夹
                st.session_state.save_id = save_id
                st.success(f"已新建空白存档！用户名：{username}，存档时间：{save_id}")


    if st.session_state.get('data_updated_step1', False):
        col1, col2 = st.columns(2, gap="small")
        with col1:
            st.write("确认数据无误后，前往下一步准备生成底图。")
        
        with col2:
            if st.button("下一步", icon="➡️", use_container_width=True):
                st.switch_page("st_pages/Generate_Pic_Resources.py")

else:
    st.warning("请先确定用户名！", icon="⚠️")
