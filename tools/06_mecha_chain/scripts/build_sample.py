# -*- coding: utf-8 -*-
"""
汎用メカチェーン（mecha_chain）の HDA とサンプルシーンを、ゼロから作り直すスクリプトです。

使い方（コマンドプロンプトで、このツールのフォルダから）:
    "C:/Program Files/Side Effects Software/Houdini 21.0.700/bin/hython.exe" scripts/build_sample.py
    ... 後ろに render を付けると images/ の画像と GIF も作ります。

作られるもの:
    otls/mecha_chain.hdalc        ... HDA 本体
    mecha_chain_sample.hiplc      ... プリセット 20 本の見本 + 検証チェーン + 練習用
    verify_log.txt                ... 自動検証の結果（PASS / FAIL の一覧）

仕様の出どころ: ikura さんの「HDA_Phase1_実装パケット v0.3」「HDA_初回構築チェックリスト v0.2」
「HDA_プリセットレシピ集」。仕様は変えず、実機に合わせて関数名などを直しています。
"""
import math
import os
import shutil
import sys

import hou

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
HIP_PATH = TOOL_DIR + "/mecha_chain_sample.hiplc"
HDA_PATH = TOOL_DIR + "/otls/mecha_chain.hdalc"
HDA_TYPE = "hclaude::mecha_chain::1.0"
IMG_DIR = TOOL_DIR + "/images"
LOG_PATH = TOOL_DIR + "/verify_log.txt"
FRAME_END = 96
TAU = 2.0 * math.pi

# ----------------------------------------------------------------------------
# プリセットレシピ 20 本（レシピ集の文字列そのまま）
# ----------------------------------------------------------------------------
PRESETS = [
    ("01", "最小構成ドリル", "base > motor_rot(speed=0.8) > drill"),
    ("02", "本命：モーター→関節→モーター",
     "base > motor_rot(speed=0.3) > hinge(axis=0, a=10, b=30, c=0.6) > link(len=1.2) > "
     "motor_osc(b=45, speed=0.8) > ball(a=20, c=10) > gripper(b=1)"),
    ("03", "12段ゴチャチェーン",
     "base > motor_rot(speed=0.2) > hinge(axis=0,b=25,c=0.5) > motor_osc(b=30,speed=0.7,phase=40) > "
     "hinge(axis=1,b=25,c=0.6,phase=80) > motor_osc(b=30,speed=0.9,phase=120) > "
     "ball(a=15,b=15,c=12,phase=160) > twist(b=45) > motor_rot(speed=0.5,phase=200) > "
     "hinge(axis=0,b=35,c=0.8,phase=240) > spring(a=4,b=15) > link(len=1.4) > gripper(b=1)"),
    ("04", "駆動消費ヒンジ",
     "base > motor_rot(speed=0.6) > link(len=0.6) > hinge(axis=0, d=1) > link(len=1.0) > cap"),
    ("05", "産業用アーム",
     "base > motor_rot(axis=1, speed=0.25) > hinge(axis=0, a=-20, b=25, c=0.4) > link(len=1.6) > "
     "hinge(axis=0, a=30, b=20, c=0.5, phase=90) > servo(b=35, c=0.7) > gripper(b=1)"),
    ("06", "スカラっぽい水平アーム",
     "base > motor_rot(axis=1, speed=0.4) > link(len=1.2) > motor_rot(axis=1, speed=-0.6) > "
     "link(len=1.0) > prismatic(a=0, b=0.4, c=1.0) > drill(a=2.0)"),
    ("07", "クレーン",
     "base > motor_rot(axis=1, speed=0.15) > hinge(axis=0, a=35) > prismatic(a=0.5, b=2.2) > "
     "twist(a=15) > cap"),
    ("08", "溶接トーチアーム",
     "base > hinge(axis=0, a=15, b=10, c=0.3) > link(len=1.5) > ball(a=25, b=10, c=15) > "
     "motor_rot(speed=2.5) > drill(len=0.25)"),
    ("09", "四脚（splitter入れ子）",
     "base > splitter(a=2, b=80) [ splitter(a=2, b=45) [ hinge(axis=0,b=30,c=1.0) > link(len=0.9) > "
     "hinge(axis=0,a=25,b=20,c=1.0,phase=180) > foot | hinge(axis=0,b=30,c=1.0,phase=180) > "
     "link(len=0.9) > hinge(axis=0,a=25,b=20,c=1.0) > foot ] | splitter(a=2, b=45) [ "
     "hinge(axis=0,b=30,c=1.0,phase=90) > link(len=0.9) > hinge(axis=0,a=25,b=20,c=1.0,phase=270) > "
     "foot | hinge(axis=0,b=30,c=1.0,phase=270) > link(len=0.9) > "
     "hinge(axis=0,a=25,b=20,c=1.0,phase=90) > foot ] ]"),
    ("10", "一輪セグウェイ風", "base > spring(a=6, b=8) > link(len=0.8) > wheel(a=1.0)"),
    ("11", "ヘビ型",
     "base > motor_osc(axis=1, b=25, speed=0.8) > link(len=0.5) > "
     "motor_osc(axis=1, b=25, speed=0.8, phase=45) > link(len=0.5) > "
     "motor_osc(axis=1, b=25, speed=0.8, phase=90) > link(len=0.5) > "
     "motor_osc(axis=1, b=25, speed=0.8, phase=135) > link(len=0.5) > head(a=20, c=0.8)"),
    ("12", "三つ又触手台座",
     "base > motor_rot(axis=1, speed=0.2) > splitter(a=3, b=50) [ motor_osc(b=35,speed=0.6) > "
     "ball(c=15) > gripper | motor_osc(b=35,speed=0.6,phase=120) > ball(c=15,phase=120) > gripper | "
     "motor_osc(b=35,speed=0.6,phase=240) > ball(c=15,phase=240) > drill ]"),
    ("13", "首＋頭（見張りメカ）", "base > link(len=0.7) > spring(a=5, b=6) > head(a=40, b=12, c=0.5)"),
    ("14", "背中のサブアーム",
     "base > bent(a=50) > motor_osc(b=20, speed=0.5) > link(len=0.8) > ball(a=20, c=10) > "
     "servo(b=25) > gripper"),
    ("15", "天井ファン",
     "base > motor_rot(axis=1, speed=1.2) > link(len=0.4) > splitter(a=3, b=60) [ link(len=0.7) > cap | "
     "link(len=0.7) > cap | link(len=0.7) > cap ]"),
    ("16", "ピストンポンプ",
     "base > motor_rot(speed=0.7) > piston(a=0.5) > link(len=0.8) > piston(a=0.5, phase=180) > cap"),
    # 17 だけ値を変えた: offset の横ずれを rad 単位にしたので、元の a=0.2（生の値）を 0.2 / 0.15 = 1.333 に読み替え
    ("17", "アンテナ／レーダー", "base > servo(b=50, c=0.3) > offset(a=1.333) > link(len=0.3) > cap(rad=0.35)"),
    ("18", "ゲート開閉（drive=Block）", "base > hinge(axis=1, a=0, b=40, c=0.25, drive=1) > link(len=1.8) > cap"),
    ("19", "カウンター回転ツイン",
     "base > motor_rot(speed=0.8) > link(len=0.5) > motor_rot(speed=-1.3) > link(len=0.5) > "
     "motor_rot(speed=2.1) > cap"),
    ("20", "スプリング・カオス",
     "base > motor_osc(b=15, speed=1.2) > spring(a=3, b=20) > link(len=0.6) > spring(a=2, b=25) > "
     "link(len=0.6) > spring(a=1.5, b=30) > cap(rad=0.25)"),
]

# 回転モーター系 5 種（仕様 v0.5）の見本と、仕様 §6 の組み合わせ例
ROTARY_PRESETS = [
    ("R1", "R-01 同軸スタック（層ごとの形）",
     "base > coax(layers=4, ratio=[1,-0.8,0.5,-1.4], form=[disc,blades,gear,ring]) > link(len=0.6) > cap"),
    ("R2", "R-02 遊星ギア（キャリア出力）",
     "base > planetary(sun_teeth=12, planet_count=3, speed=1.2) > link(len=0.6) > cap"),
    ("R3", "R-03 ジンバル（stabilize）",
     "base > motor_osc(axis=0, b=35, speed=0.35) > hinge(axis=1, b=30, c=0.45) > link(len=0.5) > "
     "gimbal(mode=stabilize, payload_form=socket, rad=0.25)"),
    ("R4", "R-04 クランク（ガイドずらし）",
     "base > crank(eccentric=0.8, rod_len=3, guide_offset=0.6, speed=0.6) > link(len=0.5) > cap"),
    ("R5", "R-05 タービン（シュラウド付き）",
     "base > turbine(blade_count=5, twist_root=45, twist_tip=15, sweep=12, shroud=1, speed=1.2, pitch_anim=10)"),
    ("C1", "R-02 → R-01 重々しく回るタワー",
     "base > planetary(sun_teeth=10, planet_count=4, speed=2) > coax(layers=5, form=[cage,disc], layer_gap=0.45, "
     "stack_mode=independent) > cap"),
    ("C2", "R-03 → R-05 向きを保つファン",
     "base > motor_osc(axis=0, b=35, speed=0.3) > link(len=0.8) > gimbal(mode=stabilize, angle_list=[0,0,0], rad=0.25) > "
     "turbine(blade_count=3, speed=2, hub_form=cyl, blade_len=2)"),
    ("C3", "R-04 → piston クランク駆動",
     "base > crank(eccentric=1, rod_len=3.5, pin_count=2, pin_phase_list=[0,180], speed=0.7) > piston(a=0.3) > cap"),
    ("C4", "R-01 二重反転プロペラ",
     "base > coax(layers=2, ratio=[1,-1], form=blades, blade_count=3, stack_mode=independent, layer_gap=0.5, speed=1.5) > cap"),
    ("C5", "R-02 → R-04 減速して往復（プレス）",
     "base > planetary(sun_teeth=12, planet_count=3, speed=3) > crank(eccentric=1.2, rod_len=4, d=1) > "
     "link(len=0.5) > cap"),
]
RECIPES = dict((k, r) for k, _, r in PRESETS + ROTARY_PRESETS)

# 検証用のチェーン（実装パケット §5.2 の bent テスト + 順序の差が出る 2 回折りテスト）
BENT_SINGLE = "base > bent(a=45) > link > cap"
BENT_DOUBLE = "base > bent(a=90) > bent(a=90, b=90) > link"

# ----------------------------------------------------------------------------
# 1〜4. ノードの中身（Python SOP と VEX）は scripts/sop_code/ の別ファイルに置いています
#   recipe_parser.py   … レシピ → パーツの点（文法 v1.2、回転系 5 種の分解）
#   socket_solver.vex  … 親から順に frame / socket を計算（ジンバルの分解、クランクの式）
#   frame_decompose.vex… 標準の属性へ（回転系は _housing / _rotor の 2 個に分ける）
#   detail_pieces.vex  … 軸 rod、グリッパの指、タービンの羽根
#   variant_builder.py … 回転系の形のバリアント（geo_id ごとに 1 回）
#   classify_shapes.py … 第2入力の読み分け（断面カーブ / 差し替えメッシュ / ターゲット点）
# ----------------------------------------------------------------------------
CODE_DIR = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/") + "/sop_code"


def load_code(name):
    with open(CODE_DIR + "/" + name, "r", encoding="utf-8") as fh:
        return fh.read()


PARSER_CODE = load_code("recipe_parser.py")
SOLVER_VEX = load_code("socket_solver.vex")
DECOMPOSE_VEX = load_code("frame_decompose.vex")
PIECES_VEX = load_code("detail_pieces.vex")
VARIANT_CODE = load_code("variant_builder.py")
CLASSIFY_CODE = load_code("classify_shapes.py")

# ----------------------------------------------------------------------------
# 5. skeleton_view（Detail Wrangle）… デバッグ表示（OUT_SOCKETS）
# ----------------------------------------------------------------------------
SKELETON_VEX = r'''// skeleton_view（Detail Wrangle）… ソケットの骨組みを見るためのデバッグ表示
// 点 = 各パーツの入力ソケット（frame_pos）、線 = 親子。末端のパーツには出力ソケットの点を足します。
// 3@transform も付けるので、KineFX のスケルトンとしてそのまま読めます（FBX 経路の下準備）。
int n = npoints(0);
int haschild[];
resize(haschild, n);
for (int i = 0; i < n; i++) {
    vector fp = point(0, "frame_pos", i);
    vector4 q = point(0, "frame_orient", i);
    matrix3 m = qconvert(q);
    setpointattrib(0, "P", i, fp);
    setpointattrib(0, "transform", i, m);
    int p = point(0, "parent_id", i);
    if (p >= 0) haschild[p] = 1;
}
for (int i = 0; i < n; i++) {
    if (haschild[i]) continue;
    int tp = addpoint(0, i);
    vector sp = point(0, "socket_pos", i);
    string nm = point(0, "name", i);
    setpointattrib(0, "P", tp, sp);
    setpointattrib(0, "name", tp, nm + "_tip");
    addprim(0, "polyline", i, tp);
}
'''

