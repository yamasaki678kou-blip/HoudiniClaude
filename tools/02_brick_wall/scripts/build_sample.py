# -*- coding: utf-8 -*-
"""
Brick Wall の HDA とサンプルシーンを、ゼロから作り直すスクリプトです。

使い方（コマンドプロンプトで、このツールのフォルダから）:
    "C:/Program Files/Side Effects Software/Houdini 21.0.700/bin/hython.exe" scripts/build_sample.py
    ... 後ろに render を付けると images/ の画像も作ります。export を付けると export/ に FBX を書き出します。

作られるもの:
    otls/brick_wall.hdalc        ... HDA 本体
    brick_wall_sample.hiplc      ... 4 種類の壁を並べたサンプルシーン

ふだん HDA やサンプルを使うだけなら、このスクリプトを動かす必要はありません。
"""
import math
import os
import shutil
import sys

import hou

# ----------------------------------------------------------------------------
# 場所と基本設定
# ----------------------------------------------------------------------------
TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
HIP_PATH = TOOL_DIR + "/brick_wall_sample.hiplc"
HDA_PATH = TOOL_DIR + "/otls/brick_wall.hdalc"
HDA_TYPE = "hclaude::brick_wall::1.0"
IMG_DIR = TOOL_DIR + "/images"


# ----------------------------------------------------------------------------
# HDA の中身（VEX）
# ----------------------------------------------------------------------------
VEX_GENERATE = r'''// ============================================================
// レンガ 1 個につき、点を 1 つ作ります（点 = レンガの中心）
// あとで Copy to Points が、この点にレンガの形を置きます。
// ============================================================
// chf("../xxx") は「1 つ上の階層 = この HDA 本体」のパラメータ xxx を読む書き方です。
float  W      = chf("../width");         // 壁の幅
float  H      = chf("../height");        // 壁の高さ
vector bs     = chv("../brick_size");    // レンガの大きさ（長さ, 高さ, 奥行き）
float  gap    = chf("../gap");           // 目地（レンガのすき間）
float  bond   = chf("../bond_offset");   // 段ごとの横ずれ（0.5 = 半分ずらす）
float  mincut = chf("../min_cut");       // これより短い切れ端は作らない（レンガの長さに対する割合）
float  seed   = chf("../seed");

float pitch_x = bs.x + gap;   // 横のくり返し幅
float pitch_y = bs.y + gap;   // 縦のくり返し幅
int   nrows   = int(ceil(H / pitch_y));
int   id      = 0;            // レンガの通し番号

for (int row = 0; row < nrows; row++)
{
    float y0 = row * pitch_y;                 // この段の下端
    float y1 = min(y0 + bs.y, H);             // 上端（壁の高さで切る）
    if (y1 - y0 < bs.y * mincut) continue;    // 薄すぎる段は作らない

    // 段ごとに横へずらします。row * bond の「小数部分」を使うので、
    // bond = 0.5 なら 1 段おきに半分、bond = 0.333 なら 3 段で 1 周する階段模様になります。
    float shift = frac(row * bond) * pitch_x;

    for (float x0 = -W * 0.5 - shift; x0 < W * 0.5; x0 += pitch_x)
    {
        float a = max(x0, -W * 0.5);          // レンガの左端（壁の端で切る）
        float b = min(x0 + bs.x, W * 0.5);    // レンガの右端
        if (b - a < bs.x * mincut) continue;  // 短すぎる切れ端は作らない

        // このレンガ専用の乱数。id と seed から作るので、同じ seed なら毎回同じ結果になります。
        float s = id * 3.1 + seed * 97.0;
        id++;
        if (rand(s + 0.11) < chf("../missing")) continue;   // 抜けたレンガ（作らない）

        vector center = set((a + b) * 0.5, (y0 + y1) * 0.5, 0);
        vector size   = set(b - a, y1 - y0, bs.z);

        // ---- ばらつき ----
        size.x   *= 1.0 - rand(s + 0.23) * chf("../jitter_size");          // 少し短く（目地が不ぞろいになる）
        size.y   *= 1.0 - rand(s + 0.37) * chf("../jitter_size") * 0.5;    // 高さは控えめに
        center.z += (rand(s + 0.41) - 0.5) * 2.0 * chf("../jitter_depth");  // 前後にでこぼこ
        vector rot_deg = set(rand(s + 0.53), rand(s + 0.59), rand(s + 0.61));
        rot_deg = (rot_deg - 0.5) * 2.0 * chf("../jitter_rot");            // 少し傾ける（度）
        vector4 orient = eulertoquaternion(radians(rot_deg), 0);           // 角度 → クォータニオン

        // ---- 色: 2 色を混ぜて、明るさを少しばらつかせる ----
        vector col = (rand(s + 0.67) < chf("../color_mix")) ? chv("../color_b") : chv("../color_a");
        col *= 1.0 + (rand(s + 0.79) - 0.5) * 2.0 * chf("../color_var");

        int pt = addpoint(0, center);
        setpointattrib(0, "scale",    pt, size);      // Copy to Points がレンガの大きさに使う
        setpointattrib(0, "orient",   pt, orient);    // Copy to Points がレンガの向きに使う
        setpointattrib(0, "Cd",       pt, col);       // 色
        setpointattrib(0, "brick_id", pt, id - 1);    // 通し番号
        setpointattrib(0, "row",      pt, row);       // 何段目か
        setpointattrib(0, "cut",      pt, (b - a) < bs.x - 1e-5 ? 1 : 0);  // 端で切られたレンガなら 1
    }
}
'''

