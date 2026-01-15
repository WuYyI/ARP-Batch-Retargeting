import bpy
import os
from bpy.app.handlers import persistent

# ================= 配置区域 (User Configuration) =================
# 请根据实际情况修改以下路径
# Please update paths below

# 目标 .blend 文件
BLEND_FILE_PATH = r"C:\Path\To\Your\Input_Character.blend" 

# 源动作 .fbx 文件
FBX_FILE_PATH = r"C:\Path\To\Your\Source_Action.fbx"

# 输出文件
OUTPUT_FILE_PATH = r"C:\Path\To\Your\Output.blend"

# 预设名称 (Blender 4.2+ Extensions 路径下)
PRESET_NAME = "remap_preset_to_smal" 

# 源骨架旋转修正 (X, Y, Z)
SOURCE_ROTATION_EULER = (0, 0, 270)
# ===========================================================

def clean_source_bone_names(armature_obj):
    """清洗源骨架名称"""
    print(">>> 清洗源骨架名称...")
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='EDIT')
    for bone in armature_obj.data.edit_bones:
        if ":" in bone.name:
            bone.name = bone.name.split(":")[-1]
    bpy.ops.object.mode_set(mode='OBJECT')

@persistent
def retarget_logic(dummy):
    if retarget_logic in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(retarget_logic)
    
    # --- 环境准备 ---
    bpy.context.view_layer.update()
    if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.mode != 'OBJECT':
        try: bpy.ops.object.mode_set(mode='OBJECT')
        except: pass
    bpy.ops.object.select_all(action='DESELECT')
    
    existing_armatures = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']

    # --- 导入 FBX ---
    print(f"正在导入 FBX...")
    try:
        bpy.ops.import_scene.fbx(filepath=FBX_FILE_PATH, automatic_bone_orientation=True)
    except: return

    # --- 锁定源骨架 ---
    source_armature = None
    if bpy.context.selected_objects: source_armature = bpy.context.selected_objects[0]
    if not source_armature:
        all_objs = set(bpy.context.scene.objects)
        new_objs = [o for o in all_objs if o not in existing_armatures and o.type == 'ARMATURE']
        if new_objs: source_armature = new_objs[0]
    
    if not source_armature: 
        print("错误：找不到源骨架")
        return

    # --- 预处理 ---
    clean_source_bone_names(source_armature)
    
    if SOURCE_ROTATION_EULER != (0, 0, 0):
        import math
        source_armature.rotation_mode = 'XYZ'
        source_armature.rotation_euler[0] = math.radians(SOURCE_ROTATION_EULER[0])
        source_armature.rotation_euler[1] = math.radians(SOURCE_ROTATION_EULER[1])
        source_armature.rotation_euler[2] = math.radians(SOURCE_ROTATION_EULER[2])
        bpy.context.view_layer.update()
        bpy.ops.object.select_all(action='DESELECT')
        source_armature.select_set(True)
        bpy.context.view_layer.objects.active = source_armature
        bpy.ops.object.transform_apply(rotation=True)

    # 帧范围
    fs, fe = bpy.context.scene.frame_start, bpy.context.scene.frame_end
    if source_armature.animation_data and source_armature.animation_data.action:
        fs = int(source_armature.animation_data.action.frame_range[0])
        fe = int(source_armature.animation_data.action.frame_range[1])

    # --- 循环重定向 ---
    for target_armature in existing_armatures:
        if target_armature == source_armature: continue
        
        print(f"\nProcessing Target: {target_armature.name}")
        
        # 强制模式重置
        if bpy.context.view_layer.objects.active and bpy.context.view_layer.objects.active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        bpy.ops.object.select_all(action='DESELECT')
        target_armature.select_set(True)
        bpy.context.view_layer.objects.active = target_armature
        
        try:
            bpy.context.scene.source_rig = source_armature.name
            bpy.context.scene.target_rig = target_armature.name
            
            print("构建骨骼列表...")
            bpy.ops.arp.build_bones_list()
            
            print(f"尝试加载预设: {PRESET_NAME}")
            # ====================================================
            # 【核心修改】即使报错也继续执行
            # ====================================================
            try:
                bpy.ops.arp.import_config_preset(preset_name=PRESET_NAME)
                print(">>> 预设加载完美成功。")
            except RuntimeError as e:
                # 只要不是找不到文件，我们就认为是“部分骨骼未匹配”的正常警告
                print(f">>> 捕获到 ARP 警告 (通常是部分骨骼不匹配)，正在忽略并强行继续...")
                # 注意：这里去掉了 'continue'，让代码往下走！
            except Exception as e:
                print(f">>> 未知错误: {e}")
                print("尝试强行继续...")

            # 无论上面是否报错，都尝试执行后续步骤
            try: bpy.ops.arp.auto_scale()
            except: pass
            
            print("校准 Rest Pose...")
            bpy.ops.arp.redefine_rest_pose()
            bpy.ops.arp.save_pose_rest()
            
            print("Retargeting (Ignoring previous warnings)...")
            bpy.ops.arp.retarget(frame_start=fs, frame_end=fe)
            print(f">>> {target_armature.name} 处理完成。")
            
        except Exception as e:
            print(f"!!! 致命错误跳过: {e}")

    # --- 保存 ---
    try: bpy.data.objects.remove(source_armature, do_unlink=True)
    except: pass
    
    bpy.ops.wm.save_as_mainfile(filepath=OUTPUT_FILE_PATH)
    print("========== 全部完成 ==========")

def main():
    if os.path.exists(BLEND_FILE_PATH):
        bpy.app.handlers.load_post.clear()
        bpy.app.handlers.load_post.append(retarget_logic)
        bpy.ops.wm.open_mainfile(filepath=BLEND_FILE_PATH)

if __name__ == "__main__":
    main()