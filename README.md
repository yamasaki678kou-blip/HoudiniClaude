# HoudiniClaude — 汎用 HDA 無限開発

Houdini で使える「汎用的なツール / HDA」を作り続けるリポジトリです。
ひとつひとつのツールに、**使い方マニュアル（README.md）** と **解説レポート（REPORT.md）** を付けています。

- 第一の用途は **入門**。触って、壊して、仕組みを学べるように、作りはできるだけシンプルにしてあります。
- 中心になる技術は **SOP・VEX・COP**。主な使いどころは背景モデリングとテクスチャリングです。
- 出力先は **Unity** と **Houdini 内** を前提にしています。

## ツール一覧

| # | フォルダ | 内容 | 主な技術 |
|---|---|---|---|
| 01 | [tools/01_mech_transform](tools/01_mech_transform/) | メカ変形パーツ。スライド・ヒンジ・ピストンなどの機構を属性で動かし、VAT（Vertex Animation Texture）で書き出す | パックドプリミティブ、VEX、SideFX Labs VAT ROP |
| 02 | [tools/02_brick_wall](tools/02_brick_wall/) | レンガ壁ジェネレーター。レンガ・タイル・石積みを、段ずらし・目地・ばらつき・抜けつきで敷き詰める | VEX で点を作る、Copy to Points、ボックス投影 UV |
| 03 | [tools/03_pipe_run](tools/03_pipe_run/) | 配管ジェネレーター。折れ線から角の丸い配管を作り、フランジ・バンド・取り付け金具を付ける | PolyBevel、Sweep、PolyFrame、Copy to Points、VEX |
| 04 | [tools/04_weathering_mask](tools/04_weathering_mask/) | ウェザリングマスク。角の擦れ・へこみの汚れ・上面のほこり・地際の苔を、形から計算して頂点カラーに書く | Measure（曲率）、Mask by Feature（AO）、VEX |

## 作品（showcase）

ここまでの HDA を組み合わせて、実際に 1 枚の絵にしたものです。

| # | フォルダ | 内容 | 使った HDA |
|---|---|---|---|
| 01 | [showcase/01_maintenance_bay](showcase/01_maintenance_bay/) | 整備ドック。レンガの壁に配管が走り、産業用アームが溶接する背景。Karma でレンダリング | 01 / 02 / 03 / 04 / 05 / 06 の 6 本 |

## 動作環境

- **Houdini 21.0.700 Indie**（Windows）で作成・確認しています。ファイルは Indie 形式（`.hiplc` / `.hdalc`）です。
- VAT 書き出しなど、[SideFX Labs](https://github.com/sideeffects/SideFXLabs) のノードを使うツールがあります。Labs は Houdini Launcher から無料で入れられます。
- Unity 向けの出力は、SideFX Labs に同梱されている Unity 用パッケージ（URP）で確認する前提です。

## フォルダ構成

```
HoudiniClaude/
├─ README.md                 … このファイル
└─ tools/
   └─ 01_mech_transform/     … ツール 1 個 = フォルダ 1 個（連番_名前）
      ├─ README.md           … 使い方マニュアル（パラメータ一覧、Unity への持っていき方）
      ├─ REPORT.md           … 解説レポート（使ったノード・VEX・仕組みの説明、公式マニュアルへのリンク付き）
      ├─ otls/*.hdalc        … HDA 本体
      ├─ *_sample.hiplc      … サンプルシーン。メモ（Sticky Note）に「試してみよう」が書いてあります
      ├─ images/             … スクリーンショット・GIF
      ├─ export/             … 書き出し結果（Unity でそのまま試せます）
      └─ scripts/            … サンプルを Python で作り直すスクリプト（使わなくても大丈夫）
```

## 使い方（共通）

1. ツールのフォルダにあるサンプル `*_sample.hiplc` を Houdini で開きます。HDA はサンプルと同じフォルダの `otls/` から自動で読み込まれます。
2. 自分のシーンで使うときは、次のどちらかで HDA を入れます。
   - その場だけ使う: Houdini のメニュー **File ▸ Import ▸ Houdini Digital Asset...** で `otls/` の中の `.hdalc` を選ぶ
   - いつでも使う: `.hdalc` を `ドキュメント/houdini21.0/otls/` にコピーする（Houdini を起動し直すと使えます）
3. ネットワークエディタで Tab キーを押し、**HoudiniClaude** の中からノードを選びます。

## 作るときの決まりごと（今後のツールも同じ）

- 1 ツール = `tools/NN_名前/` のフォルダ 1 個。中身は上の構成に合わせます。
- HDA の名前は `hclaude::名前::1.0` のように名前空間とバージョンを付け、Tab メニューの **HoudiniClaude** に入れます。
- 密度より量。複雑にするより、改変しやすいシンプルな作りを選びます。
- VEX には「何をしている行か」を日本語でコメントします。サンプルには Sticky Note でメモを置きます。
- レポートは Markdown。ノード名や機能名は [Houdini 公式マニュアル](https://www.sidefx.com/docs/houdini/) へリンクします。