VEX_UNIT_UV = r'''// レンガの形（1 x 1 x 1 の箱）に、面ごとに 0〜1 の UV を付けます。
// 出力が Packed のときは、この UV がそのまま使われます。
vector n = prim_normal(0, @primnum, 0.5, 0.5);   // この面の向き
vector p = @P + 0.5;                              // 箱は -0.5〜0.5 なので、0〜1 にずらす
if (abs(n.x) >= abs(n.y) && abs(n.x) >= abs(n.z))
    @uv = set(n.x > 0 ? 1.0 - p.z : p.z, p.y, 0);   // 左右を向く面
else if (abs(n.y) >= abs(n.z))
    @uv = set(p.x, n.y > 0 ? 1.0 - p.z : p.z, 0);   // 上下を向く面
else
    @uv = set(n.z > 0 ? p.x : 1.0 - p.x, p.y, 0);   // 前後を向く面
'''

VEX_WORLD_UV = r'''// ============================================================
// ボックス投影 UV
// 面の向き（法線）がいちばん強い軸を見て、残りの 2 軸の座標をそのまま UV にします。
// ワールド座標から作るので、レンガの大きさが違ってもテクスチャの細かさがそろいます。
// ============================================================
vector n = prim_normal(0, @primnum, 0.5, 0.5);   // この面の向き
vector p = @P * chf("../uv_scale");               // uv_scale = 1 m にテクスチャを何回くり返すか
if (abs(n.x) >= abs(n.y) && abs(n.x) >= abs(n.z))
    @uv = set(-p.z * sign(n.x), p.y, 0);          // 左右を向く面 → (z, y)
else if (abs(n.y) >= abs(n.z))
    @uv = set(p.x, -p.z * sign(n.y), 0);          // 上下を向く面 → (x, z)
else
    @uv = set(p.x * sign(n.z), p.y, 0);           // 前後を向く面 → (x, y)
'''

VEX_NAME_BRICKS = r'''// 面ごとに「どのレンガか」が分かる名前を付けます（brick_0, brick_1, ...）。
// 点に付いている brick_id を、面の最初の点から読んでいます。
int id = point(0, "brick_id", primpoint(0, @primnum, 0));
s@name = sprintf("brick_%d", id);
'''

VEX_NAME_MORTAR = r'''// 目地の板。名前は面に、色は点に付けます（レンガの色も点に付いているので、そろえる）。
s@name = "mortar";
foreach (int pt; primpoints(0, @primnum))
    setpointattrib(0, "Cd", pt, chv("../mortar_color"));
'''

