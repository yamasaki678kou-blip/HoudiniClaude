# -*- coding: utf-8 -*-
"""
Pipe Run の HDA とサンプルシーンを、ゼロから作り直すスクリプトです。

使い方（コマンドプロンプトで、このツールのフォルダから）:
    "C:/Program Files/Side Effects Software/Houdini 21.0.700/bin/hython.exe" scripts/build_sample.py
    ... 後ろに render を付けると images/ の画像も作ります。export を付けると export/ に FBX を書き出します。

作られるもの:
    otls/pipe_run.hdalc        ... HDA 本体
    pipe_run_sample.hiplc      ... 配管 5 種を並べたサンプルシーン
"""
import math
import os
import shutil
import sys

import hou

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
HIP_PATH = TOOL_DIR + "/pipe_run_sample.hiplc"
HDA_PATH = TOOL_DIR + "/otls/pipe_run.hdalc"
HDA_TYPE = "hclaude::pipe_run::1.0"
IMG_DIR = TOOL_DIR + "/images"


# ----------------------------------------------------------------------------
# HDA の中身（VEX）
# ----------------------------------------------------------------------------
VEX_PICK_FLANGES = r'''// ============================================================
// フランジ（継ぎ目の輪）を置く点だけを残します
// ============================================================
int at_end  = neighbourcount(0, @ptnum) == 1;           // つながりが 1 本だけ = 曲線の端
int at_bend = inpointgroup(0, "bend_ends", @ptnum);     // PolyBevel が作った「曲がりの始まり・終わり」の点

int keep = 0;
if (at_end  && chi("../flange_ends"))  keep = 1;
if (at_bend && chi("../flange_bends")) keep = 1;
if (!keep) removepoint(0, @ptnum);
'''

VEX_DROP_ENDS = r'''// 曲線の端の点を消します（端にはフランジがあるので、バンドは置かない）
if (neighbourcount(0, @ptnum) == 1) removepoint(0, @ptnum);
'''

VEX_BRACKET_POINTS = r'''// ============================================================
// 取り付け金具を置く点を、まっすぐな区間ごとに等間隔で作ります
// 入力の折れ線（丸める前）の辺を 1 本ずつ見ていきます。
// 丸めた曲線でも、まっすぐな部分は元の辺の上にあるので、位置はずれません。
// ============================================================
float  interval = max(chf("../bracket_interval"), 0.01);
float  margin   = chf("../bend_radius") + chf("../radius") * chf("../flange_radius") + chf("../bracket_size");  // 角とフランジを避ける長さ
vector dir      = normalize(chv("../bracket_dir"));

int pts[] = primpoints(0, @primnum);   // この折れ線の点を順番に
for (int i = 0; i < len(pts) - 1; i++)
{
    vector a = point(0, "P", pts[i]);
    vector b = point(0, "P", pts[i + 1]);
    vector t = normalize(b - a);                 // この辺の向き
    float  L = distance(a, b) - 2.0 * margin;    // 金具を置ける長さ
    if (L <= 0.0) continue;                      // 短すぎる辺
    if (abs(dot(t, dir)) > 0.99) continue;       // 取り付け方向と平行な辺（壁に向かう管）には置けない

    int   n     = int(floor(L / interval)) + 1;               // 置く個数
    float start = margin + (L - (n - 1) * interval) * 0.5;    // 辺の中央にそろえる
    for (int k = 0; k < n; k++)
    {
        int pt = addpoint(0, a + t * (start + k * interval));
        setpointattrib(0, "N",  pt, t);      // Copy to Points が、型の +Z をこの向きに合わせる
        setpointattrib(0, "up", pt, -dir);   // 型の +Y を取り付け方向の逆に合わせる（金具の型は -Y に伸びている）
    }
}
removeprim(0, @primnum, 1);   // 元の曲線は消して、作った点だけ残す
'''

VEX_PART_ATTRS = r'''// 部品の名前と色を付けます（Unity でマテリアルを分けるときの目印）
// 名前は面に、色は点に付けます（点の色 = 頂点カラーとして FBX に入る）
s@name = "PART";
foreach (int pt; primpoints(0, @primnum))
    setpointattrib(0, "Cd", pt, chv("../COLOR"));
'''

