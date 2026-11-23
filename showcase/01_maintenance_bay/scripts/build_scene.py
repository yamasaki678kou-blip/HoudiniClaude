# -*- coding: utf-8 -*-
u"""整備ドック（Maintenance Bay）— 既存 HDA を組み合わせて 1 枚絵を作るスクリプト。

画面なしの hython から実行します。

    hython scripts/build_scene.py            # シーンを組んで .hiplc に保存するだけ
    hython scripts/build_scene.py test       # + 低解像度のテストレンダー
    hython scripts/build_scene.py still      # + 本番の静止画（1920x1080）
    hython scripts/build_scene.py seq        # + 連番（アニメーション）

使っている HDA
    tools/01_mech_transform   … 壁の点検ハッチの開閉
    tools/02_brick_wall       … 奥の壁・左の壁・床
    tools/03_pipe_run         … 配管 5 本
    tools/04_weathering_mask  … 汚しマスク（色・粗さ・金属度のもと）
    tools/05_mech_leg         … 床に転がっている油圧シリンダー
    tools/06_mecha_chain      … アーム・見張りメカ・レーダー・吊りアーム
"""
import os
import sys
import math
import hou

# ---------------------------------------------------------------- 基本設定
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
REPO = os.path.dirname(os.path.dirname(HERE)).replace("\\", "/")
HIP = HERE + "/maintenance_bay.hiplc"

FPS = 24
FSTART, FEND = 1, 96
HERO_FRAME = 46

OTLS = [
    "tools/01_mech_transform/otls/mech_transform.hdalc",
    "tools/02_brick_wall/otls/brick_wall.hdalc",
    "tools/03_pipe_run/otls/pipe_run.hdalc",
    "tools/04_weathering_mask/otls/weathering_mask.hdalc",
    "tools/05_mech_leg/otls/hydraulic_piston.hdalc",
    "tools/06_mecha_chain/otls/mecha_chain.hdalc",
]

# USD のどのプリムにどのマテリアルを貼るか。構築中に埋めていく。
MASONRY, METAL, GLOW_WARM, GLOW_ARC = [], [], [], []


# ---------------------------------------------------------------- 小道具
def setp(node, **kwargs):
    u"""パラメータをまとめて設定する。無いパラメータは警告だけ出して飛ばす。"""
    for k in sorted(kwargs.keys()):
        v = kwargs[k]
        p = node.parm(k)
        if p is None:
            p = node.parmTuple(k)
        if p is None:
            print("  ! no parm '%s' on %s" % (k, node.path()))
            continue
        try:
            p.set(v)
        except hou.PermissionError:
            # 解像度の縦など、連動していてロックされているものはロックを外す
            try:
                p.lock(False)
                p.set(v)
            except Exception as exc:
                print("  ! locked parm '%s' on %s (%s)" % (k, node.path(), exc))
        except Exception as exc:
            print("  ! could not set '%s' on %s (%s)" % (k, node.path(), exc))
    return node


def xform(parent, name, inp, t=(0, 0, 0), r=(0, 0, 0), s=1.0):
    n = parent.createNode("xform", name)
    n.setFirstInput(inp)
    setp(n, tx=t[0], ty=t[1], tz=t[2], rx=r[0], ry=r[1], rz=r[2], scale=s)
    return n


def aim_rot(pos, target):
    u"""pos から target を向く（-Z 前方の）回転 rx, ry を度で返す。"""
    d = hou.Vector3(target) - hou.Vector3(pos)
    d = d.normalized()
    rx = math.degrees(math.asin(max(-1.0, min(1.0, d[1]))))
    ry = math.degrees(math.atan2(-d[0], -d[2]))
    return rx, ry


# 汚しマスク（mask_edge / mask_cavity / mask_top / mask_bottom）を
# 「色 basecol・粗さ rough・金属度 metal」の 3 つの点属性に落とす VEX。
# この 3 つをそのまま USD の primvar として Karma のマテリアルに渡す。
LOOK_VEX = u"""// === 汚しマスク -> 見た目（色・粗さ・金属度）===
// 素の色。use_cd=1 なら入力の Cd（レンガごとの色など）をそのまま使う
vector base = {USE_CD} ? @Cd : set({BR}, {BG}, {BB});

// 04 Weathering Mask が書いた 4 つのマスクを、強さを掛けて取り出す
float e = clamp(@mask_edge   * {EW}, 0.0, 1.0);   // 角の擦れ
float c = clamp(@mask_cavity * {CW}, 0.0, 1.0);   // へこみの汚れ
float t = clamp(@mask_top    * {TW}, 0.0, 1.0);   // 上面のほこり
float g = clamp(@mask_bottom * {GW}, 0.0, 1.0);   // 地際の苔・泥

// 点の位置で細かいムラを作る（頂点カラーだけだと平坦に見えるため）
float n = noise(@P * {NFREQ} + {NOFF});

// 色を順に混ぜる。最後に角（地金）を混ぜるので、擦れがいちばん上に出る
vector col = base * (1.0 + ({CVAR}) * (n - 0.5) * 2.0);
col = lerp(col, set({DR}, {DG}, {DB}), c);        // へこみの汚れ
col = lerp(col, set({GR}, {GG}, {GB}), g);        // 地際の苔
col = lerp(col, set({TR}, {TG}, {TB}), t);        // 上面のほこり
col = lerp(col, set({ER}, {EG}, {EB}), e);        // 角の擦れ

// 粗さ: へこみはざらつき、角は擦れて少し光る
float rough = lerp({ROUGH}, 0.96, c * 0.85);
rough = lerp(rough, {ROUGH_E}, e);

// 金属度: 塗装がはげた角だけ地金が出る
float metal = lerp({METAL}, {METAL_E}, e);

v@basecol = clamp(col, 0.0, 1.0);
f@rough   = clamp(rough + 0.10 * (n - 0.5), 0.04, 1.0);
f@metal   = clamp(metal, 0.0, 1.0);
"""

