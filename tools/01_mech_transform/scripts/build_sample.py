# -*- coding: utf-8 -*-
"""
Mech Transform の HDA とサンプルシーンを、ゼロから作り直すスクリプトです。

使い方（コマンドプロンプトで、このツールのフォルダから）:
    "C:/Program Files/Side Effects Software/Houdini 21.0.700/bin/hython.exe" scripts/build_sample.py

作られるもの:
    otls/mech_transform.hdalc      ... HDA 本体
    mech_transform_sample.hiplc    ... 機構パーツのカタログ（サンプルシーン）

ふだん HDA やサンプルを使うだけなら、このスクリプトを動かす必要はありません。
「サンプルがどう組み立てられているか」を Python で読みたいとき、
または壊してしまったサンプルを元に戻したいときに使ってください。
"""
import os
import shutil

import hou

# ----------------------------------------------------------------------------
# 場所と基本設定
# ----------------------------------------------------------------------------
TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
HIP_PATH = TOOL_DIR + "/mech_transform_sample.hiplc"
HDA_PATH = TOOL_DIR + "/otls/mech_transform.hdalc"
HDA_TYPE = "hclaude::mech_transform::1.0"
FRAMES = (1, 72)          # 変形にかけるフレーム範囲
FPS = 24

# HDA が読み取るパーツ属性の一覧（Pack と Attribute Promote に渡す）
PART_ATTRIBS = "name parent move hinge axis angle begin end aim aim_pos stretch Cd"

# 色
GRAY_DARK = (0.22, 0.23, 0.25)
GRAY = (0.38, 0.40, 0.43)
GRAY_LIGHT = (0.62, 0.64, 0.68)
STEEL = (0.80, 0.82, 0.85)
ORANGE = (0.90, 0.52, 0.10)
YELLOW = (0.95, 0.78, 0.15)
BLUE = (0.15, 0.42, 0.85)
TEAL = (0.10, 0.65, 0.70)


# ----------------------------------------------------------------------------
# HDA の中身（VEX）
# ----------------------------------------------------------------------------
VEX_PREPARE = r'''// ============================================================
// 0. 入力の下ごしらえ
// ============================================================
// name が空の面は、動かない 1 個のパーツ "unnamed" としてまとめます。
// （入力に name 属性そのものが無いときも、ここで作られます）
if (s@name == "") s@name = "unnamed";

// HDA が読む属性が入力に無いときは、ここで作っておきます。
// 「自分に自分を代入する」と、値は変えずに属性だけ用意できます。
// 無かった属性の中身は 0 や空文字、つまり「動かない」になります。
s@parent  = s@parent;
v@move    = v@move;
v@hinge   = v@hinge;
v@axis    = v@axis;
f@angle   = f@angle;
f@begin   = f@begin;
f@end     = f@end;
s@aim     = s@aim;
v@aim_pos = v@aim_pos;
i@stretch = i@stretch;

// 色が無いときは白にします（VAT のカラーテクスチャ用）。
if (!hasprimattrib(0, "Cd")) v@Cd = {1, 1, 1};
'''

VEX_SETUP = r'''// ============================================================
// 1. 準備: 動かす前の状態を覚えておく
//    パック 1 個につき点が 1 つあります（点 = パーツの代表）。
// ============================================================
v@rest_P = @P;   // 動く前の、パーツの中心の位置
v@pivot  = @P;   // 回転の中心（VAT ROP の剛体モードが必要とする属性）

// パーツの「名前」を「点番号」に変換しておきます（相手がいなければ -1）。
// 番号にしておくと、あとの計算で相手の属性をすぐ読めます。
i@parent_pt = -1;   // 親パーツの点番号
i@aim_pt    = -1;   // ピストンが向く相手パーツの点番号
if (s@parent != "") i@parent_pt = findattribval(0, "point", "name", s@parent);
if (s@aim    != "") i@aim_pt    = findattribval(0, "point", "name", s@aim);

// 名前の書きまちがいに気づけるように、相手が見つからないときは記録しておきます。
// （すぐ下の Error ノードが、これを HDA の警告として表示します）
if (s@parent != "" && i@parent_pt < 0)
    setdetailattrib(0, "missing", sprintf("parent = %s (part: %s)", s@parent, s@name), "set");
if (s@aim != "" && i@aim_pt < 0)
    setdetailattrib(0, "missing", sprintf("aim = %s (part: %s)", s@aim, s@name), "set");
'''

