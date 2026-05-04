#!/usr/bin/env python3
"""诊断脚本：验证游戏窗口区域设置是否正确截取到手牌区域。"""
import os
import sys
import yaml
import cv2
import numpy as np
import mss

# 加载配置
config_path = os.path.join(os.path.dirname(__file__), "config", "settings.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

gw = config["game_window"]
layout = config["layout"]

print(f"游戏窗口设置: {gw['width']}×{gw['height']} @ ({gw['left']}, {gw['top']})")

# 计算手牌区域（像素坐标，相对于屏幕）
sh = layout["self_hand"]
hand_x = int(gw["left"] + sh["x"] * gw["width"])
hand_y = int(gw["top"] + sh["y"] * gw["height"])
hand_w = int(sh["w"] * gw["width"])
hand_h = int(sh["h"] * gw["height"])

print(f"手牌区域计算: x={hand_x}, y={hand_y}, w={hand_w}, h={hand_h}")

# 静默截取全屏
with mss.mss() as sct:
    shot = sct.grab(sct.monitors[1])
    arr = np.frombuffer(shot.raw, dtype=np.uint8)
    frame = arr.reshape((shot.height, shot.width, 4))[:, :, :3].copy()

print(f"全屏尺寸: {frame.shape[1]}×{frame.shape[0]}")

# 保存带标注的全屏截图（绿色框 = 手牌区域）
annotated = frame.copy()
cv2.rectangle(annotated, (hand_x, hand_y), (hand_x + hand_w, hand_y + hand_h), (0, 255, 0), 3)
cv2.putText(annotated, "HAND REGION", (hand_x, hand_y - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

# 裁剪手牌区域
hand_strip = frame[hand_y:hand_y+hand_h, hand_x:hand_x+hand_w]

# HSV 掩码分析（与 pipeline.py 一致）
hsv = cv2.cvtColor(hand_strip, cv2.COLOR_BGR2HSV)
mask = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 60, 255]))
k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)

mask_pixels = cv2.countNonZero(mask)
print(f"HSV mask 非零像素: {mask_pixels} / {mask.size} ({100.0*mask_pixels/mask.size:.1f}%)")

# 连通域分析
n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
candidates = []
for i in range(1, n):
    x, y, w, h, area = stats[i]
    if area >= 2000 and 40 <= w <= 130 and 55 <= h <= 140:
        candidates.append((x, y, w, h, area))
        print(f"  连通域 PASS: x={x} y={y} w={w} h={h} area={area}")
    else:
        print(f"  连通域 SKIP: x={x} y={y} w={w} h={h} area={area}")

print(f"\n总连通域: {n-1}, 通过过滤: {len(candidates)}")

# 保存诊断图像
out_dir = os.path.join(os.path.dirname(__file__), "diagnose_output")
os.makedirs(out_dir, exist_ok=True)

cv2.imwrite(os.path.join(out_dir, "01_fullscreen_annotated.png"), annotated)
cv2.imwrite(os.path.join(out_dir, "02_hand_strip.png"), hand_strip)
cv2.imwrite(os.path.join(out_dir, "03_hsv_mask.png"), mask)

# 在 mask 上标注连通域
mask_vis = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
for i, (x, y, w, h, area) in enumerate(candidates):
    cv2.rectangle(mask_vis, (x, y), (x+w, y+h), (0, 255, 0), 2)
    cv2.putText(mask_vis, str(i), (x, y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
cv2.imwrite(os.path.join(out_dir, "04_mask_with_boxes.png"), mask_vis)

print(f"\n诊断图像已保存到: {out_dir}")
print("请检查以下文件：")
print("  01_fullscreen_annotated.png — 绿色框是否准确框住你的手牌？")
print("  02_hand_strip.png — 截取到的内容是否确实是手牌？")
print("  03_hsv_mask.png — 白色牌面是否被检测为白色区域？")
print("  04_mask_with_boxes.png — 绿色框是否正确包围每张牌？")