LOOKS = {
    # 名前: (use_cd, base, edge, dirt, dust, grime, rough, rough_edge,
    #        metal, metal_edge, edge_w, cav_w, top_w, grime_w, cvar, nfreq, noff)
    "brick":   (1, (0.52, 0.27, 0.21), (0.70, 0.60, 0.52), (0.14, 0.11, 0.09),
                (0.58, 0.56, 0.50), (0.17, 0.26, 0.13), 0.88, 0.75, 0.0, 0.0,
                0.8, 0.7, 0.5, 1.0, 0.18, 6.0, 11.0),
    "stone":   (1, (0.34, 0.33, 0.32), (0.52, 0.51, 0.49), (0.10, 0.10, 0.10),
                (0.42, 0.41, 0.37), (0.15, 0.22, 0.13), 0.90, 0.78, 0.0, 0.0,
                0.9, 0.8, 0.4, 0.8, 0.16, 5.0, 29.0),
    "pipe":    (1, (0.36, 0.40, 0.44), (0.76, 0.77, 0.78), (0.10, 0.08, 0.06),
                (0.44, 0.43, 0.39), (0.16, 0.24, 0.14), 0.52, 0.22, 0.55, 0.95,
                1.0, 1.0, 0.7, 1.0, 0.12, 7.0, 47.0),
    "pipe_y":  (0, (0.56, 0.42, 0.13), (0.78, 0.78, 0.78), (0.12, 0.09, 0.05),
                (0.46, 0.44, 0.39), (0.17, 0.24, 0.14), 0.55, 0.24, 0.45, 0.95,
                1.0, 1.0, 0.7, 1.0, 0.12, 7.0, 61.0),
    "mech":    (1, (0.40, 0.42, 0.45), (0.80, 0.81, 0.82), (0.09, 0.08, 0.07),
                (0.40, 0.39, 0.36), (0.14, 0.20, 0.12), 0.42, 0.16, 0.70, 1.0,
                1.0, 0.9, 0.5, 0.6, 0.10, 9.0, 73.0),
    "mech_h":  (1, (0.62, 0.46, 0.10), (0.80, 0.81, 0.82), (0.10, 0.08, 0.06),
                (0.42, 0.41, 0.37), (0.15, 0.21, 0.12), 0.46, 0.18, 0.55, 1.0,
                1.0, 0.9, 0.5, 0.5, 0.10, 9.0, 83.0),
    "crate":   (0, (0.36, 0.26, 0.16), (0.52, 0.42, 0.28), (0.12, 0.10, 0.07),
                (0.48, 0.46, 0.41), (0.16, 0.23, 0.13), 0.86, 0.70, 0.0, 0.0,
                1.0, 0.9, 0.8, 1.0, 0.16, 11.0, 97.0),
    "steel":   (0, (0.30, 0.31, 0.33), (0.78, 0.78, 0.79), (0.09, 0.07, 0.05),
                (0.40, 0.39, 0.35), (0.15, 0.21, 0.12), 0.45, 0.18, 0.75, 1.0,
                1.0, 1.0, 0.6, 0.9, 0.10, 8.0, 113.0),
}


def look_snippet(key):
    (use_cd, b, e, d, t, g, rough, rough_e, metal, metal_e,
     ew, cw, tw, gw, cvar, nfreq, noff) = LOOKS[key]
    return LOOK_VEX.format(
        USE_CD=use_cd, BR=b[0], BG=b[1], BB=b[2],
        ER=e[0], EG=e[1], EB=e[2], DR=d[0], DG=d[1], DB=d[2],
        TR=t[0], TG=t[1], TB=t[2], GR=g[0], GG=g[1], GB=g[2],
        ROUGH=rough, ROUGH_E=rough_e, METAL=metal, METAL_E=metal_e,
        EW=ew, CW=cw, TW=tw, GW=gw, CVAR=cvar, NFREQ=nfreq, NOFF=noff)


def weather(parent, name, inp, look, prim_path, bevel=0.0, subdiv=0,
            ao=0.0, edge_w=0.4, cav_w=0.4, bottom_h=0.35, top_angle=55.0,
            path_vex=None, seed=0.0):
    u"""入力 →（角を丸める → 細かくする）→ 04 Weathering Mask → 見た目 VEX → path。"""
    cur = inp
    if bevel > 0:
        pb = parent.createNode("polybevel", name + "_bevel")
        pb.setFirstInput(cur)
        setp(pb, offset=bevel, divisions=1)
        cur = pb
    if subdiv > 0:
        sd = parent.createNode("subdivide", name + "_subdiv")
        sd.setFirstInput(cur)
        setp(sd, iterations=subdiv)
        cur = sd
    wm = parent.createNode("hclaude::weathering_mask::1.0", name + "_weather")
    wm.setFirstInput(cur)
    setp(wm, edge_width=edge_w, cavity_width=cav_w, cavity_ao=ao,
         ao_samples=16, bottom_height=bottom_h, top_angle=top_angle,
         seed=seed, noise_freq=9.0, preview=0)
    look_n = parent.createNode("attribwrangle", name + "_look")
    look_n.setFirstInput(wm)
    setp(look_n, **{"class": 2, "snippet": look_snippet(look)})
    pw = parent.createNode("attribwrangle", name + "_path")
    pw.setFirstInput(look_n)
    if path_vex is None:
        path_vex = u's@path = "%s";' % prim_path
    setp(pw, **{"class": 1, "snippet": path_vex})
    return pw