VEX_ANIMATE = r'''// ============================================================
// 2. 進み具合 t (0〜1) から、いまの位置と回転を決める
// ============================================================
// chf("../xxx") は「1 つ上の階層 = この HDA 本体」のパラメータ xxx を読む書き方です。

// ---- イージング（動きの緩急）をかける関数 ----
float apply_ease(float x; int type)
{
    if (type == 1) return x * x;                         // Ease In     : ゆっくり動き出す
    if (type == 2) return 1.0 - (1.0 - x) * (1.0 - x);   // Ease Out    : ゆっくり止まる
    if (type == 3) return smooth(0.0, 1.0, x);           // Ease In-Out : 動き出しも止まりもゆっくり
    if (type == 4)                                       // Overshoot   : 少し行き過ぎてから戻る
    {
        float s = 1.70158;
        float u = x - 1.0;
        return u * u * ((s + 1.0) * u + s) + 1.0;
    }
    return x;                                            // Linear      : 一定の速さ
}

// ---- パーツ 1 個ぶんの動き（スライド + ヒンジ回転）を、4x4 行列で返す関数 ----
//   pt : パーツ（パックの点）の番号
//   t  : 全体の進み具合 (0〜1)
matrix part_motion(int pt; float t; int ease_type)
{
    // このパーツの属性を読む
    vector move  = point(0, "move",  pt);            // スライドする量
    vector hinge = point(0, "hinge", pt);            // ヒンジ（回転の中心）の位置
    vector axis  = point(0, "axis",  pt);            // ヒンジの軸の向き
    float  angle = radians(point(0, "angle", pt));   // 回す角度（度 → ラジアン）
    float  begin = point(0, "begin", pt);            // 動き始めるタイミング
    float  end   = point(0, "end",   pt);            // 動き終わるタイミング
    if (end <= begin) end = 1.0;                     // end を省略したら、最後 (1.0) まで動く
    if (length(axis) < 0.0001) axis = {0, 1, 0};     // axis を省略したら、Y 軸

    // 全体の t を、このパーツの進み具合 lt に変換する（begin で 0、end で 1）
    float lt = clamp((t - begin) / (end - begin), 0.0, 1.0);
    lt = apply_ease(lt, ease_type);

    // 「ヒンジを中心に回す」と「スライドする」を、1 つの行列にまとめる
    matrix m = ident();
    translate(m, -hinge);                     // ヒンジを原点へ運ぶ
    rotate(m, angle * lt, normalize(axis));   // 軸のまわりに回す
    translate(m, hinge + move * lt);          // 元の場所へ戻し、さらにスライドさせる
    return m;
}

// ---- 親をたどって、パーツの最終的な動きを返す関数 ----
//   自分の動き → 親の動き → 親の親の動き … の順に掛け合わせます。
//   こうすると「親が動けば、子も一緒に動く」ようになります。
matrix chain_motion(int pt; float t; int ease_type)
{
    matrix m = part_motion(pt, t, ease_type);
    int parent = point(0, "parent_pt", pt);
    for (int i = 0; i < 32 && parent >= 0; i++)   // 最大 32 段。親子が輪になっていても止まる
    {
        m *= part_motion(parent, t, ease_type);
        parent = point(0, "parent_pt", parent);
    }
    return m;
}

// ---- 全体の進み具合 t ----
float t = chf("../progress");                 // Progress スライダーの値
if (chi("../drive") == 1)                     // Drive が Frame Range のとき
{
    // 今のフレーム番号を「開始フレーム〜終了フレーム」→「0〜1」に変換します
    vector2 range = chu("../frames");
    t = fit(@Frame, range.x, range.y, 0.0, 1.0);
}
t = clamp(t, 0.0, 1.0);
if (chi("../reverse")) t = 1.0 - t;           // 逆再生
int ease_type = chi("../ease");

// ---- このパーツの動き（親の動きも込み） ----
matrix m = chain_motion(@ptnum, t, ease_type);

// ---- ピストン用: aim を持つパーツは、相手パーツの上の 1 点を向き続ける ----
if (i@aim_pt >= 0)
{
    vector target = v@aim_pos * chain_motion(i@aim_pt, t, ease_type);   // 相手側の取り付け点の、いまの位置
    vector base   = v@hinge * m;                       // 自分側の取り付け点（根元）の、いまの位置
    vector dir0   = normalize(v@aim_pos * m - base);   // 何もしないときに向いている向き
    vector dir1   = normalize(target - base);          // 向きたい向き

    // base を中心に、dir0 が dir1 に重なるように回す
    translate(m, -base);
    m *= matrix(dihedral(dir0, dir1));
    translate(m, base);

    // stretch = 1 のパーツ（ロッド）は、相手との距離が変わったぶんだけ、向きに沿ってスライドする
    if (i@stretch == 1)
        translate(m, dir1 * (distance(target, base) - distance(v@aim_pos, v@hinge)));
}

// ---- 行列から、位置と回転を取り出す ----
@P       = v@rest_P * m;              // 動く前の中心を、行列で動かす
p@orient = quaternion(matrix3(m));    // 行列の回転成分を、クォータニオンにする
'''

VEX_APPLY = r'''// ============================================================
// 3. 点の orient 属性を、パックドプリミティブ本体に反映する
// ============================================================
// パックドプリミティブは、点を動かせば（@P）一緒に動きます。
// しかし点の orient 属性を書いただけでは回転しません。
// 回転は、プリミティブが内部に持つ値（intrinsic）の "transform" に書き込みます。

int     prims[] = pointprims(0, @ptnum);   // この点を使っているプリミティブ（= パック 1 個）
matrix3 rot     = qconvert(p@orient);      // クォータニオン → 3x3 の回転行列
setprimintrinsic(0, "transform", prims[0], rot, "set");
'''

HDA_HELP = '''= Mech Transform =

#icon: SOP/transformpieces

"""パーツに付けた属性のとおりに、スライド・ヒンジ回転・親子連動・ピストンの「変形機構」アニメーションを作ります。"""

入力ジオメトリを `name` 属性ごとに [パックドプリミティブ|/model/packed] にまとめ、
各パーツが持つ属性（スライド量、ヒンジの位置と軸、角度、動くタイミング、親パーツ）を読んで動かします。
スライドするパネル、ヒンジで折り返る板、伸びるシリンダー、油圧ピストン、開閉するハッチなどを、属性を書くだけで作れます。

出力はパックドプリミティブで、ポイント属性 `P`、`orient`、`pivot` を持っています。
そのまま SideFX Labs の Vertex Animation Textures ROP（Rigid-Body Dynamics モード）に渡して、
ゲームエンジン用の VAT として書き出せます。

TIP:
    Progress = 0 は「入力した形のまま」、Progress = 1 は「すべてのパーツが動ききった姿」です。

WARNING:
    VAT に書き出すときは Reverse をオフにし、書き出しの最初のフレームで Progress が 0 になるようにしてください。
    VAT は最初のフレームが「入力した形のまま」である必要があります。

== 入力に付ける属性 ==

パーツごとに、次のプリミティブ属性を付けます。書かなかった属性は 0（動かない）として扱われます。

`name` (文字列):
    パーツ名。同じ名前の面が 1 個のパーツになります。空の面はまとめて `unnamed` という動かないパーツになります。
`parent` (文字列):
    親パーツ名。親が動くと、このパーツも一緒に動きます。
`move` (ベクトル):
    スライドする量。
`hinge` (ベクトル):
    ヒンジ（回転の中心）の位置。
`axis` (ベクトル):
    ヒンジの軸の向き。省略すると Y 軸です。
`angle` (小数):
    回す角度（度）。マイナスで逆回りになります。
`begin` (小数):
    動き始めるタイミング。全体の進み具合 0〜1 のどこで動き出すか。
`end` (小数):
    動き終わるタイミング。省略すると 1（最後まで）です。

`hinge`、`axis`、`move` は、どれも「動く前の形」での位置や向きで書きます。
親を持つパーツでも、親が動く前の座標で書けば大丈夫です。

== ピストン用の属性 ==

油圧ピストンのように「根元を支点にして、相手の取り付け点を向き続ける」パーツに使います。

`aim` (文字列):
    向く相手のパーツ名。
`aim_pos` (ベクトル):
    相手側の取り付け点の位置（動く前の座標）。
`stretch` (整数):
    1 にすると、相手との距離が変わったぶんだけ伸び縮みします（ロッド用）。0 なら向きだけ変えます（シリンダー用）。

ピストンでは `hinge` を「自分側の取り付け点（根元）」として使います。
`aim` を持つパーツは、ほかのパーツの親にはできません。

@parameters

== Animation ==

Drive:
    何で動きを進めるかを選びます。
    Progress Slider:
        Progress の値で動かします。
    Frame Range:
        タイムラインのフレーム番号で自動的に動かします。
Progress:
    全体の進み具合です。0 = 入力した形のまま、1 = すべてのパーツが動ききった姿。
Start/End Frame:
    Drive が Frame Range のとき、動きが始まるフレームと終わるフレームです。
Reverse:
    逆再生します。
Easing:
    パーツの動きの緩急です。Overshoot は少し行き過ぎてから戻る動きになります。

@related
- [Node:sop/pack]
- [Node:sop/attribpromote]
- [Node:sop/attribwrangle]
'''

