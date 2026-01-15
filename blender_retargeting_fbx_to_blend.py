import bpy
import os
import json
import math
from bpy.app.handlers import persistent

# ================= 配置区域 (User Configuration) =================
# 1. 输入：角色 Blend 文件所在的文件夹路径
INPUT_BLEND_DIR = r""

# 2. 输入：动作 FBX 文件所在的文件夹路径
INPUT_FBX_DIR = r""

# 3. 输出：结果保存的文件夹路径
OUTPUT_DIR = r""

# 4. 预设名称 (Blender 4.2+ Extensions 路径下)
PRESET_NAME = "remap_preset_to_smal" 

# 5. 源骨架旋转修正 (X, Y, Z)
SOURCE_ROTATION_EULER = (0, 0, 270)

# 临时任务文件路径 (用于在文件切换间存储进度，放在输出目录里)
QUEUE_FILE_PATH = os.path.join(OUTPUT_DIR, "batch_job_queue.json")
# ===========================================================

def clean_source_bone_names(armature_obj):
    """清洗源骨架名称"""
    print(">>> [Pre-process] Cleaning source bone names...")
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')
    for bone in armature_obj.data.edit_bones:
        if ":" in bone.name:
            bone.name = bone.name.split(":")[-1]
    bpy.ops.object.mode_set(mode='OBJECT')

def execute_retarget_task(fbx_path, preset_name, rotation_euler):
    """
    核心重定向逻辑 (针对当前打开的场景)
    """
    # 1. 环境清理
    bpy.context.view_layer.update()
    if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.mode != 'OBJECT':
        try: bpy.ops.object.mode_set(mode='OBJECT')
        except: pass
    bpy.ops.object.select_all(action='DESELECT')
    
    existing_armatures = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']

    # 2. 导入 FBX
    print(f">>> Importing FBX: {os.path.basename(fbx_path)}")
    try:
        bpy.ops.import_scene.fbx(filepath=fbx_path, automatic_bone_orientation=True)
    except Exception as e:
        print(f"!!! FBX Import Failed: {e}")
        return False

    # 3. 锁定源骨架
    source_armature = None
    if bpy.context.selected_objects: source_armature = bpy.context.selected_objects[0]
    if not source_armature:
        all_objs = set(bpy.context.scene.objects)
        new_objs = [o for o in all_objs if o not in existing_armatures and o.type == 'ARMATURE']
        if new_objs: source_armature = new_objs[0]
    
    if not source_armature: 
        print("!!! Error: Source armature not found.")
        return False

    # 4. 预处理
    clean_source_bone_names(source_armature)
    
    if rotation_euler != (0, 0, 0):
        source_armature.rotation_mode = 'XYZ'
        source_armature.rotation_euler[0] = math.radians(rotation_euler[0])
        source_armature.rotation_euler[1] = math.radians(rotation_euler[1])
        source_armature.rotation_euler[2] = math.radians(rotation_euler[2])
        bpy.context.view_layer.update()
        bpy.ops.object.select_all(action='DESELECT')
        source_armature.select_set(True)
        bpy.context.view_layer.objects.active = source_armature
        bpy.ops.object.transform_apply(rotation=True)

    # 5. 获取帧范围
    fs, fe = bpy.context.scene.frame_start, bpy.context.scene.frame_end
    if source_armature.animation_data and source_armature.animation_data.action:
        fs = int(source_armature.animation_data.action.frame_range[0])
        fe = int(source_armature.animation_data.action.frame_range[1])

    # 6. 循环重定向目标
    for target_armature in existing_armatures:
        if target_armature == source_armature: continue
        
        print(f">>> Processing Target Rig: {target_armature.name}")
        
        # Reset Mode
        if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        bpy.ops.object.select_all(action='DESELECT')
        target_armature.select_set(True)
        bpy.context.view_layer.objects.active = target_armature
        
        try:
            bpy.context.scene.source_rig = source_armature.name
            bpy.context.scene.target_rig = target_armature.name
            
            bpy.ops.arp.build_bones_list()
            
            try:
                bpy.ops.arp.import_config_preset(preset_name=preset_name)
            except RuntimeError:
                print("--- Warning: Preset mismatch (Ignored)")
            except Exception as e:
                print(f"--- Warning: Preset loading issue: {e}")

            try: bpy.ops.arp.auto_scale()
            except: pass
            
            bpy.ops.arp.redefine_rest_pose()
            bpy.ops.arp.save_pose_rest()
            
            print(">>> Retargeting...")
            bpy.ops.arp.retarget(frame_start=fs, frame_end=fe)
            
        except Exception as e:
            print(f"!!! Error on target {target_armature.name}: {e}")

    # 7. 清理源骨架
    try: bpy.data.objects.remove(source_armature, do_unlink=True)
    except: pass
    
    return True