# ----------------------------------------------------------------------------
# 6. 造形テンプレート … 規約: 半径 1・長さ 1・+Z 向き。固定サイズのパーツは半径 1 を単位に設計
#    shape: ("tube", r1, r2, h, z0, axis)  axis "z" = Rotate X 90° で +Z へ / "x" = X 向き
#           ("box", (sx, sy, sz), (cx, cy, cz))
#           ("sphere", r, (cx, cy, cz))
# ----------------------------------------------------------------------------
GRAY = (0.72, 0.74, 0.78)
TEMPLATES = [
    ("base", (0.30, 0.32, 0.36), [("tube", 2.6, 2.6, 0.6, -0.6, "z")]),
    ("motor_rot", (0.95, 0.52, 0.12), [("tube", 1.35, 1.35, 1.6, 0.0, "z"),
                                       ("box", (0.35, 0.7, 1.2), (0.0, 1.55, 0.8))]),
    ("motor_osc", (0.98, 0.78, 0.18), [("tube", 1.35, 1.35, 1.6, 0.0, "z"),
                                       ("box", (0.35, 0.7, 1.2), (0.0, 1.55, 0.8))]),
    ("servo", (0.62, 0.82, 0.25), [("box", (2.4, 2.4, 1.6), (0.0, 0.0, 0.8)),
                                   ("box", (0.35, 0.7, 1.0), (0.0, 1.5, 0.8))]),
    ("hinge", (0.18, 0.68, 0.74), [("sphere", 1.25, (0.0, 0.0, 0.0)),
                                   ("tube", 0.55, 0.55, 3.0, 0.0, "x")]),
    ("ball", (0.62, 0.42, 0.85), [("sphere", 1.35, (0.0, 0.0, 0.0))]),
    ("universal", (0.30, 0.45, 0.90), [("sphere", 1.25, (0.0, 0.0, 0.0))]),
    ("spring", (0.30, 0.78, 0.40), [("sphere", 1.15, (0.0, 0.0, 0.0)),
                                    ("tube", 0.8, 0.8, 1.4, 0.0, "z")]),
    ("twist", (0.25, 0.80, 0.85), [("tube", 1.45, 1.45, 0.6, 0.0, "z")]),
    ("splitter", (0.40, 0.42, 0.48), [("box", (2.2, 2.2, 1.0), (0.0, 0.0, 0.5))]),
    ("link", GRAY, [("box", (1.3, 1.3, 1.0), (0.0, 0.0, 0.5))]),
    ("offset", GRAY, [("box", (1.3, 1.3, 1.0), (0.0, 0.0, 0.5))]),
    ("bent", GRAY, [("box", (1.3, 1.3, 1.0), (0.0, 0.0, 0.5))]),
    ("fixed", GRAY, [("box", (1.6, 1.6, 1.6), (0.0, 0.0, 0.8))]),
    ("piston", (0.85, 0.28, 0.25), [("tube", 0.9, 0.9, 1.0, 0.0, "z")]),
    ("prismatic", (0.45, 0.58, 0.72), [("box", (1.0, 1.0, 1.0), (0.0, 0.0, 0.5))]),
    ("gripper", (0.25, 0.26, 0.30), [("box", (2.2, 1.6, 0.8), (0.0, 0.0, 0.4))]),
    ("finger", (0.82, 0.84, 0.88), [("box", (0.5, 0.35, 1.6), (0.0, 0.0, 0.8))]),
    ("drill", (0.80, 0.82, 0.86), [("tube", 1.3, 1.3, 0.4, 0.0, "z"),
                                   ("tube", 1.0, 0.08, 2.5, 0.4, "z")]),
    ("wheel", (0.22, 0.22, 0.24), [("tube", 2.2, 2.2, 0.9, 0.0, "x")]),
    ("head", (0.70, 0.20, 0.22), [("box", (3.0, 2.0, 2.2), (0.0, 0.0, 1.1)),
                                  ("box", (2.4, 0.6, 0.3), (0.0, 0.3, 2.3))]),
    ("foot", (0.30, 0.32, 0.36), [("box", (3.0, 3.0, 0.5), (0.0, 0.0, 0.25))]),
    ("cap", (0.60, 0.62, 0.66), [("sphere", 1.0, (0.0, 0.0, 0.0))]),
    ("rod", (0.42, 0.44, 0.48), [("tube", 1.0, 1.0, 1.0, 0.0, "z")]),
]

TAG_VEX = r'''// このテンプレートの名前（piece）と色を付ける。色は点に付けます（プリミティブの Cd と混ぜると片方が白くなるため）
s@piece = "%s";
foreach (int pt; primpoints(0, @primnum)) setpointattrib(0, "Cd", pt, set(%f, %f, %f));
'''


def sp(node, name, value):
    """パラメータを設定する。メニューの文字が通らない時は番号で入れ直す。"""
    parm = node.parm(name)
    if parm is None:
        print("WARN no parm %s on %s" % (name, node.path()))
        return
    try:
        parm.set(value)
    except hou.OperationFailed:
        items = parm.menuItems()
        if value in items:
            parm.set(items.index(value))
        else:
            print("WARN cannot set %s=%r on %s (menu %r)" % (name, value, node.path(), items))


def make_shape(parent, name, spec):
    kind = spec[0]
    if kind == "tube":
        _, r1, r2, h, z0, axis = spec
        t = parent.createNode("tube", name)
        sp(t, "type", "poly")
        sp(t, "cap", 1)
        sp(t, "rad1", r1)
        sp(t, "rad2", r2)
        sp(t, "height", h)
        sp(t, "cols", 24)
        x = parent.createNode("xform", name + "_toZ" if axis == "z" else name + "_toX")
        x.setInput(0, t)
        if axis == "z":
            # Tube は Y 軸向きが既定。X 軸まわりに 90° 回すと +Z 向きになる（初回の最頻トラップ）
            x.parmTuple("r").set((90, 0, 0))
            x.parmTuple("t").set((0, 0, z0 + h / 2.0))
        else:
            x.parmTuple("r").set((0, 0, -90))
            x.parmTuple("t").set((0, 0, z0))
        return x
    if kind == "box":
        _, size, center = spec
        b = parent.createNode("box", name)
        sp(b, "type", "poly")
        b.parmTuple("size").set(size)
        b.parmTuple("t").set(center)
        return b
    _, r, center = spec
    s = parent.createNode("sphere", name)
    sp(s, "type", "poly")
    sp(s, "freq", 3)
    s.parmTuple("rad").set((r, r, r))
    s.parmTuple("t").set(center)
    return s


def build_templates(sub):
    tpl = sub.createNode("subnet", "templates")
    tpl.setComment("造形テンプレート（半径 1・長さ 1・+Z 向き）\ns@piece = パーツ名で 1 個ずつパック")
    tpl.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    merge = tpl.createNode("merge", "all_templates")
    for idx, (piece, col, shapes) in enumerate(TEMPLATES):
        outs = [make_shape(tpl, "%s_%d" % (piece, k), s) for k, s in enumerate(shapes)]
        if len(outs) > 1:
            m = tpl.createNode("merge", piece + "_merge")
            for k, o in enumerate(outs):
                m.setInput(k, o)
            src = m
        else:
            src = outs[0]
        tag = tpl.createNode("attribwrangle", "tag_" + piece)
        tag.parm("class").set("primitive")
        tag.parm("snippet").set(TAG_VEX % (piece, col[0], col[1], col[2]))
        tag.setInput(0, src)
        merge.setInput(idx, tag)
    pack = tpl.createNode("pack", "pack_by_piece")
    pack.setInput(0, merge)
    sp(pack, "packbyname", 1)
    sp(pack, "nameattribute", "piece")
    sp(pack, "pivot", "origin")
    sp(pack, "transfer_attributes", "piece")
    pack.setComment("piece ごとに 1 個のパック済みプリミティブ\n（ピボットは原点 = 入力ソケット）")
    pack.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    out = tpl.createNode("output", "OUT_TEMPLATES")
    out.setInput(0, pack)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    tpl.layoutChildren()
    return tpl


# ----------------------------------------------------------------------------
# HDA のパラメータ・ヘルプ・Python モジュール
# ----------------------------------------------------------------------------
HDA_PYMODULE = '''# -*- coding: utf-8 -*-
# プリセットメニューから選ぶと、レシピ欄をそのプリセットで上書きします。
PRESETS = %r


def load_preset(kwargs):
    node = kwargs["node"]
    key = kwargs["script_value"]
    if key in PRESETS:
        node.parm("recipe").set(PRESETS[key])
''' % RECIPES

HDA_HELP = '''= 汎用メカチェーン（Mecha Chain） =

#icon: SOP/copytopoints

"""文字列のレシピから、モーター・関節・リンクをつないだメカを組み立てて動かします。"""

`base > motor_rot(speed=0.3) > hinge(axis=0, a=10, b=30, c=0.6) > link(len=1.2) > gripper(b=1)`
のように、パーツを `>` でつなぐだけで、段数を増やしても減らしても組み替えても、そのまま動きます。

しくみ（ソケット契約）:
    どのパーツも「入力ソケット」で親の「出力ソケット」につながり、自分の回転を足して、
    ローカル +Z の `len` 先に自分の出力ソケットを作ります。パーツ同士はこの約束しか知りません。

ノードの流れ:
    # [Python SOP|Node:sop/python] がレシピを読んで「パーツ 1 個 = 点 1 個」にする
    # [Attribute Wrangle|Node:sop/attribwrangle]（Detail）が親から順に位置と向きを計算する
    # [Copy to Points|Node:sop/copytopoints] が `piece` 属性で形を差し替えて置く

回転モーター系 5 種:
    `coax`（同軸スタック）、`planetary`（遊星ギア）、`gimbal`（ジンバル）、`crank`（クランク）、`turbine`（タービン）を
    1 個書くだけで、中の部品を自動で組み立てて動かします。`ratio=[1,-0.8,0.5]` のようなリストや `form=disc` のような名前も書けます。
    プリセットの R1〜R5、C1〜C5 から試せます。

@inputs

ベースポイント（任意）:
    最初の点の P と orient に、チェーンの根を置きます。
形の素材（任意）:
    グループ `sections`（断面カーブ）、`meshes`（差し替えメッシュ）、`targets`（ジンバルの目標点）。
    グループが無い時は、開いたカーブ = 断面、閉じた面 = メッシュ、面に属さない点 = 目標点として読みます。

@parameters

プリセットを読み込む:
    選ぶとレシピ欄をそのプリセットで上書きします（20 本）。

レシピ:
    パーツを `>` でつないだ文字列。`#` から行末まではメモとして読み飛ばします。

全体の速さ:
    時間の進み方を一括で変えます（0.5 で半分の速さ、2 で倍）。

全体の大きさ:
    でき上がりをまとめて拡大・縮小します。

骨組み（ソケット）を重ねて表示:
    各パーツの入力ソケット（点）と親子（線）を重ねて見せます。2 番目の出力からも取り出せます。

@outputs

パーツ:
    パック済みのパーツ（VAT の剛体モードにそのまま渡せる形）。
ソケット:
    ソケットの骨組み（点に `name` と `3@transform` があるので KineFX のスケルトンとして読めます）。
'''

HDA_TOOLS = '''<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <tool name="$HDA_DEFAULT_TOOL" label="$HDA_LABEL" icon="$HDA_ICON">
    <toolMenuContext name="viewer">
      <contextNetType>SOP</contextNetType>
    </toolMenuContext>
    <toolMenuContext name="network">
      <contextOpType>$HDA_TABLE_AND_NAME</contextOpType>
    </toolMenuContext>
    <toolSubmenu>HoudiniClaude</toolSubmenu>
    <script scriptType="python"><![CDATA[import soptoolutils

soptoolutils.genericTool(kwargs, '$HDA_NAME')]]></script>
  </tool>
</shelfDocument>
'''