HDA_TOOLS = '''<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <!-- This file contains definitions of shelves, toolbars, and tools.
 It should not be hand-edited when it is being used by the application.
 Note, that two definitions of the same element are not allowed in
 a single file. -->

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
    """HDA のパラメータ（インターフェース）を作る。"""
    g = hou.ParmTemplateGroup()

    f = hou.FolderParmTemplate("fd_anim", "Animation", folder_type=hou.folderType.Simple)
    f.addParmTemplate(hou.MenuParmTemplate(
        "drive", "Drive", ("slider", "frames"), ("Progress Slider", "Frame Range"), default_value=0,
        help="何で動きを進めるか。Progress Slider: 下の Progress の値で動かします。"
             "Frame Range: タイムラインのフレーム番号で自動的に動かします（VAT 書き出しのときはこちら）。"))
    f.addParmTemplate(hou.FloatParmTemplate(
        "progress", "Progress", 1, default_value=(0.0,), min=0.0, max=1.0,
        min_is_strict=True, max_is_strict=True, disable_when="{ drive != slider }",
        help="全体の進み具合。0 = 入力した形のまま、1 = すべてのパーツが動ききった姿。"))
    f.addParmTemplate(hou.FloatParmTemplate(
        "frames", "Start/End Frame", 2, default_value=(float(FRAMES[0]), float(FRAMES[1])),
        disable_when="{ drive != frames }",
        help="Drive が Frame Range のとき、動きが始まるフレームと終わるフレーム。"))
    f.addParmTemplate(hou.ToggleParmTemplate(
        "reverse", "Reverse", default_value=False,
        help="逆再生します（動ききった姿から、入力した形へ戻る動き）。VAT に書き出すときはオフにしてください。"
             "VAT は最初のフレームが「入力した形のまま」である必要があるためです。"))
    f.addParmTemplate(hou.MenuParmTemplate(
        "ease", "Easing",
        ("linear", "easein", "easeout", "easeinout", "overshoot"),
        ("Linear", "Ease In", "Ease Out", "Ease In-Out", "Overshoot"), default_value=3,
        help="パーツの動きの緩急。Linear: 一定の速さ。Ease In: ゆっくり動き出す。Ease Out: ゆっくり止まる。"
             "Ease In-Out: 両方ゆっくり。Overshoot: 少し行き過ぎてから戻る（カチッとはまる感じ）。"))
    g.append(f)

    f = hou.FolderParmTemplate("fd_attribs", "Part Attributes (input)", folder_type=hou.folderType.Collapsible)
    rows = [
        ("lb_info", "", "入力ジオメトリのプリミティブ属性で、パーツごとの動きを決めます"),
        ("lb_name", "name", "文字列 : パーツ名。同じ名前の面が 1 個のパーツになる"),
        ("lb_parent", "parent", "文字列 : 親パーツ名。親が動くと一緒に動く"),
        ("lb_move", "move", "ベクトル : スライドする量"),
        ("lb_hinge", "hinge", "ベクトル : ヒンジ（回転の中心）の位置"),
        ("lb_axis", "axis", "ベクトル : ヒンジの軸の向き"),
        ("lb_angle", "angle", "小数 : 回す角度（度）"),
        ("lb_begin", "begin", "小数 : 動き始めるタイミング (0〜1)"),
        ("lb_end", "end", "小数 : 動き終わるタイミング (0〜1)"),
        ("lb_aim", "aim", "文字列 : ピストン用。向く相手のパーツ名"),
        ("lb_aim_pos", "aim_pos", "ベクトル : ピストン用。相手側の取り付け点の位置"),
        ("lb_stretch", "stretch", "整数 : ピストン用。1 なら伸び縮みする（ロッド）"),
    ]
    for name, label, text in rows:
        f.addParmTemplate(hou.LabelParmTemplate(name, label, column_labels=(text,)))
    g.append(f)
    return g


def build_hda():
    """HDA をゼロから作って HDA_PATH に保存する。"""
    # 古い定義とファイルを片付ける
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

    # 仮のジオメトリの中でサブネットを組む
    geo = hou.node("/obj").createNode("geo", "hda_build_tmp")
    src = geo.createNode("box", "tmp_box")
    sub = geo.createNode("subnet", "mech_transform1")
    sub.setInput(0, src)
    inp = sub.indirectInputs()[0]

    def wrangle(name, cls, code, source):
        w = sub.createNode("attribwrangle", name)
        w.setInput(0, source)
        w.parm("class").set(cls)
        w.parm("snippet").set(code)
        return w

    w0 = wrangle("prepare_attribs", "primitive", VEX_PREPARE, inp)

    pack = sub.createNode("pack", "pack_pieces")
    pack.setInput(0, w0)
    pack.parm("packbyname").set(1)
    pack.parm("nameattribute").set("name")
    pack.parm("pivot").set("centroid")
    pack.parm("transfer_attributes").set(PART_ATTRIBS)

    prom = sub.createNode("attribpromote", "attribs_to_points")
    prom.setInput(0, pack)
    prom.parm("inname").set(PART_ATTRIBS)
    prom.parm("inclass").set("primitive")
    prom.parm("outclass").set("point")
    prom.parm("method").set("first")
    prom.parm("deletein").set(0)

    w1 = wrangle("setup", "point", VEX_SETUP, prom)

    # パーツ名の書きまちがいを、HDA の警告として見せる
    err = sub.createNode("error", "warn_missing_names")
    err.setInput(0, w1)
    err.parm("numerror").set(1)
    # opinputpath(".", 0) は「このノードの 1 番目の入力につながっているノード」のパス
    err.parm("errormsg1").set('パーツ名が見つかりません: `details(opinputpath(".", 0), "missing")`')
    err.parm("severity1").set("warn")
    err.parm("enable1").setExpression('strlen(details(opinputpath(".", 0), "missing")) > 0')

    w2 = wrangle("animate", "point", VEX_ANIMATE, err)
    w3 = wrangle("apply_to_packed", "point", VEX_APPLY, w2)

    out = sub.createNode("output", "OUT")
    out.setInput(0, w3)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)

    # 見やすいように、上から下へ一列に並べてコメントを付ける
    comments = {
        "prepare_attribs": "0. 名前のない面をまとめ、\n足りない属性を用意する",
        "pack_pieces": "name が同じ面を 1 個の\nパックドプリミティブにまとめる",
        "attribs_to_points": "パーツの属性を、パックの点へ移す\n（プリミティブ属性 → ポイント属性）",
        "setup": "1. 動く前の位置を覚え、\n親や相手の点番号を調べる",
        "warn_missing_names": "親や相手の名前が見つからないとき\nHDA に警告を出す",
        "animate": "2. 進み具合から、いまの\n位置 P と回転 orient を計算する",
        "apply_to_packed": "3. orient をパック本体の\n回転（intrinsic）に書き込む",
    }
    order = ["prepare_attribs", "pack_pieces", "attribs_to_points", "setup", "warn_missing_names",
             "animate", "apply_to_packed", "OUT"]
    y = 0.0
    for name in order:
        n = sub.node(name)
        n.setPosition(hou.Vector2(0, y))
        y -= 1.6
        if name in comments:
            n.setComment(comments[name])
            n.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    inp.setPosition(hou.Vector2(0, 1.6))
    for name in ("prepare_attribs", "pack_pieces", "attribs_to_points"):
        sub.node(name).setColor(hou.Color((0.45, 0.6, 0.8)))
    for name in ("setup", "animate", "apply_to_packed"):
        sub.node(name).setColor(hou.Color((0.95, 0.7, 0.3)))

    # サブネットを HDA にする
    node = sub.createDigitalAsset(
        name=HDA_TYPE,
        hda_file_name=HDA_PATH,
        description="Mech Transform",
        min_num_inputs=1,
        max_num_inputs=1,
        ignore_external_references=True,
    )
    d = node.type().definition()
    d.setParmTemplateGroup(hda_parm_templates())
    node.removeSpareParms()

    # 入力のラベル
    sec = d.sections()["DialogScript"]
    sec.setContents(sec.contents().replace(
        'inputlabel\t1\t"Sub-Network Input #1"', 'inputlabel\t1\t"Geometry with part attributes"'))

    d.setIcon("SOP_transformpieces")
    d.setVersion("1.0")
    d.setComment("Animate packed pieces by per-piece attributes (slide, hinge, parent, piston).")
    d.addSection("Help", HDA_HELP)
    d.addSection("Tools.shelf", HDA_TOOLS)
    # 中の Error ノードの警告を、HDA 本体に表示させる（Type Properties の Node タブ > Message Nodes と同じ）
    d.addSection("MessageNodes", "warn_missing_names")

    d.updateFromNode(node)
    node.matchCurrentDefinition()
    geo.destroy()

    # 保存のたびに Houdini が作るバックアップは、配布には要らないので消す
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir)

    # .hip には HDA の場所が記録されます。絶対パスではなく "$HIP/otls/..." で記録されるように、
    # いったん外して $HIP 付きのパスで入れ直します（フォルダごと別の場所に移しても開けるようにするため）。
    hou.hda.uninstallFile(HDA_PATH)
    hou.hda.installFile("$HIP/otls/mech_transform.hdalc")
    return hou.nodeType(hou.sopNodeTypeCategory(), HDA_TYPE).definition()


# ----------------------------------------------------------------------------
# サンプル用の小道具
# ----------------------------------------------------------------------------
def box(geo, name, size, center):
    n = geo.createNode("box", name)
    n.parmTuple("size").set(size)
    n.parmTuple("t").set(center)
    return n


def tube(geo, name, axis, radius, length, center):
    """axis ('x' / 'y' / 'z') 方向にのびる、ふた付きの円筒。"""
    n = geo.createNode("tube", name)
    n.parm("type").set("poly")
    n.parm("orient").set(axis)
    n.parm("cap").set(1)
    n.parmTuple("t").set(center)
    n.parm("rad1").set(radius)
    n.parm("rad2").set(radius)
    n.parm("height").set(length)
    n.parm("cols").set(24)
    return n


def named(geo, name, shapes):
    """形（1 個または複数）を 1 個のパーツとして、name 属性を付ける。"""
    if len(shapes) == 1:
        src = shapes[0]
    else:
        src = geo.createNode("merge", "shapes_" + name)
        for i, s in enumerate(shapes):
            src.setInput(i, s)
    n = geo.createNode("name", "name_" + name)
    n.setInput(0, src)
    n.parm("name1").set(name)
    return n


def vec(v):
    return "{%s}" % ", ".join("%g" % c for c in v)


def part_block(name, title, color, parent=None, move=None, hinge=None, axis=None, angle=None,
               begin=None, end=None, aim=None, aim_pos=None, stretch=None):
    """パーツ 1 個ぶんの属性を書く VEX の「if ブロック」を作る。"""
    rows = []

    def add(code, comment):
        rows.append((code + ";", comment))

    if parent is not None:
        add('s@parent  = "%s"' % parent, "親パーツ名（親が動くと一緒に動く）")
    if move is not None:
        add("v@move    = %s" % vec(move), "スライドする量")
    if hinge is not None:
        add("v@hinge   = %s" % vec(hinge),
            "根元の取り付け点（ここを支点に向きを変える）" if aim else "ヒンジ（回転の中心）の位置")
    if axis is not None:
        add("v@axis    = %s" % vec(axis), "ヒンジの軸の向き")
    if angle is not None:
        add("f@angle   = %g" % angle, "回す角度（度）。マイナスで逆回り")
    if begin is not None:
        add("f@begin   = %g" % begin, "動き始めるタイミング (0〜1)")
    if end is not None:
        add("f@end     = %g" % end, "動き終わるタイミング (0〜1)")
    if aim is not None:
        add('s@aim     = "%s"' % aim, "ピストン用: 向く相手のパーツ名")
    if aim_pos is not None:
        add("v@aim_pos = %s" % vec(aim_pos), "ピストン用: 相手側の取り付け点（動く前の位置）")
    if stretch is not None:
        add("i@stretch = %d" % stretch, "ピストン用: 1 なら伸び縮みする（ロッド）、0 なら向きだけ変える")
    add("v@Cd      = %s" % vec(color), "色")

    width = max(len(code) for code, _ in rows) + 2
    lines = ["// ---- %s : %s ----" % (name, title),
             'if (s@name == "%s")' % name,
             "{"]
    lines += ["    " + code.ljust(width) + "// " + comment for code, comment in rows]
    lines += ["}"]
    return "\n".join(lines)


def finish(geo, parts, blocks, offset, note):
    """パーツをまとめ、属性を書く Wrangle と HDA につなぎ、出力とメモを置く。"""
    merge = geo.createNode("merge", "merge_parts")
    for i, p in enumerate(parts):
        merge.setInput(i, p)

    # 面の向き（法線）を付けて、箱の角がくっきり見えるようにする
    normals = geo.createNode("normal", "add_normals")
    normals.setInput(0, merge)

    w = geo.createNode("attribwrangle", "part_attributes")
    w.setInput(0, normals)
    w.parm("class").set("primitive")
    w.parm("snippet").set(
        "// このノードに、パーツごとの動きがまとめて書いてあります。\n"
        "// name が一致するパーツに、動きの属性と色を書き込みます。\n"
        "// 書かなかった属性は 0、つまり「動かない」になります。\n\n"
        + "\n\n".join(blocks) + "\n")
    w.setColor(hou.Color((0.95, 0.7, 0.3)))
    w.setComment("パーツごとの動きを\nここで決めています")
    w.setGenericFlag(hou.nodeFlag.DisplayComment, True)

    hda = geo.createNode(HDA_TYPE, "mech_transform1")
    hda.setInput(0, w)
    hda.parm("drive").set("frames")
    hda.setColor(hou.Color((0.3, 0.75, 0.45)))

    out = geo.createNode("null", "OUT_VAT")
    out.setInput(0, hda)
    out.setComment("VAT ROP はここを読みます")
    out.setGenericFlag(hou.nodeFlag.DisplayComment, True)

    place = geo.createNode("xform", "place_in_catalog")
    place.setInput(0, out)
    place.parmTuple("t").set(offset)
    place.setComment("カタログとして並べるために\n横へずらしているだけです")
    place.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    place.setDisplayFlag(True)
    place.setRenderFlag(True)

    geo.layoutChildren()

    # メモ（Sticky Note）をネットワークの左上に置く
    xs = [n.position()[0] for n in geo.children()]
    ys = [n.position()[1] for n in geo.children()]
    sticky = geo.createStickyNote()
    sticky.setText(note)
    sticky.setSize(hou.Vector2(7.5, 5.5))
    sticky.setPosition(hou.Vector2(min(xs) - 8.5, max(ys) - 5.0))
    sticky.setColor(hou.Color((1.0, 0.97, 0.8)))
    return hda


# ----------------------------------------------------------------------------
# 機構パーツ 6 種
# ----------------------------------------------------------------------------
def build_slide_panel(offset):
    geo = hou.node("/obj").createNode("geo", "slide_panel")
    parts = [
        named(geo, "frame", [
            box(geo, "base_slab", (3.0, 0.2, 1.2), (0, 0.1, 0)),
            box(geo, "rail_front", (3.0, 0.16, 0.06), (0, 0.28, 0.57)),
            box(geo, "rail_back", (3.0, 0.16, 0.06), (0, 0.28, -0.57)),
            box(geo, "cover_left", (0.75, 0.05, 1.08), (-1.125, 0.335, 0)),
            box(geo, "cover_right", (0.75, 0.05, 1.08), (1.125, 0.335, 0)),
        ]),
        named(geo, "core", [box(geo, "core_plate", (1.3, 0.04, 0.9), (0, 0.22, 0))]),
        named(geo, "panel_L", [box(geo, "panel_left", (0.75, 0.05, 1.08), (-0.375, 0.275, 0))]),
        named(geo, "panel_R", [box(geo, "panel_right", (0.75, 0.05, 1.08), (0.375, 0.275, 0))]),
    ]
    blocks = [
        part_block("frame", "土台とレール、固定のカバー（動かない）", GRAY),
        part_block("core", "パネルが開くと見える中身（動かない）", TEAL),
        part_block("panel_L", "左へスライドして、固定カバーの下にしまわれる", ORANGE,
                   move=(-0.75, 0, 0), begin=0.0, end=0.7),
        part_block("panel_R", "左より少し遅れて、右へスライドする", ORANGE,
                   move=(0.75, 0, 0), begin=0.3, end=1.0),
    ]
    finish(geo, parts, blocks, offset,
           "【スライドパネル】\n"
           "パネルが左右にスライドして、固定カバーの下にしまわれます。\n\n"
           "使っている属性: move（スライドする量）、begin / end（タイミング）\n\n"
           "試してみよう（オレンジ色の part_attributes を開く）:\n"
           "・panel_L の move を {-0.4, 0, 0} にすると、半分だけ開きます\n"
           "・begin と end を左右で同じにすると、同時に開きます\n"
           "・緑の mech_transform1 の Drive を Progress Slider にすると、\n"
           "  スライダーで動かせます")
    return geo


def build_hinge_fold(offset):
    geo = hou.node("/obj").createNode("geo", "hinge_fold")
    parts = [
        named(geo, "base", [
            box(geo, "base_block", (1.2, 0.3, 1.0), (0, 0.15, 0)),
            tube(geo, "hinge_pin_A", "z", 0.03, 0.94, (0.5, 0.33, 0)),
        ]),
        named(geo, "plate_A", [
            box(geo, "plate_A_box", (1.0, 0.06, 0.9), (0, 0.33, 0)),
            tube(geo, "hinge_pin_B", "z", 0.03, 0.94, (-0.5, 0.39, 0)),
        ]),
        named(geo, "plate_B", [box(geo, "plate_B_box", (1.0, 0.06, 0.9), (0, 0.39, 0))]),
    ]
    blocks = [
        part_block("base", "土台と、1 枚目の板のヒンジ軸（動かない）", GRAY),
        part_block("plate_A", "下の板。上の板が開いたあと、右のふちをヒンジにして 180 度折り返る", ORANGE,
                   hinge=(0.5, 0.33, 0), axis=(0, 0, 1), angle=-180, begin=0.45, end=1.0),
        part_block("plate_B", "上の板。先に左へ 180 度開く。親が plate_A なので、あとで一緒に運ばれる", YELLOW,
                   parent="plate_A", hinge=(-0.5, 0.39, 0), axis=(0, 0, 1), angle=180, begin=0.0, end=0.55),
    ]
    finish(geo, parts, blocks, offset,
           "【折り返しヒンジ板】\n"
           "重なった 2 枚の板が、ヒンジで順番に開いて 1 本の長い板になります。\n\n"
           "使っている属性: hinge / axis / angle（ヒンジ回転）、parent（親子）\n"
           "hinge は「動く前の形」での位置で書きます。\n\n"
           "試してみよう（オレンジ色の part_attributes を開く）:\n"
           "・plate_A の angle を -90 にすると、長い板が立った状態で止まります\n"
           "・plate_B の parent の行を消すと、上の板が置いていかれます\n"
           "・plate_A と plate_B の begin / end を入れ替えると、\n"
           "  上の板が床にめり込みます（動かす順番の大切さが分かります）")
    return geo


def build_flip_block(offset):
    geo = hou.node("/obj").createNode("geo", "flip_block")
    parts = [
        named(geo, "base", [
            box(geo, "base_slab", (2.6, 0.2, 0.9), (0, 0.1, 0)),
            box(geo, "post", (0.16, 0.5, 0.16), (0, 0.45, 0)),
        ]),
        named(geo, "arm", [box(geo, "arm_box", (0.75, 0.08, 0.12), (-0.375, 0.62, 0))]),
        named(geo, "block", [box(geo, "block_box", (0.5, 0.3, 0.5), (-1.0, 0.62, 0))]),
        named(geo, "face_top", [box(geo, "face_top_box", (0.42, 0.03, 0.42), (-1.0, 0.785, 0))]),
        named(geo, "face_bottom", [box(geo, "face_bottom_box", (0.42, 0.03, 0.42), (-1.0, 0.455, 0))]),
    ]
    blocks = [
        part_block("base", "土台と支柱（動かない）", GRAY),
        part_block("arm", "支柱を中心に、水平に 180 度回り込む（軸は Y）", GRAY_DARK,
                   hinge=(0, 0.62, 0), axis=(0, 1, 0), angle=180, begin=0.0, end=0.6),
        part_block("block", "腕に運ばれながら、腕の軸（X）のまわりに 180 度回って裏返る", GRAY_LIGHT,
                   parent="arm", hinge=(-1.0, 0.62, 0), axis=(1, 0, 0), angle=180, begin=0.5, end=1.0),
        part_block("face_top", "ブロックの上の面。ブロックと一緒に動くだけ", ORANGE, parent="block"),
        part_block("face_bottom", "ブロックの下の面。裏返ると、こちらが上になる", BLUE, parent="block"),
    ]
    finish(geo, parts, blocks, offset,
           "【回り込んで裏返るブロック】\n"
           "腕がブロックを反対側へ運び、そのあとブロックが裏返って青い面が上になります。\n\n"
           "使っている属性: hinge / axis / angle、parent（腕 → ブロック → 面 の 3 段）\n\n"
           "試してみよう（オレンジ色の part_attributes を開く）:\n"
           "・arm の axis を {0, 0, 1} にすると、上を通って反対側へ行きます\n"
           "・block の begin を 0 にすると、運ばれながら同時に裏返ります\n"
           "・block の angle を 90 にすると、横倒しで止まります")
    return geo


def build_telescopic_cylinder(offset):
    geo = hou.node("/obj").createNode("geo", "telescopic_cylinder")
    parts = [
        named(geo, "floor", [box(geo, "floor_plate", (3.6, 0.04, 0.8), (0.6, 0.02, 0))]),
        named(geo, "cylinder", [
            box(geo, "mount", (0.2, 0.7, 0.7), (-1.1, 0.39, 0)),
            tube(geo, "cylinder_tube", "x", 0.22, 1.0, (-0.5, 0.39, 0)),
        ]),
        named(geo, "sleeve", [tube(geo, "sleeve_tube", "x", 0.16, 1.0, (-0.45, 0.39, 0))]),
        named(geo, "rod", [tube(geo, "rod_tube", "x", 0.10, 1.0, (-0.40, 0.39, 0))]),
        named(geo, "head", [box(geo, "head_plate", (0.08, 0.5, 0.5), (0.14, 0.39, 0))]),
        named(geo, "cargo", [box(geo, "cargo_box", (0.45, 0.45, 0.45), (0.405, 0.265, 0))]),
    ]
    blocks = [
        part_block("floor", "床の板（動かない）", GRAY_DARK),
        part_block("cylinder", "シリンダーの本体と取り付け台（動かない）", GRAY),
        part_block("sleeve", "1 段目の筒。本体から +X へ伸びる", GRAY_LIGHT,
                   move=(0.8, 0, 0), begin=0.0, end=0.6),
        part_block("rod", "2 段目のロッド。sleeve に運ばれたうえで、自分もさらに伸びる", STEEL,
                   parent="sleeve", move=(0.8, 0, 0), begin=0.4, end=1.0),
        part_block("head", "ロッドの先の押し板。ロッドと一緒に動くだけ", ORANGE, parent="rod"),
        part_block("cargo", "押し出される箱。押し板と一緒に動くだけ", BLUE, parent="head"),
    ]
    finish(geo, parts, blocks, offset,
           "【伸縮シリンダー】\n"
           "2 段の筒が順番に伸びて、先の箱を押し出します。\n\n"
           "使っている属性: move、parent（筒 → ロッド → 押し板 → 箱 の 4 段）\n\n"
           "試してみよう（オレンジ色の part_attributes を開く）:\n"
           "・sleeve と rod の move を変えると、伸びる長さが変わります\n"
           "・cargo の parent の行を消すと、箱が置いていかれます\n"
           "・緑の mech_transform1 の Easing を Overshoot にすると、\n"
           "  勢いよく押し出します")
    return geo


def build_hydraulic_arm(offset):
    geo = hou.node("/obj").createNode("geo", "hydraulic_arm")
    # 取り付け点: A = アーム側、B = 土台側。動く前はどちらも高さ 0.34 にあり、ピストンは水平です。
    pin_a = (-0.25, 0.34, 0)
    pin_b = (0.75, 0.34, 0)
    parts = [
        named(geo, "base", [
            box(geo, "base_slab", (2.2, 0.2, 1.0), (0, 0.1, 0)),
            box(geo, "hinge_bracket", (0.16, 0.34, 0.5), (-0.95, 0.37, 0)),
            box(geo, "base_lug_front", (0.1, 0.2, 0.06), (0.75, 0.3, 0.3)),
            box(geo, "base_lug_back", (0.1, 0.2, 0.06), (0.75, 0.3, -0.3)),
            tube(geo, "base_pin", "z", 0.03, 0.84, pin_b),
        ]),
        named(geo, "arm", [
            box(geo, "arm_box", (1.9, 0.1, 0.5), (0, 0.47, 0)),
            box(geo, "arm_lug_front", (0.1, 0.14, 0.06), (-0.25, 0.37, 0.2)),
            box(geo, "arm_lug_back", (0.1, 0.14, 0.06), (-0.25, 0.37, -0.2)),
            tube(geo, "arm_pin", "z", 0.03, 0.84, pin_a),
        ]),
        named(geo, "cylinder", [
            tube(geo, "cylinder_front", "x", 0.06, 0.62, (0.44, 0.34, 0.36)),
            tube(geo, "cylinder_back", "x", 0.06, 0.62, (0.44, 0.34, -0.36)),
        ]),
        named(geo, "rod", [
            tube(geo, "rod_front", "x", 0.035, 0.9, (0.2, 0.34, 0.36)),
            tube(geo, "rod_back", "x", 0.035, 0.9, (0.2, 0.34, -0.36)),
        ]),
    ]
    blocks = [
        part_block("base", "土台、アームのヒンジ台、ピストンの根元のピン（動かない）", GRAY),
        part_block("arm", "左端のヒンジで 55 度持ち上がる。ピストンの先を留めるピンも同じパーツ", ORANGE,
                   hinge=(-0.95, 0.47, 0), axis=(0, 0, 1), angle=55, begin=0.0, end=1.0),
        part_block("cylinder", "ピストンの外側の筒。根元を支点に、アーム側のピンを向き続ける", GRAY_DARK,
                   hinge=pin_b, aim="arm", aim_pos=pin_a, stretch=0),
        part_block("rod", "ピストンのロッド。筒と同じ向きを向きつつ、ピンとの距離のぶん伸び縮みする", STEEL,
                   hinge=pin_b, aim="arm", aim_pos=pin_a, stretch=1),
    ]
    finish(geo, parts, blocks, offset,
           "【油圧ピストンで持ち上がるアーム】\n"
           "アームが上がると、ピストンが自動でアームのピンを追いかけて伸びます。\n\n"
           "使っている属性: hinge / axis / angle（アーム）、\n"
           "aim / aim_pos / stretch（ピストン）\n\n"
           "試してみよう（オレンジ色の part_attributes を開く）:\n"
           "・arm の angle を 30 や 80 にしても、ピストンは外れません\n"
           "・rod の stretch を 0 にすると、ロッドが伸びずピンから離れます\n"
           "・cylinder の aim の行を消すと、筒が水平のまま取り残されます")
    return geo


def build_hatch_box(offset):
    geo = hou.node("/obj").createNode("geo", "hatch_box")
    parts = [
        named(geo, "box", [
            box(geo, "box_floor", (1.6, 0.06, 1.2), (0, 0.03, 0)),
            box(geo, "box_wall_front", (1.6, 0.8, 0.06), (0, 0.4, 0.57)),
            box(geo, "box_wall_back", (1.6, 0.8, 0.06), (0, 0.4, -0.57)),
            box(geo, "box_wall_left", (0.06, 0.8, 1.08), (-0.77, 0.4, 0)),
            box(geo, "box_wall_right", (0.06, 0.8, 1.08), (0.77, 0.4, 0)),
        ]),
        named(geo, "door_L", [box(geo, "door_left", (0.8, 0.05, 1.2), (-0.4, 0.825, 0))]),
        named(geo, "door_R", [box(geo, "door_right", (0.8, 0.05, 1.2), (0.4, 0.825, 0))]),
        named(geo, "lift", [box(geo, "lift_plate", (1.2, 0.06, 0.9), (0, 0.12, 0))]),
        named(geo, "payload", [box(geo, "payload_box", (0.5, 0.4, 0.5), (0, 0.35, 0))]),
    ]
    blocks = [
        part_block("box", "箱の本体。床と壁 4 枚（動かない）", GRAY),
        part_block("door_L", "左のフタ。箱の左上のふちをヒンジにして、外側へ開く", ORANGE,
                   hinge=(-0.8, 0.825, 0), axis=(0, 0, 1), angle=115, begin=0.0, end=0.45),
        part_block("door_R", "右のフタ。左と鏡写しなので、ヒンジの位置と回す向きが逆", ORANGE,
                   hinge=(0.8, 0.825, 0), axis=(0, 0, 1), angle=-115, begin=0.05, end=0.5),
        part_block("lift", "箱の中の台。フタが開いたあとで、上へスライドする", GRAY_LIGHT,
                   move=(0, 0.62, 0), begin=0.45, end=1.0),
        part_block("payload", "台に載っている中身。台と一緒にせり上がる", BLUE, parent="lift"),
    ]
    finish(geo, parts, blocks, offset,
           "【開閉ハッチ付きの箱】\n"
           "フタが左右に開き、そのあと中の台がせり上がります。\n\n"
           "使っている属性: hinge / axis / angle（フタ）、move（台）、\n"
           "parent（中身）、begin / end（順番）\n\n"
           "試してみよう（オレンジ色の part_attributes を開く）:\n"
           "・フタの angle を 90 や 170 にして、開き具合を変えます\n"
           "・lift の begin を 0 にすると、フタが開く前に台が上がってぶつかります\n"
           "・緑の mech_transform1 の Reverse をオンにすると、閉じる動きになります")
    return geo


# (作る関数, カタログ上の置き場所)
PARTS = [
    (build_slide_panel, (0.0, 0, 0.0)),
    (build_hinge_fold, (4.5, 0, 0.0)),
    (build_flip_block, (9.0, 0, 0.0)),
    (build_telescopic_cylinder, (0.0, 0, 3.8)),
    (build_hydraulic_arm, (4.5, 0, 3.8)),
    (build_hatch_box, (9.0, 0, 3.8)),
]


def build_vat_rop(geo):
    """パーツ 1 個ぶんの VAT 書き出し ROP を /out に作る。"""
    name = geo.name()
    rop = hou.node("/out").createNode("labs::vertex_animation_textures::3.0", "vat_" + name)
    rop.parm("engine").set("unity")
    rop.hm().setEnginePreset(rop)                       # Unity 用の座標系とスケールにする
    rop.parm("mode").set(1)                             # Rigid-Body Dynamics (Rigid)
    rop.parm("soppath").set(geo.path() + "/OUT_VAT")
    rop.parmTuple("f").deleteAllKeyframes()
    rop.parmTuple("f").set(FRAMES)
    rop.parm("slerpmode").set(1)                        # 角速度 w を使わない回転補間
    rop.parm("exportpath").set("$HIP/export")
    rop.parm("assetname").set(name)
    return rop


def main():
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.setFps(FPS)
    hou.playbar.setFrameRange(FRAMES[0], FRAMES[1])
    hou.playbar.setPlaybackRange(FRAMES[0], FRAMES[1])
    hou.setFrame(FRAMES[0])
    hou.hipFile.save(HIP_PATH)          # 先に保存して $HIP を決める

    build_hda()

    for i, (func, offset) in enumerate(PARTS):
        geo = func(offset)
        geo.setPosition(hou.Vector2((i % 3) * 3.5, -(i // 3) * 1.5))
        build_vat_rop(geo)
    hou.node("/out").layoutChildren()

    # /obj と /out に全体のメモを置く
    note = hou.node("/obj").createStickyNote()
    note.setText(
        "【メカ変形パーツ カタログ】\n"
        "箱・板・円筒だけで作った、変形機構の部品 6 種です。\n"
        "再生ボタンを押すと、1〜72 フレームで全部が動きます。\n\n"
        "各オブジェクトの中に入ると、形（Box / Tube）→ 名前（Name）→\n"
        "動きを書く Wrangle（オレンジ）→ Mech Transform（緑）の順に並んでいます。\n"
        "メモに「試してみよう」があります。\n\n"
        "VAT の書き出しは /out にある vat_... ノードの Render All を押します。")
    note.setSize(hou.Vector2(9.5, 4.0))
    note.setPosition(hou.Vector2(-0.5, 1.2))
    note.setColor(hou.Color((1.0, 0.97, 0.8)))

    note = hou.node("/out").createStickyNote()
    note.setText(
        "【VAT 書き出し】\n"
        "部品ごとに 1 個ずつ ROP があります。Render All を押すと、\n"
        "$HIP/export に FBX・テクスチャ・Unity マテリアルが出ます。\n\n"
        "設定: Rigid-Body Dynamics / Unity / 1〜72 フレーム。\n"
        "最初のフレームは必ず「動く前の形」にします（HDA の Reverse はオフ）。")
    note.setSize(hou.Vector2(8.5, 3.0))
    xs = [n.position()[0] for n in hou.node("/out").children()]
    ys = [n.position()[1] for n in hou.node("/out").children()]
    note.setPosition(hou.Vector2(min(xs) - 9.5, max(ys) - 2.0))
    note.setColor(hou.Color((1.0, 0.97, 0.8)))

    hou.hipFile.save(HIP_PATH)
    print("saved:", HIP_PATH)
    print("hda:  ", HDA_PATH)


if __name__ == "__main__":
    main()
