#!/usr/bin/env python3
"""動画の中の「暗い無地の面に載った明るいロゴ」をフレームごとに消す。

暗い面（PCの天板など）を自動で見つけ、その内側に囲まれた明るい部分をロゴとみなして
周囲の色でなじませる。カメラや被写体が動いても追従する。

使い方: remove_logo_video.py <入力動画> <出力動画> [--start 秒] [--end 秒] [--dark 80] [--roi x,y,w,h] [--blur]
  --roi   処理してよい範囲。光沢のある小物など、対象外の物を巻き込まないために指定する
  --start この秒数から処理する
  --end   この秒数まで処理する（面が見えなくなる時刻。省略時は最後まで）
  --dark  「暗い面」とみなす明るさの上限（0-255）
  --blur  消さずにぼかす
"""
import argparse, os, subprocess, tempfile
import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("src"); p.add_argument("dst")
p.add_argument("--start", type=float, default=0.0)
p.add_argument("--end", type=float, default=1e9)
p.add_argument("--dark", type=int, default=80)
p.add_argument("--roi", help="処理してよい範囲 x,y,w,h。範囲外は一切変更しない（必ず指定を推奨）")
p.add_argument("--blur", action="store_true")
a = p.parse_args()

# 読み書きは ffmpeg に任せる（回転情報と色の扱いを ffmpeg の標準どおりにするため）
probe = subprocess.run(["ffmpeg", "-v", "error", "-i", a.src, "-frames:v", "1", "-f", "image2pipe",
                        "-vcodec", "png", "-"], capture_output=True, check=True).stdout
h, w = cv2.imdecode(np.frombuffer(probe, np.uint8), cv2.IMREAD_COLOR).shape[:2]
r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                    "stream=r_frame_rate", "-of", "csv=p=0", a.src], capture_output=True, text=True).stdout.strip().split(",")[0].split()[0]
num_, den_ = r.split("/")
fps = float(num_) / float(den_)
tmp = tempfile.mktemp(suffix=".mp4")
rd = subprocess.Popen(["ffmpeg", "-v", "error", "-i", a.src, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                      stdout=subprocess.PIPE)
wr = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                       "-r", r, "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", tmp],
                      stdin=subprocess.PIPE)
n = touched = 0
k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
while True:
    buf = rd.stdout.read(w * h * 3)
    if len(buf) < w * h * 3:
        break
    f = np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()
    if a.start <= n / fps <= a.end:
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        dark = (cv2.GaussianBlur(gray, (5, 5), 0) < a.dark).astype(np.uint8)
        num, lab, st, _ = cv2.connectedComponentsWithStats(dark)
        if num > 1:
            big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
            face = (lab == big).astype(np.uint8)
            # 面の外側を塗りつぶし、残った「面に囲まれた穴」をロゴとする
            ff = face.copy()
            cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 1)
            holes = (ff == 0).astype(np.uint8)
            if a.roi:
                rx, ry, rw, rh = (int(v) for v in a.roi.split(","))
                keep = np.zeros_like(holes); keep[ry:ry + rh, rx:rx + rw] = 1
                holes &= keep
            if holes.sum() < 0.08 * h * w and holes.any():
                mask = cv2.dilate(holes, k, iterations=2) * 255
                if a.blur:
                    f = np.where(mask[..., None] > 0, cv2.GaussianBlur(f, (71, 71), 0), f)
                else:
                    f = cv2.inpaint(f, mask, 5, cv2.INPAINT_TELEA)
                touched += 1
    wr.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
    n += 1
wr.stdin.close(); wr.wait(); rd.wait()
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-i", a.src, "-map", "0:v", "-map", "1:a?",
                "-c:v", "copy", "-c:a", "copy", a.dst], check=True)
os.remove(tmp)
print(f"{n} フレーム中 {touched} フレームを処理しました: {a.dst}")