def hda_parm_templates():
    g = hou.ParmTemplateGroup()
    tokens = ["none"] + [k for k, _, _ in PRESETS + ROTARY_PRESETS]
    labels = ["（選ぶとレシピ欄を上書きします）"] + ["%s  %s" % (k, t) for k, t, _ in PRESETS + ROTARY_PRESETS]
    g.append(hou.MenuParmTemplate(
        "preset", "プリセットを読み込む", tokens, labels, default_value=tokens.index("02"),
        script_callback="hou.phm().load_preset(kwargs)",
        script_callback_language=hou.scriptLanguage.Python,
        help="選ぶとレシピ欄をそのプリセットで上書きします。"))
    g.append(hou.StringParmTemplate(
        "recipe", "レシピ", 1, default_value=(RECIPES["02"],),
        tags={"editor": "1", "editorlines": "3-12"},
        help="パーツを > でつないだ文字列。# から行末まではメモ。"))
    g.append(hou.FloatParmTemplate(
        "global_speed", "全体の速さ", 1, default_value=(1.0,), min=0.0, max=4.0,
        help="時間の進み方を一括で変えます。"))
    g.append(hou.FloatParmTemplate(
        "scale", "全体の大きさ", 1, default_value=(1.0,), min=0.01, max=10.0,
        help="でき上がりをまとめて拡大・縮小します。"))
    g.append(hou.ToggleParmTemplate(
        "show_skeleton", "骨組み（ソケット）を重ねて表示", default_value=False,
        help="入力ソケットの点と親子の線を重ねて表示します。"))
    return g


def comment(node, text, color=None):
    node.setComment(text)
    node.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    if color:
        node.setColor(hou.Color(color))


def build_hda():
    old = hou.nodeType(hou.sopNodeTypeCategory(), HDA_TYPE)
    if old is not None and old.definition() is not None:
        hou.hda.uninstallFile(old.definition().libraryFilePath())
    if os.path.exists(HDA_PATH):
        os.remove(HDA_PATH)
    backup_dir = os.path.dirname(HDA_PATH) + "/backup"
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir)
    if not os.path.isdir(os.path.dirname(HDA_PATH)):
        os.makedirs(os.path.dirname(HDA_PATH))

    geo = hou.node("/obj").createNode("geo", "hda_build_tmp")
    sub = geo.createNode("subnet", "mecha_chain1")
    spare = sub.parmTemplateGroup()  # 中のノードが ../recipe などを参照できるように先に付けておく
    for pt in hda_parm_templates().entries():
        spare.append(pt)
    sub.setParmTemplateGroup(spare)

    # Stage 1: レシピ → パーツの点
    seed = sub.createNode("add", "one_point")
    sp(seed, "points", 1)
    parser = sub.createNode("python", "recipe_parser")
    parser.setInput(0, seed)
    ptg = parser.parmTemplateGroup()
    ptg.append(hou.StringParmTemplate("recipe", "Recipe", 1))
    ptg.append(hou.FloatParmTemplate("global_speed", "Global Speed", 1, default_value=(1.0,)))
    parser.setParmTemplateGroup(ptg)
    parser.parm("recipe").setExpression('chs("../recipe")', hou.exprLanguage.Hscript)
    parser.parm("global_speed").setExpression('ch("../global_speed")', hou.exprLanguage.Hscript)
    parser.parm("python").set(PARSER_CODE)
    comment(parser, "1. recipe_parser（Python SOP）\nレシピ → パーツ 1 個 = 点 1 個\n親子は線でつなぐ", (0.55, 0.75, 0.95))

    # Stage 1.5: ソルバ
    solver = sub.createNode("attribwrangle", "socket_solver")
    solver.setInput(0, parser)
    # 入力 1 = ベースポイント（根の置き場所）、入力 2 = 形の素材（断面カーブ / 差し替えメッシュ / ターゲット点）
    ins = sub.indirectInputs()
    solver.setInput(1, ins[0])
    classify = sub.createNode("python", "classify_shapes")
    classify.setInput(0, ins[1])
    classify.parm("python").set(CLASSIFY_CODE)
    comment(classify, "第2入力の読み分け\nグループ sections / meshes / targets\nなければ開閉と点で判定")
    solver.setInput(2, classify)
    solver.parm("class").set("detail")
    solver.parm("snippet").set(SOLVER_VEX)
    comment(solver, "2. socket_solver（Detail Wrangle）\n親の出力ソケットを継いで\nframe / socket を順に計算", (0.95, 0.7, 0.3))

    # Stage 2: 造形
    decomp = sub.createNode("attribwrangle", "frame_decompose")
    decomp.setInput(0, solver)
    decomp.parm("class").set("point")
    decomp.parm("snippet").set(DECOMPOSE_VEX)
    comment(decomp, "3. frame_decompose\n→ @P / @orient / v@scale / s@piece")

    pieces = sub.createNode("attribwrangle", "detail_pieces")
    pieces.setInput(0, decomp)
    pieces.parm("class").set("point")
    pieces.parm("snippet").set(PIECES_VEX)
    comment(pieces, "（追加）軸 rod とグリッパの指を足す")

    tpl = build_templates(sub)
    variants = sub.createNode("python", "variant_builder")
    variants.setInput(0, parser)
    variants.setInput(1, classify)
    variants.parm("python").set(VARIANT_CODE)
    comment(variants, "4b. 回転系の形のバリアント\ngeo_id ごとに 1 回だけ作る\n（パーサの出力から = 時間で変わらない）", (0.6, 0.85, 0.6))
    lib = sub.createNode("merge", "all_templates")
    lib.setInput(0, tpl)
    lib.setInput(1, variants)

    copy = sub.createNode("copytopoints", "copy_parts")
    copy.setInput(0, lib)
    copy.setInput(1, pieces)
    sp(copy, "useidattrib", 1)
    sp(copy, "idattrib", "piece")
    sp(copy, "pack", 0)
    copy.parm("resettargetattribs").pressButton()
    # 既定の除外リストから ^orient だけ外す: パック済みパーツの点に向き orient を残す（VAT の剛体モードが読む）。
    # 点の orient はパックの表示には効かない（回転はパックの intrinsic transform が持つ）ので二重には回らない
    copy.parm("applyattribs1").set("*,^v,^Alpha,^N,^up,^pscale,^scale,^rot,^pivot,^trans,^transform")
    comment(copy, "5. copy_parts（Copy to Points）\nPiece Attribute = piece で形を差し替え", (0.6, 0.85, 0.6))

    scale_parts = sub.createNode("xform", "global_scale")
    scale_parts.setInput(0, copy)
    scale_parts.parm("scale").setExpression('ch("../scale")')

    skel = sub.createNode("attribwrangle", "skeleton_view")
    skel.setInput(0, solver)
    skel.parm("class").set("detail")
    skel.parm("snippet").set(SKELETON_VEX)
    comment(skel, "デバッグ: ソケットの骨組み\n（KineFX スケルトン形式）")
    scale_skel = sub.createNode("xform", "global_scale_skel")
    scale_skel.setInput(0, skel)
    scale_skel.parm("scale").setExpression('ch("../scale")')

    both = sub.createNode("merge", "parts_and_skeleton")
    both.setInput(0, scale_parts)
    both.setInput(1, scale_skel)
    sw = sub.createNode("switch", "show_skeleton")
    sw.setInput(0, scale_parts)
    sw.setInput(1, both)
    sw.parm("input").setExpression('ch("../show_skeleton")')

    out = sub.createNode("output", "OUT")
    out.setInput(0, sw)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    out_sk = sub.createNode("output", "OUT_SOCKETS")
    out_sk.setInput(0, scale_skel)
    out_sk.parm("outputidx").set(1)
    sub.layoutChildren()

    node = sub.createDigitalAsset(
        name=HDA_TYPE, hda_file_name=HDA_PATH, description="汎用メカチェーン",
        min_num_inputs=0, max_num_inputs=2, ignore_external_references=True)
    d = node.type().definition()
    d.setParmTemplateGroup(hda_parm_templates())
    node.removeSpareParms()
    sec = d.sections()["DialogScript"]
    sec.setContents(sec.contents()
                    .replace('inputlabel\t1\t"Sub-Network Input #1"', 'inputlabel\t1\t"Base Points (optional)"')
                    .replace('inputlabel\t2\t"Sub-Network Input #2"', 'inputlabel\t2\t"Shapes: sections / meshes / targets"'))
    try:
        d.setMaxNumOutputs(2)
    except AttributeError:
        print("WARN setMaxNumOutputs not available")
    d.addSection("PythonModule", HDA_PYMODULE)
    d.setExtraFileOption("PythonModule/IsPython", True)
    d.setExtraFileOption("PythonModule/IsScript", True)
    d.setExtraFileOption("PythonModule/IsExpr", False)
    d.setIcon("SOP_copytopoints")
    d.setVersion("1.0")
    d.setComment("Socket-contract mecha chain: a recipe string becomes a chain of motors, joints and links.")
    d.addSection("Help", HDA_HELP)
    d.addSection("Tools.shelf", HDA_TOOLS)
    d.updateFromNode(node)
    node.matchCurrentDefinition()
    geo.destroy()
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir)
    hou.hda.uninstallFile(HDA_PATH)
    hou.hda.installFile("$HIP/otls/mecha_chain.hdalc")
    return hou.nodeType(hou.sopNodeTypeCategory(), HDA_TYPE).definition()


# ----------------------------------------------------------------------------
# サンプルシーン
# ----------------------------------------------------------------------------
PLAYGROUND_NOTE = """触って壊して学ぶ（playground）

このオブジェクトの中の mecha_chain1 を選んで、レシピ欄を書き換えてみてください。
1. speed=0.3 を 1.5 にする → 根元の回転が速くなる
2. link(len=1.2) を link(len=3) にする → 腕だけ伸び、モーターの形は伸びない
3. hinge と motor_osc の順番を入れ替える → 組み替えてもそのまま動く
4. link(len=1.2, rad=0.3) にする → そこから先だけ太くなる（rad は下流へ受け継がれる）
5. ] を 1 個消す / motr_rot と打ち間違える → 赤いエラーとメッセージが出る
6. 全体の速さを 0 にする → 時間が止まる（ポーズ確認用）
7.「骨組みを重ねて表示」をオン → ソケットの点と親子の線が見える
"""

TEST_NOTE = """検証チェーン（実装パケット §5.2）

test_bent_single: base > bent(a=45) > link > cap
  折れた先の link が 45° 傾いた方向に伸びれば合格。
test_bent_double: base > bent(a=90) > bent(a=90, b=90) > link
  回転を 2 回重ねると掛け算の順番の差が出る。link が +X 方向へ伸びれば合格
  （順番が逆だと -Y 方向へ伸びる）。1 回だけの bent テストでは順番の誤りは見分けられない。
"""


VAT_PREP_VEX = r'''// vat_prepare（Point Wrangle）… VAT（剛体モード）に渡す前の下ごしらえ
// Labs VAT の剛体モードは「書き出しの最初のフレームでは、全パーツが回転なし」を前提にしています。
// レシピ02 は 1 フレーム目から曲がっているので、1 フレーム目の姿勢を基準（回転なし）に置き直します。
//   orient = 今の向き × (1 フレーム目の向き)^-1   … 1 フレーム目から、どれだけ回ったか
//   pivot  = 1 フレーム目の位置                    … 回転の中心
// これで「1 フレーム目の形を pivot まわりに orient だけ回して、P へ動かす」と、どのフレームの形にも戻せます。
int src = findattribval(1, "point", "name", s@name);   // 2 番目の入力 = 1 フレーム目の、同じ名前のパーツ
vector4 q1 = point(1, "orient", src);
vector p1 = point(1, "P", src);
v@pivot = p1;
p@orient = qmultiply(p@orient, qinvert(q1));            // 先に「1 フレーム目の回転を戻す」、次に「今の回転」
'''

VAT_NOTE = """VAT（剛体モード）で書き出す

1. /out の vat_recipe02 を選んで Render。export/ に FBX（メッシュ）と EXR（位置・回転）ができます。
2. 中の vat_prepare が「1 フレーム目 = 回転なし」に置き直しています（Labs VAT の前提）。
3. Unity 側の手順は tools/01_mech_transform の README「Unity に持っていく」と同じです。
注意: 伸び縮みするパーツ（piston / prismatic）は剛体モードでは伸びません。
"""


VAT_TARGETS = [("vat_recipe02", "02", (0, 0, -12)),       # Phase1 の合格ライン
               ("vat_rotary", "C1", (14, 0, -12))]        # 回転系: 遊星ギア → 同軸スタック（housing / rotor 分割つき）


