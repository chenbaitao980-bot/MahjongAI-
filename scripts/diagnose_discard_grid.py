"""
弃牌区网格诊断脚本。
把配置的网格格子叠加画到最新 session 的关键帧截图上，
保存到 data/discard_grid_debug.png，方便肉眼校准坐标。
"""
import os, sys, json, cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.paths import data_path
from game.session import GameSession

# ------------------------------------------------------------------ #
# 找最新 session 的 keyframe 截图
# ------------------------------------------------------------------ #
data_root = data_path("data")
sessions = GameSession.list_sessions(data_root)
if not sessions:
    print("没有找到 session 目录")
    sys.exit(1)

latest = sessions[0]
kf_path = os.path.join(data_root, latest, "keyframes", "frame_0000.png")
if not os.path.exists(kf_path):
    print(f"找不到关键帧: {kf_path}")
    sys.exit(1)

frame = cv2.imread(kf_path)
if frame is None:
    print("读取截图失败")
    sys.exit(1)

h_win, w_win = frame.shape[:2]
print(f"截图尺寸: {w_win} x {h_win}")

# ------------------------------------------------------------------ #
# 读取配置
# ------------------------------------------------------------------ #
import yaml
cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml")
with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

layout = cfg.get("layout", {})
discard_cfg = layout.get("discard", {})

seats = {
    "self":   (discard_cfg.get("self",   {}), (255, 80,  0)),    # 橙色
    "across": (discard_cfg.get("across", {}), (0,   200, 0)),    # 绿色
    "right":  (discard_cfg.get("right",  {}), (0,   0,   255)),  # 红色
    "left":   (discard_cfg.get("left",   {}), (255, 0,   255)),  # 紫色
}

vis = frame.copy()

for seat_name, (dc, color) in seats.items():
    rx  = dc.get("x", 0)
    ry  = dc.get("y", 0)
    rw  = dc.get("w", 0)
    rh  = dc.get("h", 0)
    cols = dc.get("cols", 1)
    rows = dc.get("rows", 1)

    # 像素坐标
    px  = int(rx * w_win)
    py  = int(ry * h_win)
    pw  = int(rw * w_win)
    ph  = int(rh * h_win)
    cw  = pw // cols
    ch  = ph // rows

    # 画整体边框（粗）
    cv2.rectangle(vis, (px, py), (px + pw, py + ph), color, 3)

    # 画每个格子（细）
    for r in range(rows):
        for c in range(cols):
            x0 = px + c * cw
            y0 = py + r * ch
            x1 = x0 + cw
            y1 = y0 + ch
            cv2.rectangle(vis, (x0, y0), (x1, y1), color, 1)
            # 标注 slot 编号
            idx = r * cols + c
            if idx < 6:  # 只标前几个格子，避免拥挤
                cv2.putText(vis, str(idx), (x0 + 2, y0 + 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

    # 标注座位名称
    label = f"{seat_name} ({cols}x{rows})"
    cv2.putText(vis, label, (px + 4, py - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    print(f"[{seat_name}] 像素区域: x={px}, y={py}, w={pw}, h={ph}, "
          f"格子={cw}x{ch}, 共 {cols*rows} 格")

# ------------------------------------------------------------------ #
# 保存
# ------------------------------------------------------------------ #
out = os.path.join(data_root, "discard_grid_debug.png")
cv2.imwrite(out, vis)
print(f"\n已保存诊断图: {out}")
print("用图片查看器打开，检查各座位的格子 slot-0 是否对准牌的左上角。")
