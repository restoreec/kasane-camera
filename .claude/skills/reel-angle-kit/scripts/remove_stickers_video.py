#!/usr/bin/env python3
"""動画の中のシールや小さなロゴを、カメラの動きに追従しながら本体の色で塗りつぶして消す。

基準フレーム上で消したい範囲（多角形）を指定すると、平らな面（PCのキーボード面など）の
動きを追いかけて全フレームに当てはめる。手や指（肌色）は塗らない。

使い方: remove_stickers_video.py <入力動画> <出力動画> <設定.json>
設定.json:
  {"ref": 6.0,                      基準フレームの時刻（秒）
   "start": 4.3,                    処理を始める時刻（秒）
   "plane": [[x,y],...],            追従に使う平らな面の範囲（基準フレーム上）
   "rois": [{"name": "...", "poly": [[x,y],...],
             "mode": "all" | "bright" | "darkfill", "margin": 8, "skin": true, "skin_cr": 138, "start": 4.8}]}
  min_cover: 範囲のうちこの割合以上が対象として見えているときだけ塗る（既定 0.3）
  beige: true にすると、肌色に近いベージュのシールと指を黄みの強さで見分ける
  start: その範囲だけ処理開始を遅らせる / skin_cr: 肌色とみなす赤みの下限（大きいほど肌と判定しにくい）
  skin: false にすると肌色の保護を切る（赤・橙のシールで、手が重ならない範囲向け）
  mode: all=範囲全体を塗る / bright=周囲より明るい部分だけ塗る / darkfill=範囲内の暗い色で塗る
"""
import json, os, subprocess, sys, tempfile
import cv2
import numpy as np

src, dst, cfgp = sys.argv[1:4]
cfg = json.load(open(cfgp))


def ff(*a, **k):
    return subprocess.run(["ffmpeg", "-v", "error", *a], check=True, **k)


probe = ff("-i", src, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-", capture_output=True).stdout
H, W = cv2.imdecode(np.frombuffer(probe, np.uint8), cv2.IMREAD_COLOR).shape[:2]
rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                       "-of", "csv=p=0", src], capture_output=True, text=True).stdout.strip().split(",")[0]
fps = float(rate.split("/")[0]) / float(rate.split("/")[1])


def frames(pix, ch):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", pix, "-"],
                         stdout=subprocess.PIPE)
    n = W * H * ch
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape((H, W, ch) if ch > 1 else (H, W))
    p.wait()


# --- 1回目: 面の動き（基準フレーム→各フレームの変換）を求める
i_ref, i_start = round(cfg["ref"] * fps), round(cfg["start"] * fps)
grays = {i: g.copy() for i, g in enumerate(frames("gray", 1)) if i >= i_start}
N = max(grays) + 1
plane = np.array(cfg["plane"], np.float32)
lk = dict(winSize=(31, 31), maxLevel=4, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))


def step(g0, g1, Hprev):
    m = np.zeros((H, W), np.uint8)
    cv2.fillPoly(m, [cv2.perspectiveTransform(plane[None], Hprev)[0].astype(np.int32)], 255)
    p0 = cv2.goodFeaturesToTrack(g0, 600, 0.01, 7, mask=m)
    if p0 is None or len(p0) < 12:
        return Hprev
    p1, st, _ = cv2.calcOpticalFlowPyrLK(g0, g1, p0, None, **lk)
    b0, st2, _ = cv2.calcOpticalFlowPyrLK(g1, g0, p1, None, **lk)
    ok = (st.ravel() == 1) & (st2.ravel() == 1) & (np.linalg.norm((p0 - b0).reshape(-1, 2), axis=1) < 1.0)
    if ok.sum() < 12:
        return Hprev
    Hs, _ = cv2.findHomography(p0[ok], p1[ok], cv2.RANSAC, 2.0)
    return Hprev if Hs is None else Hs @ Hprev


Hs = {i_ref: np.eye(3)}
for i in range(i_ref + 1, N):
    Hs[i] = step(grays[i - 1], grays[i], Hs[i - 1])
for i in range(i_ref - 1, i_start - 1, -1):
    Hs[i] = step(grays[i + 1], grays[i], Hs[i + 1])
del grays

# --- 2回目: 各フレームで範囲を塗りつぶす
tmp = tempfile.mktemp(suffix=".mp4")
wr = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", rate,
                       "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
yy, xx = np.mgrid[0:H, 0:W]
# 粒状感は毎フレーム変えると「ちらつき」に見えるため、固定の模様を弱くかける
grain = np.random.default_rng(0).normal(0, 0.6, (H, W, 1)).astype(np.float32)
state = {}   # 範囲ごとの、前フレームの塗り色と塗り範囲
el = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
count = {r["name"]: 0 for r in cfg["rois"]}


def skin_mask(ycc, cr, beige):
    # 肌色: 赤みが強い部分、または「やや赤みがあり黄みが弱い」部分（指の明るいところ・爪）。
    # ベージュのシールは指の影や映り込みで赤みが近くなるが、黄みが強いので見分けられる。
    Yc, Crc, Cbc = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    if beige:
        skin = (((Crc >= cr + 2) | ((Crc >= cr - 4) & (Cbc >= 119))) & (Yc > 70)).astype(np.uint8)
    else:
        skin = ((Crc >= cr - 2) & (Yc > 70)).astype(np.uint8)
    skin = cv2.morphologyEx(cv2.morphologyEx(skin, cv2.MORPH_OPEN, el(2)), cv2.MORPH_CLOSE, el(3))
    # 手の内側にできた抜けを埋める（指の中を塗ってしまわないため）
    nlab, lab, stt, _ = cv2.connectedComponentsWithStats((1 - skin).astype(np.uint8), connectivity=4)
    skin[np.isin(lab, [j for j in range(1, nlab) if stt[j, cv2.CC_STAT_AREA] < 1500])] = 1
    return cv2.dilate(skin, el(1))