HDA_HELP = '''= Brick Wall =

#icon: SOP/box

"""レンガ・タイル・石積みの壁を作ります。段ごとのずれ、目地、ばらつき、抜けを調整できます。"""

幅と高さ、レンガ 1 個の大きさを決めると、壁いっぱいにレンガを敷き詰めます。
VEX でレンガ 1 個につき点を 1 つ作り、[Copy to Points|Node:sop/copytopoints] でレンガの形を置いています。

出力はレンガごとに `name`（brick_0, brick_1, ...）が付いたポリゴンで、ボックス投影の `uv`、頂点カラー `Cd`、法線 `N` を持ちます。
そのまま FBX で Unity に持っていけます。Output を Packed にすると軽いパックドプリミティブになります。

@parameters

== Wall ==

Width:
    壁の幅。X 方向で、原点を中心にします。
Height:
    壁の高さ。地面（Y = 0）から上に伸びます。
Mortar Backing:
    レンガの後ろに目地の板を置きます。抜けたレンガの穴から見えます。
Backing Depth:
    目地の板の厚み。
Mortar Color:
    目地の板の色。

== Brick ==

Brick Size:
    レンガ 1 個の大きさ（長さ, 高さ, 奥行き）。
Gap:
    レンガとレンガのすき間（目地の幅）。
Bond Offset:
    段ごとに横へずらす量（レンガ 1 個ぶん = 1）。0.5 = いわゆるレンガ積み、0 = タイルのように縦にそろう、0.333 = 3 段で 1 周する階段模様。
Min Cut:
    壁の端で切れたレンガが、この割合より短ければ作りません。
Bevel / Bevel Size:
    レンガの角を落とします。

== Variation ==

Seed:
    乱数のタネ。変えると、ばらつき方が変わります。
Size Jitter:
    レンガをランダムに少し短くして、目地を不ぞろいにします。
Depth Jitter:
    レンガを前後にランダムにずらします。
Rotation Jitter:
    レンガをランダムに少し傾けます（度）。
Missing:
    抜けるレンガの割合。0.1 なら 1 割が抜けます。
Color A / Color B / Color Mix:
    2 色のレンガを混ぜます。Color Mix は B になる割合。
Color Variation:
    レンガごとの明るさのばらつき。

== Output ==

Output:
    Polygons: ポリゴン（Unity へ持っていくときはこちら）。Packed: パックドプリミティブ（軽い）。
UV Scale:
    1 m にテクスチャを何回くり返すか（ボックス投影 UV の細かさ）。

@related
- [Node:sop/copytopoints]
- [Node:sop/attribwrangle]
- [Node:sop/box]
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
    S = hou.folderType.Simple

    f = hou.FolderParmTemplate("fd_wall", "Wall", folder_type=S)
    f.addParmTemplate(hou.FloatParmTemplate("width", "Width", 1, default_value=(4.0,), min=0.1, max=20.0,
                                            help="壁の幅。X 方向で、原点を中心にします。"))
    f.addParmTemplate(hou.FloatParmTemplate("height", "Height", 1, default_value=(2.5,), min=0.1, max=10.0,
                                            help="壁の高さ。地面（Y = 0）から上に伸びます。"))
    f.addParmTemplate(hou.ToggleParmTemplate("backing", "Mortar Backing", default_value=True,
                                             help="レンガの後ろに目地の板を置きます。抜けたレンガの穴から見えます。"))
    f.addParmTemplate(hou.FloatParmTemplate("backing_depth", "Backing Depth", 1, default_value=(0.05,), min=0.001, max=0.5,
                                            disable_when="{ backing == 0 }", help="目地の板の厚み。"))
    f.addParmTemplate(hou.FloatParmTemplate("mortar_color", "Mortar Color", 3, default_value=(0.62, 0.60, 0.56),
                                            look=hou.parmLook.ColorSquare, naming_scheme=hou.parmNamingScheme.RGBA,
                                            disable_when="{ backing == 0 }", help="目地の板の色。"))
    g.append(f)

    f = hou.FolderParmTemplate("fd_brick", "Brick", folder_type=S)
    f.addParmTemplate(hou.FloatParmTemplate("brick_size", "Brick Size", 3, default_value=(0.4, 0.1, 0.2),
                                            help="レンガ 1 個の大きさ（長さ, 高さ, 奥行き）。"))
    f.addParmTemplate(hou.FloatParmTemplate("gap", "Gap", 1, default_value=(0.012,), min=0.0, max=0.1,
                                            help="レンガとレンガのすき間（目地の幅）。"))
    f.addParmTemplate(hou.FloatParmTemplate("bond_offset", "Bond Offset", 1, default_value=(0.5,), min=0.0, max=1.0,
                                            min_is_strict=True, max_is_strict=True,
                                            help="段ごとに横へずらす量（レンガ 1 個ぶん = 1）。0.5 = レンガ積み、0 = タイル、0.333 = 階段模様。"))
    f.addParmTemplate(hou.FloatParmTemplate("min_cut", "Min Cut", 1, default_value=(0.3,), min=0.0, max=1.0,
                                            min_is_strict=True, max_is_strict=True,
                                            help="壁の端で切れたレンガが、この割合より短ければ作りません。"))
    f.addParmTemplate(hou.ToggleParmTemplate("bevel", "Bevel", default_value=False, help="レンガの角を落とします。"))
    f.addParmTemplate(hou.FloatParmTemplate("bevel_size", "Bevel Size", 1, default_value=(0.01,), min=0.0, max=0.05,
                                            disable_when="{ bevel == 0 }", help="角を落とす大きさ。"))
    g.append(f)

    f = hou.FolderParmTemplate("fd_var", "Variation", folder_type=S)
    f.addParmTemplate(hou.FloatParmTemplate("seed", "Seed", 1, default_value=(0.0,), min=0.0, max=100.0,
                                            help="乱数のタネ。変えると、ばらつき方が変わります。"))
    f.addParmTemplate(hou.FloatParmTemplate("jitter_size", "Size Jitter", 1, default_value=(0.1,), min=0.0, max=1.0,
                                            min_is_strict=True, max_is_strict=True,
                                            help="レンガをランダムに少し短くして、目地を不ぞろいにします。"))
    f.addParmTemplate(hou.FloatParmTemplate("jitter_depth", "Depth Jitter", 1, default_value=(0.0,), min=0.0, max=0.1,
                                            help="レンガを前後にランダムにずらす量。"))
    f.addParmTemplate(hou.FloatParmTemplate("jitter_rot", "Rotation Jitter", 1, default_value=(0.0,), min=0.0, max=15.0,
                                            help="レンガをランダムに少し傾けます（度）。"))
    f.addParmTemplate(hou.FloatParmTemplate("missing", "Missing", 1, default_value=(0.0,), min=0.0, max=1.0,
                                            min_is_strict=True, max_is_strict=True,
                                            help="抜けるレンガの割合。0.1 なら 1 割が抜けます。"))
    f.addParmTemplate(hou.SeparatorParmTemplate("sep_color"))
    f.addParmTemplate(hou.FloatParmTemplate("color_a", "Color A", 3, default_value=(0.66, 0.33, 0.25),
                                            look=hou.parmLook.ColorSquare, naming_scheme=hou.parmNamingScheme.RGBA,
                                            help="レンガの基本の色。"))
    f.addParmTemplate(hou.FloatParmTemplate("color_b", "Color B", 3, default_value=(0.48, 0.24, 0.20),
                                            look=hou.parmLook.ColorSquare, naming_scheme=hou.parmNamingScheme.RGBA,
                                            help="混ぜる 2 色目。"))
    f.addParmTemplate(hou.FloatParmTemplate("color_mix", "Color Mix", 1, default_value=(0.3,), min=0.0, max=1.0,
                                            min_is_strict=True, max_is_strict=True, help="Color B になるレンガの割合。"))
    f.addParmTemplate(hou.FloatParmTemplate("color_var", "Color Variation", 1, default_value=(0.15,), min=0.0, max=1.0,
                                            min_is_strict=True, max_is_strict=True, help="レンガごとの明るさのばらつき。"))
    g.append(f)

    f = hou.FolderParmTemplate("fd_out", "Output", folder_type=S)
    f.addParmTemplate(hou.MenuParmTemplate("output", "Output", ("polygons", "packed"), ("Polygons", "Packed"), default_value=0,
                                           help="Polygons: ポリゴン（Unity へ持っていくときはこちら）。Packed: パックドプリミティブ（軽い）。"))
    f.addParmTemplate(hou.FloatParmTemplate("uv_scale", "UV Scale", 1, default_value=(1.0,), min=0.01, max=10.0,
                                            help="1 m にテクスチャを何回くり返すか（ボックス投影 UV の細かさ）。"))
    g.append(f)
    return g


def set_normal_type(normal_node, vertex=True, cusp=40.0):
    """Normal SOP を「頂点法線、カスプ角 cusp」にする。"""
    p = normal_node.parm("type")
    try:
        p.set("typevertex" if vertex else "typepoint")
    except hou.OperationFailed:
        p.set(1 if vertex else 0)
    normal_node.parm("cuspangle").set(cusp)


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
    sub = geo.createNode("subnet", "brick_wall1")

    def wrangle(name, cls, code, source=None):
        w = sub.createNode("attribwrangle", name)
        if source is not None:
            w.setInput(0, source)
        w.parm("class").set(cls)
        w.parm("snippet").set(code)
        return w

    # ---- レンガの点 ----
    gen = wrangle("generate_brick_points", "detail", VEX_GENERATE)

    # ---- レンガの形（1 x 1 x 1 の箱。大きさは Copy to Points が scale 属性で決める）----
    box = sub.createNode("box", "brick_box")
    bevel = sub.createNode("polybevel::3.0", "brick_bevel")
    bevel.setInput(0, box)
    bevel.parm("grouptype").set("edges")
    bevel.parm("offset").setExpression('ch("../bevel_size")')
    bevel.parm("filletshape").set("round")
    bevel.parm("divisions").set(1)
    sw_bevel = sub.createNode("switch", "switch_bevel")
    sw_bevel.setInput(0, box)
    sw_bevel.setInput(1, bevel)
    sw_bevel.parm("input").setExpression('ch("../bevel")')
    unit_uv = wrangle("unit_box_uv", "vertex", VEX_UNIT_UV, sw_bevel)
    nrm_shape = sub.createNode("normal", "normals_shape")   # Packed 出力でも角がカクッと見えるように、形に先に法線を付ける
    nrm_shape.setInput(0, unit_uv)
    set_normal_type(nrm_shape, True, 40.0)

    # ---- 点にレンガを置く ----
    copy = sub.createNode("copytopoints::2.0", "copy_bricks")
    copy.setInput(0, nrm_shape)
    copy.setInput(1, gen)
    copy.parm("resettargetattribs").pressButton()      # 点の属性（Cd, brick_id, row, cut）をレンガに渡す既定値にする
    copy.parm("pack").setExpression('ch("../output")')  # Output が Packed のときだけパックする

    # ---- ポリゴン出力のときの後処理（名前、ワールド UV、法線）----
    name_b = wrangle("name_bricks", "primitive", VEX_NAME_BRICKS, copy)
    uv_b = wrangle("box_projection_uv", "vertex", VEX_WORLD_UV, name_b)
    nrm_b = sub.createNode("normal", "normals_bricks")
    nrm_b.setInput(0, uv_b)
    set_normal_type(nrm_b, True, 40.0)
    sw_out = sub.createNode("switch", "switch_output")
    sw_out.setInput(0, nrm_b)
    sw_out.setInput(1, copy)
    sw_out.parm("input").setExpression('ch("../output")')

    # ---- 目地の板 ----
    back = sub.createNode("box", "backing_box")
    back.parm("sizex").setExpression('ch("../width")')
    back.parm("sizey").setExpression('ch("../height")')
    back.parm("sizez").setExpression('ch("../backing_depth")')
    back.parm("ty").setExpression('ch("../height") / 2')
    back.parm("tz").setExpression('-ch("../brick_sizez") / 2 + 0.004 - ch("../backing_depth") / 2')
    name_m = wrangle("name_mortar", "primitive", VEX_NAME_MORTAR, back)
    uv_m = wrangle("box_projection_uv_mortar", "vertex", VEX_WORLD_UV, name_m)
    nrm_m = sub.createNode("normal", "normals_mortar")
    nrm_m.setInput(0, uv_m)
    set_normal_type(nrm_m, True, 40.0)
    empty = sub.createNode("null", "no_backing")
    sw_back = sub.createNode("switch", "switch_backing")
    sw_back.setInput(0, empty)
    sw_back.setInput(1, nrm_m)
    sw_back.parm("input").setExpression('ch("../backing")')

    merge = sub.createNode("merge", "merge_all")
    merge.setInput(0, sw_out)
    merge.setInput(1, sw_back)
    out = sub.createNode("output", "OUT")
    out.setInput(0, merge)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)

    comments = {
        "generate_brick_points": "VEX でレンガ 1 個につき点を 1 つ作る\n（位置、大きさ scale、向き orient、色 Cd）",
        "brick_box": "レンガの形。1 x 1 x 1 の箱",
        "unit_box_uv": "箱に面ごとの 0〜1 UV（Packed 用）",
        "copy_bricks": "点にレンガを置く。scale と orient で\n大きさと向きが決まる",
        "name_bricks": "面に brick_0, brick_1, ... の名前",
        "box_projection_uv": "ワールド座標からボックス投影 UV",
        "normals_bricks": "頂点法線（角はカクッと）",
        "backing_box": "目地の板",
        "switch_output": "Polygons / Packed の切り替え",
        "switch_backing": "目地の板のオン / オフ",
    }
    for nm, c in comments.items():
        n = sub.node(nm)
        n.setComment(c)
        n.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    for nm in ("generate_brick_points", "unit_box_uv", "name_bricks", "box_projection_uv", "name_mortar", "box_projection_uv_mortar"):
        sub.node(nm).setColor(hou.Color((0.95, 0.7, 0.3)))
    sub.layoutChildren()

    node = sub.createDigitalAsset(
        name=HDA_TYPE, hda_file_name=HDA_PATH, description="Brick Wall",
        min_num_inputs=0, max_num_inputs=0, ignore_external_references=True)
    d = node.type().definition()
    d.setParmTemplateGroup(hda_parm_templates())
    node.removeSpareParms()
    d.setIcon("SOP_box")
    d.setVersion("1.0")
    d.setComment("Generate brick / tile / stone walls with bond offset, gaps, jitter and missing bricks.")
    d.addSection("Help", HDA_HELP)
    d.addSection("Tools.shelf", HDA_TOOLS)
    d.updateFromNode(node)
    node.matchCurrentDefinition()
    geo.destroy()
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir)

    hou.hda.uninstallFile(HDA_PATH)
    hou.hda.installFile("$HIP/otls/brick_wall.hdalc")
    return hou.nodeType(hou.sopNodeTypeCategory(), HDA_TYPE).definition()


# ----------------------------------------------------------------------------
# サンプル
# ----------------------------------------------------------------------------
WALLS = [
    # (名前, 置く位置 x, パラメータ, メモ)
    ("wall_default", -7.2, {},
     "【基本のレンガ壁】\n"
     "パラメータは全部そのまま（既定値）です。\n\n"
     "試してみよう:\n"
     "・Bond Offset を 0 にすると、目地が縦にそろいます（タイル積み）\n"
     "・Bond Offset を 0.333 にすると、階段模様になります\n"
     "・Gap を 0.03 にすると、目地が太くなります\n"
     "・Min Cut を 0.9 にすると、端の半端なレンガが消えます"),
    ("wall_tiles", -2.4,
     {"brick_size": (0.3, 0.3, 0.03), "gap": 0.004, "bond_offset": 0.0, "bevel": 1, "bevel_size": 0.004,
      "color_a": (0.86, 0.86, 0.83), "color_b": (0.74, 0.78, 0.80), "color_mix": 0.2, "color_var": 0.05,
      "jitter_size": 0.0, "mortar_color": (0.45, 0.45, 0.45), "backing_depth": 0.02},
     "【タイル】\n"
     "レンガを正方形で薄くして、Bond Offset を 0 にしただけです。\n"
     "角を落とす Bevel をオンにしています。\n\n"
     "試してみよう:\n"
     "・Brick Size を (0.6, 0.3, 0.03) にすると、長方形のタイルになります\n"
     "・Missing を 0.05 にすると、はがれたタイルができます\n"
     "・UV Scale を 2 にすると、テクスチャが 2 倍細かくくり返されます"),
    ("wall_old", 2.4,
     {"jitter_size": 0.25, "jitter_depth": 0.012, "jitter_rot": 3.0, "missing": 0.1, "seed": 3.0,
      "color_mix": 0.45, "color_var": 0.3, "mortar_color": (0.40, 0.38, 0.35)},
     "【古い壁】\n"
     "ばらつき（Variation）のパラメータだけで、くずれた感じを出しています。\n"
     "抜けたレンガの穴から、後ろの目地の板（Mortar Backing）が見えます。\n\n"
     "試してみよう:\n"
     "・Seed を変えると、別のくずれ方になります\n"
     "・Missing を 0.3 にすると、かなり壊れた壁になります\n"
     "・Mortar Backing をオフにすると、穴が貫通します"),
    ("wall_stone", 7.2,
     {"brick_size": (0.5, 0.22, 0.25), "gap": 0.02, "bond_offset": 0.333, "jitter_size": 0.15, "jitter_depth": 0.02,
      "color_a": (0.55, 0.55, 0.52), "color_b": (0.42, 0.40, 0.38), "color_mix": 0.5, "color_var": 0.2,
      "output": 1, "mortar_color": (0.30, 0.30, 0.30)},
     "【石積み（Packed 出力）】\n"
     "大きめの石を 3 段で 1 周する階段模様（Bond Offset 0.333）で積んでいます。\n"
     "Output が Packed なので、石 1 個が 1 個のパックドプリミティブです。\n"
     "大きな壁をたくさん並べるときに軽くなります。\n\n"
     "試してみよう:\n"
     "・Output を Polygons にして、Geometry Spreadsheet で面の数を比べてみる\n"
     "・Depth Jitter を 0.05 にすると、石がごつごつ出っ張ります"),
]


def build_sample():
    obj = hou.node("/obj")
    for i, (name, x, parms, note) in enumerate(WALLS):
        geo = obj.createNode("geo", name)
        wall = geo.createNode(HDA_TYPE, "brick_wall1")
        for k, v in parms.items():
            if isinstance(v, tuple):
                wall.parmTuple(k).set(v)
            else:
                wall.parm(k).set(v)
        wall.setColor(hou.Color((0.3, 0.75, 0.45)))
        out = geo.createNode("null", "OUT")
        out.setInput(0, wall)
        place = geo.createNode("xform", "place_in_catalog")
        place.setInput(0, out)
        place.parm("tx").set(x)
        place.setComment("カタログとして並べるために\n横へずらしているだけです")
        place.setGenericFlag(hou.nodeFlag.DisplayComment, True)
        place.setDisplayFlag(True)
        place.setRenderFlag(True)
        geo.layoutChildren()
        sticky = geo.createStickyNote()
        sticky.setText(note)
        sticky.setSize(hou.Vector2(7.5, 4.8))
        sticky.setPosition(hou.Vector2(-9.0, 1.0))
        sticky.setColor(hou.Color((1.0, 0.97, 0.8)))
        geo.setPosition(hou.Vector2(i * 3.5, 0))

    note = obj.createStickyNote()
    note.setText(
        "【Brick Wall カタログ】\n"
        "同じ HDA（緑のノード）のパラメータを変えただけで、4 種類の壁を作っています。\n"
        "左から: 基本のレンガ、タイル、古い壁、石積み（Packed）。\n\n"
        "各オブジェクトの中に入って、brick_wall1 のパラメータを動かしてみてください。\n"
        "黄色いメモに「試してみよう」があります。\n\n"
        "Unity へは /out の fbx_... ノードで FBX を書き出します（export/ に出ます）。")
    note.setSize(hou.Vector2(9.5, 3.6))
    note.setPosition(hou.Vector2(-0.5, 1.4))
    note.setColor(hou.Color((1.0, 0.97, 0.8)))

    # FBX 書き出し用 ROP
    for name in ("wall_default", "wall_old"):
        rop = hou.node("/out").createNode("filmboxfbx", "fbx_" + name)
        rop.parm("startnode").set("/obj/" + name)
        rop.parm("sopoutput").set("$HIP/export/" + name + ".fbx")
        rop.parm("exportkind").set(0)          # バイナリ FBX
        rop.parm("convertunits").set(1)        # Houdini の 1 m を FBX の 100 cm として書く（Unity で正しい大きさになる）
    hou.node("/out").layoutChildren()
    note = hou.node("/out").createStickyNote()
    note.setText("【FBX 書き出し】\nRender ボタンで $HIP/export/ に FBX が出ます。\n頂点カラー Cd と UV、法線が入ります。")
    note.setSize(hou.Vector2(6.5, 2.2))
    note.setPosition(hou.Vector2(-7.5, 0.5))
    note.setColor(hou.Color((1.0, 0.97, 0.8)))


# ----------------------------------------------------------------------------
# 確認・画像・書き出し
# ----------------------------------------------------------------------------
def verify():
    ok = True
    for name, _, _, _ in WALLS:
        n = hou.node("/obj/%s/brick_wall1" % name)
        n.cook(force=True)
        g = n.geometry()
        bb = g.boundingBox()
        names = set(p.attribValue("name") for p in g.prims()) if g.findPrimAttrib("name") else set()
        bricks = [nm for nm in names if nm.startswith("brick_")]
        has_uv = g.findVertexAttrib("uv") is not None
        has_cd = g.findPointAttrib("Cd") is not None
        packed = sum(1 for p in g.prims() if p.type() == hou.primType.PackedGeometry)
        print("%-13s prims=%6d pts=%6d packed=%4d bricks=%4d uv=%s Cd=%s bbox=(%.2f..%.2f, %.2f..%.2f, %.2f..%.2f) err=%s warn=%s" % (
            name, len(g.prims()), len(g.points()), packed, len(bricks), has_uv, has_cd,
            bb.minvec()[0], bb.maxvec()[0], bb.minvec()[1], bb.maxvec()[1], bb.minvec()[2], bb.maxvec()[2],
            n.errors(), n.warnings()))
        if n.errors() or n.warnings() or not has_cd:
            ok = False
    # 既定値での数の確認: 4 x 2.5 の壁、レンガ 0.4 x 0.1、目地 0.012 → 23 段 x 約 10 個
    n = hou.node("/obj/wall_default/brick_wall1")
    g = n.geometry()
    rows = set(p.attribValue("row") for p in g.points())
    print("wall_default rows:", len(rows), "unique brick names:", len(set(p.attribValue("name") for p in g.prims() if p.attribValue("name") != "mortar")))
    print("VERIFY:", "OK" if ok else "FAILED")
    return ok


def export_fbx():
    for name in ("wall_default", "wall_old"):
        rop = hou.node("/out/fbx_" + name)
        rop.render()
        p = hou.text.expandString(rop.parm("sopoutput").eval())
        print("fbx:", p, os.path.getsize(p) if os.path.exists(p) else "MISSING", rop.errors())


def render_docs():
    obj = hou.node("/obj")
    for lname, rot, inten in (("docs_key", (-45, 35, 0), 1.15), ("docs_fill", (-30, -50, 0), 0.7), ("docs_under", (30, 10, 0), 0.45)):
        lt = obj.createNode("hlight::2.0", lname)
        lt.parm("light_type").set("distant")
        lt.parmTuple("r").set(rot)
        lt.parm("light_intensity").set(inten)
        try:
            lt.parm("shadow_type").set("off")      # 影は縞模様のノイズが出やすいので切る
        except hou.OperationFailed:
            lt.parm("shadow_type").set(0)
    ground = obj.createNode("geo", "docs_ground")
    grid = ground.createNode("grid")
    grid.parmTuple("size").set((80, 80))
    grid.parmTuple("t").set((0, -0.002, 0))
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
    ogl.parm("shadows").set(0)          # 影は縞模様のノイズが出やすいので切る
    ogl.parm("ambocclusion").set(0)     # 画面空間の環境遮蔽も縞が出るので切る
    ogl.parm("trange").set(0)
    if not os.path.isdir(IMG_DIR):
        os.makedirs(IMG_DIR)

    def shoot(tag, res, target, dist, pitch, yaw, vobjects="*"):
        cam.parmTuple("res").set(res)
        ogl.parmTuple("res").set(res)
        cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
        cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        cam.parmTuple("t").set((target[0] + dist * cp * sy, target[1] + dist * sp, target[2] + dist * cp * cy))
        cam.parmTuple("r").set((-pitch, yaw, 0))
        ogl.parm("vobjects").set(vobjects)
        # 2 倍の大きさで描いてから縮小する（細かい模様のちらつきを減らす）
        cam.parmTuple("res").set((res[0] * 2, res[1] * 2))
        ogl.parmTuple("res").set((res[0] * 2, res[1] * 2))
        tmp = IMG_DIR + "/_" + tag + "_2x.png"
        ogl.parm("picture").set(tmp)
        ogl.render()
        from PIL import Image
        Image.open(tmp).convert("RGB").resize(res, Image.LANCZOS).save(IMG_DIR + "/" + tag + ".png")
        os.remove(tmp)
        print("image:", tag)

    shoot("catalog", (1600, 640), (0, 1.1, 0), 21.0, 9, 5)
    for name, x, _, _ in WALLS:
        shoot(name, (900, 620), (x, 1.2, 0), 5.2, 10, 22, "/obj/%s /obj/docs_ground" % name)
    shoot("wall_old_closeup", (900, 620), (2.4 + 0.8, 1.0, 0), 2.2, 8, 30, "/obj/wall_old /obj/docs_ground")


def main():
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.hipFile.save(HIP_PATH)
    build_hda()
    build_sample()
    hou.hipFile.save(HIP_PATH)
    print("saved:", HIP_PATH)
    print("hda:  ", HDA_PATH)
    verify()
    if "export" in sys.argv[1:]:
        export_fbx()
    if "render" in sys.argv[1:]:
        render_docs()


if __name__ == "__main__":
    main()