@persistent
def job_processor(dummy):
    """
    任务处理器：每次文件加载后自动运行
    """
    # 1. 读取队列文件
    if not os.path.exists(QUEUE_FILE_PATH):
        print(">>> 队列文件不存在，批处理结束或未开始。")
        # 清理 handler 以免误触发
        if job_processor in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(job_processor)
        return

    try:
        with open(QUEUE_FILE_PATH, 'r', encoding='utf-8') as f:
            queue = json.load(f)
    except Exception as e:
        print(f"!!! 读取队列失败: {e}")
        return

    # 2. 检查队列是否为空
    if not queue:
        print("\n========== 所有任务处理完成！(Queue Finished) ==========")
        os.remove(QUEUE_FILE_PATH) # 删除临时文件
        if job_processor in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(job_processor)
        return

    # 3. 取出第一个任务
    current_job = queue[0]
    
    blend_path = current_job['blend']
    fbx_path = current_job['fbx']
    output_path = current_job['output']
    
    # 4. 判断当前打开的文件是否是任务需要的文件
    # 注意：路径规范化处理，避免斜杠方向不同导致判断错误
    current_blend_path = bpy.data.filepath
    
    if os.path.normpath(current_blend_path) != os.path.normpath(blend_path):
        print(f"\n>>> [Job Switch] 正在打开下一个 Blend 文件: {os.path.basename(blend_path)}")
        # 如果当前不是目标文件，则打开它
        # open_mainfile 会触发 load_post，再次调用这个函数，进入下面的 else 分支
        bpy.ops.wm.open_mainfile(filepath=blend_path)
        return

    else:
        # 5. 如果当前已经是目标文件，开始干活！
        print(f"\n>>> [Processing Job] {os.path.basename(blend_path)} + {os.path.basename(fbx_path)}")
        
        success = execute_retarget_task(fbx_path, PRESET_NAME, SOURCE_ROTATION_EULER)
        
        if success:
            print(f">>> Saving output to: {os.path.basename(output_path)}")
            bpy.ops.wm.save_as_mainfile(filepath=output_path)
        else:
            print("!!! Task failed, skipping save.")

        # 6. 任务完成，更新队列
        # 无论成功失败，都移除当前任务，避免死循环
        queue.pop(0)
        
        with open(QUEUE_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(queue, f, indent=2)

        # 7. 触发下一个循环
        # 无论队列里还是否有任务，我们都强制“重置”一下场景或者进入下个循环
        # 如果队列空了，下次进来会在步骤2结束
        # 如果队列还有任务，我们需要 open_mainfile 来加载（可能相同也可能不同的）Blend文件
        # 即使是同一个Blend文件，为了保证环境干净，重新打开一次也是最稳妥的
        
        if queue:
            next_blend = queue[0]['blend']
            print(f">>> 准备下一个任务... 打开: {os.path.basename(next_blend)}")
            bpy.ops.wm.open_mainfile(filepath=next_blend)
        else:
            # 最后一个任务刚做完，已经在步骤2里会处理退出，但为了触发它：
            # 我们重新加载当前保存的文件（或者新建一个空文件）来触发最后的完成提示
            print(">>> 触发最终清理...")
            bpy.ops.wm.read_homefile(app_template="") 

def bootstrap():
    """
    启动函数：扫描目录，生成任务队列，启动循环
    """
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # 1. 扫描文件
    blend_files = [os.path.join(INPUT_BLEND_DIR, f) for f in os.listdir(INPUT_BLEND_DIR) if f.lower().endswith('.blend')]
    fbx_files = [os.path.join(INPUT_FBX_DIR, f) for f in os.listdir(INPUT_FBX_DIR) if f.lower().endswith('.fbx')]

    if not blend_files:
        print("错误：Blend 输入目录为空")
        return
    if not fbx_files:
        print("错误：FBX 输入目录为空")
        return

    # 2. 生成任务列表 (笛卡尔积：每个Blend * 每个FBX)
    queue = []
    print(f">>> 扫描到 {len(blend_files)} 个角色文件 和 {len(fbx_files)} 个动作文件。")
    print(">>> 生成任务列表:")
    
    for b_path in blend_files:
        for f_path in fbx_files:
            b_name = os.path.splitext(os.path.basename(b_path))[0]
            f_name = os.path.splitext(os.path.basename(f_path))[0]
            
            # === 命名规则 ===
            # 规则: 角色名_动作名.blend
            out_name = f"{b_name}_{f_name}.blend"
            out_path = os.path.join(OUTPUT_DIR, out_name)
            
            job = {
                'blend': b_path,
                'fbx': f_path,
                'output': out_path
            }
            queue.append(job)
            print(f"  + Task: {out_name}")

    # 3. 保存队列到磁盘
    with open(QUEUE_FILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(queue, f, indent=2)

    print(f"\n>>> 任务队列已保存 ({len(queue)} 个任务)。开始执行...")

    # 4. 注册 Handler 并启动第一个任务
    # 先清理旧的，防止重复注册
    if job_processor in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(job_processor)
    
    bpy.app.handlers.load_post.append(job_processor)
    
    # 启动引擎：打开队列中第一个 Blend 文件
    # 这会触发 job_processor
    first_blend = queue[0]['blend']
    bpy.ops.wm.open_mainfile(filepath=first_blend)

if __name__ == "__main__":
    bootstrap()