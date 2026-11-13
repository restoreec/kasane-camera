---
name: reel-angle-kit
description: 手元の短い動画1本から、リール用に別画角（引き・さらに引き・真横・斜め上・反対側）の生成素材とプロンプト一式を作る。「この動画から違う画角を量産したい」「画角違いを作りたい」「リール用にカットを増やしたい」と言われたときに使う。
---

# reel-angle-kit

元動画1本と人物の参照写真から、動画生成ツールに入れる素材とプロンプトをそろえる。
動画の生成そのものは外部ツールで行う（このスキルは準備と指示文まで）。

## 手順

1. 元動画を確認する。`contact_sheet.jpg` を見て、映っているもの（人物の有無、小物、背景、動き）を言葉にする。
   映っていない部分（顔・髪・服など）は生成で新しく作ることになるので、その旨を依頼者に伝える。
2. 素材を作る。出力先は作業用フォルダにし、人物写真や元動画はリポジトリにコミットしない。

   ```bash
   scripts/prepare_assets.sh <元動画> <出力先> [参照写真] [none|cw|ccw|180]
   ```

   できるもの: `frame_start.jpg` / `frame_end.jpg` / `source_10s_720p.mp4` / `contact_sheet.jpg` / `ref_person.jpg`
3. ロゴや商標を消す指定があれば、開始フレームに対して実行する（`pip install opencv-python-headless` が必要）。

   ```bash
   python3 scripts/remove_logo.py <出力先>/frame_start.jpg <出力先>/frame_start_nologo.jpg --box x,y,w,h
   ```

   実行後は必ず画像を見て、消し残しや境目のはみ出しがないか確かめる。範囲は元画像の実寸で指定する。
   元動画そのものを使う場合は、暗い無地の面に載ったロゴを動画全体で消せる（カメラが動いても追従する）。

   ```bash
   python3 scripts/remove_logo_video.py <元動画> <出力動画> --end <面が見えなくなる秒数>
   ```

   実行後は一覧画像を作って、色味が元動画と変わっていないこと、消し残しがないことを確かめる。
   シールや小さなロゴなど、暗い面に囲まれていないものは対象外なので、残っていれば依頼者に伝える。
4. プロンプトを組み立てる。共通部分＋画角別の1文を、画角ごとに1本ずつ渡す。
5. 人物をそろえる。最初に「引いた画角」で静止画を1枚作り、残りの画角ではその静止画を参照画像に使う。

## プロンプトのひな形

共通部分（場面・人物・服装・小物を元動画に合わせて書き換える）:

```
Same scene as the reference video: <人物> sits at <机> against <背景>, and <動作>.
<小物> are on the desk. All devices are plain with no logos, no text, no stickers.
Her hair is <髪型>, matching the reference photo. She wears <服装>.
Soft natural daylight, realistic, vertical 9:16, smooth steady camera.
```

画角別:

| 画角 | 追加する1文 |
|---|---|
| 引き | `Medium shot from the front-left of the desk, showing her upper body, both hands and the whole laptop.` |
| さらに引き | `Wide shot of the whole desk and her seated figure from the waist up, with the surrounding room visible.` |
| 真横 | `Exact side profile shot at desk height, camera perpendicular to her.` |
| 斜め上 | `High-angle shot from diagonally above her shoulder, looking down at her hands and the desk surface.` |
| 反対側 | `Reverse angle from behind the laptop screen, camera facing her; the lid rises in the foreground and reveals her face.` |

ネガティブ指定: `ponytail, tied hair, casual clothes, logo, brand name, text, sticker`
（髪型・服装の禁止語は依頼に合わせて入れ替える）

## 納品前の確認

- ロゴ・商標・画面の文字が残っていないか。
- 人物の顔・髪・服が画角ごとにぶれていないか。
- 手の指の本数、PCの開き方など不自然な動きがないか。
- 使った生成ツールの無料枠の透かしと商用利用の可否（規約は変わるので、その都度確認する）。