VEX_FITTING_UV = r'''// ============================================================
// パイプ以外の部品に、ボックス投影の UV を付けます
// （パイプ本体は Sweep が長さに沿った UV を付けているので、そのまま）
// ============================================================
if (prim(0, "name", @primnum) == "pipe") return;

vector n = prim_normal(0, @primnum, 0.5, 0.5);   // この面の向き
vector p = @P * chf("../uv_scale");               // 1 m にテクスチャを何回くり返すか
if (abs(n.x) >= abs(n.y) && abs(n.x) >= abs(n.z))
    @uv = set(-p.z * sign(n.x), p.y, 0);          // 左右を向く面 → (z, y)
else if (abs(n.y) >= abs(n.z))
    @uv = set(p.x, -p.z * sign(n.y), 0);          // 上下を向く面 → (x, z)
else
    @uv = set(p.x * sign(n.z), p.y, 0);           // 前後を向く面 → (x, y)
'''

HDA_HELP = '''= Pipe Run =

#icon: SOP/sweep

"""折れ線のカーブから、角の丸い配管を作ります。端と曲がり目のフランジ、等間隔のバンド、壁への取り付け金具も付けられます。"""

入力は折れ線（Polygon の曲線）です。角の点を [PolyBevel|Node:sop/polybevel] で丸め、[Sweep|Node:sop/sweep] で管にします。
フランジやバンドは、曲線の上の「端の点」「曲がりの始まりと終わりの点」「等間隔の点」に [Copy to Points|Node:sop/copytopoints] で置いています。

出力は `name`（pipe / flange / band / bracket）と `Cd`、`uv`、`N` を持つポリゴンです。そのまま FBX で Unity に持っていけます。

TIP:
    入力の曲線は、角だけ点がある折れ線がいちばんきれいです。点が多い曲線でも、ほとんど曲がっていない点（3 度未満）は丸めません。

@parameters

== Pipe ==

Radius:
    パイプの半径。
Segments:
    パイプの断面の分割数。
Bend Radius:
    角を丸める半径。隣の角までの距離の半分より大きくはできません。
Bend Divisions:
    角の丸めの分割数。
End Caps:
    パイプの端にフタをします。
UV Scale:
    フランジなどの部品のボックス投影 UV の細かさ（1 m にテクスチャを何回くり返すか）。

== Flanges ==

Flange at Ends / Flange at Bends:
    曲線の端 / 曲がりの始まりと終わりにフランジを置きます。
Flange Radius:
    フランジの半径（パイプの半径に対する倍率）。
Flange Width:
    フランジの厚み。

== Bands ==

Band Interval:
    バンド（細い輪）を置く間隔。0 で置きません。
Band Radius / Band Width:
    バンドの半径（倍率）と幅。

== Brackets ==

Brackets:
    壁や天井への取り付け金具を置きます。
Bracket Interval:
    金具の間隔。曲がっている部分には置きません。
Bracket Direction:
    金具が伸びる向き（壁の向き）。(0, -1, 0) なら下の床へ、(0, 0, -1) なら奥の壁へ。
Bracket Length:
    パイプの中心から壁までの長さ。
Bracket Size:
    金具の太さ。

== Colors ==

Pipe Color / Fitting Color:
    パイプ本体 / 部品の色（頂点カラー Cd）。

@related
- [Node:sop/polybevel]
- [Node:sop/sweep]
- [Node:sop/polyframe]
- [Node:sop/copytopoints]
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

    f = hou.FolderParmTemplate("fd_pipe", "Pipe", folder_type=S)
    f.addParmTemplate(hou.FloatParmTemplate("radius", "Radius", 1, default_value=(0.08,), min=0.005, max=1.0, help="パイプの半径。"))
    f.addParmTemplate(hou.IntParmTemplate("cols", "Segments", 1, default_value=(12,), min=3, max=48, help="パイプの断面の分割数。"))
    f.addParmTemplate(hou.FloatParmTemplate("bend_radius", "Bend Radius", 1, default_value=(0.25,), min=0.0, max=2.0, help="角を丸める半径。"))
    f.addParmTemplate(hou.IntParmTemplate("bend_divisions", "Bend Divisions", 1, default_value=(4,), min=1, max=16, help="角の丸めの分割数。"))
    f.addParmTemplate(hou.ToggleParmTemplate("end_caps", "End Caps", default_value=True, help="パイプの端にフタをします。"))
    f.addParmTemplate(hou.FloatParmTemplate("uv_scale", "UV Scale", 1, default_value=(1.0,), min=0.01, max=10.0,
                                            help="フランジなどの部品のボックス投影 UV の細かさ。"))
    g.append(f)

    f = hou.FolderParmTemplate("fd_flange", "Flanges", folder_type=S)
    f.addParmTemplate(hou.ToggleParmTemplate("flange_ends", "Flange at Ends", default_value=True, help="曲線の端にフランジを置きます。"))
    f.addParmTemplate(hou.ToggleParmTemplate("flange_bends", "Flange at Bends", default_value=True, help="曲がりの始まりと終わりにフランジを置きます。"))
    f.addParmTemplate(hou.FloatParmTemplate("flange_radius", "Flange Radius", 1, default_value=(1.6,), min=1.0, max=3.0, help="フランジの半径（パイプの半径に対する倍率）。"))
    f.addParmTemplate(hou.FloatParmTemplate("flange_width", "Flange Width", 1, default_value=(0.04,), min=0.001, max=0.5, help="フランジの厚み。"))
    g.append(f)

    f = hou.FolderParmTemplate("fd_band", "Bands", folder_type=S)
    f.addParmTemplate(hou.FloatParmTemplate("band_interval", "Band Interval", 1, default_value=(0.0,), min=0.0, max=5.0, help="バンドを置く間隔。0 で置きません。"))
    f.addParmTemplate(hou.FloatParmTemplate("band_radius", "Band Radius", 1, default_value=(1.15,), min=1.0, max=2.0,
                                            disable_when="{ band_interval == 0 }", help="バンドの半径（倍率）。"))
    f.addParmTemplate(hou.FloatParmTemplate("band_width", "Band Width", 1, default_value=(0.03,), min=0.001, max=0.5,
                                            disable_when="{ band_interval == 0 }", help="バンドの幅。"))
    g.append(f)

    f = hou.FolderParmTemplate("fd_bracket", "Brackets", folder_type=S)
    f.addParmTemplate(hou.ToggleParmTemplate("brackets", "Brackets", default_value=False, help="壁や天井への取り付け金具を置きます。"))
    f.addParmTemplate(hou.FloatParmTemplate("bracket_interval", "Bracket Interval", 1, default_value=(1.2,), min=0.1, max=10.0,
                                            disable_when="{ brackets == 0 }", help="金具の間隔。曲がっている部分には置きません。"))
    f.addParmTemplate(hou.FloatParmTemplate("bracket_dir", "Bracket Direction", 3, default_value=(0.0, -1.0, 0.0),
                                            disable_when="{ brackets == 0 }", help="金具が伸びる向き（壁の向き）。"))
    f.addParmTemplate(hou.FloatParmTemplate("bracket_length", "Bracket Length", 1, default_value=(0.25,), min=0.01, max=3.0,
                                            disable_when="{ brackets == 0 }", help="パイプの中心から壁までの長さ。"))
    f.addParmTemplate(hou.FloatParmTemplate("bracket_size", "Bracket Size", 1, default_value=(0.04,), min=0.005, max=0.3,
                                            disable_when="{ brackets == 0 }", help="金具の太さ。"))
    g.append(f)

    f = hou.FolderParmTemplate("fd_color", "Colors", folder_type=S)
    f.addParmTemplate(hou.FloatParmTemplate("color_pipe", "Pipe Color", 3, default_value=(0.55, 0.57, 0.60),
                                            look=hou.parmLook.ColorSquare, naming_scheme=hou.parmNamingScheme.RGBA, help="パイプ本体の色。"))
    f.addParmTemplate(hou.FloatParmTemplate("color_fitting", "Fitting Color", 3, default_value=(0.30, 0.30, 0.32),
                                            look=hou.parmLook.ColorSquare, naming_scheme=hou.parmNamingScheme.RGBA, help="フランジ・バンド・金具の色。"))
    g.append(f)
    return g


def set_normal_type(normal_node, vertex=True, cusp=60.0):
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
    src = geo.createNode("line", "tmp_line")
    sub = geo.createNode("subnet", "pipe_run1")
    sub.setInput(0, src)
    inp = sub.indirectInputs()[0]

    def wrangle(name, cls, code, source=None):
        w = sub.createNode("attribwrangle", name)
        if source is not None:
            w.setInput(0, source)
        w.parm("class").set(cls)
        w.parm("snippet").set(code)
        return w

    def part_attrs(name, source, part_name, color_parm):
        """name と Cd を付ける Wrangle。どの部品かはスペアパラメータに書いておく。"""
        return wrangle(name, "primitive", VEX_PART_ATTRS.replace("PART", part_name).replace("COLOR", color_parm), source)

    def tube(name, radius_expr, height_expr):
        t = sub.createNode("tube", name)
        t.parm("type").set("poly")
        t.parm("orient").set("z")                 # 軸を Z にする（Copy to Points が +Z を曲線の向きに合わせる）
        t.parm("cap").set(1)
        t.parm("rad1").setExpression(radius_expr)
        t.parm("rad2").setExpression(radius_expr)
        t.parm("height").setExpression(height_expr)
        t.parm("cols").setExpression('ch("../cols")')
        return t

    def frame(name, source):
        """曲線の各点に、進む向き（接線）を N として付ける。"""
        pf = sub.createNode("polyframe", name)
        pf.setInput(0, source)
        pf.parm("entity").set("point")        # 点ごとに計算する（既定の Primitives だと頂点属性になり、点から読めない）
        pf.parm("style").set("edge2")
        pf.parm("Non").set(0)
        pf.parm("tangentuon").set(1)
        pf.parm("tangentu").set("N")
        return pf

    # ---- 角を丸める ----
    bevel = sub.createNode("polybevel::3.0", "round_bends")
    bevel.setInput(0, inp)
    bevel.parm("grouptype").set("points")
    bevel.parm("offset").setExpression('ch("../bend_radius")')
    bevel.parm("filletshape").set("round")
    bevel.parm("divisions").setExpression('ch("../bend_divisions")')
    bevel.parm("ignoreflatpoints").set(1)
    bevel.parm("flatangle").set(3.0)
    bevel.parm("useoffsetpoints").set(1)
    bevel.parm("offsetpoints").set("bend_ends")

    # ---- パイプ本体 ----
    sweep = sub.createNode("sweep::2.0", "pipe_sweep")
    sweep.setInput(0, bevel)
    sweep.parm("surfaceshape").set("tube")
    sweep.parm("radius").setExpression('ch("../radius")')
    sweep.parm("cols").setExpression('ch("../cols")')
    sweep.parm("endcaptype").setExpression('ch("../end_caps")')   # 0 = None, 1 = Single Polygon
    sweep.parm("computeuvs").set(1)
    pipe_attrs = part_attrs("pipe_attrs", sweep, "pipe", "color_pipe")

    # ---- フランジ ----
    fr1 = frame("tangent_for_flanges", bevel)
    pick_f = wrangle("pick_flange_points", "point", VEX_PICK_FLANGES, fr1)
    flange_shape = tube("flange_shape", 'ch("../radius") * ch("../flange_radius")', 'ch("../flange_width")')
    copy_f = sub.createNode("copytopoints::2.0", "copy_flanges")
    copy_f.setInput(0, flange_shape)
    copy_f.setInput(1, pick_f)
    flange_attrs = part_attrs("flange_attrs", copy_f, "flange", "color_fitting")

    # ---- バンド ----
    res_b = sub.createNode("resample", "resample_for_bands")
    res_b.setInput(0, bevel)
    res_b.parm("length").setExpression('max(ch("../band_interval"), 0.01)')
    fr2 = frame("tangent_for_bands", res_b)
    drop = wrangle("drop_end_points", "point", VEX_DROP_ENDS, fr2)
    band_shape = tube("band_shape", 'ch("../radius") * ch("../band_radius")', 'ch("../band_width")')
    copy_b = sub.createNode("copytopoints::2.0", "copy_bands")
    copy_b.setInput(0, band_shape)
    copy_b.setInput(1, drop)
    band_attrs = part_attrs("band_attrs", copy_b, "band", "color_fitting")
    empty_b = sub.createNode("null", "no_bands")
    sw_b = sub.createNode("switch", "switch_bands")
    sw_b.setInput(0, empty_b)
    sw_b.setInput(1, band_attrs)
    sw_b.parm("input").setExpression('ch("../band_interval") > 0')

    # ---- 取り付け金具 ----
    pick_k = wrangle("bracket_points", "primitive", VEX_BRACKET_POINTS, inp)   # 丸める前の折れ線から作る
    ring = tube("bracket_ring", 'ch("../radius") * 1.2', 'ch("../bracket_size") * 0.8')
    stem = sub.createNode("box", "bracket_stem")
    stem.parm("sizex").setExpression('ch("../bracket_size")')
    stem.parm("sizey").setExpression('ch("../bracket_length")')
    stem.parm("sizez").setExpression('ch("../bracket_size")')
    stem.parm("ty").setExpression('-ch("../bracket_length") / 2')     # 型は -Y 方向に伸ばす
    plate = sub.createNode("box", "bracket_plate")
    plate.parm("sizex").setExpression('ch("../bracket_size") * 2.5')
    plate.parm("sizey").setExpression('ch("../bracket_size") * 0.5')
    plate.parm("sizez").setExpression('ch("../bracket_size") * 2.5')
    plate.parm("ty").setExpression('-ch("../bracket_length")')
    bracket_shape = sub.createNode("merge", "bracket_shape")
    for i, n in enumerate((ring, stem, plate)):
        bracket_shape.setInput(i, n)
    copy_k = sub.createNode("copytopoints::2.0", "copy_brackets")
    copy_k.setInput(0, bracket_shape)
    copy_k.setInput(1, pick_k)
    bracket_attrs = part_attrs("bracket_attrs", copy_k, "bracket", "color_fitting")
    empty_k = sub.createNode("null", "no_brackets")
    sw_k = sub.createNode("switch", "switch_brackets")
    sw_k.setInput(0, empty_k)
    sw_k.setInput(1, bracket_attrs)
    sw_k.parm("input").setExpression('ch("../brackets")')

    # ---- まとめ ----
    merge = sub.createNode("merge", "merge_parts")
    for i, n in enumerate((pipe_attrs, flange_attrs, sw_b, sw_k)):
        merge.setInput(i, n)
    uv = wrangle("fitting_box_uv", "vertex", VEX_FITTING_UV, merge)
    nrm = sub.createNode("normal", "normals")
    nrm.setInput(0, uv)
    set_normal_type(nrm, True, 60.0)
    out = sub.createNode("output", "OUT")
    out.setInput(0, nrm)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)

    comments = {
        "round_bends": "角の点を丸める。丸めの始まりと終わりの点を\nbend_ends グループに入れる",
        "pipe_sweep": "丸めた曲線に沿って管を作る（UV 付き）",
        "tangent_for_flanges": "各点に進む向き（接線）を N として付ける",
        "pick_flange_points": "端の点と bend_ends の点だけ残す",
        "copy_flanges": "点にフランジの形を置く\n（+Z が N の向きになる）",
        "resample_for_bands": "等間隔に点を打ち直す",
        "bracket_points": "丸める前の折れ線の辺ごとに、等間隔で\n金具の点を作る（角とフランジは避ける）",
        "bracket_shape": "輪 + 柱 + 板。柱は -Y に伸びる",
        "fitting_box_uv": "パイプ以外にボックス投影 UV",
        "normals": "頂点法線",
    }
    for nm, c in comments.items():
        n = sub.node(nm)
        n.setComment(c)
        n.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    for nm in ("pick_flange_points", "drop_end_points", "bracket_points", "fitting_box_uv",
               "pipe_attrs", "flange_attrs", "band_attrs", "bracket_attrs"):
        sub.node(nm).setColor(hou.Color((0.95, 0.7, 0.3)))
    sub.layoutChildren()

    node = sub.createDigitalAsset(
        name=HDA_TYPE, hda_file_name=HDA_PATH, description="Pipe Run",
        min_num_inputs=1, max_num_inputs=1, ignore_external_references=True)
    d = node.type().definition()
    d.setParmTemplateGroup(hda_parm_templates())
    node.removeSpareParms()
    sec = d.sections()["DialogScript"]
    sec.setContents(sec.contents().replace('inputlabel\t1\t"Sub-Network Input #1"', 'inputlabel\t1\t"Curves (polylines)"'))
    d.setIcon("SOP_sweep")
    d.setVersion("1.0")
    d.setComment("Pipes with rounded bends, flanges, bands and brackets from polyline curves.")
    d.addSection("Help", HDA_HELP)
    d.addSection("Tools.shelf", HDA_TOOLS)
    d.updateFromNode(node)
    node.matchCurrentDefinition()
    geo.destroy()
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir)
    hou.hda.uninstallFile(HDA_PATH)
    hou.hda.installFile("$HIP/otls/pipe_run.hdalc")
    return hou.nodeType(hou.sopNodeTypeCategory(), HDA_TYPE).definition()


# ----------------------------------------------------------------------------
# サンプル
# ----------------------------------------------------------------------------
def polyline(geo, name, pts):
    """点の列から 1 本の折れ線を作る（Add SOP）。"""
    add = geo.createNode("add", name)
    add.parm("points").set(len(pts))
    for i, p in enumerate(pts):
        add.parmTuple("pt%d" % i).set(p)
    add.parm("prims").set(1)
    add.parm("prim0").set("0-%d" % (len(pts) - 1))
    return add


RUNS = [
    ("run_L", -9.0, {},
     [[(0, 0.3, 0), (0, 0.3, 3), (3, 0.3, 3)]],
     "【L 字の配管】\n折れ線 3 点（角 1 つ）を入力しただけです。\n角が Bend Radius で丸まり、端と曲がり目にフランジが付きます。\n\n"
     "試してみよう:\n・Bend Radius を 0 にすると、角がとがります\n・Bend Divisions を 1 にすると、角が面取りになります\n"
     "・Flange at Bends をオフにすると、曲がり目のフランジが消えます\n・Add ノード（curve）の点を動かすと、配管が追いかけます"),
    ("run_U", -4.5, {"radius": 0.12, "band_interval": 0.5, "flange_radius": 1.4},
     [[(0, 0.8, 0), (0, 2.2, 0), (2, 2.2, 0), (2, 0.8, 0)]],
     "【太い U 字 + バンド】\nRadius を太くし、Band Interval 0.5 で等間隔のバンドを付けています。\n\n"
     "試してみよう:\n・Band Interval を 0.2 にすると、じゃばらホースのようになります\n・Band Radius を 1.5 にすると、バンドが目立ちます"),
    ("run_zigzag", 0.0, {"brackets": 1, "bracket_dir": (0, 0, -1), "bracket_length": 0.2, "bracket_interval": 0.7},
     [[(0, 0.2, 0.25), (0, 1.2, 0.25), (1.6, 1.2, 0.25), (1.6, 2.4, 0.25), (3.2, 2.4, 0.25)]],
     "【壁づたいのジグザグ + 取り付け金具】\n後ろの壁（Z = 0 の板）に向かって、Bracket Direction (0, 0, -1) の金具を付けています。\n"
     "曲がっている部分には金具が付きません。\n\n"
     "試してみよう:\n・Bracket Interval を変えると、金具の数が変わります\n・Bracket Direction を (0, -1, 0) にすると、床へ向かう金具になります"),
    ("run_multi", 4.5, {"radius": 0.05, "flange_radius": 1.8, "band_interval": 1.0},
     [[(0 + k * 0.22, 0.4, 0 - k * 0.22), (2 + k * 0.22, 0.4, 0 - k * 0.22), (2 + k * 0.22, 0.4, 2 - k * 0.22), (4 + k * 0.22, 0.4, 2 - k * 0.22)] for k in range(3)],
     "【3 本まとめて】\n1 つの HDA に 3 本の折れ線をまとめて入力しています。\n本数が増えても、設定は 1 か所です。\n\n"
     "試してみよう:\n・Merge の本数を増やしてみる\n・Radius を本ごとに変えたいときは、HDA を本ごとに分けます"),
    ("run_freehand", 9.0, {"radius": 0.06, "flange_bends": 0, "bend_radius": 0.15},
     None,
     "【なめらかな曲線】\n直線を細かく分けて、VEX のノイズで少し波打たせた曲線を入力しています。\n"
     "点がたくさんあっても、ほとんど曲がっていない点（3 度未満）は丸めません。\n\n"
     "試してみよう:\n・wave ノードの amp を大きくすると、うねりが強くなります\n・Flange at Bends をオンにすると、曲がりごとにフランジが付きます"),
]


def build_sample():
    obj = hou.node("/obj")
    for i, (name, x, parms, curves, note) in enumerate(RUNS):
        geo = obj.createNode("geo", name)
        if curves is None:
            line = geo.createNode("line", "line")
            line.parm("dist").set(4.0)
            line.parmTuple("dir").set((1, 0, 0))
            line.parmTuple("origin").set((0, 0.6, 0))
            res = geo.createNode("resample", "resample")
            res.setInput(0, line)
            res.parm("length").set(0.25)
            wave = geo.createNode("attribwrangle", "wave")
            wave.setInput(0, res)
            wave.parm("snippet").set(
                "// 直線を、ノイズで少し波打たせます\n"
                "float amp = chf(\"amp\");\n"
                "@P.y += amp * noise(@P.x * 1.3 + 7.0);\n"
                "@P.z += amp * noise(@P.x * 0.9 + 3.0);\n")
            hou.hscript("opparm %s amp ( 0.6 )" % wave.path()) if False else None
            pt = hou.FloatParmTemplate("amp", "amp", 1, default_value=(0.6,), min=0, max=2)
            wave.addSpareParmTuple(pt)
            src = wave
        else:
            adds = [polyline(geo, "curve%d" % (k + 1) if len(curves) > 1 else "curve", pts) for k, pts in enumerate(curves)]
            if len(adds) == 1:
                src = adds[0]
            else:
                src = geo.createNode("merge", "merge_curves")
                for k, a in enumerate(adds):
                    src.setInput(k, a)
        pipe = geo.createNode(HDA_TYPE, "pipe_run1")
        pipe.setInput(0, src)
        for k, v in parms.items():
            if isinstance(v, tuple):
                pipe.parmTuple(k).set(v)
            else:
                pipe.parm(k).set(v)
        pipe.setColor(hou.Color((0.3, 0.75, 0.45)))
        out = geo.createNode("null", "OUT")
        out.setInput(0, pipe)
        last = out
        if name == "run_zigzag":
            wall = geo.createNode("grid", "wall_for_context")
            wall.parm("orient").set("xy")
            wall.parmTuple("size").set((4.0, 2.9))
            wall.parmTuple("t").set((1.6, 1.45, 0))
            wall.parmTuple("rows").set((2,)) if False else None
            wcol = geo.createNode("color", "wall_color")
            wcol.setInput(0, wall)
            wcol.parmTuple("color").set((0.85, 0.84, 0.80))
            m = geo.createNode("merge", "merge_with_wall")
            m.setInput(0, out)
            m.setInput(1, wcol)
            m.setComment("壁の板は見た目のためだけ。配管には関係ありません")
            m.setGenericFlag(hou.nodeFlag.DisplayComment, True)
            last = m
        place = geo.createNode("xform", "place_in_catalog")
        place.setInput(0, last)
        place.parm("tx").set(x)
        place.setComment("カタログとして並べるために\n横へずらしているだけです")
        place.setGenericFlag(hou.nodeFlag.DisplayComment, True)
        place.setDisplayFlag(True)
        place.setRenderFlag(True)
        geo.layoutChildren()
        sticky = geo.createStickyNote()
        sticky.setText(note)
        sticky.setSize(hou.Vector2(7.5, 4.6))
        sticky.setPosition(hou.Vector2(-9.0, 1.0))
        sticky.setColor(hou.Color((1.0, 0.97, 0.8)))
        geo.setPosition(hou.Vector2(i * 3.5, 0))

    note = obj.createStickyNote()
    note.setText(
        "【Pipe Run カタログ】\n"
        "折れ線（Add ノード）を HDA（緑のノード）につなぐだけで配管になります。\n"
        "左から: L 字、太い U 字 + バンド、壁づたい + 金具、3 本まとめて、なめらかな曲線。\n\n"
        "各オブジェクトの中で、曲線の点を動かしたり pipe_run1 のパラメータを変えてみてください。\n"
        "黄色いメモに「試してみよう」があります。\n\n"
        "Unity へは /out の fbx_... ノードで FBX を書き出します（export/ に出ます）。")
    note.setSize(hou.Vector2(9.5, 3.6))
    note.setPosition(hou.Vector2(-0.5, 1.4))
    note.setColor(hou.Color((1.0, 0.97, 0.8)))

    for name in ("run_L", "run_zigzag"):
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


def verify():
    ok = True
    for name, _, _, _, _ in RUNS:
        n = hou.node("/obj/%s/pipe_run1" % name)
        n.cook(force=True)
        g = n.geometry()
        counts = {}
        for p in g.prims():
            counts[p.attribValue("name")] = counts.get(p.attribValue("name"), 0) + 1
        uv = g.findVertexAttrib("uv")
        pipe_uv = [v.attribValue("uv") for p in g.prims() if p.attribValue("name") == "pipe" for v in p.vertices()]
        us = [u[0] for u in pipe_uv]
        vs = [u[1] for u in pipe_uv]
        print("%-13s prims=%5d  parts=%s  uv=%s  pipe u:%.2f..%.2f v:%.2f..%.2f  err=%s warn=%s" % (
            name, len(g.prims()), counts, uv is not None, min(us), max(us), min(vs), max(vs), n.errors(), n.warnings()))
        if n.errors() or n.warnings() or uv is None:
            ok = False
    # L 字: フランジは端 2 + 曲がり目 2 = 4 個。1 個は cols の側面 + ふた 2 枚
    n = hou.node("/obj/run_L/pipe_run1")
    g = n.geometry()
    cols = n.parm("cols").eval()
    flange_prims = sum(1 for p in g.prims() if p.attribValue("name") == "flange")
    print("run_L flanges:", flange_prims / float(cols + 2), "(expected 4)")
    if abs(flange_prims / float(cols + 2) - 4) > 1e-6:
        ok = False
    n = hou.node("/obj/run_zigzag/pipe_run1")
    g = n.geometry()
    brackets = sum(1 for p in g.prims() if p.attribValue("name") == "bracket")
    print("run_zigzag bracket prims:", brackets)
    if brackets == 0:
        ok = False
    # フランジの向き: 曲線の端の点で、フランジの面の法線が曲線の向きと平行か
    inner = hou.node("/obj/run_L/pipe_run1/pick_flange_points").geometry()
    print("flange points N:", [tuple(round(c, 2) for c in pt.attribValue("N")) for pt in inner.points()])
    print("VERIFY:", "OK" if ok else "FAILED")
    return ok


def export_fbx():
    for name in ("run_L", "run_zigzag"):
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

    shoot("catalog", (1800, 600), (2.0, 0.8, 1.2), 30.0, 19, 3)
    views = {"run_L": ((1.5, 0.6, 1.5), 6.0, 28, 35), "run_U": ((1.0, 1.5, 0), 5.0, 15, 25),
             "run_zigzag": ((1.6, 1.3, 0.3), 5.6, 12, 20), "run_multi": ((2.2, 0.5, 1.0), 6.5, 30, 35),
             "run_freehand": ((2.0, 0.6, 0), 5.5, 20, 15)}
    for name, x, _, _, _ in RUNS:
        t, dist, pitch, yaw = views[name]
        shoot(name, (900, 620), (t[0] + x, t[1], t[2]), dist, pitch, yaw, "/obj/%s /obj/docs_ground" % name)
    shoot("run_L_closeup", (900, 620), (-9.0 + 0.0, 0.3, 3.0), 1.6, 20, 40, "/obj/run_L /obj/docs_ground")


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
