# -*- coding: utf-8 -*-
"""
Weathering Mask の HDA とサンプルシーンを、ゼロから作り直すスクリプトです。

使い方（コマンドプロンプトで、このツールのフォルダから）:
    "C:/Program Files/Side Effects Software/Houdini 21.0.700/bin/hython.exe" scripts/build_sample.py
    ... 後ろに render を付けると images/ の画像も作ります。export を付けると export/ に FBX を書き出します。

作られるもの:
    otls/weathering_mask.hdalc        ... HDA 本体
    weathering_mask_sample.hiplc      ... 小物 4 種にマスクを付けたサンプルシーン
"""
import math
import os
import re
import shutil
import sys

import hou

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
HIP_PATH = TOOL_DIR + "/weathering_mask_sample.hiplc"
HDA_PATH = TOOL_DIR + "/otls/weathering_mask.hdalc"
HDA_TYPE = "hclaude::weathering_mask::1.0"
IMG_DIR = TOOL_DIR + "/images"

PREVIEW_MODES = ("material", "packed", "edge", "cavity", "top", "bottom")


# ----------------------------------------------------------------------------
# HDA の中身（VEX）
# ----------------------------------------------------------------------------
VEX_MASKS = r'''// ============================================================
// 4 つのマスクを計算して、点の属性に書きます
//   mask_edge   : 出っぱった角（擦れ、塗装はがれ）
//   mask_cavity : へこみ・すき間（汚れ、ほこりだまり）
//   mask_top    : 上を向いた面（ほこり、雪）
//   mask_bottom : 地面に近い部分（水あか、苔）
// どれも 0〜1 で、1 がいちばん強い場所です。
// ============================================================
// chf("../xxx") は「1 つ上の階層 = この HDA 本体」のパラメータ xxx を読む書き方です。

// ---- 共通: ばらつき用のノイズ ----
// noise() は 0〜1 の値をなめらかに返します。fit() で 0.3〜0.7 を 0〜1 に広げて、コントラストを強めています。
// マスク m にノイズをどれだけ混ぜるか: amount = 0 でそのまま、1 でノイズで大きく欠けます。
float breakup(float m; vector p; float amount)
{
    float n = fit(noise(p), 0.3, 0.7, 0.0, 1.0);
    return clamp(m * lerp(1.0, n, amount), 0.0, 1.0);
}
vector np = @P * chf("../noise_freq") + chf("../seed") * 17.3;   // ノイズを引く位置（Seed でずらす）

// ---- 1. 角 (edge): 曲率がプラス = 出っぱり ----
// Measure SOP の平均曲率は、モデル全体の大きさで割った相対的な値です（球なら大きさによらず約 0.22）。
// Edge Width で割って 0〜1 に切りそろえます。Edge Width が小さいほど、ゆるい丸みでも「角」になります。
float curv = f@curvature;
float edge = clamp(curv / max(chf("../edge_width"), 0.0001), 0.0, 1.0);
edge = breakup(edge, np + 101.0, chf("../edge_noise")) * chf("../edge_strength") * chi("../edge_enable");

// ---- 2. へこみ (cavity): 曲率がマイナス = へこみ。それと AO（まわりに遮られている度合い）を合わせる ----
float cavity = clamp(-curv / max(chf("../cavity_width"), 0.0001), 0.0, 1.0);
if (haspointattrib(0, "ao"))                                    // AO を計算してあれば
    cavity = max(cavity, (1.0 - f@ao) * chf("../cavity_ao"));    // 遮られている（ao が小さい）ほど汚れる
cavity = breakup(cavity, np + 202.0, chf("../cavity_noise")) * chf("../cavity_strength") * chi("../cavity_enable");

// ---- 3. 上向き (top): 法線が上を向いているほど 1 ----
float up  = dot(normalize(v@N), {0, 1, 0});                              // 真上で 1、水平で 0、下向きでマイナス
float top = fit(up, cos(radians(chf("../top_angle"))), 1.0, 0.0, 1.0);   // Top Angle より立っている面は 0
top = breakup(top, np + 303.0, chf("../top_noise")) * chf("../top_strength") * chi("../top_enable");

// ---- 4. 地面に近い (bottom): 入力全体のいちばん低い点から Bottom Height の高さまで ----
float ymin   = getbbox_min(0).y;
float bottom = 1.0 - clamp((@P.y - ymin) / max(chf("../bottom_height"), 0.0001), 0.0, 1.0);
bottom = breakup(bottom, np + 404.0, chf("../bottom_noise")) * chf("../bottom_strength") * chi("../bottom_enable");

// ---- マスクを属性として残す（Unity や、ほかのノードで使う）----
f@mask_edge   = edge;
f@mask_cavity = cavity;
f@mask_top    = top;
f@mask_bottom = bottom;

// ---- 見せ方（Preview パラメータ）----
int mode = chi("../preview");
if (mode == 0)
{
    // Material Preview: マスクで色を混ぜて、使い道が分かるようにする
    vector col = chv("../preview_base");                 // 下地の色
    col = lerp(col, chv("../preview_dirt"),   cavity);   // へこみに汚れ
    col = lerp(col, chv("../preview_edge"),   edge);     // 角は擦れて金属が見える
    col = lerp(col, chv("../preview_top"),    top);      // 上面にほこり
    col = lerp(col, chv("../preview_bottom"), bottom);   // 地際に苔
    v@Cd = col;
}
else if (mode == 1)
{
    // Packed: R = 角, G = へこみ, B = 上向き（Unity へ持っていく形）
    v@Cd = set(edge, cavity, top);
    // 地際は Alpha に入れます。ただし Alpha があるとビューポートで透けて見えるので、
    // FBX に書き出すときだけ Write Alpha をオンにします。
    if (chi("../write_alpha")) f@Alpha = bottom;
}
else if (mode == 2) v@Cd = edge;     // 白黒でマスクを 1 つずつ確認する
else if (mode == 3) v@Cd = cavity;
else if (mode == 4) v@Cd = top;
else                v@Cd = bottom;
'''

