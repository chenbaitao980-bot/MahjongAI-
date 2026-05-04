#!/usr/bin/env python3
"""
快速诊断脚本：从截图文件测试完整识别流程。
用法：
    python debug_recognition.py <截图文件路径>

输出：
    - 手牌区域位置
    - HSV 分割出的每张牌 ROI 尺寸
    - 每张牌的最佳匹配结果 + top3 候选
    - 诊断图像保存到 debug_output/
"""
from __future__ import annotations
import sys
import os
import cv2
import numpy as np
import json

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vision.recognizer import TileRecognizer
from vision.layout import LayoutCalculator
from vision.capture import ScreenCapture
from vision.pipeline import RecognitionPipeline
from game.session import GameSession
from utils.paths import data_path, template_dir


def load_config():
    """加载 settings.yaml。"""
    import yaml
    config_path = os.path.join(data_path("config"), "settings.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def diagnose_image(image_path: str):
    config = load_config()
    gw = config.get("game_window", {})

    print(f"\n{'='*60}")
    print(f"诊断文件: {image_path}")
    print(f"{'='*60}")

    # 检查图片
    img = cv2.imread(image_path)
    if img is None:
        print(f"错误: 无法读取图片 {image_path}")
        return
    print(f"图片尺寸: {img.shape[1]}x{img.shape[0]}")

    # 检查 game_window 配置
    print(f"\n--- settings.yaml game_window ---")
    print(f"  top={gw.get('top')}, left={gw.get('left')}")
    print(f"  width={gw.get('width')}, height={gw.get('height')}")

    if not gw.get("width"):
        print("  ⚠️ 警告: game_window 未设置！请先在 UI 中框选游戏窗口。")
        return

    # 检查模板
    tile_dir = template_dir("tiles")
    hog_model_path = os.path.join(os.path.dirname(tile_dir), "..", "models", "tile_svm.xml")
    hog_model_path = os.path.normpath(os.path.abspath(hog_model_path))
    tile_rec = TileRecognizer(tile_dir, hog_model_path=hog_model_path)
    print(f"\n--- 模板状态 ---")
    print(f"  模板目录: {tile_dir}")
    print(f"  已加载: {len(tile_rec.loaded_tiles)} / 34 种")
    print(f"  阈值: {tile_rec.threshold}")
    if hasattr(tile_rec, '_hog_clf') and tile_rec._hog_clf and tile_rec._hog_clf.is_ready:
        print(f"  HOG 分类器: 已加载 ({tile_rec._hog_clf.n_classes} 类)")
    else:
        print(f"  HOG 分类器: 未加载")
    if tile_rec.loaded_tiles:
        print(f"  已收集: {', '.join(tile_rec.loaded_tiles)}")

    # 初始化布局计算器和截图
    layout = LayoutCalculator(config)
    capture = ScreenCapture(region={
        "top": gw.get("top", 0),
        "left": gw.get("left", 0),
        "width": gw["width"],
        "height": gw["height"],
    })

    # 手牌区域
    hand_rect = layout.hand_region(meld_count=0)
    print(f"\n--- 手牌区域 (relative to game_window) ---")
    print(f"  x={hand_rect.x}, y={hand_rect.y}, w={hand_rect.w}, h={hand_rect.h}")

    # 从图片裁剪手牌区域
    hand_strip = capture.grab_from_frame(img, hand_rect)
    print(f"  裁剪后尺寸: {hand_strip.shape[1]}x{hand_strip.shape[0]}")

    # 保存手牌区域供检查
    os.makedirs("debug_output", exist_ok=True)
    cv2.imwrite("debug_output/hand_strip.png", hand_strip)
    print(f"  已保存: debug_output/hand_strip.png")

    # HSV 分割
    hsv = cv2.cvtColor(hand_strip, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 160]), np.array([180, 60, 255]))
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    cv2.imwrite("debug_output/hand_mask.png", mask)
    print(f"  已保存: debug_output/hand_mask.png")

    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    print(f"\n--- HSV 连通域分割 ---")
    print(f"  总连通域数: {n-1}")

    candidates = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 2000:
            continue
        if not (40 <= w <= 130 and 55 <= h <= 140):
            continue
        candidates.append((x, y, w, h, area))

    print(f"  过滤后候选: {len(candidates)} 个")
    if not candidates:
        print("  ⚠️ 警告: 没有分割出任何牌！可能 HSV 范围不适合当前画面。")
        print("  建议: 检查 hand_strip.png 和 hand_mask.png，看牌面是否被正确掩码。")
        return

    candidates.sort(key=lambda t: t[0])

    # 逐个匹配
    print(f"\n--- 模板匹配结果 ---")
    for idx, (x, y, w, h, area) in enumerate(candidates):
        roi = hand_strip[y:y+h, x:x+w]
        roi_path = f"debug_output/roi_{idx}.png"
        cv2.imwrite(roi_path, roi)

        dbg = {}
        result = tile_rec.match_tile(roi, debug_info=dbg)

        name = result.tile_id or "未识别"
        print(f"\n  [{idx}] ROI: {w}x{h} @ ({x},{y}) area={area}")
        print(f"       最佳匹配: {name} (置信度 {result.confidence:.3f})")
        print(f"       ROI/模板比例: {dbg.get('avg_scale', 0):.2f}x")
        print(f"       尝试的 scales: {dbg.get('scales', [])}")

        top5 = dbg.get("top5_matches", [])
        if top5:
            print(f"       Top3 候选:")
            for m in top5[:3]:
                marker = " ✓" if m["tile_id"] == result.tile_id else ""
                print(f"         - {m['tile_id']}: {m['confidence']:.4f} (scale={m['best_scale']}){marker}")

    # 保存完整诊断报告
    report = {
        "image_path": image_path,
        "image_size": [img.shape[1], img.shape[0]],
        "game_window": gw,
        "hand_region": {"x": hand_rect.x, "y": hand_rect.y, "w": hand_rect.w, "h": hand_rect.h},
        "template_count": len(tile_rec.loaded_tiles),
        "templates": tile_rec.loaded_tiles,
        "roi_count": len(candidates),
        "rois": [],
    }
    for idx, (x, y, w, h, area) in enumerate(candidates):
        roi = hand_strip[y:y+h, x:x+w]
        dbg = {}
        result = tile_rec.match_tile(roi, debug_info=dbg)
        report["rois"].append({
            "index": idx,
            "x": int(x), "y": int(y), "w": int(w), "h": int(h), "area": int(area),
            "result_tile_id": result.tile_id,
            "result_confidence": round(result.confidence, 4),
            "avg_scale": round(dbg.get("avg_scale", 0), 3),
            "top5": dbg.get("top5_matches", []),
        })

    with open("debug_output/report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n  完整报告已保存: debug_output/report.json")
    print(f"\n{'='*60}")
    print("诊断完成。请检查 debug_output/ 目录下的图像和报告。")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python debug_recognition.py <截图文件路径>")
        print("示例: python debug_recognition.py data/screenshot.png")
        sys.exit(1)

    diagnose_image(sys.argv[1])