def polyline(parent, name, pts):
    u"""Add SOP で折れ線を 1 本作る（03 Pipe Run の入力になる）。"""
    a = parent.createNode("add", name)
    a.parm("points").set(len(pts))
    for i, p in enumerate(pts):
        a.parmTuple("pt%d" % i).set((p[0], p[1], p[2]))
    a.parm("prims").set(1)
    a.parm("prim0").set(" ".join(str(i) for i in range(len(pts))))
    return a


def note(parent, name, text, pos, size=(5.5, 2.2), color=(0.95, 0.85, 0.35)):
    s = parent.createStickyNote(name)
    s.setText(text)
    s.setPosition(hou.Vector2(pos))
    s.setSize(hou.Vector2(size))
    s.setColor(hou.Color(color))
    return s


# ---------------------------------------------------------------- ジオメトリ
def build_geo():
    obj = hou.node("/obj")
    bay = obj.createNode("geo", "BAY")
    merges = []

    # ======================================================= 壁と床（02）
    def wall(name, w, h, bs, bond, missing, seed, look, t, r, mortar_col,
             col_a, col_b, mix, jitter_rot=0.0, jitter_depth=0.0,
             bottom_h=0.5, edge_w=0.25):
        bw = bay.createNode("hclaude::brick_wall::1.0", name)
        setp(bw, width=w, height=h, brick_sizex=bs[0], brick_sizey=bs[1],
             brick_sizez=bs[2], bond_offset=bond, missing=missing, seed=seed,
             bevel=1, bevel_size=0.008, gap=0.014, jitter_size=0.12,
             jitter_rot=jitter_rot, jitter_depth=jitter_depth,
             color_ar=col_a[0], color_ag=col_a[1], color_ab=col_a[2],
             color_br=col_b[0], color_bg=col_b[1], color_bb=col_b[2],
             color_mix=mix, color_var=0.2, output=0, uv_scale=1.0,
             mortar_colorr=mortar_col[0], mortar_colorg=mortar_col[1],
             mortar_colorb=mortar_col[2], backing=1, backing_depth=0.06)
        x = xform(bay, name + "_place", bw, t=t, r=r)
        brick_path = "/bay/env/%s_brick" % name
        mortar_path = "/bay/env/%s_mortar" % name
        MASONRY.extend([brick_path, mortar_path])
        pv = (u'// 面の name を見て、USD のプリムを「レンガ」と「目地」に分ける\n'
              u's@path = (s@name == "mortar") ? "%s" : "%s";' % (mortar_path, brick_path))
        return weather(bay, name, x, look, brick_path, bevel=0.0, subdiv=0,
                       ao=0.0, edge_w=edge_w, cav_w=0.5, bottom_h=bottom_h,
                       top_angle=62.0, path_vex=pv, seed=seed)

    merges.append(wall("wall_back", 11.0, 4.6, (0.42, 0.105, 0.21), 0.5, 0.035, 3.0,
                       "brick", (0, 0, -3.25), (0, 0, 0), (0.46, 0.44, 0.40),
                       (0.47, 0.25, 0.19), (0.33, 0.21, 0.18), 0.35,
                       jitter_rot=1.2, jitter_depth=0.012, bottom_h=0.75))
    merges.append(wall("wall_left", 9.0, 4.6, (0.42, 0.105, 0.21), 0.5, 0.02, 17.0,
                       "brick", (-4.75, 0, 0.3), (0, 90, 0), (0.44, 0.42, 0.38),
                       (0.42, 0.23, 0.18), (0.30, 0.20, 0.17), 0.45,
                       jitter_rot=1.0, jitter_depth=0.010, bottom_h=0.75))
    merges.append(wall("floor", 13.0, 11.0, (0.62, 0.62, 0.12), 0.333, 0.012, 5.0,
                       "stone", (0, 0, 6.3), (-90, 0, 0), (0.30, 0.30, 0.29),
                       (0.33, 0.32, 0.31), (0.25, 0.25, 0.25), 0.5,
                       jitter_rot=0.6, jitter_depth=0.006, bottom_h=0.02,
                       edge_w=0.6))

    # ======================================================= 配管（03）
    def pipe(name, pts, look, radius, bend_r, band_iv, brackets, bdir,
             blen, flange_bends=1):
        crv = polyline(bay, name + "_curve", pts)
        pr = bay.createNode("hclaude::pipe_run::1.0", name)
        pr.setFirstInput(crv)
        setp(pr, radius=radius, cols=16, bend_radius=bend_r, bend_divisions=6,
             end_caps=1, flange_ends=1, flange_bends=int(flange_bends),
             flange_radius=1.55, flange_width=0.045,
             band_interval=band_iv, band_radius=1.18, band_width=0.035,
             brackets=int(brackets), bracket_interval=1.35,
             bracket_dirx=bdir[0], bracket_diry=bdir[1], bracket_dirz=bdir[2],
             bracket_length=blen, bracket_size=0.05, uv_scale=1.0)
        p = "/bay/pipes/%s" % name
        METAL.append(p)
        return weather(bay, name, pr, look, p, bevel=0.0, subdiv=1, ao=0.0,
                       edge_w=0.12, cav_w=0.2, bottom_h=0.3, top_angle=55.0,
                       seed=abs(hash(name)) % 97)

    merges.append(pipe("pipe_main", [(-5.10, 3.62, -2.95), (3.15, 3.62, -2.95),
                                     (3.15, 1.15, -2.95), (5.30, 1.15, -2.95)],
                       "pipe", 0.135, 0.34, 0.95, True, (0, 0, -1), 0.26))
    merges.append(pipe("pipe_yellow", [(-5.10, 3.04, -2.86), (1.25, 3.04, -2.86),
                                       (1.25, 3.04, -1.15)],
                       "pipe_y", 0.075, 0.26, 0.45, True, (0, 0, -1), 0.20))
    merges.append(pipe("pipe_thin", [(-5.10, 4.12, -2.90), (4.90, 4.12, -2.90)],
                       "pipe", 0.045, 0.2, 0.35, True, (0, 0, -1), 0.18,
                       flange_bends=0))
    merges.append(pipe("pipe_left", [(-4.52, 2.35, 4.10), (-4.52, 2.35, -2.90),
                                     (-2.10, 2.35, -2.90)],
                       "pipe", 0.095, 0.30, 0.0, True, (-1, 0, 0), 0.22))
    merges.append(pipe("pipe_floor", [(-4.30, 0.26, 2.15), (2.45, 0.26, 2.15),
                                      (2.45, 0.26, 5.60)],
                       "pipe", 0.195, 0.40, 1.1, True, (0, -1, 0), 0.20))

    # ======================================================= 小道具（04）
    def prop_box(name, size, t, r, look, bevel=0.025, subdiv=1, ao=0.75):
        b = bay.createNode("box", name + "_box")
        setp(b, sizex=size[0], sizey=size[1], sizez=size[2])
        x = xform(bay, name + "_place", b, t=t, r=r)
        p = "/bay/props/%s" % name
        (MASONRY if look in ("crate", "stone", "brick") else METAL).append(p)
        return weather(bay, name, x, look, p, bevel=bevel, subdiv=subdiv,
                       ao=ao, edge_w=0.35, cav_w=0.35, bottom_h=0.25,
                       top_angle=50.0, seed=abs(hash(name)) % 53)

    merges.append(prop_box("pedestal", (1.70, 0.42, 1.70), (0.55, 0.21, -0.55),
                           (0, 0, 0), "steel", bevel=0.035))
    merges.append(prop_box("crate_a", (0.95, 0.95, 0.95), (-2.62, 0.475, 0.95),
                           (0, 17, 0), "crate", bevel=0.04))
    merges.append(prop_box("crate_b", (0.74, 0.70, 0.74), (-2.50, 1.30, 1.02),
                           (0, -11, 0), "crate", bevel=0.035))
    merges.append(prop_box("crate_c", (0.86, 0.86, 0.86), (3.35, 0.43, 2.05),
                           (0, -28, 0), "crate", bevel=0.04))
    merges.append(prop_box("plinth", (1.10, 0.26, 0.90), (-3.55, 0.13, -1.95),
                           (0, 6, 0), "steel", bevel=0.03))

    def barrel(name, t, r, rad=0.30, h=0.92):
        tb = bay.createNode("tube", name + "_tube")
        setp(tb, rad1=rad, rad2=rad, height=h, cols=20, rows=4, cap=1, type=1)
        x = xform(bay, name + "_place", tb, t=t, r=r)
        p = "/bay/props/%s" % name
        METAL.append(p)
        return weather(bay, name, x, "steel", p, bevel=0.02, subdiv=1, ao=0.75,
                       edge_w=0.3, cav_w=0.3, bottom_h=0.22, top_angle=50.0,
                       seed=abs(hash(name)) % 71)

    merges.append(barrel("barrel_a", (2.95, 0.46, 1.25), (0, 0, 0)))
    merges.append(barrel("barrel_b", (3.52, 0.46, 0.55), (0, 0, 0)))
    merges.append(barrel("barrel_c", (-3.70, 0.31, 1.95), (0, 24, 96)))

    # ============================================= 油圧シリンダー（05）
    def piston(name, p0, p1, cyl=0.62):
        # 05 Hydraulic Piston は「原点から 2 点目へ」作るので、
        # 向きだけ渡して、置き場所は後ろの xform で決める。
        ln = bay.createNode("add", name + "_line")
        ln.parm("points").set(2)
        ln.parmTuple("pt0").set((0.0, 0.0, 0.0))
        ln.parmTuple("pt1").set((p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]))
        ln.parm("prims").set(1)
        ln.parm("prim0").set("0 1")
        hp = bay.createNode("hclaude::hydraulic_piston::1.0", name)
        hp.setFirstInput(ln)
        setp(hp, cyl_ratio=cyl, tie_rods=1, ports=1, bevel=0.03)
        x = xform(bay, name + "_place", hp, t=p0)
        p = "/bay/props/%s" % name
        METAL.append(p)
        return weather(bay, name, x, "steel", p, bevel=0.0, subdiv=0, ao=0.0,
                       edge_w=0.18, cav_w=0.25, bottom_h=0.2, top_angle=50.0,
                       seed=abs(hash(name)) % 29)

    merges.append(piston("piston_spare_a", (-3.30, 0.30, -1.55), (-2.35, 0.95, -1.05)))
    merges.append(piston("piston_spare_b", (-3.95, 0.14, 0.35), (-2.90, 0.14, 0.75)))

    # ============================================= 点検ハッチ（01）
    # 枠 + 扉 2 枚を作り、「どこを軸にどれだけ回るか」をプリム属性で書いて
    # 01 Mech Transform に渡すと、開閉のアニメーションになる。
    hw, hh, hd = 1.05, 1.30, 0.075   # 扉 1 枚の 幅 / 高さ / 厚み
    parts = []
    for i, (nm, sx, ang) in enumerate([("door_l", -1.0, -104.0), ("door_r", 1.0, 104.0)]):
        d = bay.createNode("box", "hatch_%s" % nm)
        setp(d, sizex=hw, sizey=hh, sizez=hd, tx=sx * (hw * 0.5 + 0.01))
        w = bay.createNode("attribwrangle", "hatch_%s_attr" % nm)
        w.setFirstInput(d)
        setp(w, **{"class": 1, "snippet": (
            u'// 01 Mech Transform が読むプリム属性\n'
            u's@name   = "%s";\n'
            u's@parent = "";\n'
            u'v@move   = {0,0,0};\n'
            u'v@hinge  = set(%f, 0, 0);   // 回転の中心（扉の外側の辺）\n'
            u'v@axis   = {0,1,0};         // 縦の軸でひらく\n'
            u'f@angle  = %f;\n'
            u'f@begin  = %f;\n'
            u'f@end    = 1.0;\n' % (nm, sx * (hw + 0.02), ang, 0.08 * (i + 1)))})
        parts.append(w)

    frame_parts = []
    for nm, size, pos in [("ft", (2.34, 0.10, 0.16), (0.0, hh * 0.5 + 0.05, -0.03)),
                          ("fb", (2.34, 0.10, 0.16), (0.0, -hh * 0.5 - 0.05, -0.03)),
                          ("fl", (0.10, hh + 0.20, 0.16), (-1.12, 0.0, -0.03)),
                          ("fr", (0.10, hh + 0.20, 0.16), (1.12, 0.0, -0.03))]:
        b = bay.createNode("box", "hatch_%s" % nm)
        setp(b, sizex=size[0], sizey=size[1], sizez=size[2],
             tx=pos[0], ty=pos[1], tz=pos[2])
        frame_parts.append(b)
    fm = bay.createNode("merge", "hatch_frame_merge")
    for i, n in enumerate(frame_parts):
        fm.setInput(i, n)
    fw = bay.createNode("attribwrangle", "hatch_frame_attr")
    fw.setFirstInput(fm)
    setp(fw, **{"class": 1, "snippet": (
        u'// 動かない枠。属性は揃えておく\n'
        u's@name = "frame"; s@parent = ""; v@move = {0,0,0};\n'
        u'v@hinge = {0,0,0}; v@axis = {0,1,0}; f@angle = 0; f@begin = 0; f@end = 1;')})
    parts.append(fw)

    hm = bay.createNode("merge", "hatch_merge")
    for i, n in enumerate(parts):
        hm.setInput(i, n)
    mt = bay.createNode("hclaude::mech_transform::1.0", "hatch_mech")
    mt.setFirstInput(hm)
    print("  mech_transform drive menu: %s" % (mt.parm("drive").menuLabels(),))
    setp(mt, framesx=14.0, framesy=52.0, ease=3, reverse=0)
    mt.parm("progress").setExpression("clamp(($FF-14)/38.0, 0, 1)")
    hup = bay.createNode("unpack", "hatch_unpack")   # 01 の出力はパック済み
    hup.setFirstInput(mt)
    hx = xform(bay, "hatch_place", hup, t=(-1.95, 1.62, -3.18))
    METAL.append("/bay/mech/hatch")
    merges.append(weather(bay, "hatch", hx, "steel", "/bay/mech/hatch",
                          bevel=0.012, subdiv=1, ao=0.0, edge_w=0.2, cav_w=0.25,
                          bottom_h=0.0, top_angle=50.0, seed=7.0))

    # ハッチの奥で光る板（中の作業灯のイメージ）
    gl = bay.createNode("box", "hatch_glow_box")
    setp(gl, sizex=2.05, sizey=1.45, sizez=0.04)
    glx = xform(bay, "hatch_glow_place", gl, t=(-1.95, 1.62, -3.33))
    glp = bay.createNode("attribwrangle", "hatch_glow_path")
    glp.setFirstInput(glx)
    setp(glp, **{"class": 1, "snippet": u's@path = "/bay/fx/hatch_glow";'})
    GLOW_WARM.append("/bay/fx/hatch_glow")
    merges.append(glp)

    # ======================================================= メカ（06）
    def mecha(name, recipe, t, r, scale, look, speed=1.0):
        mc = bay.createNode("hclaude::mecha_chain::1.0", name)
        setp(mc, recipe=recipe, scale=scale, global_speed=speed, show_skeleton=0)
        up = bay.createNode("unpack", name + "_unpack")
        up.setFirstInput(mc)
        x = xform(bay, name + "_place", up, t=t, r=r)
        p = "/bay/mech/%s" % name
        METAL.append(p)
        node = weather(bay, name, x, look, p, bevel=0.0, subdiv=1, ao=0.0,
                       edge_w=0.10, cav_w=0.18, bottom_h=0.25, top_angle=55.0,
                       seed=abs(hash(name)) % 37)
        return mc, node

    hero_recipe = (
        u"# 主役の産業用アーム。先端は回り続ける溶接トーチ\n"
        u"base(len=0.34, rad=0.27) > motor_osc(axis=2, b=16, speed=0.18, len=0.30) > "
        u"hinge(axis=0, a=30, b=6, c=0.22, len=0.30) > link(len=1.25, rad=0.17) > "
        u"hinge(axis=0, a=105, b=7, c=0.30, phase=90, len=0.26) > link(len=0.95, rad=0.13) > "
        u"ball(a=10, b=6, c=6, len=0.22) > motor_rot(speed=2.6, len=0.18, rad=0.10) > "
        u"drill(len=0.28)")
    hero_t, hero_r = (0.55, 0.42, -0.55), (-90, -38, 0)
    hero, hero_out = mecha("mech_hero", hero_recipe, hero_t, hero_r, 1.0, "mech_h")
    merges.append(hero_out)

    watcher_recipe = (u"# 見張りメカ（箱の上）\n"
                      u"base(len=0.22, rad=0.13) > link(len=0.46, rad=0.065) > "
                      u"spring(a=5, b=7, len=0.26) > head(a=46, b=12, c=0.45, len=0.30)")
    merges.append(mecha("mech_watcher", watcher_recipe,
                        (-2.50, 1.65, 1.02), (-90, 150, 0), 1.0, "mech")[1])

    radar_recipe = (u"# 壁のレーダー\n"
                    u"base(len=0.20, rad=0.15) > servo(b=62, c=0.22, len=0.28) > "
                    u"offset(a=1.2, len=0.24) > link(len=0.30, rad=0.09) > cap(rad=0.42)")
    merges.append(mecha("mech_radar", radar_recipe,
                        (-3.55, 3.55, -3.05), (-24, 14, 0), 1.0, "mech")[1])

    hang_recipe = (u"# 天井の配管から吊ったサブアーム\n"
                   u"base(len=0.20, rad=0.12) > motor_osc(axis=1, b=22, speed=0.5, len=0.26) > "
                   u"link(len=0.44, rad=0.065) > "
                   u"motor_osc(axis=1, b=22, speed=0.5, phase=55, len=0.24) > "
                   u"link(len=0.44, rad=0.06) > "
                   u"motor_osc(axis=1, b=22, speed=0.5, phase=110, len=0.24) > "
                   u"link(len=0.40, rad=0.055) > gripper(b=1, len=0.26)")
    merges.append(mecha("mech_hang", hang_recipe,
                        (3.15, 3.45, -2.95), (90, 24, 0), 1.0, "mech")[1])

    # ============================== 溶接トーチの光（主役の先端を追う）
    # 06 の 2 番目の出力（ソケット = 骨組みの点）から、いちばん先の点だけ残す。
    tip = bay.createNode("attribwrangle", "torch_tip")
    tip.setInput(0, hero, 1)
    setp(tip, **{"class": 2, "snippet": (
        u'// いちばん深いソケット（チェーンの先端）だけ残す\n'
        u'float md = 0;\n'
        u'for (int i = 0; i < @numpt; i++) md = max(md, point(0, "depth", i));\n'
        u'if (@depth < md - 0.5) removepoint(0, @ptnum);')})
    tip_x = xform(bay, "torch_tip_place", tip, t=hero_t, r=hero_r)
    sph = bay.createNode("sphere", "torch_sphere")
    setp(sph, type=1, rows=10, cols=14, radx=0.075, rady=0.075, radz=0.075)
    cp = bay.createNode("copytopoints::2.0", "torch_copy")
    cp.setInput(0, sph)
    cp.setInput(1, tip_x)
    tp = bay.createNode("attribwrangle", "torch_path")
    tp.setFirstInput(cp)
    setp(tp, **{"class": 1, "snippet": u's@path = "/bay/fx/torch";'})
    GLOW_ARC.append("/bay/fx/torch")
    merges.append(tp)

    # ======================================================= まとめ
    allm = bay.createNode("merge", "MERGE_ALL")
    for i, n in enumerate(merges):
        allm.setInput(i, n)
    out = bay.createNode("null", "OUT")
    out.setFirstInput(allm)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)
    bay.layoutChildren()
    note(bay, "note_bay",
         u"整備ドックのジオメトリ\n\n"
         u"・壁と床 … 02 Brick Wall\n"
         u"・配管 … 03 Pipe Run（折れ線 → HDA）\n"
         u"・小道具 … Box/Tube + 04 Weathering Mask\n"
         u"・点検ハッチ … 01 Mech Transform\n"
         u"・シリンダー … 05 Hydraulic Piston\n"
         u"・メカ 4 体 … 06 Mecha Chain\n\n"
         u"*_look の VEX が、マスクを色・粗さ・金属度に変えています。\n"
         u"*_path の VEX が、USD のプリム名を決めています。",
         (-14, 6), size=(9, 5))
    return bay, out, tip_x, hero_t, hero_r