for i, f in enumerate(frames("bgr24", 3)):
    f = f.copy()
    if i in Hs:
        ycc = cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)
        Y = ycc[..., 0].astype(np.float32)
        skins = {}
        # 塗りつぶし色は「追従している面の内側」だけから取る（机やマウスパッドの色を拾わないため）
        pm = np.zeros((H, W), np.uint8)
        cv2.fillPoly(pm, [cv2.perspectiveTransform(plane[None], Hs[i])[0].astype(np.int32)], 1)
        pm = cv2.erode(pm, el(6))
        noskin = np.zeros((H, W), np.uint8)
        for r in cfg["rois"]:
            if i < round(r.get("start", cfg["start"]) * fps):
                continue
            key = (r.get("skin_cr", 138), bool(r.get("beige", False)))
            if key not in skins:
                skins[key] = skin_mask(ycc, *key)
            skin = skins[key]
            poly = cv2.perspectiveTransform(np.array(r["poly"], np.float32)[None], Hs[i])[0].astype(np.int32)
            core = np.zeros((H, W), np.uint8)
            cv2.fillPoly(core, [poly], 1)
            if core.sum() < 30:
                continue
            x0, y0, w0, h0 = cv2.boundingRect(poly)
            pad = 40
            sl = (slice(max(0, y0 - pad), min(H, y0 + h0 + pad)), slice(max(0, x0 - pad), min(W, x0 + w0 + pad)))
            c, sk, Yl, fl = core[sl], (skin if r.get("skin", True) else noskin)[sl], Y[sl], f[sl]
            area = cv2.dilate(c, el(r.get("margin", 8)))
            if r["mode"] == "darkfill":
                base = np.percentile(Yl[c > 0], 10)
                mask = (area > 0) & (Yl > base + 12) & (sk == 0)
                if mask.sum() < 4:
                    continue
                col = np.median(fl[(c > 0) & (Yl <= base + 4)], axis=0)
                fill = np.broadcast_to(col, fl.shape).astype(np.float32)
            else:
                ring = (cv2.dilate(c, el(r.get("margin", 8) + 22)) > 0) & (area == 0) & (sk == 0) & (pm[sl] > 0)
                if ring.sum() < 50:
                    continue
                med = np.median(Yl[ring])
                ring &= np.abs(Yl - med) < 14
                # 周囲の色を平面で近似して、範囲の中を同じ明るさの傾きで埋める
                A = np.c_[xx[sl][ring], yy[sl][ring], np.ones(ring.sum())].astype(np.float32)
                coef, *_ = np.linalg.lstsq(A, fl[ring].astype(np.float32), rcond=None)
                fill = (np.dstack([xx[sl], yy[sl], np.ones_like(xx[sl])]).astype(np.float32) @ coef)
                medcol = np.median(fl[ring], axis=0).astype(np.float32)
                if np.abs(fill[area > 0] - medcol).max() > 10:
                    # 手や影で周囲が欠けて近似が傾いたときは、周囲の代表色で埋める
                    fill = np.broadcast_to(medcol, fl.shape).astype(np.float32)
                # シールは「本体より明るい」か「色が付いている」部分（暗い側の差は影なので無視）
                chroma = np.abs(ycc[sl][..., 1:].astype(np.float32) - 128).max(axis=2)
                diff = ((Yl - fill.mean(axis=2)) > 12) | ((chroma > 10) & (sk == 0) if not r.get("skin", True) else False)
                if (diff & (c > 0)).sum() < 0.15 * c.sum():
                    continue  # 対象がまだ見えていない
                mask = (area > 0) & (sk == 0) if r["mode"] == "all" else (area > 0) & diff & (sk == 0)
            if r["mode"] != "darkfill" and mask.sum() < r.get("min_cover", 0.3) * c.sum():
                # 対象の大半が隠れている（開く途中のフタの下など）ときは塗らない。中途半端に塗ると跡が目立つ
                state.pop(r["name"], None)
                continue
            mask = cv2.dilate(cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, el(3)), el(2))
            mask[sk > 0] = 0
            alpha = cv2.GaussianBlur(mask.astype(np.float32), (5, 5), 0)[..., None]
            # 塗り色と塗る範囲を前フレームとなじませる（フレームごとの揺れを抑える）
            st_ = state.setdefault(r["name"], {})
            mean_now = fill[area > 0].mean(axis=0)
            # 明るさが急に変わる場面（影から出るなど）では追従を優先し、古い色を引きずらない
            if "mean" not in st_ or np.abs(st_["mean"] - mean_now).max() > 4:
                st_["mean"] = mean_now
            else:
                st_["mean"] = 0.7 * st_["mean"] + 0.3 * mean_now
            fill = fill + (st_["mean"] - mean_now) + grain[sl]
            full = st_.get("alpha")
            if full is None:
                full = np.zeros((H, W, 1), np.float32)
            cur = np.zeros((H, W, 1), np.float32); cur[sl] = alpha
            full = np.maximum(cur * 0.6 + full * 0.4, 0) if st_.get("alpha") is not None else cur
            st_["alpha"] = full
            alpha = full[sl] * (1 - cv2.GaussianBlur(sk.astype(np.float32), (5, 5), 0)[..., None])
            f[sl] = np.clip(fl * (1 - alpha) + fill * alpha, 0, 255).astype(np.uint8)
            count[r["name"]] += 1
    wr.stdin.write(f.tobytes())
wr.stdin.close(); wr.wait()
ff("-y", "-i", tmp, "-i", src, "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", dst)
os.remove(tmp)
print("処理したフレーム数:", count, "→", dst)
