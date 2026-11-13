#!/usr/bin/env python3
"""暗い物体の上にある白く細い線（ロゴの線など）を、指定した時間帯だけ消す。

物体が大きく動いていて remove_logo_video.py で消し残した数フレーム向け。
その時間帯は物体上の白い細字（キーの文字など）もまとめて消える点に注意。

使い方: remove_thin_marks_video.py <入力動画> <出力動画> <開始秒> <終了秒> [--dark 80] [--roi x,y,w,h]
"""
import argparse, os, subprocess, tempfile
import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("src"); p.add_argument("dst"); p.add_argument("t0", type=float); p.add_argument("t1", type=float)
p.add_argument("--dark", type=int, default=80)
p.add_argument("--thresh", type=int, default=14, help="線とみなす明るさの差。薄い線が残るときは下げる")
p.add_argument("--roi", help="処理してよい範囲 x,y,w,h。範囲外は一切変更しない（必ず指定を推奨）")
a = p.parse_args()
probe = subprocess.run(["ffmpeg", "-v", "error", "-i", a.src, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                       capture_output=True, check=True).stdout
H, W = cv2.imdecode(np.frombuffer(probe, np.uint8), cv2.IMREAD_COLOR).shape[:2]
rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                       "-of", "csv=p=0", a.src], capture_output=True, text=True).stdout.strip().split(",")[0]
fps = float(rate.split("/")[0]) / float(rate.split("/")[1])
tmp = tempfile.mktemp(suffix=".mp4")
rd = subprocess.Popen(["ffmpeg", "-v", "error", "-i", a.src, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
wr = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", rate,
                       "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
k = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
n = touched = 0
while True:
    b = rd.stdout.read(W * H * 3)
    if len(b) < W * H * 3:
        break
    f = np.frombuffer(b, np.uint8).reshape(H, W, 3).copy()
    if a.t0 <= n / fps <= a.t1:
        ycc = cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)
        Y = ycc[..., 0]
        dark = (cv2.GaussianBlur(Y, (5, 5), 0) < a.dark).astype(np.uint8)
        num, lab, st, _ = cv2.connectedComponentsWithStats(dark)
        if num > 1:
            big = (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
            body = cv2.erode(cv2.morphologyEx(big, cv2.MORPH_CLOSE, k(25)), k(4))  # 細い線は本体の一部として埋まる
            top = cv2.morphologyEx(Y, cv2.MORPH_TOPHAT, k(9))
            neutral = (np.abs(ycc[..., 1].astype(int) - 128) < 12) & (np.abs(ycc[..., 2].astype(int) - 128) < 12)
            mask = ((top > a.thresh) & neutral & (body > 0)).astype(np.uint8)
            if a.roi:
                rx, ry, rw, rh = (int(v) for v in a.roi.split(","))
                keep = np.zeros_like(mask); keep[ry:ry + rh, rx:rx + rw] = 1
                mask &= keep
            if mask.any():
                f = cv2.inpaint(f, cv2.dilate(mask, k(3)) * 255, 5, cv2.INPAINT_TELEA)
                touched += 1
    wr.stdin.write(f.tobytes())
    n += 1
wr.stdin.close(); wr.wait(); rd.wait()
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-i", a.src, "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", a.dst], check=True)
os.remove(tmp)
print(f"{touched} フレームを処理しました: {a.dst}")