# ---------------------------------------------------------------- /stage
def build_stage(out_node, tip_node):
    st = hou.node("/stage")

    si = st.createNode("sopimport", "import_bay")
    setp(si, soppath=out_node.path(), primpath="/bay",
         enable_pathattr=1, pathattr="path")

    # --------------------------------------------- マテリアル（MaterialX）
    ml = st.createNode("materiallibrary", "materials")
    ml.setFirstInput(si)
    setp(ml, matpathprefix="/materials/")

    def geoprop(name, prop, sig, default):
        g = ml.createNode("mtlxgeompropvalue", name)
        g.parm("signature").set(sig)
        g.parm("geomprop").set(prop)
        if sig == "color3":
            setp(g, default_color3r=default[0], default_color3g=default[1],
                 default_color3b=default[2])
        else:
            setp(g, default=default)
        return g

    def surface(name, spec=1.0, coat=0.0, metal_pv=True, emission=0.0,
                emis_col=(1, 1, 1), base_default=(0.5, 0.5, 0.5)):
        s = ml.createNode("mtlxstandard_surface", name)
        setp(s, base=1.0, specular=spec, coat=coat, coat_roughness=0.25,
             emission=emission, emission_colorr=emis_col[0],
             emission_colorg=emis_col[1], emission_colorb=emis_col[2],
             specular_IOR=1.5)
        if emission <= 0.0:
            bc = geoprop(name + "_basecol", "basecol", "color3", base_default)
            s.setNamedInput("base_color", bc, 0)
            rg = geoprop(name + "_rough", "rough", "float", 0.5)
            s.setNamedInput("specular_roughness", rg, 0)
            if metal_pv:
                mt = geoprop(name + "_metal", "metal", "float", 0.0)
                s.setNamedInput("metalness", mt, 0)
        else:
            setp(s, base_colorr=base_default[0], base_colorg=base_default[1],
                 base_colorb=base_default[2], metalness=0.0)
        return s

    surface("mat_masonry", spec=0.3, coat=0.0, metal_pv=False,
            base_default=(0.45, 0.30, 0.24))
    surface("mat_metal", spec=1.0, coat=0.06, metal_pv=True,
            base_default=(0.40, 0.42, 0.45))
    surface("mat_glow_warm", emission=2.6, emis_col=(1.0, 0.72, 0.42),
            base_default=(0.05, 0.04, 0.03))
    surface("mat_glow_arc", emission=90.0, emis_col=(0.78, 0.88, 1.0),
            base_default=(0.02, 0.02, 0.02))
    ml.layoutChildren()

    am = st.createNode("assignmaterial", "assign_materials")
    am.setFirstInput(ml)
    groups = [(MASONRY, "/materials/mat_masonry"),
              (METAL, "/materials/mat_metal"),
              (GLOW_WARM, "/materials/mat_glow_warm"),
              (GLOW_ARC, "/materials/mat_glow_arc")]
    am.parm("nummaterials").set(len(groups))
    for i, (paths, mat) in enumerate(groups, start=1):
        am.parm("primpattern%d" % i).set(" ".join(paths))
        am.parm("matspecpath%d" % i).set(mat)

    cur = am

    # --------------------------------------------- ライト
    def L(name, ltype, pos, target, intensity, color, exposure=0.0,
          radius=None, width=None, height=None, cone=None, cone_soft=0.4,
          normalize=True, diffuse=1.0, specular=1.0):
        n = st.createNode("light", name)
        n.setFirstInput(cur[0])
        setp(n, primpath="/lights/" + name)
        n.parm("lighttype").set(ltype)
        rx, ry = aim_rot(pos, target)
        setp(n, tx=pos[0], ty=pos[1], tz=pos[2], rx=rx, ry=ry, rz=0.0)
        setp(n, **{"xn__inputsintensity_control_jeb": "set",
                   "xn__inputsintensity_i0a": intensity,
                   "xn__inputsexposure_control_wcb": "set",
                   "xn__inputsexposure_vya": exposure,
                   "xn__inputscolor_control_06a": "set",
                   "xn__inputscolor_ztar": color[0],
                   "xn__inputscolor_ztag": color[1],
                   "xn__inputscolor_ztab": color[2],
                   "xn__inputsnormalize_control_jeb": "set",
                   "xn__inputsnormalize_i0a": int(normalize),
                   "xn__inputsdiffuse_control_99a": "set",
                   "xn__inputsdiffuse_8wa": diffuse,
                   "xn__inputsspecular_control_wcb": "set",
                   "xn__inputsspecular_vya": specular})
        if radius is not None:
            setp(n, **{"xn__inputsradius_control_n8a": "set",
                       "xn__inputsradius_mva": radius})
        if width is not None:
            setp(n, **{"xn__inputswidth_control_06a": "set",
                       "xn__inputswidth_zta": width,
                       "xn__inputsheight_control_n8a": "set",
                       "xn__inputsheight_mva": height})
        if cone is not None:
            setp(n, **{"xn__inputsshapingconeangle_control_xpbhe": "set",
                       "xn__inputsshapingconeangle_wcbhe": cone,
                       "xn__inputsshapingconesoftness_control_tubhe": "set",
                       "xn__inputsshapingconesoftness_shbhe": cone_soft})
        cur[0] = n
        return n

    cur = [am]

    dome = st.createNode("domelight", "sky_ambient")
    dome.setFirstInput(cur[0])
    setp(dome, primpath="/lights/sky_ambient")
    setp(dome, **{"xn__inputsintensity_control_jeb": "set",
                  "xn__inputsintensity_i0a": 0.14,
                  "xn__inputscolor_control_06a": "set",
                  "xn__inputscolor_ztar": 0.42,
                  "xn__inputscolor_ztag": 0.56,
                  "xn__inputscolor_ztab": 0.80})
    cur[0] = dome

    # 作業灯（キーライト）。右手前の上から、主役のアームへ
    L("key_lamp", "UsdLuxRectLight", (4.60, 4.30, 2.60), (0.45, 1.35, -0.90),
      34.0, (1.0, 0.84, 0.62), exposure=1.2, width=1.9, height=1.2)
    # 奥左からの冷たいリムライト（シルエットを出す）
    L("rim_cool", "UsdLuxRectLight", (-4.10, 4.40, -1.30), (0.60, 1.60, 0.40),
      26.0, (0.50, 0.68, 1.0), exposure=1.0, width=2.4, height=1.6)
    # 床を少し起こすバウンス
    L("floor_bounce", "UsdLuxRectLight", (1.40, 0.55, 3.40), (0.40, 1.20, -1.20),
      8.0, (0.95, 0.80, 0.66), exposure=0.0, width=3.0, height=2.0,
      specular=0.25)
    # ハッチの中の灯り
    L("hatch_inner", "UsdLuxSphereLight", (-1.95, 1.62, -3.42), (-1.95, 1.62, 0.0),
      9.0, (1.0, 0.70, 0.40), exposure=1.0, radius=0.35, specular=0.6)
    # 溶接トーチ。アームの先端をフレームごとに追いかける
    torch = L("torch_arc", "UsdLuxSphereLight", (0.0, 1.0, 0.0), (0.0, 0.0, -1.0),
              2.2, (0.80, 0.90, 1.0), exposure=3.4, radius=0.09)

    # --------------------------------------------- うっすらした空気（霧）
    fog = st.createNode("karmafogbox", "air_haze")
    fog.setFirstInput(cur[0])
    setp(fog, primpath="/lights/air_haze", density=0.016, shadow=0,
         colorr=0.62, colorg=0.66, colorb=0.72, addnoise=1, noisescale=1.6,
         amplitude=0.5, tx=0.0, ty=2.4, tz=0.4, sx=13.0, sy=5.2, sz=10.0)
    cur[0] = fog

    # --------------------------------------------- カメラ
    def cam(name, pos, target, focal, fstop=0.0):
        c = st.createNode("camera", name)
        c.setFirstInput(cur[0])
        setp(c, primpath="/cameras/" + name)
        rx, ry = aim_rot(pos, target)
        setp(c, tx=pos[0], ty=pos[1], tz=pos[2], rx=rx, ry=ry, rz=0.0,
             focalLength=focal, horizontalAperture=20.955,
             clippingRange1=0.02, clippingRange2=200.0)
        dist = (hou.Vector3(target) - hou.Vector3(pos)).length()
        setp(c, focusDistance=dist)
        if fstop > 0:
            setp(c, fStop=fstop)
        cur[0] = c
        return c

    cam("cam_hero", (5.27, 3.09, 6.79), (-0.25, 1.60, -0.80), 24.0)
    cam("cam_wide", (6.60, 2.30, 8.40), (-0.60, 1.90, -1.20), 20.0)
    cam("cam_detail", (2.35, 2.55, 2.05), (0.40, 2.05, -0.70), 48.0)

    # --------------------------------------------- レンダー設定
    rs = st.createNode("karmarendersettings", "render_settings")
    rs.setFirstInput(cur[0])
    setp(rs, primpath="/Render/rendersettings", camera="/cameras/cam_hero",
         resolutionx=1920, resolutiony=1080, samplesperpixel=160)
    for nm, val in (("engine", "cpu"), ("denoiser", "oidn")):
        p = rs.parm(nm)
        if p is None:
            continue
        try:
            print("  %s menu: %s" % (nm, p.menuItems()))
            p.set(val)
        except Exception as exc:
            print("  ! could not set %s=%s (%s)" % (nm, val, exc))
    cur[0] = rs

    rop = st.createNode("usdrender_rop", "render_karma")
    rop.setFirstInput(cur[0])
    setp(rop, rendersettings="/Render/rendersettings",
         outputimage=HERE + "/render/hero.exr", trange=0)
    p = rop.parm("renderer")
    print("  renderer menu: %s" % (p.menuItems(),))

    st.layoutChildren()
    note(st, "note_stage",
         u"ここから先が USD（LOP）です\n\n"
         u"1. import_bay … SOP の形を USD に取り込む。path 属性がプリム名になります\n"
         u"2. materials … MaterialX のマテリアル 4 個。色・粗さ・金属度は primvar から読みます\n"
         u"3. assign_materials … プリムのパターンでマテリアルを割り当て\n"
         u"4. ライト 6 個 … 環境光・作業灯・リム・バウンス・ハッチの灯り・溶接トーチ\n"
         u"5. air_haze … うっすらした空気（Karma Fog Box）\n"
         u"6. カメラ 3 台 … hero / wide / detail\n"
         u"7. render_settings → render_karma … Karma でレンダリング",
         (-16, 4), size=(11, 5))
    return rs, rop, torch


