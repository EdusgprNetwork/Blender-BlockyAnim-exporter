import bpy
import json
from math import acos
from mathutils import Vector, Quaternion
from bpy_extras import anim_utils

#
# Script Made by Edrax (EdraxDoodles)
# Please credit if used pls pls pls I want a job
#

# =====================================================
# CONFIG
# =====================================================
OUTPUT_PATH = bpy.path.abspath("//export.blockyanim")

INTERP = "smooth"

TARGET_FPS = 60  # Blockbench FPS target

POS_EPS = 1e-5
ROT_EPS = 1e-5
SCALE_EPS = 1e-5

POS_QUANT = 1e-4
ROT_QUANT = 1e-5
SCALE_QUANT = 1e-4

FLOAT_EPS = 1e-9
FLOAT_DECIMALS = 6
IDENTITY_SCALE = Vector((1.0, 1.0, 1.0))

# =====================================================
# FLOAT CLEANUP (NO SCIENTIFIC NOTATION)
# =====================================================
def clean_float(v):
    if abs(v) < FLOAT_EPS:
        return 0.0
    return round(v, FLOAT_DECIMALS)

def clean_vec3(v):
    return {
        "x": clean_float(v.x),
        "y": clean_float(v.y),
        "z": clean_float(v.z),
    }

def clean_quat(q):
    return {
        "x": clean_float(q.x),
        "y": clean_float(q.y),
        "z": clean_float(q.z),
        "w": clean_float(q.w),
    }

# =====================================================
# QUANTIZATION (KILLS BAKED NOISE)
# =====================================================
def quantize(v, step):
    return round(v / step) * step

def quant_vec3(v):
    return Vector((
        quantize(v.x, POS_QUANT),
        quantize(v.y, POS_QUANT),
        quantize(v.z, POS_QUANT),
    ))

def quant_quat(q):
    q = q.normalized()
    return Quaternion((
        quantize(q.w, ROT_QUANT),
        quantize(q.x, ROT_QUANT),
        quantize(q.y, ROT_QUANT),
        quantize(q.z, ROT_QUANT),
    )).normalized()
    
def quant_scale(v):
    return Vector((
        quantize(v.x, SCALE_QUANT),
        quantize(v.y, SCALE_QUANT),
        quantize(v.z, SCALE_QUANT),
    ))

# =====================================================
# VALIDATION
# =====================================================
obj = bpy.context.active_object
if not obj or obj.type != "ARMATURE":
    raise RuntimeError("Select an Armature object in Object Mode")

anim = obj.animation_data
if not anim or not anim.action or not anim.action_slot:
    raise RuntimeError("No active action / slot")

action = anim.action
slot = anim.action_slot
scene = bpy.context.scene

# FPS conversion
BLENDER_FPS = scene.render.fps
TIME_MULT = TARGET_FPS / BLENDER_FPS

start = int(action.frame_range[0])
end = int(action.frame_range[1])
duration = (end - start) * TIME_MULT

# =====================================================
# CHANNELBAG (BLENDER 5.0+)
# =====================================================
channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)

# =====================================================
# COLLECT BONES + THEIR KEYFRAMES
# =====================================================
bone_frames = {}

for fcurve in channelbag.fcurves:
    dp = fcurve.data_path
    if not dp.startswith('pose.bones["'):
        continue

    bone = dp.split('"')[1]
    bone_frames.setdefault(bone, set())

    for kp in fcurve.keyframe_points:
        bone_frames[bone].add(int(round(kp.co.x)))

# =====================================================
# ROTATION COMPARISON
# =====================================================
IDENTITY_LOC = Vector((0.0, 0.0, 0.0))
IDENTITY_ROT = Quaternion((1.0, 0.0, 0.0, 0.0))

def quat_angle(q1, q2):
    d = abs(q1.dot(q2))
    d = max(-1.0, min(1.0, d))
    return acos(d) * 2.0

# =====================================================
# EXPORT
# =====================================================
node_animations = {}

for bone_name, frames in bone_frames.items():
    pbone = obj.pose.bones.get(bone_name)
    if not pbone:
        continue

    frames = sorted(frames)

    prev_loc = None
    prev_rot = None
    prev_scale = None
    
    pos_keys = []
    rot_keys = []
    scale_keys = []

    for frame in frames:
        scene.frame_set(frame)

        # TRUE LOCAL ANIMATION (NO PARENT INFLUENCE)
        basis = pbone.matrix_basis.copy()

        loc = quant_vec3(basis.to_translation())
        rot = quant_quat(basis.to_quaternion())
        scale = quant_scale(basis.to_scale())
        
        t = (frame - start) * TIME_MULT

        # ---------- POSITION ----------
        if prev_loc is None:
            if (loc - IDENTITY_LOC).length > POS_EPS:
                pos_keys.append((t, loc.copy()))
                prev_loc = loc.copy()
        else:
            if (loc - prev_loc).length > POS_EPS:
                pos_keys.append((t, loc.copy()))
                prev_loc = loc.copy()
        # ---------- SCALE ----------
        if prev_scale is None:
            if (scale - IDENTITY_SCALE).length > SCALE_EPS:
                scale_keys.append((t, scale.copy()))
                prev_scale = scale.copy()
        else:
            if (scale - prev_scale).length > SCALE_EPS:
                scale_keys.append((t, scale.copy()))
                prev_scale = scale.copy()
        # ---------- ROTATION ----------
        if prev_rot is None:
            if quat_angle(IDENTITY_ROT, rot) > ROT_EPS:
                rot_keys.append((t, rot.copy()))
                prev_rot = rot.copy()
        else:
            if quat_angle(prev_rot, rot) > ROT_EPS:
                rot_keys.append((t, rot.copy()))
                prev_rot = rot.copy()

    if not pos_keys and not rot_keys and not scale_keys:
        continue

    node_animations[bone_name] = {
        "scale": [
            {
                "time": t,
                "delta": clean_vec3(v),
                "interpolationType": INTERP
            }
            for t, v in scale_keys
        ],
        "position": [
            {
                "time": t,
                "delta": clean_vec3(v*64),
                "interpolationType": INTERP
            }
            for t, v in pos_keys
        ],
        "orientation": [
            {
                "time": t,
                "delta": clean_quat(q),
                "interpolationType": INTERP
            }
            for t, q in rot_keys
        ],
        "shapeStretch": [],
        "shapeVisible": [],
        "shapeUvOffset": []
    }

# =====================================================
# WRITE JSON
# =====================================================
export_data = {
    "formatVersion": 1,
    "duration": duration,
    "holdLastKeyframe": False,
    "nodeAnimations": node_animations
}

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(export_data, f, indent=4)

print(f"Exported animation @ {TARGET_FPS}fps → {OUTPUT_PATH}")

