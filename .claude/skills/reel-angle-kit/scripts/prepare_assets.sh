#!/usr/bin/env bash
# リール用の別画角生成に使う素材を元動画から作る。
# 使い方: prepare_assets.sh <元動画> <出力先フォルダ> [参照写真] [参照写真の回転: none|cw|ccw|180]
set -euo pipefail
VIDEO="$1"; OUT="$2"; REF="${3:-}"; ROT="${4:-none}"
mkdir -p "$OUT"
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")
END=$(python3 -c "print(max(0, $DUR - 1.0))")
# 開始・終了フレーム（回転情報は ffmpeg が自動で反映する）
ffmpeg -v error -y -ss 0.2 -i "$VIDEO" -frames:v 1 -q:v 2 "$OUT/frame_start.jpg"
ffmpeg -v error -y -ss "$END" -i "$VIDEO" -frames:v 1 -q:v 2 "$OUT/frame_end.jpg"
# 生成ツールの入力上限に合わせた 10秒・720p・音声なし版
ffmpeg -v error -y -i "$VIDEO" -t 10 -vf "scale='if(gt(iw,ih),1280,720)':-2" -c:v libx264 -crf 20 -an "$OUT/source_10s_720p.mp4"
# 全体を確認するための一覧画像
ffmpeg -v error -y -i "$VIDEO" -vf "fps=1/2.5,scale=-2:640,tile=5x1" -frames:v 1 "$OUT/contact_sheet.jpg"
if [ -n "$REF" ]; then
  case "$ROT" in
    cw) VF="transpose=1,";; ccw) VF="transpose=2,";; 180) VF="transpose=1,transpose=1,";; *) VF="";;
  esac
  ffmpeg -v error -y -i "$REF" -vf "${VF}scale='min(1440,iw)':-2" -q:v 2 "$OUT/ref_person.jpg"
fi
ls -la "$OUT"