def keyframe_torch(torch, tip_node):
    u"""溶接トーチのライトを、アームの先端にフレームごとに貼り付ける。"""
    names = ("tx", "ty", "tz")
    keys = {n: [] for n in names}
    last = None
    for f in range(FSTART, FEND + 1):
        hou.setFrame(f)
        g = tip_node.geometry()
        if len(g.points()):
            last = g.points()[0].position()
        if last is None:
            continue
        for i, n in enumerate(names):
            k = hou.Keyframe()
            k.setFrame(f)
            k.setValue(last[i])
            k.setExpression("linear()")
            keys[n].append(k)
    for n in names:
        torch.parm(n).setKeyframes(keys[n])
    hou.setFrame(HERO_FRAME)
    print("  torch tip at frame %d: %s" % (HERO_FRAME, last))


# ---------------------------------------------------------------- 検査
def report(root):
    bad = []
    for n in root.allSubChildren():
        try:
            if n.errors():
                bad.append((n.path(), n.errors()[0][:220]))
            elif n.warnings():
                print("  warn %s: %s" % (n.path(), n.warnings()[0][:160]))
        except hou.OperationFailed as exc:
            bad.append((n.path(), str(exc)[:220]))
    for p, e in bad:
        print("  ERROR %s: %s" % (p, e))
    return bad


