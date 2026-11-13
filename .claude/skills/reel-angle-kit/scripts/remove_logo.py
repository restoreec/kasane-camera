#!/usr/bin/env python3
"""静止画のロゴを周囲の色でなじませて消す（無地に近い面向け）。

使い方: remove_logo.py <入力画像> <出力画像> --box x,y,w,h [--box ...] [--blur]
  --box  消したい範囲（左上x, 左上y, 幅, 高さ）。複数指定可。
  --blur 消さずにぼかすだけにする。
"""
import argparse
import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("src")
p.add_argument("dst")
p.add_argument("--box", action="append", required=True)
p.add_argument("--blur", action="store_true")
a = p.parse_args()

img = cv2.imread(a.src)
if img is None:
    raise SystemExit(f"画像を読めません: {a.src}")
mask = np.zeros(img.shape[:2], np.uint8)
for b in a.box:
    x, y, w, h = (int(v) for v in b.split(","))
    mask[y:y + h, x:x + w] = 255

if a.blur:
    k = max(31, (min(img.shape[:2]) // 12) | 1)
    out = np.where(mask[..., None] > 0, cv2.GaussianBlur(img, (k, k), 0), img)
else:
    out = cv2.inpaint(img, mask, 7, cv2.INPAINT_TELEA)
    # 塗りつぶし跡がのっぺりしないよう、周囲と同程度の粒状感を足す
    noise = np.random.default_rng(0).normal(0, 1.5, img.shape)
    out = np.where(mask[..., None] > 0, np.clip(out + noise, 0, 255), out).astype(np.uint8)
cv2.imwrite(a.dst, out, [cv2.IMWRITE_JPEG_QUALITY, 95])
print(f"保存しました: {a.dst}")
