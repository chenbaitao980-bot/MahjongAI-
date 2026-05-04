"""提取视频关键帧到本地，用于分析。"""
import cv2, os

VIDEO = r"C:\Users\67554\Documents\xwechat_files\wxid_tz4f0gzdrdy022_a355\msg\video\2026-05\2b3a4df0e027ff677929e9f92a510eba.mp4"
OUT = r"C:\MahjongAI\templates\debug_frames"
os.makedirs(OUT, exist_ok=True)

cap = cv2.VideoCapture(VIDEO)
fps = cap.get(cv2.CAP_PROP_FPS)

# 每10秒取一帧，另外加几个早期帧
targets = list(range(0, 85, 10)) + [3, 6, 15, 25, 45, 60, 75]
for sec in sorted(set(targets)):
    fidx = int(sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
    ret, frame = cap.read()
    if not ret:
        continue
    # 只保存手牌条带（y=440~592）
    strip = frame[440:592, :]
    path = os.path.join(OUT, f"sec{sec:02d}_f{fidx}.png")
    cv2.imwrite(path, strip)
    print(f"sec={sec} frame={fidx} -> {path}")

cap.release()
print("Done")