def build_vat_object(name="vat_recipe02", key="02", t=(0, 0, -12)):
    """レシピを VAT（剛体モード）で書き出すためのオブジェクトと ROP"""
    obj = hou.node("/obj").createNode("geo", name)
    obj.parmTuple("t").set(t)
    m = obj.createNode(HDA_TYPE, "mecha_chain1")
    m.parm("recipe").set(RECIPES[key])
    m.parm("preset").set(key)
    rest = obj.createNode("timeshift", "first_frame")
    rest.setInput(0, m)
    rest.parm("frame").deleteAllKeyframes()
    rest.parm("frame").set(1)
    comment(rest, "1 フレーム目に固定")
    prep = obj.createNode("attribwrangle", "vat_prepare")
    prep.setInput(0, m)
    prep.setInput(1, rest)
    prep.parm("class").set("point")
    prep.parm("snippet").set(VAT_PREP_VEX)
    comment(prep, "1 フレーム目を「回転なし」の基準にして\norient と pivot を書く", (0.95, 0.7, 0.3))
    out = obj.createNode("null", "OUT_VAT")
    out.setInput(0, prep)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    obj.layoutChildren()
    obj.setComment("VAT 書き出し用（レシピ %s）" % key)
    obj.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    try:
        rop = hou.node("/out").createNode("labs::vertex_animation_textures::3.0", name)
    except hou.OperationFailed:
        print("WARN SideFX Labs の VAT ROP が見つからないので ROP は作りません")
        return None
    rop.parm("engine").set("unity")
    rop.hm().setEnginePreset(rop)                       # Unity 用の座標系とスケール
    rop.parm("mode").set(1)                             # Rigid-Body Dynamics（剛体）
    rop.parm("soppath").set(out.path())
    rop.parmTuple("f").deleteAllKeyframes()
    rop.parmTuple("f").set((1, FRAME_END))             # VAT ROP 3.0 の f は（開始, 終了）の 2 つ
    rop.parm("slerpmode").set(1)                        # 角速度 w を使わない回転補間
    rop.parm("exportpath").set("$HIP/export")
    rop.parm("assetname").set("mecha_recipe02" if key == "02" else "mecha_" + key)
    return rop