# ---------------------------------------------------------------- レンダー
def render(rop, rs, camera, outfile, res, spp, seq=False):
    setp(rs, camera="/cameras/" + camera, resolutionx=res[0], resolutiony=res[1],
         samplesperpixel=spp)
    setp(rop, outputimage=outfile)
    if seq:
        setp(rop, trange=1, f1=FSTART, f2=FEND, f3=2)
    else:
        setp(rop, trange=0)
    print("  rendering %s (%dx%d, spp=%d) ..." % (outfile, res[0], res[1], spp))
    sys.stdout.flush()
    rop.render(verbose=False)
    print("  done: %s" % outfile)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    hou.hipFile.clear(suppress_save_prompt=True)
    hou.setFps(FPS)
    hou.playbar.setFrameRange(FSTART, FEND)
    hou.playbar.setPlaybackRange(FSTART, FEND)
    for o in OTLS:
        hou.hda.installFile(REPO + "/" + o)

    print("[1/4] ジオメトリを組む")
    bay, out, tip_node, hero_t, hero_r = build_geo()
    hou.setFrame(HERO_FRAME)
    geo = out.geometry()
    print("  polygons: %d   points: %d" % (len(geo.prims()), len(geo.points())))

    print("[2/4] USD とマテリアルとライト")
    rs, rop, torch = build_stage(out, tip_node)
    keyframe_torch(torch, tip_node)

    print("[3/4] エラー検査")
    bad = report(hou.node("/obj")) + report(hou.node("/stage"))

    hou.hipFile.save(HIP)
    print("  saved %s" % HIP)
    if bad:
        print("!! %d 個のノードがエラーです" % len(bad))

    if mode == "test":
        render(rop, rs, "cam_hero", HERE + "/render/test.png", (640, 360), 12)
    elif mode == "still":
        for camname, res, spp in (("cam_hero", (1920, 1080), 200),
                                  ("cam_wide", (1920, 1080), 160),
                                  ("cam_detail", (1600, 1600), 160)):
            render(rop, rs, camname, HERE + "/render/%s.png" % camname, res, spp)
    elif mode == "seq":
        render(rop, rs, "cam_hero", HERE + "/render/seq/bay.$F4.png",
               (960, 540), 48, seq=True)
    print("[4/4] 完了")


main()