HDA_HELP = '''= Weathering Mask =

#icon: SOP/attribpaint

"""メッシュの形から「汚れやすい場所」を計算して、4 つのマスクを頂点カラーに書きます。角の擦れ、へこみの汚れ、上面のほこり、地際の苔。"""

テクスチャを描かずに、形だけからウェザリング（汚し）のマスクを作ります。
[Measure|Node:sop/measure] で曲率（出っぱり・へこみ）、[Mask by Feature|Node:sop/maskbyfeature] で AO（まわりに遮られている度合い）を計算し、VEX でノイズを混ぜて 4 つのマスクにまとめます。

出力はポイント属性 `mask_edge`、`mask_cavity`、`mask_top`、`mask_bottom`（どれも 0〜1）です。
Preview を Packed にすると `Cd` の RGB と `Alpha` に 4 つを詰めるので、FBX の頂点カラーとして Unity に持っていけます。

TIP:
    曲率は面の細かさに左右されます。角が 1 枚の面で折れているローポリでは「角」が見つかりません。
    [PolyBevel|Node:sop/polybevel] で角を丸め、[Subdivide|Node:sop/subdivide] で少し細かくしてから入れてください。

@parameters

== Edge Wear ==

Enable / Strength:
    角のマスクのオン・オフと強さ。
Edge Width:
    曲率をこの値で割って角のマスクにします。小さいほど、ゆるい丸みでも「角」になります。
Noise:
    ノイズでマスクを欠けさせる量。

== Cavity Dirt ==

Enable / Strength:
    へこみのマスクのオン・オフと強さ。
Cavity Width:
    曲率をこの値で割ってへこみのマスクにします。小さいほど、ゆるいへこみでも拾います。
AO Weight:
    AO（遮られている度合い）をどれだけ足すか。0 にすると AO の計算を省いて速くなります。
AO Samples:
    AO の計算の細かさ。
Noise:
    ノイズでマスクを欠けさせる量。

== Top Dust ==

Enable / Strength:
    上向きのマスクのオン・オフと強さ。
Top Angle:
    真上からこの角度（度）まで傾いた面に、ほこりが積もります。
Noise:
    ノイズでマスクを欠けさせる量。

== Bottom Grime ==

Enable / Strength:
    地際のマスクのオン・オフと強さ。
Bottom Height:
    いちばん低い点からこの高さ（メートル）まで、上へ向かって薄くなります。
Noise:
    ノイズでマスクを欠けさせる量。

== Noise ==

Seed / Frequency:
    ノイズのタネと細かさ（1 m に何回）。

== Output ==

Preview:
    Material Preview: マスクで色を混ぜた見本。Packed: R = 角, G = へこみ, B = 上向き。
    Edge / Cavity / Top / Bottom: マスクを 1 つずつ白黒で見る。
Write Alpha:
    Packed のとき、地際のマスクを `Alpha` にも書きます。FBX の頂点カラーの A に入ります。
    Alpha があるとビューポートでは透けて見えるので、書き出すときだけオンにしてください。
Preview Colors:
    Material Preview で使う色（下地、角、汚れ、ほこり、苔）。

@related
- [Node:sop/measure]
- [Node:sop/maskbyfeature]
- [Node:sop/attribwrangle]
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


def color_parm(name, label, default, help_text):
    return hou.FloatParmTemplate(name, label, 3, default_value=default, look=hou.parmLook.ColorSquare,
                                 naming_scheme=hou.parmNamingScheme.RGBA, help=help_text)


def hda_parm_templates():
    g = hou.ParmTemplateGroup()
    S = hou.folderType.Simple

    def mask_folder(fid, label, prefix, extra):
        f = hou.FolderParmTemplate(fid, label, folder_type=S)
        f.addParmTemplate(hou.ToggleParmTemplate(prefix + "_enable", "Enable", default_value=True, help=label + " のマスクを計算します。"))
        f.addParmTemplate(hou.FloatParmTemplate(prefix + "_strength", "Strength", 1, default_value=(1.0,), min=0.0, max=1.0,
                                                disable_when="{ %s_enable == 0 }" % prefix, help="マスクの強さ。"))
        for pt in extra:
            pt.setConditional(hou.parmCondType.DisableWhen, "{ %s_enable == 0 }" % prefix)
            f.addParmTemplate(pt)
        f.addParmTemplate(hou.FloatParmTemplate(prefix + "_noise", "Noise", 1, default_value=(0.5,), min=0.0, max=1.0,
                                                disable_when="{ %s_enable == 0 }" % prefix, help="ノイズでマスクを欠けさせる量。"))
        return f

    g.append(mask_folder("fd_edge", "Edge Wear", "edge", [
        hou.FloatParmTemplate("edge_width", "Edge Width", 1, default_value=(0.5,), min=0.02, max=3.0,
                              help="曲率をこの値で割って角のマスクにします。小さいほど、ゆるい丸みでも「角」になります。"),
    ]))
    g.append(mask_folder("fd_cavity", "Cavity Dirt", "cavity", [
        hou.FloatParmTemplate("cavity_width", "Cavity Width", 1, default_value=(0.5,), min=0.02, max=3.0,
                              help="曲率をこの値で割ってへこみのマスクにします。小さいほど、ゆるいへこみでも拾います。"),
        hou.FloatParmTemplate("cavity_ao", "AO Weight", 1, default_value=(1.0,), min=0.0, max=1.0,
                              help="AO（遮られている度合い）をどれだけ足すか。0 にすると AO の計算を省きます。"),
        hou.IntParmTemplate("ao_samples", "AO Samples", 1, default_value=(30,), min=4, max=200,
                            help="AO の計算の細かさ。多いほどなめらかで遅い。"),
    ]))
    g.append(mask_folder("fd_top", "Top Dust", "top", [
        hou.FloatParmTemplate("top_angle", "Top Angle", 1, default_value=(45.0,), min=1.0, max=90.0,
                              help="真上からこの角度（度）まで傾いた面に、ほこりが積もります。"),
    ]))
    g.append(mask_folder("fd_bottom", "Bottom Grime", "bottom", [
        hou.FloatParmTemplate("bottom_height", "Bottom Height", 1, default_value=(0.3,), min=0.001, max=5.0,
                              help="いちばん低い点からこの高さまで、上へ向かって薄くなります（メートル）。"),
    ]))

    f = hou.FolderParmTemplate("fd_noise", "Noise", folder_type=S)
    f.addParmTemplate(hou.FloatParmTemplate("seed", "Seed", 1, default_value=(0.0,), min=0.0, max=100.0, help="ノイズのタネ。"))
    f.addParmTemplate(hou.FloatParmTemplate("noise_freq", "Frequency", 1, default_value=(8.0,), min=0.1, max=50.0, help="ノイズの細かさ（1 m に何回）。"))
    g.append(f)

    f = hou.FolderParmTemplate("fd_out", "Output", folder_type=S)
    f.addParmTemplate(hou.MenuParmTemplate("preview", "Preview", PREVIEW_MODES,
                                           ("Material Preview", "Packed (RGB + Alpha)", "Edge", "Cavity", "Top", "Bottom"), default_value=0,
                                           help="Material Preview: マスクで色を混ぜた見本。Packed: R = 角, G = へこみ, B = 上向き。ほかは白黒で 1 つずつ。"))
    f.addParmTemplate(hou.ToggleParmTemplate("write_alpha", "Write Alpha (for FBX)", default_value=False, disable_when="{ preview != packed }",
                                             help="Packed のとき、地際のマスクを Alpha にも書きます（FBX の頂点カラーの A）。ビューポートでは透けて見えるので、書き出すときだけオンに。"))
    f.addParmTemplate(color_parm("preview_base", "Base Color", (0.55, 0.36, 0.22), "下地の色。"))
    f.addParmTemplate(color_parm("preview_edge", "Edge Color", (0.82, 0.82, 0.85), "角の擦れで見える色（金属など）。"))
    f.addParmTemplate(color_parm("preview_dirt", "Dirt Color", (0.12, 0.10, 0.08), "へこみの汚れの色。"))
    f.addParmTemplate(color_parm("preview_top", "Dust Color", (0.90, 0.90, 0.86), "上面のほこりの色。"))
    f.addParmTemplate(color_parm("preview_bottom", "Grime Color", (0.22, 0.32, 0.14), "地際の苔・水あかの色。"))
    g.append(f)
    return g


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
    src = geo.createNode("box", "tmp_box")
    sub = geo.createNode("subnet", "weathering_mask1")
    sub.setInput(0, src)
    inp = sub.indirectInputs()[0]

    nrm = sub.createNode("normal", "point_normals")
    nrm.setInput(0, inp)
    try:
        nrm.parm("type").set("typepoint")
    except hou.OperationFailed:
        nrm.parm("type").set(0)

    curv = sub.createNode("measure", "curvature")
    curv.setInput(0, nrm)
    curv.parm("grouptype").set("points")
    curv.parm("measure").set("curvature")
    curv.parm("curvaturetype").set("mean")
    curv.parm("attribname").set("curvature")

    ao = sub.createNode("maskbyfeature", "ambient_occlusion")
    ao.setInput(0, curv)
    ao.parm("usecombinedmask").set(0)
    ao.parm("enabledirection").set(0)
    ao.parm("castshadows").set(0)
    ao.parm("enableao").set(1)
    ao.parm("useaomask").set(1)
    ao.parm("aomaskattrib").set("ao")
    ao.parm("aosamples").setExpression('ch("../ao_samples")')
    sw_ao = sub.createNode("switch", "switch_ao")
    sw_ao.setInput(0, curv)
    sw_ao.setInput(1, ao)
    sw_ao.parm("input").setExpression('ch("../cavity_enable") && ch("../cavity_ao") > 0')

    masks = sub.createNode("attribwrangle", "masks")
    masks.setInput(0, sw_ao)
    masks.parm("class").set("point")
    masks.parm("snippet").set(VEX_MASKS)

    out = sub.createNode("output", "OUT")
    out.setInput(0, masks)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)

    comments = {
        "point_normals": "点の法線 N（上向きの判定に使う）",
        "curvature": "Measure: 平均曲率を curvature に\n（プラス = 出っぱり、マイナス = へこみ）",
        "ambient_occlusion": "Mask by Feature: AO を ao に\n（1 = 開けている、0 = 遮られている）",
        "switch_ao": "AO Weight が 0 のときは AO を計算しない",
        "masks": "VEX: 4 つのマスクを計算して\nmask_* と Cd に書く",
    }
    for nm, c in comments.items():
        n = sub.node(nm)
        n.setComment(c)
        n.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    masks.setColor(hou.Color((0.95, 0.7, 0.3)))
    sub.layoutChildren()

    node = sub.createDigitalAsset(
        name=HDA_TYPE, hda_file_name=HDA_PATH, description="Weathering Mask",
        min_num_inputs=1, max_num_inputs=1, ignore_external_references=True)
    d = node.type().definition()
    d.setParmTemplateGroup(hda_parm_templates())
    node.removeSpareParms()
    sec = d.sections()["DialogScript"]
    sec.setContents(sec.contents().replace('inputlabel\t1\t"Sub-Network Input #1"', 'inputlabel\t1\t"Mesh"'))
    d.setIcon("SOP_attribpaint")
    d.setVersion("1.0")
    d.setComment("Edge / cavity / top / bottom weathering masks from mesh shape, written to point attributes and vertex colors.")
    d.addSection("Help", HDA_HELP)
    d.addSection("Tools.shelf", HDA_TOOLS)
    d.updateFromNode(node)
    node.matchCurrentDefinition()
    geo.destroy()
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir)
    hou.hda.uninstallFile(HDA_PATH)
    hou.hda.installFile("$HIP/otls/weathering_mask.hdalc")
    return hou.nodeType(hou.sopNodeTypeCategory(), HDA_TYPE).definition()


# ----------------------------------------------------------------------------
# サンプルの小物
# ----------------------------------------------------------------------------
def box(geo, name, size, center, divs=None):
    n = geo.createNode("box", name)
    n.parmTuple("size").set(size)
    n.parmTuple("t").set(center)
    if divs:
        n.parm("dodivs").set(1)
        n.parmTuple("divrate").set(divs)
    return n


def tube(geo, name, radius, height, center, cols=32, rows=1):
    n = geo.createNode("tube", name)
    n.parm("type").set("poly")
    n.parm("cap").set(1)
    n.parm("rad1").set(radius)
    n.parm("rad2").set(radius)
    n.parm("height").set(height)
    n.parm("cols").set(cols)
    n.parm("rows").set(rows)
    n.parmTuple("t").set(center)
    return n


def torus(geo, name, radius, thickness, center, rows=12, cols=48):
    n = geo.createNode("torus", name)
    n.parm("type").set("poly")
    n.parm("radx").set(radius)
    n.parm("rady").set(thickness)
    n.parm("rows").set(rows)
    n.parm("cols").set(cols)
    n.parmTuple("t").set(center)
    return n


def soften(geo, name, source, bevel=0.03, bevel_div=2, subdiv=1):
    """角を丸めて少し細かくする（曲率が取れる形にする）。
    Box の Divisions は使わない: 分割した Box は面の向きが内側になり、法線も AO も狂う。"""
    bv = geo.createNode("polybevel::3.0", "bevel_" + name)
    bv.setInput(0, source)
    bv.parm("grouptype").set("edges")
    bv.parm("offset").set(bevel)
    bv.parm("filletshape").set("round")
    bv.parm("divisions").set(bevel_div)
    sd = geo.createNode("subdivide", "subdivide_" + name)
    sd.setInput(0, bv)
    sd.parm("iterations").set(subdiv)
    sd.setComment("曲率が取れるように\n角を丸めて細かくする")
    sd.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    return sd


def make_shape(geo, kind):
    """小物の形（HDA に入れる前）を作って、最後のノードを返す。"""
    if kind == "crate":
        b = box(geo, "crate_box", (1.0, 1.0, 1.0), (0, 0.5, 0))
        return soften(geo, "crate", b, bevel=0.04, bevel_div=2, subdiv=2)
    if kind == "tank":
        body = tube(geo, "tank_body", 0.45, 1.2, (0, 0.6, 0), cols=24, rows=3)
        rim = torus(geo, "tank_rim", 0.47, 0.05, (0, 1.2, 0), rows=8, cols=32)
        base = torus(geo, "tank_base", 0.47, 0.05, (0, 0.05, 0), rows=8, cols=32)
        m = geo.createNode("merge", "merge_tank")
        for i, n in enumerate((body, rim, base)):
            m.setInput(i, n)
        return soften(geo, "tank", m, bevel=0.03, bevel_div=2, subdiv=1)
    if kind == "blocks":
        lower = box(geo, "block_lower", (1.4, 0.5, 1.0), (0, 0.25, 0))
        upper = box(geo, "block_upper", (0.7, 0.6, 1.0), (-0.35, 0.8, 0))
        m = geo.createNode("merge", "merge_blocks")
        m.setInput(0, lower)
        m.setInput(1, upper)
        return soften(geo, "blocks", m, bevel=0.03, bevel_div=2, subdiv=2)
    if kind == "barrel":
        body = tube(geo, "barrel_body", 0.4, 1.1, (0, 0.55, 0), cols=24, rows=4)
        m = geo.createNode("merge", "merge_barrel")
        m.setInput(0, body)
        for i, y in enumerate((0.25, 0.55, 0.85)):
            m.setInput(i + 1, torus(geo, "barrel_band%d" % (i + 1), 0.42, 0.035, (0, y, 0), rows=8, cols=32))
        return soften(geo, "barrel", m, bevel=0.02, bevel_div=2, subdiv=1)
    raise ValueError(kind)


PROPS = [
    # (名前, 形, 置く位置 x, HDA のパラメータ, メモ)
    ("prop_crate", "crate", -4.8, {},
     "【木箱】\n角を丸めた箱。角（Edge）、上面（Top）、地際（Bottom）が分かりやすい基本形です。\n\n"
     "試してみよう（緑の weathering_mask1 を開く）:\n・Preview を Edge / Cavity / Top / Bottom にして、マスクを 1 つずつ見る\n"
     "・Edge Width を 0.2 にすると角の擦れが広がり、1.5 にすると細くなります\n・Top Angle を 80 にすると、ほぼ水平でない面にもほこりが積もります"),
    ("prop_tank", "tank", -1.6, {"edge_width": 0.4, "bottom_height": 0.5},
     "【タンク】\n筒に上下の縁（トーラス）を付けています。縁の付け根に Cavity（へこみ + AO）が出ます。\n\n"
     "試してみよう:\n・AO Weight を 0 にすると、曲率だけのへこみになり、付け根の汚れが細くなります\n・Bottom Height を 1.0 にすると、苔が高くまで登ります"),
    ("prop_blocks", "blocks", 1.6, {"cavity_width": 0.6},
     "【段になったブロック】\n2 つの箱を重ねています。段の入り隅（内側の角）に Cavity が、段の上面に Top が出ます。\n\n"
     "試してみよう:\n・Cavity Width を変えると、入り隅の汚れの幅が変わります\n・Noise の Frequency を 20 にすると、まだら模様が細かくなります"),
    ("prop_barrel", "barrel", 4.8, {"edge_width": 0.35, "cavity_ao": 1.0, "top_noise": 0.3},
     "【樽】\n筒に 3 本の帯を巻いています。帯の角が擦れ、帯の下に汚れがたまります。\n\n"
     "試してみよう:\n・Seed を変えると、まだらの出方が変わります\n・Preview を Packed にすると、Unity に持っていく RGB の形になります（赤 = 角、緑 = へこみ、青 = 上面）"),
]


def build_sample():
    obj = hou.node("/obj")
    for i, (name, kind, x, parms, note) in enumerate(PROPS):
        geo = obj.createNode("geo", name)
        shape = make_shape(geo, kind)
        shape_out = geo.createNode("null", "SHAPE")
        shape_out.setInput(0, shape)
        shape_out.setComment("マスクを付ける前の形。\nexport_packed からも参照しています")
        shape_out.setGenericFlag(hou.nodeFlag.DisplayComment, True)
        wm = geo.createNode(HDA_TYPE, "weathering_mask1")
        wm.setInput(0, shape_out)
        for k, v in parms.items():
            wm.parm(k).set(v)
        wm.setColor(hou.Color((0.3, 0.75, 0.45)))
        out = geo.createNode("null", "OUT")
        out.setInput(0, wm)
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
        sticky.setSize(hou.Vector2(7.5, 4.6))
        sticky.setPosition(hou.Vector2(-9.0, 1.0))
        sticky.setColor(hou.Color((1.0, 0.97, 0.8)))
        geo.setPosition(hou.Vector2(i * 3.5, 0))

    # Unity 向け: 4 つの形をまとめて、Packed で書き出すオブジェクト
    geo = obj.createNode("geo", "export_packed")
    m = geo.createNode("merge", "merge_shapes")
    for i, (name, kind, x, parms, note) in enumerate(PROPS):
        om = geo.createNode("object_merge", "get_" + name)
        om.parm("objpath1").set("/obj/%s/SHAPE" % name)
        om.parm("xformtype").set("local")
        xf = geo.createNode("xform", "place_" + name)
        xf.setInput(0, om)
        xf.parm("tx").set(x)
        m.setInput(i, xf)
    wm = geo.createNode(HDA_TYPE, "weathering_mask1")
    wm.setInput(0, m)
    wm.parm("preview").set("packed")
    wm.parm("write_alpha").set(1)
    wm.setColor(hou.Color((0.3, 0.75, 0.45)))
    out = geo.createNode("null", "OUT")
    out.setInput(0, wm)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    geo.setDisplayFlag(False)
    geo.layoutChildren()
    sticky = geo.createStickyNote()
    sticky.setText("【Unity 向けの書き出し用】\n4 つの小物の形を Object Merge で集めて、Preview = Packed + Write Alpha で\n"
                   "マスクを Cd の RGB と Alpha に詰めています。\n/out の fbx_export_packed で FBX にします。\n"
                   "（表示はオフにしてあります。見たいときはオブジェクトの表示をオンに）")
    sticky.setSize(hou.Vector2(8.0, 3.2))
    sticky.setPosition(hou.Vector2(-9.5, 1.0))
    sticky.setColor(hou.Color((1.0, 0.97, 0.8)))
    geo.setPosition(hou.Vector2(0, -2.5))

    note = obj.createStickyNote()
    note.setText(
        "【Weathering Mask カタログ】\n"
        "小物 4 種に同じ HDA（緑のノード）を付けています。Material Preview で、\n"
        "角の擦れ（明るい）、へこみの汚れ（暗い）、上面のほこり（白）、地際の苔（緑）が見えます。\n\n"
        "各オブジェクトの中で weathering_mask1 の Preview を切り替えて、マスクを 1 つずつ見てください。\n"
        "黄色いメモに「試してみよう」があります。\n\n"
        "Unity へは export_packed（Packed 出力）を /out の fbx_export_packed で書き出します。")
    note.setSize(hou.Vector2(10.0, 3.8))
    note.setPosition(hou.Vector2(-0.5, 1.6))
    note.setColor(hou.Color((1.0, 0.97, 0.8)))

    rop = hou.node("/out").createNode("filmboxfbx", "fbx_export_packed")
    rop.parm("startnode").set("/obj/export_packed")
    rop.parm("sopoutput").set("$HIP/export/weathering_masks_packed.fbx")
    rop.parm("exportkind").set(0)          # バイナリ FBX
    rop.parm("convertunits").set(1)        # Houdini の 1 m を FBX の 100 cm として書く（Unity で正しい大きさになる）
    rop.parm("invisobj").set("visiblenodes")   # 表示オフのオブジェクトも中身ごと書き出す（既定だと空のヌルになる）
    hou.node("/out").layoutChildren()
    note = hou.node("/out").createStickyNote()
    note.setText("【FBX 書き出し】\nRender ボタンで $HIP/export/ に FBX が出ます。\n頂点カラー Cd（RGB = 角・へこみ・上向き）と Alpha（地際）が入ります。")
    note.setSize(hou.Vector2(7.0, 2.2))
    note.setPosition(hou.Vector2(-8.0, 0.5))
    note.setColor(hou.Color((1.0, 0.97, 0.8)))


# ----------------------------------------------------------------------------
# 確認・画像・書き出し
# ----------------------------------------------------------------------------
def stats(vals):
    return "min %.2f avg %.2f max %.2f" % (min(vals), sum(vals) / len(vals), max(vals))


def verify():
    ok = True
    for name, kind, x, parms, note in PROPS:
        n = hou.node("/obj/%s/weathering_mask1" % name)
        n.cook(force=True)
        g = n.geometry()
        line = "%-12s pts=%6d prims=%6d" % (name, len(g.points()), len(g.prims()))
        for a in ("mask_edge", "mask_cavity", "mask_top", "mask_bottom"):
            vals = [pt.attribValue(a) for pt in g.points()]
            line += "  %s: %s" % (a.replace("mask_", ""), stats(vals))
            if min(vals) < -1e-6 or max(vals) > 1 + 1e-6:
                ok = False
        print(line, "err=%s warn=%s" % (n.errors(), n.warnings()))
        if n.errors() or n.warnings():
            ok = False
    # 木箱: 平らな面（法線が軸に沿う）の角マスクは小さく、丸めた角では大きいはず
    g = hou.node("/obj/prop_crate/weathering_mask1").geometry()
    flat, round_ = [], []
    for pt in g.points():
        nrm = pt.attribValue("N")
        (flat if max(abs(c) for c in nrm) > 0.99 else round_).append(pt.attribValue("mask_edge"))
    flat_avg = sum(flat) / max(len(flat), 1)
    round_avg = sum(round_) / max(len(round_), 1)
    print("crate edge mask: flat faces avg %.3f (n=%d), rounded corners avg %.3f (n=%d)" % (flat_avg, len(flat), round_avg, len(round_)))
    if not flat or not round_ or round_avg < flat_avg + 0.2:
        ok = False
    ao_vals = [pt.attribValue("ao") for pt in g.points()]
    print("crate ao: %s" % stats(ao_vals))
    top_pts = [pt.attribValue("mask_top") for pt in g.points() if pt.attribValue("N")[1] > 0.99]
    side_pts = [pt.attribValue("mask_top") for pt in g.points() if abs(pt.attribValue("N")[1]) < 0.01]
    print("crate top mask: top face avg %.3f (n=%d), side faces avg %.3f (n=%d)" % (
        sum(top_pts) / max(len(top_pts), 1), len(top_pts), sum(side_pts) / max(len(side_pts), 1), len(side_pts)))
    if not top_pts or not side_pts or sum(side_pts) / len(side_pts) > 1e-6 or sum(top_pts) / len(top_pts) < 0.3:
        ok = False
    # 段のブロック: 入り隅の点（上の箱の側面の根元）は、開けた面より cavity が大きいはず
    g = hou.node("/obj/prop_blocks/weathering_mask1").geometry()
    corner = [pt.attribValue("mask_cavity") for pt in g.points() if abs(pt.position()[0] - 0.0) < 0.06 and 0.5 <= pt.position()[1] <= 0.6]
    open_ = [pt.attribValue("mask_cavity") for pt in g.points() if pt.position()[0] > 0.3 and abs(pt.position()[1] - 0.5) < 0.01]
    print("blocks cavity mask: inner corner avg %.3f (n=%d), open top avg %.3f (n=%d)" % (
        sum(corner) / max(len(corner), 1), len(corner), sum(open_) / max(len(open_), 1), len(open_)))
    # 書き出し用: Packed で Cd と Alpha があるか
    n = hou.node("/obj/export_packed/weathering_mask1")
    g = n.geometry()
    print("export_packed: pts=%d Cd=%s Alpha=%s err=%s" % (len(g.points()), g.findPointAttrib("Cd") is not None, g.findPointAttrib("Alpha") is not None, n.errors()))
    if g.findPointAttrib("Alpha") is None:
        ok = False
    print("VERIFY:", "OK" if ok else "FAILED")
    return ok


def export_fbx():
    rop = hou.node("/out/fbx_export_packed")
    rop.render()
    p = hou.text.expandString(rop.parm("sopoutput").eval())
    print("fbx:", p, os.path.getsize(p) if os.path.exists(p) else "MISSING", rop.errors())
    # FBX の頂点カラーに Alpha が入っているか（ASCII で書いて中を見る）
    tmp = TOOL_DIR + "/export/_check_ascii.fbx"
    rop2 = hou.node("/out").createNode("filmboxfbx", "ascii_check")
    rop2.parm("startnode").set("/obj/export_packed")
    rop2.parm("sopoutput").set(tmp)
    rop2.parm("exportkind").set(1)
    rop2.parm("invisobj").set("visiblenodes")
    rop2.render()
    s = open(tmp, "r", errors="ignore").read()
    m = re.search(r"Colors: \*(\d+) \{\s*a: ([^}]+)\}", s)
    if m:
        vals = [float(v) for v in m.group(2).replace("\n", "").split(",") if v.strip()]
        alphas = vals[3::4]
        print("fbx vertex colors: %d values (%d x RGBA), alpha range %.2f..%.2f" % (len(vals), len(vals) // 4, min(alphas), max(alphas)))
    else:
        print("fbx vertex colors: not found")
    rop2.destroy()
    os.remove(tmp)


def render_docs():
    obj = hou.node("/obj")
    for lname, rot, inten in (("docs_key", (-45, 35, 0), 1.15), ("docs_fill", (-30, -50, 0), 0.7), ("docs_under", (30, 10, 0), 0.45)):
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
    ogl.parm("shadows").set(0)
    ogl.parm("ambocclusion").set(0)
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

    def set_preview(mode):
        for name, kind, x, parms, note in PROPS:
            hou.node("/obj/%s/weathering_mask1" % name).parm("preview").set(mode)

    props = " ".join("/obj/%s" % name for name, _, _, _, _ in PROPS) + " /obj/docs_ground"
    for mode in PREVIEW_MODES:
        set_preview(mode)
        shoot("catalog_" + mode, (1600, 560), (0, 0.6, 0), 14.5, 16, 8, props)
    set_preview("material")
    for name, kind, x, parms, note in PROPS:
        shoot(name, (900, 620), (x, 0.6, 0), 3.4, 18, 30, "/obj/%s /obj/docs_ground" % name)
    set_preview("packed")
    shoot("prop_barrel_packed", (900, 620), (4.8, 0.6, 0), 3.4, 18, 30, "/obj/prop_barrel /obj/docs_ground")
    set_preview("material")


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