def export_vat():
    for name, _, _ in VAT_TARGETS:
        rop = hou.node("/out/" + name)
        if rop is not None:
            rop.hm().cookAndRender(rop)
    for root, _, files in os.walk(TOOL_DIR + "/export"):
        for fn in files:
            p = os.path.join(root, fn)
            print("vat:", p.replace("\\", "/").split("/export/")[-1], os.path.getsize(p) // 1024, "KB")


def make_mecha(name, recipe, t=(0, 0, 0), skeleton=False, label=None):
    obj = hou.node("/obj").createNode("geo", name)
    obj.parmTuple("t").set(t)
    m = obj.createNode(HDA_TYPE, "mecha_chain1")
    m.parm("recipe").set(recipe)
    key = [k for k, _, r in PRESETS if r == recipe]
    m.parm("preset").set(key[0] if key else "none")
    m.parm("show_skeleton").set(1 if skeleton else 0)
    m.setDisplayFlag(True)
    m.setRenderFlag(True)
    if label:
        obj.setComment(label)
        obj.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    return obj


def sticky(text, pos, size):
    n = hou.node("/obj").createStickyNote()
    n.setText(text)
    n.setPosition(hou.Vector2(*pos))
    n.setSize(hou.Vector2(*size))
    return n


def gallery_pos(i):
    col, row = i % 5, i // 5
    return (30 + col * 9.0, 0, row * 16.0)


def build_sample():
    hou.setFps(24)
    hou.playbar.setFrameRange(1, FRAME_END)
    hou.playbar.setPlaybackRange(1, FRAME_END)
    hou.setFrame(1)
    make_mecha("recipe02", RECIPES["02"], (0, 0, 0), label="合格ライン: レシピ02")
    make_mecha("playground", RECIPES["02"], (-10, 0, 0), skeleton=True, label="触って壊して学ぶ")
    make_mecha("test_bent_single", BENT_SINGLE, (-18, 0, 0), skeleton=True, label="bent テスト（1 回）")
    make_mecha("test_bent_double", BENT_DOUBLE, (-24, 0, 0), skeleton=True, label="bent テスト（2 回）")
    for i, (key, title, recipe) in enumerate(PRESETS):
        make_mecha("preset%s" % key, recipe, gallery_pos(i), label="%s %s" % (key, title))
    for i, (key, title, recipe) in enumerate(ROTARY_PRESETS):
        make_mecha("rotary%s" % key, recipe, (-30 - (i % 5) * 9.0, 0, (i // 5) * 14.0), label="%s %s" % (key, title))
    for name, key, t in VAT_TARGETS:
        build_vat_object(name, key, t)
    obj = hou.node("/obj")
    obj.layoutChildren()
    sticky(PLAYGROUND_NOTE, (-12, 3), (9, 4.5))
    sticky(TEST_NOTE, (-12, -2.5), (9, 3.2))
    sticky(VAT_NOTE, (-12, -7), (9, 2.8))


# ----------------------------------------------------------------------------
# 自動検証
# ----------------------------------------------------------------------------
def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def qconj(q):
    return (-q[0], -q[1], -q[2], q[3])


def qrot(q, v):
    r = qmul(qmul(q, (v[0], v[1], v[2], 0.0)), qconj(q))
    return r[:3]


def vsub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def vlen(a):
    return math.sqrt(sum(x * x for x in a))


def signed_angle(q, axis_index):
    """q がほぼ 1 軸まわりの回転のとき、その角度（度, -180〜180）"""
    a = math.degrees(2.0 * math.atan2(q[axis_index], q[3]))
    return (a + 180.0) % 360.0 - 180.0


def chain_state(m, frame):
    g = m.node("socket_solver").geometryAtFrame(frame)
    n = len(g.points())

    def grp(name, k):
        vals = g.pointFloatAttribValues(name)
        return [tuple(vals[i * k:(i + 1) * k]) for i in range(n)]
    fp = grp("frame_pos", 3)
    fo = grp("frame_orient", 4)
    sp_ = grp("socket_pos", 3)
    par = g.pointIntAttribValues("parent_id")
    ty = g.pointStringAttribValues("part_type")
    ln = g.pointFloatAttribValues("length")
    ex = g.pointFloatAttribValues("ext")
    pa = g.pointFloatAttribValues("pa")
    pb = g.pointFloatAttribValues("pb")
    drv = g.pointFloatAttribValues("drive_angle")
    rad = g.pointFloatAttribValues("radius")
    pe = g.pointFloatAttribValues("pe")
    pf = g.pointFloatAttribValues("pf")
    gid = g.pointStringAttribValues("geo_id")
    lock = g.pointFloatAttribValues("lock_fade")
    axis = g.pointIntAttribValues("axis")
    internal = g.pointIntAttribValues("internal")
    parts = []
    for i in range(n):
        parts.append(dict(fp=fp[i], fo=fo[i], sp=sp_[i], parent=par[i], type=ty[i], len=ln[i],
                          ext=ex[i], pa=pa[i], pb=pb[i], drive=drv[i], rad=rad[i], pe=pe[i], pf=pf[i],
                          gid=gid[i], lock=lock[i], axis=axis[i], internal=internal[i]))
    return parts


def local_q(parts, i):
    p = parts[i]["parent"]
    pq = (0.0, 0.0, 0.0, 1.0) if p < 0 else parts[p]["fo"]
    return qmul(qconj(pq), parts[i]["fo"])


def invariant_errors(parts):
    """ソケット契約が守られているか: 子の入力 = 親の出力 / 出力 = 入力から len+ext 先 / 向きは単位長"""
    worst = 0.0
    for i, p in enumerate(parts):
        vals = list(p["fp"]) + list(p["fo"]) + list(p["sp"])
        if any(v != v or abs(v) > 1e6 for v in vals):
            return float("inf")
        worst = max(worst, abs(vlen(p["fo"]) - 1.0))
        worst = max(worst, abs(vlen(vsub(p["sp"], p["fp"])) - (p["len"] + p["ext"])))
        if p["parent"] >= 0 and p["type"] not in ("crank_rod", "crank_slider"):
            par = parts[p["parent"]]
            off = (p["pa"] * p["rad"], p["pb"] * p["rad"], 0.0) if p["type"] == "offset" else (0.0, 0.0, 0.0)
            expect = tuple(a + b for a, b in zip(par["sp"], qrot(par["fo"], off)))
            worst = max(worst, vlen(vsub(p["fp"], expect)))
        if p["type"] == "crank_slider":
            # クランク: ロッドの先 = スライダのソケット（ロッドとスライダが一瞬も離れない）
            rods = [q for q in parts if q["type"] == "crank_rod" and q["parent"] == int(p["pf"])
                    and abs(q["pe"] - p["pe"]) < 1e-6]
            worst = max(worst, vlen(vsub(rods[0]["sp"], p["sp"])) if rods else float("inf"))
    return worst


class Checker(object):
    def __init__(self):
        self.lines = []
        self.fails = 0

    def check(self, ok, title, detail=""):
        tag = "PASS" if ok else "FAIL"
        if not ok:
            self.fails += 1
        line = "[%s] %s%s" % (tag, title, (" ... " + detail) if detail else "")
        self.lines.append(line)
        print(line)

    def note(self, text):
        self.lines.append("       " + text)
        print("       " + text)


def parser_errors(m, recipe):
    m.parm("recipe").set(recipe)
    parser = m.node("recipe_parser")
    try:
        parser.cook(force=True)
    except hou.OperationFailed:
        pass
    return parser.errors()


def z_angle(qa, qb):
    """qb が qa から見て Z 軸まわりに何度回っているか（-180〜180）"""
    return signed_angle(qmul(qconj(qa), qb), 2)


def frac_dist(x):
    """整数からのずれ（0〜0.5）"""
    return abs(x - round(x))


def poly_inside(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def poly_dist(pt, poly):
    best = 1e9
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / ((dx * dx + dy * dy) or 1e-12)))
        best = min(best, math.hypot(pt[0] - ax - t * dx, pt[1] - ay - t * dy))
    return best


def seg_dist(pt, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / ((dx * dx + dy * dy) or 1e-12)))
    return math.hypot(pt[0] - a[0] - t * dx, pt[1] - a[1] - t * dy)


def vec_angle(a, b):
    """2 つのベクトルのなす角（度）。acos は 1 の近くで誤差が大きいので atan2 で求める"""
    cr = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    return math.degrees(math.atan2(vlen(cr), sum(x * y for x, y in zip(a, b))))


def rot2(pts, deg, cx=0.0, cy=0.0):
    a = math.radians(deg)
    c_, s_ = math.cos(a), math.sin(a)
    return [(cx + x * c_ - y * s_, cy + x * s_ + y * c_) for x, y in pts]


def star(outline):
    """中心から見て角度順に並んだ輪郭（歯車は中心から見て 1 価）を、半径の検索表にする"""
    pts = sorted(outline, key=lambda q: math.atan2(q[1], q[0]))
    return [math.atan2(q[1], q[0]) for q in pts], pts


def star_pen(points, st, internal):
    """点が歯車の中身に入り込んでいる深さの最大（外歯車: 輪郭の内側、内歯車: 輪郭の外側が中身）"""
    import bisect
    angs, pts = st
    n = len(pts)
    worst = 0.0
    for x, y in points:
        a = math.atan2(y, x)
        i = bisect.bisect_left(angs, a) % n
        p0, p1 = pts[i - 1], pts[i]
        # 光線（中心 → 点）と輪郭の辺 p0-p1 の交点までの距離 = その向きでの輪郭の半径
        ux, uy = math.cos(a), math.sin(a)
        ex, ey = p1[0] - p0[0], p1[1] - p0[1]
        den = ux * ey - uy * ex
        rb = (p0[0] * ey - p0[1] * ex) / den if abs(den) > 1e-12 else math.hypot(*p0)
        rho = math.hypot(x, y)
        if (rho < rb) != internal:
            loc = [pts[(i + k) % n] for k in range(-8, 9)]
            worst = max(worst, min(seg_dist((x, y), loc[k], loc[k + 1]) for k in range(len(loc) - 1)))
    return worst


def gear_outline_of(vb, gid_prefix, r_lo, r_hi):
    """バリアントの歯車（パック済み）から、z = 0 の歯の輪郭を角度順に取り出す"""
    for pr in vb.prims():
        if pr.attribValue("piece").startswith(gid_prefix) and pr.attribValue("piece").endswith("_rotor"):
            g = pr.getEmbeddedGeometry()
            pts = []
            for p in g.points():
                q = p.position()
                rr = math.hypot(q[0], q[1])
                if abs(q[2]) < 1e-6 and r_lo - 1e-6 <= rr <= r_hi + 1e-6:
                    pts.append((math.atan2(q[1], q[0]), q[0], q[1]))
            pts.sort()
            out = []
            for a, x, y in pts:
                if not out or math.hypot(x - out[-1][0], y - out[-1][1]) > 1e-7:
                    out.append((x, y))
            return out
    return []


def verify_rotary(c, m):
    """回転系 5 種（仕様 v0.5）の合格条件と、精査メモで「実装が入ったら見る」とされた点"""
    def load(recipe):
        errs = parser_errors(m, recipe)
        return errs

    def geo_attr(name, frame=1):
        g = m.node("socket_solver").geometryAtFrame(frame)
        a = g.findPointAttrib(name)
        return list(g.pointFloatAttribValues(name)) if a is not None else []

    # ---- 文法 v1.2
    parser_errors(m, "base > motor_rot(speeed=0.5) > cap")
    warns = m.node("recipe_parser").warnings()
    c.check(any("speeed" in w for w in warns), "v1.2: 綴り間違いのキー（speeed=0.5）は黙って飲まずに警告",
            warns[0].splitlines()[-1][:60] if warns else "警告が出ない")
    errs = load("base > link(len=[1,2]) > cap")
    c.check(bool(errs), "v1.2: 原始パーツにリストを書くとエラー", errs[0].splitlines()[-1][:60] if errs else "")
    errs = load("base > coax(layers=3, ratio=[1, -0.8, 0.5], form=[disc, ring, gear]) > cap")
    c.check(not errs, "v1.2: 括弧の中のカンマと文字列（form=[disc, ring, gear]）を読める", errs[0] if errs else "")

    # ---- internal 子の合格条件（§9.2）: 本線は internal 子ではなく親パーツのソケットにつながる
    bad = []
    for key in ("R1", "R2", "R3", "R4", "R5", "C1", "C3", "C5"):
        load(RECIPES[key])
        st = chain_state(m, 1)
        for p in st:
            if p["internal"] == 0 and p["parent"] >= 0 and st[p["parent"]]["internal"] == 1:
                bad.append(key)
    c.check(not bad, "internal 子: 本線のパーツは internal 子（遊星・ロッドなど）にぶら下がらない",
            "OK" if not bad else ", ".join(sorted(set(bad))))

    # ---- 上限の内訳（§9.3）
    errs = load("base" + " > coax(layers=16)" * 16)
    msg = errs[0].splitlines()[-1] if errs else ""
    c.check(bool(errs) and "coax(#2): 17 個" in msg, "上限 256: エラーの内訳だけで原因のパーツが分かる", msg[:90])
    load("base" + " > coax(layers=16)" * 13)
    warns = m.node("recipe_parser").warnings()
    c.check(any("内訳" in w for w in warns), "上限の 80%（205 個）で内訳つきの警告",
            next((w.splitlines()[-1][:70] for w in warns if "内訳" in w), "警告が出ない"))
    errs = load("base" + "".join(" > coax(layers=1, form=gear, teeth=%d)" % (10 + i) for i in range(33)))
    c.check(bool(errs) and "形の種類" in errs[0], "形のバリアントは 32 まで（33 でエラー）",
            errs[0].splitlines()[-1][:60] if errs else "エラーが出ない")

    # ---- R-01 同軸スタック
    ok_all, detail = True, []
    for mode in ("cumulative", "independent"):
        for nl in range(2, 7):
            load("base > coax(layers=%d, stack_mode=%s) > link(len=0.5) > cap" % (nl, mode))
            a1, a2 = chain_state(m, 1), chain_state(m, 2)
            layers = [i for i, p in enumerate(a1) if p["gid"].startswith("layer_")]
            base_q = a1[0]["fo"]
            w = [(z_angle(base_q, a2[i]["fo"]) - z_angle(base_q, a1[i]["fo"]) + 540.0) % 360.0 - 180.0 for i in layers]
            distinct = len(layers) == nl and all(abs(x - y) > 1e-3 for k, x in enumerate(w) for y in w[k + 1:])
            ok_all = ok_all and distinct
            if nl == 6:
                detail.append("%s 6 層: %s °/フレーム" % (mode, ", ".join("%.1f" % x for x in w)))
    c.check(ok_all, "R-01: layers を 2→6 に変えるだけで、全層が別の速さで回る（2 モードとも）", " / ".join(detail))
    load("base > coax(layers=3, ratio=[1,-0.5,2], phase_list=[0,30,60], stack_mode=independent, speed=0.5) > cap")
    T = (37 - 1) / 24.0
    st = chain_state(m, 37)
    layers = [i for i, p in enumerate(st) if p["gid"].startswith("layer_")]
    got = [z_angle(st[0]["fo"], st[i]["fo"]) for i in layers]
    exp = [((360 * 0.5 * r * T + ph) + 180) % 360 - 180 for r, ph in ((1, 0), (-0.5, 30), (2, 60))]
    c.check(all(abs(((g_ - e) + 180) % 360 - 180) < 1e-3 for g_, e in zip(got, exp)),
            "R-01 independent: 各層の角度 = drive × ratio + phase（親に運ばれない）",
            "層の角度 %s（期待 %s）" % (", ".join("%.1f" % x for x in got), ", ".join("%.1f" % x for x in exp)))
    load("base > coax(layers=4, form=disc) > cap")
    gids = sorted(set(p["gid"] for p in chain_state(m, 1) if p["gid"].startswith("layer_")))
    load("base > coax(layers=4, form=[disc,blades,gear,ring]) > cap")
    gids4 = sorted(set(p["gid"] for p in chain_state(m, 1) if p["gid"].startswith("layer_")))
    c.check(len(gids) == 1 and len(gids4) == 4, "R-01: 全層が同じ形なら geo_id は 1 つに集約（形を変えると 4 つ）",
            "%s / %s" % (gids[0], ", ".join(gids4)))
    load("base > coax(layers=4, radius_step=0.7) > link(len=0.5) > cap")
    st = chain_state(m, 1)
    rr = [round(p["rad"], 4) for p in st]
    c.check(abs(st[-2]["rad"] - 0.15) < 1e-6 and min(rr) < 0.06,
            "R-01: radius_step で段々にした太さは、出力ソケットで元に戻る（下流の link は 0.15 のまま）",
            "太さ %s" % rr)

    # ---- R-02 遊星ギア
    vb_lines = []
    ok_mesh, ok_geo, ok_ratio, worst_pen, wrong_pen = True, True, True, 0.0, 0.0
    for S, N, extra in ((12, 3, ""), (10, 4, ""), (9, 3, ""), (13, 5, ""), (12, 3, ", tooth_profile=0"),
                        (12, 3, ", output=ring"), (12, 3, ", helical_angle=20")):
        errs = load("base > planetary(sun_teeth=%d, planet_count=%d, speed=0.7%s) > link(len=0.5) > cap" % (S, N, extra))
        if errs:
            c.check(False, "R-02: S=%d N=%d%s" % (S, N, extra), errs[0])
            continue
        g = m.node("socket_solver").geometryAtFrame(1)
        teeth = g.pointFloatAttribValues("geo_teeth")
        mod = g.pointFloatAttribValues("geo_module")
        st1 = chain_state(m, 1)
        idx = lambda pre: [i for i, p in enumerate(st1) if p["gid"].startswith(pre)]
        ib, isun, iring, icar = idx("pgcase")[0], idx("pgsun")[0], idx("pgring")[0], idx("pgcarrier")[0]
        ipl = idx("pgplanet")
        Sz, Rz, Pz = int(teeth[isun]), int(teeth[iring]), int(teeth[ipl[0]])
        mm = mod[isun]
        planet_gids = set(st1[i]["gid"] for i in ipl)
        ok_geo = ok_geo and len(planet_gids) == 1 and len(ipl) == N
        # 減速比（リング固定ならキャリア = 太陽 × S / (R+S)）
        st2 = chain_state(m, 2)
        ws = z_angle(st1[ib]["fo"], st2[isun]["fo"]) - z_angle(st1[ib]["fo"], st1[isun]["fo"])
        wc = z_angle(st1[ib]["fo"], st2[icar]["fo"]) - z_angle(st1[ib]["fo"], st1[icar]["fo"])
        wr = z_angle(st1[ib]["fo"], st2[iring]["fo"]) - z_angle(st1[ib]["fo"], st1[iring]["fo"])
        if "ring" in extra:
            ok_ratio = ok_ratio and abs(wc) < 1e-6 and abs(wr - (-ws * Sz / float(Rz))) < 1e-4
        else:
            ok_ratio = ok_ratio and abs(wr) < 1e-6 and abs(wc - ws * Sz / float(Sz + Rz)) < 1e-4
        # 噛み合い位相（歯と歯溝が向き合っているか）
        vb = m.node("variant_builder").geometry()
        rp = lambda z: z * mm / 2.0
        sun_o = gear_outline_of(vb, "pgsun", rp(Sz) - 1.25 * mm, rp(Sz) + mm)
        pl_o = gear_outline_of(vb, "pgplanet", rp(Pz) - 1.25 * mm, rp(Pz) + mm)
        ring_o = gear_outline_of(vb, "pgring", rp(Rz) - mm, rp(Rz) + 1.25 * mm)
        sun_s, pl_s, ring_s = star(sun_o), star(pl_o), star(ring_o)
        for f in (1, 17, 41, 73):
            st = chain_state(m, f)
            qb, pb_ = st[ib]["fo"], st[ib]["fp"]
            rad = st[ib]["rad"]
            ts = z_angle(qb, st[isun]["fo"])
            tr = z_angle(qb, st[iring]["fo"])
            for i in ipl:
                rel = qrot(qconj(qb), vsub(st[i]["fp"], pb_))
                gam = math.degrees(math.atan2(rel[1], rel[0]))
                tp = z_angle(qb, st[i]["fo"])
                us = (gam - ts) * Sz / 360.0
                up = (gam + 180.0 - tp) * Pz / 360.0
                ur = (gam - tr) * Rz / 360.0
                up2 = (gam - tp) * Pz / 360.0
                ok_mesh = ok_mesh and frac_dist(us + up - 0.5) < 1e-3 and frac_dist(ur - up2 - 0.5) < 1e-3
                # 形でも確かめる: 歯の輪郭どうしが重ならないか（両方向。めり込み量 / モジュール）
                cx, cy = rel[0] / rad, rel[1] / rad
                for wrong in (0.0, 180.0 / Pz):
                    tpw = tp + wrong
                    pen = 0.0
                    pl_b = rot2(pl_o, tpw, cx, cy)
                    pen = max(pen, star_pen(rot2(pl_b, -ts), sun_s, False))        # 遊星の歯 → 太陽の中
                    pen = max(pen, star_pen(rot2(pl_b, -tr), ring_s, True))        # 遊星の歯 → リングの中
                    near_s = [q for q in rot2(sun_o, ts) if math.hypot(q[0] - cx, q[1] - cy) < rp(Pz) + 1.2 * mm]
                    near_r = [q for q in rot2(ring_o, tr) if math.hypot(q[0] - cx, q[1] - cy) < rp(Pz) + 1.2 * mm]
                    back = lambda pts_: rot2([(q[0] - cx, q[1] - cy) for q in pts_], -tpw)
                    pen = max(pen, star_pen(back(near_s), pl_s, False))                # 太陽の歯 → 遊星の中
                    pen = max(pen, star_pen(back(near_r), pl_s, False))                # リングの歯 → 遊星の中
                    if wrong == 0.0:
                        worst_pen = max(worst_pen, pen / mm)
                    else:
                        wrong_pen = max(wrong_pen, pen / mm)
        vb_lines.append("S%d P%d R%d N%d%s" % (Sz, Pz, Rz, N, extra.replace(", ", " ")))
    c.check(ok_geo, "R-02: 遊星は全部で 1 つの geo_id（等間隔配置の条件が満たされている証拠）", " / ".join(vb_lines))
    c.check(ok_ratio, "R-02: 減速比どおりに回る（キャリア = 太陽 × S/(R+S)、リング出力は −S/R）")
    c.check(ok_mesh, "R-02: 噛み合い位相 — どの遊星も、太陽とリングに対して歯と歯溝が向き合う（4 フレームで確認）")
    c.check(worst_pen < 0.02 and wrong_pen > 0.3,
            "R-02: 歯がめり込まない（輪郭どうしの重なりで確認）",
            "めり込み最大 %.3f × モジュール（わざと半ピッチずらすと %.2f × モジュール）" % (worst_pen, wrong_pen))
    load("base > planetary(sun_teeth=12, planet_count=3, planet_teeth=13) > cap")
    warns = m.node("recipe_parser").warnings()
    c.check(any("planet_teeth" in w for w in warns), "R-02: 等間隔に置けない歯数は自動で寄せて警告",
            next((w.splitlines()[-1][:60] for w in warns if "planet_teeth" in w), ""))

    # ---- R-03 ジンバル
    up_motion = "base > motor_osc(axis=0, b=35, speed=0.35) > hinge(axis=1, b=30, c=0.45) > link(len=0.5) > "
    ok_stab, ok_axis, worst_ang = True, True, 0.0
    for order in ("zxy", "zyx", "xyz", "xzy", "yxz", "yzx"):
        load(up_motion + "gimbal(mode=stabilize, axis_order=%s, angle_list=[0,0,0]) > cap" % order)
        for f in range(1, FRAME_END + 1, 7):
            st = chain_state(m, f)
            frames = [i for i, p in enumerate(st) if p["type"] == "gimbal_frame"]
            pay = frames[-1] + 1
            dq = st[pay]["fo"]
            ang = math.degrees(2 * math.asin(min(1.0, vlen(dq[:3]))))   # acos(w) は w≈1 で誤差が大きいので使わない
            worst_ang = max(worst_ang, ang)
            for i in frames:
                lq = local_q(st, i)
                ax_i = st[i]["axis"]
                others = [abs(lq[k]) for k in range(3) if k != ax_i]
                ok_axis = ok_axis and max(others) < 1e-5
    c.check(worst_ang < 0.01, "R-03 stabilize: 上流を揺らしてもペイロードのワールドの向きが変わらない（軸順 6 通り）",
            "向きのずれ最大 %.4f°" % worst_ang)
    c.check(ok_axis, "R-03: 各リングの回転は自分の軸まわりだけ（軸受から外れない）")
    load("base > hinge(axis=0, a=85) > gimbal(mode=stabilize, axis_order=zxy) > cap")
    st = chain_state(m, 1)
    lk = max(p["lock"] for p in st)
    load("base > hinge(axis=0, a=60) > gimbal(mode=stabilize, axis_order=zxy) > cap")
    lk2 = max(p["lock"] for p in chain_state(m, 1))
    c.check(0.2 < lk < 0.8 and lk2 == 0.0,
            "R-03: ジンバルロック近く（中の角 85°）では補正をフェード（状態を持たない）",
            "85°: フェード %.2f / 60°: %.2f" % (lk, lk2))
    errs = load("base > gimbal(mode=stabilize, axis_enable=[1,0,1]) > cap")
    warns = m.node("recipe_parser").warnings()
    c.check(not errs and any("無効な軸" in w for w in warns), "R-03: 2 軸の stabilize はエラーにせず、残りの軸は成り行き（警告あり）")
    # track: リストの座標と、第2入力の点の 2 通り
    load("base > motor_osc(axis=1, b=30, speed=0.4) > link(len=0.6) > gimbal(mode=track, target=[3,2,6]) > cap")
    worst_t = 0.0
    for f in range(1, FRAME_END + 1, 9):
        st = chain_state(m, f)
        frames = [i for i, p in enumerate(st) if p["type"] == "gimbal_frame"]
        pay = frames[-1] + 1
        d = unit3(vsub((3.0, 2.0, 6.0), st[frames[0]]["fp"]))
        fwd = qrot(st[pay]["fo"], (0.0, 0.0, 1.0))
        worst_t = max(worst_t, vec_angle(d, fwd))
    tgt = m.parent().createNode("add", "track_target")
    tgt.parm("points").set(1)
    tgt.parmTuple("pt0").set((-2.0, 1.5, 5.0))
    m.setInput(1, tgt)
    load("base > link(len=0.6) > gimbal(mode=track, target=0) > cap")
    st = chain_state(m, 1)
    frames = [i for i, p in enumerate(st) if p["type"] == "gimbal_frame"]
    d = unit3(vsub((-2.0, 1.5, 5.0), st[frames[0]]["fp"]))
    fwd = qrot(st[frames[-1] + 1]["fo"], (0.0, 0.0, 1.0))
    a_in = vec_angle(d, fwd)
    m.setInput(1, None)
    tgt.destroy()
    c.check(worst_t < 0.01 and a_in < 0.01, "R-03 track: ペイロードの +Z が目標点を向く（座標指定 / 第2入力の点）",
            "ずれ最大 %.4f° / %.4f°" % (worst_t, a_in))

    # ---- R-04 クランク
    def stroke(e, L, cc, extra=""):
        load("base > crank(eccentric=%g, rod_len=%g, guide_offset=%g, speed=0.25%s) > cap" % (e, L, cc, extra))
        exts = []
        for k in range(360):
            f = 1.0 + 96.0 * k / 360.0
            st = chain_state(m, f)
            sl = [p for p in st if p["type"] == "crank_slider" and p["internal"] == 0][0]
            exts.append(sl["ext"])
        return (max(exts) - min(exts)) / 0.15
    res = []
    ok = True
    for e, L, cc in ((0.5, 3.0, 0.0), (0.8, 3.0, 0.0), (1.2, 3.0, 0.0), (0.8, 3.0, 0.6), (1.0, 2.5, 1.0)):
        got = stroke(e, L, cc)
        exp = 2 * e if cc == 0 else math.sqrt((L + e) ** 2 - cc * cc) - math.sqrt((L - e) ** 2 - cc * cc)
        ok = ok and abs(got - exp) < 2e-3
        res.append("e%g c%g: %.3f（式 %.3f）" % (e, cc, got, exp))
    c.check(ok, "R-04: eccentric を変えるだけでストロークが追従（c=0 で 2e、c≠0 でオフセット版の式）", " / ".join(res))
    worst_r = 0.0
    for extra in ("", ", pin_count=2, pin_phase_list=[0,90]", ", pin_count=3"):
        load("base > crank(eccentric=0.9, rod_len=3.2, guide_offset=0.4, speed=0.5%s) > link(len=0.4) > cap" % extra)
        for f in range(1, FRAME_END + 1, 3):
            st = chain_state(m, f)
            worst_r = max(worst_r, invariant_errors(st))
            for p in st:
                if p["type"] == "crank_rod":
                    wheel = st[p["parent"]]
                    worst_r = max(worst_r, abs(vlen(vsub(p["fp"], wheel["fp"])) - 0.9 * 0.15))
    c.check(worst_r < 1e-5, "R-04: ロッドの両端がピンとスライダから一瞬も離れない（1〜3 ピン、96 フレーム）",
            "ずれ最大 %.1e" % worst_r)
    errs = load("base > crank(eccentric=1, rod_len=2, guide_offset=1.2) > cap")
    c.check(bool(errs) and "成立条件" in errs[0], "R-04: 成立条件 c < L − r を満たさない値はエラー",
            errs[0].splitlines()[-1][:60] if errs else "")

    # ---- R-05 タービン
    ok_b, lines = True, []
    for n, tr, tt, sw in ((3, 20, 10, 0), (5, 45, 15, 0), (7, 35, 15, 25), (8, 70, 30, 0), (12, 10, 5, 0),
                          (12, 60, 40, 0)):
        load("base > turbine(blade_count=%d, twist_root=%g, twist_tip=%g, sweep=%g, lean=%g, hub_form=cyl) > cap"
             % (n, tr, tt, sw, sw / 2.0))
        vb = m.node("variant_builder").geometry()
        bl = [p for p in vb.prims() if p.attribValue("piece").endswith("_blade")][0].getEmbeddedGeometry()
        hub = [p for p in vb.prims() if p.attribValue("piece").startswith("turbine") and
               p.attribValue("piece").endswith("_rotor")][0].getEmbeddedGeometry()
        pts = [p.position() for p in bl.points()]
        # 半径ごと（断面ごと）に、羽根が占める角度の幅を測る。隣の羽根まで 360°/枚数 なので、それより狭ければ当たらない
        rings = {}
        for q in pts:
            rings.setdefault(round(q[0], 6), []).append(math.atan2(q[1], q[0]))
        span = max(max(v) - min(v) for v in rings.values())
        xmin = min(p[0] for p in pts)
        root = [p for p in pts if abs(p[0] - xmin) < 1e-6]
        top = hub.boundingBox().maxvec()[2]
        embedded = all(math.hypot(p[0], p[1]) <= 1.0 + 1e-6 and -1e-6 <= p[2] <= top + 1e-6 for p in root)
        ok_b = ok_b and span < TAU / n and embedded
        lines.append("%d 枚 %g→%g°%s: 羽根の幅は間隔の %.0f%%%s" % (n, tr, tt, " 後退%g°" % sw if sw else "",
                                                             100 * span / (TAU / n),
                                                          "" if embedded else " 根元が出る"))
    c.check(ok_b, "R-05: blade_count と twist を変えても、羽根どうしが干渉せず根元はハブに埋まる",
            " / ".join(lines))
    load(RECIPES["R5"])
    p1 = [p for p in m.node("detail_pieces").geometryAtFrame(1).points() if p.attribValue("piece").endswith("_blade")]
    p2 = [p for p in m.node("detail_pieces").geometryAtFrame(9).points() if p.attribValue("piece").endswith("_blade")]
    c.check(len(p1) == 5 and vlen(vsub(p1[0].attribValue("orient"), p2[0].attribValue("orient"))) > 1e-3,
            "R-05: 羽根 5 枚が並び、全体が回る（pitch_anim で羽根の角度も変わる）")

    # ---- 状態を持たない（直前フレームを読まない）
    load(RECIPES["C1"])
    a = chain_state(m, 50)
    chain_state(m, 90)
    chain_state(m, 3)
    b = chain_state(m, 50)
    c.check(all(vlen(vsub(x["fp"], y["fp"])) < 1e-9 for x, y in zip(a, b)),
            "ステートレス: どのフレームから計算しても同じ答え（スクラブ可・VAT の 1 フレーム目基準と両立）")


def unit3(v):
    n = vlen(v) or 1e-9
    return tuple(x / n for x in v)


def verify():
    c = Checker()
    obj = hou.node("/obj").createNode("geo", "_verify")
    m = obj.createNode(HDA_TYPE, "mecha_chain1")

    # --- 0. HDA 定義
    d = hou.nodeType(hou.sopNodeTypeCategory(), HDA_TYPE).definition()
    c.check(d.description() == "汎用メカチェーン", "HDA の名前（日本語ラベル）", d.description())
    c.check(m.parm("recipe").parmTemplate().label() == "レシピ", "パラメータの日本語ラベル")
    c.check(len(m.outputConnectors()) == 2, "出力が 2 本（パーツ / ソケット）", str(len(m.outputConnectors())))

    # --- 1. 掛け算の順番（実機確認点 3）
    t = obj.createNode("attribwrangle", "qtest")
    t.parm("class").set("detail")
    t.parm("snippet").set('vector4 a = quaternion(radians(90), {1,0,0});\n'
                          'vector4 b = quaternion(radians(90), {0,1,0});\n'
                          'v@ab = qrotate(qmultiply(a, b), {0,0,1});\n'
                          'v@seq = qrotate(a, qrotate(b, {0,0,1}));\n')
    g = t.geometry()
    ab, seq = g.attribValue("ab"), g.attribValue("seq")
    c.check(vlen(vsub(ab, seq)) < 1e-5, "qmultiply(a, b) は「先に b、次に a」",
            "qmultiply=%s / 順に回す=%s" % (tuple(round(x, 3) for x in ab), tuple(round(x, 3) for x in seq)))

    m.parm("recipe").set(BENT_SINGLE)
    st = chain_state(m, 1)
    link_dir = qrot(st[2]["fo"], (0, 0, 1))
    ang = math.degrees(math.acos(max(-1.0, min(1.0, link_dir[2]))))
    c.check(abs(ang - 45.0) < 1e-3, "bent テスト（1 回）: link が 45° 傾いた方向へ伸びる",
            "link の向き=%s, +Z からの角度=%.2f°" % (tuple(round(x, 3) for x in link_dir), ang))
    m.parm("recipe").set(BENT_DOUBLE)
    st = chain_state(m, 1)
    tip = st[-1]["sp"]
    c.check(vlen(vsub(tip, (2.0, -1.0, 0.0))) < 1e-4, "bent テスト（2 回）: 順番の差が出る形でも正しい",
            "link の先=%s（正しい順番なら (2,-1,0)、逆なら (0,-3,0)）" % (tuple(round(x, 3) for x in tip),))

    # --- 2. パーサ
    m.parm("recipe").set(RECIPES["01"])
    g = m.node("recipe_parser").geometry()
    c.check(len(g.points()) == 3 and list(g.pointIntAttribValues("parent_id")) == [-1, 0, 1],
            "レシピ01: 点 3 個、parent_id = -1/0/1")
    c.check(list(g.pointStringAttribValues("tag")) == ["", "motor_rotary", "effector_tool"], "レシピ01: tag")

    m.parm("recipe").set(RECIPES["02"])
    g = m.node("recipe_parser").geometry()
    rows = list(zip(g.pointStringAttribValues("part_type"), g.pointIntAttribValues("axis"),
                    g.pointFloatAttribValues("length"), g.pointFloatAttribValues("speed"),
                    g.pointFloatAttribValues("pa"), g.pointFloatAttribValues("pb"),
                    g.pointFloatAttribValues("pc")))
    expect = [("base", 2, 0.0, 1.0, 0.0, 0.0, 0.0),
              ("motor_rot", 2, 1.0, 0.3, 1.0, 0.0, 0.0),
              ("hinge", 0, 1.0, 1.0, 10.0, 30.0, 0.6),
              ("link", 2, 1.2, 1.0, 0.0, 0.0, 0.0),
              ("motor_osc", 2, 1.0, 0.8, 0.0, 45.0, 0.0),
              ("ball", 2, 1.0, 1.0, 20.0, 0.0, 10.0),
              ("gripper", 2, 0.3, 1.0, 25.0, 1.0, 0.0)]
    ok = len(rows) == len(expect) and all(
        r[0] == e[0] and r[1] == e[1] and all(abs(a - b) < 1e-6 for a, b in zip(r[2:], e[2:]))
        for r, e in zip(rows, expect))
    c.check(ok, "レシピ02: 全パラメータが指定どおりの属性（a= → pa など）")

    m.parm("recipe").set("base > link > motor_rot(rad=0.25) > link > cap")
    g = m.node("recipe_parser").geometry()
    rads = [round(x, 4) for x in g.pointFloatAttribValues("radius")]
    c.check(rads == [0.15, 0.15, 0.25, 0.25, 0.25], "rad の継承: 指定した所から下流だけ太くなる", str(rads))

    bad = [("base > motr_rot > drill", "知らないパーツ名"),
           ("base > splitter(a=2) [ link | link", "] の閉じ忘れ"),
           ("base > splitter(a=3) [ link | link ]", "枝の数と a の食い違い"),
           ("base > splitter(a=2) [ link | link ] > cap", "splitter の後ろに続けた"),
           ("base > link(len=) > cap", "値が空"),
           ("base > [ link ]", "splitter の無い ["),
           ("base > link $ cap", "読めない文字"),
           ("base" + " > link" * 256, "257 個（上限 256 超え）")]
    for recipe, why in bad:
        errs = parser_errors(m, recipe)
        c.check(len(errs) > 0, "文法エラーが見える: " + why, (errs[0].splitlines()[-1][:70] if errs else "エラーが出ない"))
    for recipe, why in [("base" + " > link" * 255, "ちょうど 256 個"), ("", "空のレシピ（base 1 点）"),
                        ("base>motor_rot>drill", "空白なし"),
                        ("base > link  # メモ\n > cap", "# コメントと改行")]:
        errs = parser_errors(m, recipe)
        c.check(len(errs) == 0, "通る: " + why, errs[0] if errs else "")
    parser_errors(m, "base > link(lenn=2) > cap")
    warns = m.node("recipe_parser").warnings()
    c.check(len(warns) > 0, "使われないキーは警告（黄色）で知らせる", warns[0].splitlines()[-1][:60] if warns else "警告が出ない")

    # --- 3. ソルバ: 全プリセット + レシピ02の組み替え でソケット契約が崩れない
    variants = [("02 順番入れ替え", "base > hinge(axis=0, a=10, b=30, c=0.6) > motor_rot(speed=0.3) > "
                 "motor_osc(b=45, speed=0.8) > link(len=1.2) > ball(a=20, c=10) > gripper(b=1)"),
                ("02 延長（2 倍）", RECIPES["02"].replace(" > gripper(b=1)", "") +
                 " > motor_rot(speed=0.6) > hinge(axis=1, b=40, c=0.9) > link(len=0.8) > "
                 "motor_osc(b=30, speed=1.3, phase=90) > gripper(b=1)"),
                ("02 先端で分岐", RECIPES["02"].replace(" > gripper(b=1)", "") +
                 " > splitter(a=2, b=40) [ gripper(b=1) | motor_osc(b=30) > drill ]"),
                ("02 途中から太く", RECIPES["02"].replace("link(len=1.2)", "link(len=1.2, rad=0.25)"))]
    frames = list(range(1, FRAME_END + 1, 5))
    for label, recipe in [("%s %s" % (k, t_), r) for k, t_, r in PRESETS + ROTARY_PRESETS] + variants:
        errs = parser_errors(m, recipe)
        if errs:
            c.check(False, "動く: " + label, errs[0])
            continue
        worst, moved = 0.0, 0.0
        first = chain_state(m, 1)
        for f in frames:
            st = chain_state(m, f)
            worst = max(worst, invariant_errors(st))
            moved = max(moved, max(vlen(vsub(a["sp"], b["sp"])) for a, b in zip(st, first)))
        cg = m.node("copy_parts").geometryAtFrame(1)
        sop_err = [e for nn in ("copy_parts", "socket_solver", "variant_builder", "frame_decompose", "detail_pieces")
                   for e in m.node(nn).errors()]
        # 形が消えていないか: 置くべき点（piece がテンプレートにある点）の数 = 置かれたパーツの数
        libp = set(m.node("all_templates").geometry().primStringAttribValues("piece"))
        pts = m.node("detail_pieces").geometryAtFrame(1)
        want = [p for p in pts.points() if p.attribValue("scale") != (0.0, 0.0, 0.0)]
        miss = sorted(set(p.attribValue("piece") for p in want if p.attribValue("piece") not in libp))
        c.check(worst < 1e-4 and not sop_err and not miss and len(cg.prims()) == len(want), "動く: " + label,
                "パーツ %d 個 / 置いた形 %d 個, ソケット契約のずれ最大 %.1e, 先端の移動 最大 %.2f%s%s" % (
                    len(first), len(cg.prims()), worst, moved,
                    (" / 形が無い piece: " + ", ".join(miss[:3])) if miss else "",
                    (" / " + sop_err[0][:80]) if sop_err else ""))

    # --- 4. ソルバの個別確認（チェックリスト A2）
    m.parm("recipe").set(RECIPES["02"])
    angs, moves = [], []
    base_pos = chain_state(m, 1)[4]["fp"]
    for f in range(1, FRAME_END + 1):
        st = chain_state(m, f)
        angs.append(signed_angle(local_q(st, 4), 2))
        moves.append(vlen(vsub(st[4]["fp"], base_pos)))
    c.check(43.0 < max(abs(a) for a in angs) <= 45.0 + 1e-3,
            "レシピ02: motor_osc が自分で ±45° 往復する", "最大 %.2f°" % max(abs(a) for a in angs))
    c.check(max(moves) > 0.5, "レシピ02: motor_osc は上流に運ばれて位置も動く", "最大 %.2f 移動" % max(moves))
    st_a, st_b = chain_state(m, 1), chain_state(m, 31)
    c.check(vlen(vsub(st_a[-1]["sp"], st_b[-1]["sp"])) > 0.3, "レシピ02: 先端（グリッパ）が動く")

    m.parm("recipe").set("base > hinge(axis=0, b=60, c=1, limit_min=-20, limit_max=20) > link")
    hs = [signed_angle(local_q(chain_state(m, f), 1), 0) for f in range(1, FRAME_END + 1)]
    c.check(max(hs) <= 20.0 + 1e-3 and min(hs) >= -20.0 - 1e-3 and max(hs) > 19.9,
            "hinge の limit: 振幅 60° でも ±20° で頭打ち", "%.2f〜%.2f°" % (min(hs), max(hs)))

    m.parm("recipe").set(RECIPES["04"])
    st = chain_state(m, FRAME_END)
    drive = st[3]["drive"]
    expect_ang = (drive + 180.0) % 360.0 - 180.0
    got = signed_angle(local_q(st, 3), 0)
    c.check(drive > 360.0 and abs(got - expect_ang) < 1e-2,
            "hinge(d=1): 駆動角が 180° を超えても張り付かずに回り続ける",
            "駆動角 %.1f° → 関節の向き %.1f°（%.1f° と同じ向き）" % (drive, got, expect_ang))

    def spring_angle(recipe, f=20):
        m.parm("recipe").set(recipe)
        st = chain_state(m, f)
        i = [k for k, p in enumerate(st) if p["type"] == "spring"][0]
        return signed_angle(local_q(st, i), 2), i
    a1, i1 = spring_angle("base > splitter(a=2, b=40) [ link > link | spring(a=4, b=15) > link ]")
    a2, i2 = spring_angle("base > splitter(a=2, b=40) [ link > link > link > link | spring(a=4, b=15) > link ]")
    c.check(i1 != i2 and abs(a1 - a2) < 1e-4, "spring: 他の枝を増やして点番号が変わっても揺れ方は同じ（depth 方式）",
            "点番号 %d→%d, 角度 %.3f° / %.3f°" % (i1, i2, a1, a2))

    offs = []
    for rr in (0.15, 0.3):
        m.parm("recipe").set("base(rad=%g) > offset(a=1, b=0.5) > link" % rr)
        st = chain_state(m, 1)
        offs.append((st[1]["fp"][0], st[1]["fp"][1], st[1]["rad"]))
    ok = all(abs(x / r - 1.0) < 1e-5 and abs(y / r - 0.5) < 1e-5 for x, y, r in offs)
    c.check(ok, "offset の横ずれは rad 単位: rad を 2 倍にすると、ずれも 2 倍（形との比率が一定）",
            " / ".join("rad %.2f → ずれ (%.3f, %.3f)" % (r, x, y) for x, y, r in offs))
    # 単位を変えたので、offset を使う値（プリセット17 と既定値）を読み替えた。見た目が前と同じかを確かめる
    m.parm("recipe").set(RECIPES["17"])
    st = chain_state(m, 1)
    d17 = vlen(vsub(st[2]["fp"], st[1]["sp"]))
    m.parm("recipe").set("base > offset > link")
    st = chain_state(m, 1)
    d0 = vlen(vsub(st[1]["fp"], st[0]["sp"]))
    c.check(abs(d17 - 0.2) < 1e-3 and abs(d0 - 0.3) < 1e-6,
            "offset の値の読み替え: プリセット17 と既定値のずれが単位変更前と同じ",
            "プリセット17: %.4f（前 0.2）/ 既定: %.4f（前 0.3）" % (d17, d0))

    m.parm("recipe").set(RECIPES["02"])
    tip1 = chain_state(m, 25)[-1]["sp"]
    m.parm("global_speed").set(2.0)
    tip2 = chain_state(m, 13)[-1]["sp"]
    m.parm("global_speed").set(0.5)
    tip3 = chain_state(m, 49)[-1]["sp"]
    m.parm("global_speed").set(1.0)
    c.check(vlen(vsub(tip1, tip2)) < 1e-4 and vlen(vsub(tip1, tip3)) < 1e-4,
            "global_speed: 2 倍なら半分の時間、0.5 倍なら 2 倍の時間で同じ姿勢")

    # --- 5. 造形
    lib = m.node("templates").geometry()
    names = sorted(set(lib.primStringAttribValues("piece")))
    packed = (hou.primType.PackedGeometry, hou.primType.PackedFragment)
    c.check(len(names) == len(TEMPLATES) == len(lib.prims()) and all(p.type() in packed for p in lib.prims()),
            "テンプレート: piece ごとに 1 個のパック済みプリミティブ（ピボットは原点）",
            "%d 種, %s" % (len(names), lib.prims()[0].type()))

    def piece_bounds(recipe, piece_name):
        m.parm("recipe").set(recipe)
        g = m.node("copy_parts").geometryAtFrame(1)
        for pr in g.prims():
            nm = pr.points()[0].attribValue("name")
            if nm == piece_name:
                b = pr.intrinsicValue("bounds")
                return (b[1] - b[0], b[3] - b[2], b[5] - b[4])
        return None
    lk1 = piece_bounds("base > link(len=1.0) > motor_rot(len=1.0) > cap", "part1_link")
    lk2 = piece_bounds("base > link(len=2.5) > motor_rot(len=2.0) > cap", "part1_link")
    mo1 = piece_bounds("base > link(len=1.0) > motor_rot(len=1.0) > cap", "part2_motor_rot")
    mo2 = piece_bounds("base > link(len=2.5) > motor_rot(len=2.0) > cap", "part2_motor_rot")
    mo3 = piece_bounds("base > link(len=2.5) > motor_rot(len=2.0, rad=0.3) > cap", "part2_motor_rot")
    ok = (lk1 and lk2 and mo1 and mo2 and mo3 and abs(lk1[2] - 1.0) < 1e-3 and abs(lk2[2] - 2.5) < 1e-3
          and abs(mo1[2] - mo2[2]) < 1e-4 and abs(mo3[2] / mo2[2] - 2.0) < 1e-3)
    c.check(ok, "scale_mode: link は len で伸び、motor は len で伸びず rad でだけ大きくなる",
            "link 長さ %.2f→%.2f / motor 長さ %.3f→%.3f（rad 2 倍で %.3f）" % (
                lk1[2], lk2[2], mo1[2], mo2[2], mo3[2]) if ok or (lk1 and mo3) else "")
    rod = piece_bounds("base > link(len=2.5) > motor_rot(len=2.0) > cap", "part2_motor_rot_rod")
    c.check(rod is not None and abs(rod[2] - 2.0) < 1e-3, "（追加）motor から次のソケットまで軸 rod がつながる")

    m.parm("recipe").set(RECIPES["02"])
    g = m.node("copy_parts").geometryAtFrame(1)
    pts = m.node("detail_pieces").geometryAtFrame(1)
    expect_n = len([p for p in pts.points() if p.attribValue("piece") in names])
    c.check(len(g.prims()) == expect_n and expect_n > 0,
            "Copy to Points（Piece Attribute）: 置くべき数だけパーツが出る", "%d 個" % len(g.prims()))
    copied = [a.name() for a in g.pointAttribs()]
    c.note("Copy to Points が写した点の属性: " + ", ".join(sorted(copied)))
    c.note("Attributes from Target の既定: " + str(m.node("copy_parts").parm("applyattribs1").eval()
                                                   if m.node("copy_parts").parm("applyattribs1") else "?"))

    sk = m.node("skeleton_view").geometryAtFrame(1)
    c.check(sk.findPointAttrib("transform") is not None and len(sk.points()) == 8,
            "骨組み: 7 パーツ + 先端 1 点、3@transform 付き", "%d 点" % len(sk.points()))

    # プリセットメニューのコールバック
    m.parm("preset").set("11")
    m.hdaModule().load_preset({"node": m, "script_value": "11"})
    c.check(m.evalParm("recipe") == RECIPES["11"], "プリセットメニュー: 選ぶとレシピ欄が入れ替わる")

    # --- 回転系 5 種
    verify_rotary(c, m)

    # --- 6. VAT（剛体モード）の下ごしらえ（レシピ02 と、回転系の見本）
    for vat in [hou.node("/obj/" + nm) for nm, _, _ in VAT_TARGETS]:
      if vat is not None:
        out = vat.node("OUT_VAT")
        g1 = out.geometryAtFrame(1)
        qs = g1.pointFloatAttribValues("orient")
        ident = max(abs(abs(qs[i * 4 + 3]) - 1.0) for i in range(len(qs) // 4))
        c.check(ident < 1e-5 and g1.findPointAttrib("pivot") is not None,
                "VAT %s: 1 フレーム目は全パーツが回転なし（orient = 単位）、pivot あり" % vat.name(),
                "%d パーツ" % (len(qs) // 4))
        tmp = []
        ts = vat.createNode("timeshift")
        ts.setInput(0, out)
        ts.parm("frame").deleteAllKeyframes()
        ts.parm("frame").set(1)
        rest = vat.createNode("unpack")
        rest.setInput(0, ts)
        sp(rest, "transfer_attributes", "name")
        rec = vat.createNode("attribwrangle")
        rec.setInput(0, rest)
        rec.setInput(1, out)
        rec.parm("class").set("point")
        rec.parm("snippet").set('int pr = findattribval(1, "point", "name", s@name);\n'
                                'vector P = point(1, "P", pr);\n'
                                'vector4 q = point(1, "orient", pr);\n'
                                'vector pv = point(1, "pivot", pr);\n'
                                '@P = P + qrotate(q, @P - pv);\n')
        truth = vat.createNode("unpack")
        truth.setInput(0, out)
        tmp = [ts, rest, rec, truth]
        worst = 0.0
        for f in (1, 25, 49, 73, FRAME_END):
            a = rec.geometryAtFrame(f).pointFloatAttribValues("P")
            b = truth.geometryAtFrame(f).pointFloatAttribValues("P")
            worst = max(worst, max(abs(x - y) for x, y in zip(a, b)) if len(a) == len(b) and a else float("inf"))
        c.check(worst < 1e-4, "VAT %s: 1 フレーム目の形を pivot まわりに orient だけ回して P へ動かすと、どのフレームの形とも一致" % vat.name(),
                "頂点のずれ最大 %.1e（5 フレームで比較）" % worst)
        for n_ in tmp:
            n_.destroy()

    obj.destroy()
    summary = "合計 %d 項目 / FAIL %d" % (len(c.lines) - len([l for l in c.lines if l.startswith("       ")]), c.fails)
    print(summary)
    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        fh.write("mecha_chain 自動検証ログ（build_sample.py の verify() が書き出しています）\n")
        fh.write("Houdini %s\n\n" % hou.applicationVersionString())
        fh.write("\n".join(c.lines) + "\n\n" + summary + "\n")
    return c.fails


# ----------------------------------------------------------------------------
# 画像と GIF（OpenGL ROP、画面なし）
# ----------------------------------------------------------------------------
def render_docs():
    from PIL import Image
    obj = hou.node("/obj")
    for lname, rot, inten in (("docs_key", (-45, 35, 0), 1.15), ("docs_fill", (-30, -50, 0), 0.7),
                              ("docs_under", (30, 10, 0), 0.45)):
        lt = obj.createNode("hlight::2.0", lname)
        lt.parm("light_type").set("distant")
        lt.parmTuple("r").set(rot)
        lt.parm("light_intensity").set(inten)
        try:
            lt.parm("shadow_type").set("off")
        except hou.OperationFailed:
            lt.parm("shadow_type").set(0)
    ground = obj.createNode("geo", "docs_ground")
    grid = ground.createNode("grid")
    grid.parmTuple("size").set((300, 300))
    grid.parmTuple("t").set((0, -6.0, 0))
    col = ground.createNode("color")
    col.setInput(0, grid)
    col.parmTuple("color").set((0.80, 0.82, 0.85))
    col.setDisplayFlag(True)
    col.setRenderFlag(True)
    cam = obj.createNode("cam", "docs_cam")
    ogl = hou.node("/out").createNode("opengl", "docs_render")
    ogl.parm("camera").set(cam.path())
    ogl.parm("tres").set(1)
    ogl.parm("aamode").set("aa8")
    ogl.parm("shadows").set(0)
    ogl.parm("ambocclusion").set(0)
    ogl.parm("trange").set(0)
    tmpdir = IMG_DIR + "/_tmp"
    for dd in (IMG_DIR, tmpdir):
        if not os.path.isdir(dd):
            os.makedirs(dd)

    def place(res, target, dist, pitch, yaw):
        cam.parmTuple("res").set(res)
        ogl.parmTuple("res").set(res)
        cp, spp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
        cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        cam.parmTuple("t").set((target[0] + dist * cp * sy, target[1] + dist * spp, target[2] + dist * cp * cy))
        cam.parmTuple("r").set((-pitch, yaw, 0))

    def shoot(tag, res, target, dist, pitch, yaw, vobjects, frame=1):
        hou.setFrame(frame)
        place((res[0] * 2, res[1] * 2), target, dist, pitch, yaw)
        ogl.parm("vobjects").set(vobjects)
        tmp = tmpdir + "/" + tag + ".png"
        ogl.parm("picture").set(tmp)
        ogl.render()
        Image.open(tmp).convert("RGB").resize(res, Image.LANCZOS).save(IMG_DIR + "/" + tag + ".png")
        print("image:", tag)

    def gif(tag, res, target, dist, pitch, yaw, vobjects, step=2):
        place(res, target, dist, pitch, yaw)
        ogl.parm("vobjects").set(vobjects)
        frames = []
        for f in range(1, FRAME_END + 1, step):
            hou.setFrame(f)
            tmp = "%s/%s_%03d.png" % (tmpdir, tag, f)
            ogl.parm("picture").set(tmp)
            ogl.render()
            frames.append(Image.open(tmp).convert("RGB"))
        pal = frames[0].quantize(colors=160, method=Image.MEDIANCUT)
        frames = [fr.quantize(palette=pal) for fr in frames]
        frames[0].save(IMG_DIR + "/" + tag + ".gif", save_all=True, append_images=frames[1:],
                       duration=int(1000 * step / 24.0), loop=0, optimize=True)
        print("gif:", tag)

    def fit(paths, frames, aspect, margin=1.15):
        """オブジェクトが何フレームかの間に通る範囲をまとめて、カメラの注視点と距離を決める"""
        lo, hi = [1e9] * 3, [-1e9] * 3
        for f in frames:
            hou.setFrame(f)
            for pth in paths:
                o = hou.node(pth)
                bb = o.displayNode().geometry().boundingBox()
                t = o.parmTuple("t").eval()
                for k in range(3):
                    lo[k] = min(lo[k], bb.minvec()[k] + t[k])
                    hi[k] = max(hi[k], bb.maxvec()[k] + t[k])
        center = tuple((a + b) * 0.5 for a, b in zip(lo, hi))
        radius = 0.5 * vlen(vsub(hi, lo))
        half_v = math.atan(math.tan(math.radians(22.6)) / aspect)   # 50mm / 41.42 の縦の半画角
        return center, margin * radius / math.sin(half_v)

    span = list(range(1, FRAME_END + 1, 8))
    ground = " /obj/docs_ground"
    c02, d02 = fit(["/obj/recipe02"], span, 16 / 9.0)
    gif("recipe02", (720, 405), c02, d02, 20, 50, "/obj/recipe02" + ground)
    shoot("recipe02_still", (1200, 675), c02, d02 * 0.8, 20, 50, "/obj/recipe02" + ground, frame=31)
    sk = hou.node("/obj/recipe02/mecha_chain1")
    sk.parm("show_skeleton").set(1)
    shoot("recipe02_skeleton", (1200, 675), c02, d02 * 0.8, 20, 50, "/obj/recipe02" + ground, frame=31)
    sk.parm("show_skeleton").set(0)
    c03, d03 = fit(["/obj/preset03"], span, 16 / 9.0)
    gif("recipe03", (720, 405), c03, d03, 20, 50, "/obj/preset03" + ground)
    cb, db = fit(["/obj/test_bent_single", "/obj/test_bent_double"], [1], 2.0)
    shoot("bent_tests", (1200, 600), cb, db, 15, 25, "/obj/test_bent_single /obj/test_bent_double" + ground)

    # ギャラリー: 1 本ずつ撮って 5 列に並べる（Phase1 の 20 本と、回転系の 10 本）
    try:
        from PIL import ImageDraw, ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 19)
    except Exception:
        font = None

    def sheet_of(entries, prefix, out_name, frame=37, pitch=24, yaw=50):
        tile, cols = (384, 256), 5
        rows = (len(entries) + cols - 1) // cols
        sheet = Image.new("RGB", (tile[0] * cols, (tile[1] + 34) * rows), (236, 238, 242))
        for i, (key, title, _) in enumerate(entries):
            pth = "/obj/%s%s" % (prefix, key)
            cc, dd = fit([pth], span, tile[0] / float(tile[1]), margin=1.05)
            shoot("_tile", tile, cc, dd, pitch, yaw, pth + ground, frame=frame)
            img = Image.open(IMG_DIR + "/_tile.png")
            x, y = (i % cols) * tile[0], (i // cols) * (tile[1] + 34)
            sheet.paste(img, (x, y + 34))
            if font is not None:
                ImageDraw.Draw(sheet).text((x + 10, y + 5), "%s  %s" % (key, title), fill=(40, 42, 48), font=font)
        sheet.save(IMG_DIR + "/" + out_name + ".png")
        os.remove(IMG_DIR + "/_tile.png")
        print("image:", out_name)

    sheet_of(PRESETS, "preset", "gallery")
    sheet_of(ROTARY_PRESETS, "rotary", "gallery_rotary", frame=31, pitch=22, yaw=35)

    # 回転系の GIF（遊星ギア、タワー、向きを保つファン、クランク）
    for key, pitch, yaw, margin in (("R2", 18, 20, 0.62), ("C1", 18, 40, 0.9), ("C2", 20, 55, 0.75),
                                    ("R4", 15, 75, 0.85)):
        pth = "/obj/rotary" + key
        cc, dd = fit([pth], span, 16 / 9.0)
        gif("rotary_" + key, (720, 405), cc, dd * margin, pitch, yaw, pth + ground)
    shutil.rmtree(tmpdir)


def main():
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.hipFile.save(HIP_PATH)
    build_hda()
    build_sample()
    hou.hipFile.save(HIP_PATH)
    print("saved:", HIP_PATH)
    print("hda:  ", HDA_PATH)
    fails = verify()
    if "vat" in sys.argv[1:]:
        export_vat()
    if "render" in sys.argv[1:]:
        render_docs()
    print("verify fails:", fails)


if __name__ == "__main__":
    main()
