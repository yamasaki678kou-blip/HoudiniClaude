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
     "link(len=1.0) > prismatic(a=0, b=0.4, c=1.0) > drill(pa=2.0)"),
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
    ("10", "一輪セグウェイ風", "base > spring(a=6, b=8) > link(len=0.8) > wheel(pa=1.0)"),
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
    ("17", "アンテナ／レーダー", "base > servo(b=50, c=0.3) > offset(a=0.2) > link(len=0.3) > cap(rad=0.35)"),
    ("18", "ゲート開閉（drive=Block）", "base > hinge(axis=1, a=0, b=40, c=0.25, drive=1) > link(len=1.8) > cap"),
    ("19", "カウンター回転ツイン",
     "base > motor_rot(speed=0.8) > link(len=0.5) > motor_rot(speed=-1.3) > link(len=0.5) > "
     "motor_rot(speed=2.1) > cap"),
    ("20", "スプリング・カオス",
     "base > motor_osc(b=15, speed=1.2) > spring(a=3, b=20) > link(len=0.6) > spring(a=2, b=25) > "
     "link(len=0.6) > spring(a=1.5, b=30) > cap(rad=0.25)"),
]
RECIPES = dict((k, r) for k, _, r in PRESETS)

# 検証用のチェーン（実装パケット §5.2 の bent テスト + 順序の差が出る 2 回折りテスト）
BENT_SINGLE = "base > bent(a=45) > link > cap"
BENT_DOUBLE = "base > bent(a=90) > bent(a=90, b=90) > link"

# ----------------------------------------------------------------------------
# 1. recipe_parser（Python SOP）… 実装パケット §3 v0.2 が元。実装側の追加は「# 追加:」の行
# ----------------------------------------------------------------------------
PARSER_CODE = r'''# recipe_parser - Python SOP
# レシピ文字列を読んで、パーツ 1 個 = 点 1 個 にします。親 → 子の順に点を並べ、親子を線でつなぎます。
# 元: 実装パケット v0.3 §3（パーサ v0.2）。「# 追加:」の行は実装側で足したエラーチェックなどです。
import re

node = hou.pwd()
geo = node.geometry()
geo.clear()

recipe = node.evalParm("recipe")
global_speed = node.evalParm("global_speed")

DEFAULTS = {
    "base": dict(len=0.0),
    "motor_rot": dict(pa=1.0),
    "motor_osc": dict(pa=0.0, pb=40.0),
    "servo": dict(pa=0.0, pb=30.0, pc=1.0),
    "piston": dict(pa=0.4, pb=0.5),
    "hinge": dict(pa=0.0, pb=0.0, pc=0.0, pd=0.0),
    "ball": dict(pa=15.0, pb=0.0, pc=0.0),
    "universal": dict(pa=20.0, pb=0.0, pc=0.3),
    "prismatic": dict(pa=0.0, pb=0.5, pc=0.0),
    "twist": dict(pa=0.0, pb=0.0),
    "spring": dict(pa=5.0, pb=10.0, pc=0.5),
    "fixed": dict(),
    "link": dict(),
    "offset": dict(pa=0.3, pb=0.0),
    "bent": dict(pa=30.0, pb=0.0),
    "splitter": dict(pa=2.0, pb=45.0, pc=0.0),
    "branch": dict(len=0.0),
    "gripper": dict(len=0.3, pa=25.0, pb=0.0),
    "wheel": dict(len=0.2, pa=1.0),
    "foot": dict(len=0.2),
    "drill": dict(len=0.4, pa=1.0),
    "head": dict(len=0.3, pa=30.0, pb=10.0, pc=1.0),
    "cap": dict(len=0.15),
}
ALIASES = {"mrot": "motor_rot", "mosc": "motor_osc", "uni": "universal",
           "slide": "prismatic", "endcap": "cap"}
SLOT_ALIAS = {"a": "pa", "b": "pb", "c": "pc", "d": "pd"}  # レシピは a〜d、内部は pa〜pd
COMMON = dict(len=1.0, axis=2, speed=1.0, phase=0.0, drive=0, ratio=1.0,
              join=0, limit_min=-180.0, limit_max=180.0, seed=0)
ROOT_RAD = 0.15
MAX_PARTS = 256
# 造形の大きさの決め方: 0 = 固定（太さ rad だけで決まる）, 1 = 伸びる（Z が len + ext）
SCALE_MODE = {"link": 1, "offset": 1, "bent": 1, "prismatic": 1, "piston": 1}
# APEX 用のタグ（Phase4 でリグ自動生成が読む予定）
TAGS = {"motor_rot": "motor_rotary", "motor_osc": "motor_osc", "servo": "servo",
        "hinge": "joint_hinge", "ball": "joint_ball", "universal": "joint_universal",
        "prismatic": "joint_slide", "twist": "joint_twist", "spring": "joint_spring",
        "gripper": "effector_gripper", "wheel": "effector_wheel",
        "drill": "effector_tool", "head": "effector_head"}
# 追加: レシピに書いてよいキー（これ以外は警告）
VALID_KEYS = set(COMMON) | set(["rad", "pa", "pb", "pc", "pd"])


def fail(msg):
    # Houdini のノードエラーとして表示する（赤いエラー表示 + メッセージ）
    raise hou.NodeError(msg)


def warn(msg):
    try:
        node.addWarning(msg)
    except Exception:
        pass


TOKEN_RE = re.compile(r"\s*(>|\[|\]|\||[A-Za-z_][A-Za-z0-9_]*\s*(?:\([^)]*\))?)\s*")


def tokenize(s):
    toks, i = [], 0
    s = s.strip()
    while i < len(s):
        m = TOKEN_RE.match(s, i)
        if not m or m.end() == i:
            fail("parse error / 読めない文字があります: %r" % s[i:i + 20])
        toks.append(re.sub(r"\s+", "", m.group(1)))
        i = m.end()
    return toks


def parse_part_token(tok):
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)(?:\((.*)\))?$", tok)
    name = ALIASES.get(m.group(1), m.group(1))
    if name not in DEFAULTS or name == "branch":
        # 追加: 知らないパーツ名は黙って通さない（打ち間違いに気づけるように）
        fail("unknown part / 知らないパーツ名です: %s" % m.group(1))
    explicit = {}
    if m.group(2):
        for kv in m.group(2).split(","):
            if not kv.strip():
                continue
            if kv.count("=") != 1:
                fail("bad parameter / 「名前=値」の形で書いてください: %s(%s)" % (name, kv.strip()))
            k, v = kv.split("=")
            k = SLOT_ALIAS.get(k.strip(), k.strip())
            try:
                explicit[k] = float(v)
            except ValueError:
                fail("bad value / 数値ではありません: %s(%s)" % (name, kv.strip()))
            if k not in VALID_KEYS:
                warn("unknown key / 使われないキーです: %s(%s)" % (name, k))
    return name, explicit


parts = []  # dict(name, params, parent, depth)


def add_part(name, explicit, parent):
    if len(parts) >= MAX_PARTS:
        fail("too many parts / パーツは %d 個までです" % MAX_PARTS)
    prm = dict(COMMON)
    prm.update(DEFAULTS.get(name, {}))
    # rad の継承: 明示した値が勝つ。書いていなければ親の（解決済みの）値を受け継ぐ
    explicit = dict(explicit)
    if "rad" in explicit:
        prm["rad"] = explicit.pop("rad")
    elif parent >= 0:
        prm["rad"] = parts[parent]["params"]["rad"]
    else:
        prm["rad"] = ROOT_RAD
    prm.update(explicit)
    depth = 0 if parent < 0 else parts[parent]["depth"] + 1
    parts.append(dict(name=name, params=prm, parent=parent, depth=depth))
    return len(parts) - 1


def parse_chain(toks, pos, parent):
    last = parent
    while pos < len(toks):
        tok = toks[pos]
        if tok in ("]", "|"):
            break
        if tok == ">":
            pos += 1
            continue
        if tok == "[":
            fail("'[' must follow a splitter / [ は splitter の直後にだけ書けます")
        name, explicit = parse_part_token(tok)
        idx = add_part(name, explicit, last)
        pos += 1
        if name == "splitter":
            n = int(round(parts[idx]["params"].get("pa", 2)))
            spread = parts[idx]["params"].get("pb", 45.0)
            if n < 2 or n > 4:
                fail("splitter の分岐数 a は 2〜4 です（a=%d）" % n)
            if pos >= len(toks) or toks[pos] != "[":
                fail("splitter requires [ branch | branch ] / splitter の後ろに [ 枝 | 枝 ] が必要です")
            pos += 1
            branch_ids = []
            while True:
                bidx = add_part("branch", dict(len=0.0, pre_yaw=0.0), idx)
                branch_ids.append(bidx)
                pos, _ = parse_chain(toks, pos, bidx)
                if pos < len(toks) and toks[pos] == "|":
                    pos += 1
                    continue
                if pos < len(toks) and toks[pos] == "]":
                    pos += 1
                    break
                fail("splitter branches must end with ] / 枝の最後は ] で閉じてください")
            if len(branch_ids) != n:
                # 追加: 枝の数と a の食い違いを止める（少ない場合も黙って進まない）
                fail("splitter(a=%d) なのに枝が %d 本あります" % (n, len(branch_ids)))
            for k, bidx in enumerate(branch_ids):
                parts[bidx]["params"]["pre_yaw"] = spread * (k - (n - 1) / 2.0)
            return pos, idx  # splitter はそのチェーンの終わり（枝の中での入れ子は可）
        last = idx
    return pos, last


# 追加: # から行末まではコメントとして読み飛ばす（複数行のレシピにメモを書けるように）
recipe = re.sub(r"#[^\n]*", "", recipe)
toks = tokenize(recipe)
if toks:
    end, _ = parse_chain(toks, 0, -1)
    if end < len(toks):
        # 追加: splitter の ] の後ろに続けた、余分な ] や | がある、など
        fail("extra tokens / ここから先が読めません（splitter の後ろには続けられません）: %s"
             % " ".join(toks[end:end + 3]))
if not parts:
    add_part("base", {}, -1)  # 空のレシピは base 1 点で通す

# ---- 属性を作る（所有権表 §4: ここで書いた属性を、ソルバ以降が読む）
geo.addAttrib(hou.attribType.Global, "global_speed", 1.0)
geo.setGlobalAttribValue("global_speed", float(global_speed))
for nm in ("part_type", "tag", "name"):
    geo.addAttrib(hou.attribType.Point, nm, "")
for nm, dv in [("parent_id", -1), ("order", 0), ("depth", 0), ("axis", 2),
               ("drive_mode", 0), ("join_mode", 0), ("scale_mode", 0), ("has_geo", 1)]:
    geo.addAttrib(hou.attribType.Point, nm, dv)
for nm in ("length", "radius", "speed", "phase", "ratio",
           "limit_min", "limit_max", "pa", "pb", "pc", "pd", "pre_yaw", "pre_pitch"):
    geo.addAttrib(hou.attribType.Point, nm, 0.0)

points = []
for i, p in enumerate(parts):
    pt = geo.createPoint()
    prm = p["params"]
    pt.setAttribValue("part_type", p["name"])
    pt.setAttribValue("tag", TAGS.get(p["name"], ""))
    pt.setAttribValue("name", "part%d_%s" % (i, p["name"]))
    pt.setAttribValue("parent_id", p["parent"])
    pt.setAttribValue("order", i)
    pt.setAttribValue("depth", p["depth"])
    pt.setAttribValue("length", float(prm.get("len", 1.0)))
    pt.setAttribValue("radius", float(prm["rad"]))
    pt.setAttribValue("speed", float(prm.get("speed", 1.0)))
    pt.setAttribValue("phase", float(prm.get("phase", 0.0)))
    pt.setAttribValue("ratio", float(prm.get("ratio", 1.0)))
    pt.setAttribValue("limit_min", float(prm.get("limit_min", -180.0)))
    pt.setAttribValue("limit_max", float(prm.get("limit_max", 180.0)))
    pt.setAttribValue("axis", int(prm.get("axis", 2)))
    pt.setAttribValue("drive_mode", int(prm.get("drive", 0)))
    pt.setAttribValue("join_mode", int(prm.get("join", 0)))
    pt.setAttribValue("scale_mode", SCALE_MODE.get(p["name"], 0))
    pt.setAttribValue("has_geo", 0 if p["name"] == "branch" else 1)
    for k in ("pa", "pb", "pc", "pd", "pre_yaw", "pre_pitch"):
        pt.setAttribValue(k, float(prm.get(k, 0.0)))
    points.append(pt)

for i, p in enumerate(parts):
    if p["parent"] >= 0:
        poly = geo.createPolygon(False)
        poly.addVertex(points[p["parent"]])
        poly.addVertex(points[i])
'''

# ----------------------------------------------------------------------------
# 2. socket_solver（Detail Wrangle）… 実装パケット §5 v0.3（クォータニオン状態方式）
# ----------------------------------------------------------------------------
SOLVER_VEX = r'''// ============================================================
// socket_solver（Detail Wrangle = 1 回だけ実行）
// 各パーツの置き場所（frame）と出力ソケット（socket）を、親から順に計算します。
// パーサが「親が先」の順で点を並べているので、0 番から順に計算すれば
// 親のソケットは必ず先に求まっています。
// 元: 実装パケット v0.3 §5.3。関数名は実機に合わせてあります。
// ============================================================

// ---- 掛け算の順番に気をつける場所は、この compose() 1 か所だけ ----
// qmultiply(a, b) は「先に b（子のローカル回転）、次に a（親の向き）」の順で回す合成です。
// 実機テストで qrotate(qmultiply(a, b), v) == qrotate(a, qrotate(b, v)) を確かめてあります。
vector4 compose(vector4 parent_q; vector4 local_q)
{
    return qmultiply(parent_q, local_q);
}
// 角度（度）と軸から回転（クォータニオン）を作る
vector4 q_axis(float deg; vector axis)
{
    return quaternion(radians(deg), axis);
}

float T = @Time * f@global_speed;   // 時刻（秒）× 全体の速さ（パーサが detail 属性に書いた値）
int n = npoints(0);

addpointattrib(0, "frame_pos", {0, 0, 0});
addpointattrib(0, "frame_orient", {0, 0, 0, 1});
addpointattrib(0, "socket_pos", {0, 0, 0});
addpointattrib(0, "drive_angle", 0.0);
addpointattrib(0, "ext", 0.0);
addpointattrib(0, "open_angle", 0.0);

// ---- 入力を配列に写す（point() は入力のスナップショットを読むので安全） ----
string types[];
int parents[];
int axes[];
int dmodes[];
int joins[];
int depths[];
float lens[];
float speeds[];
float phases[];
float ratios[];
float lmins[];
float lmaxs[];
float pas[];
float pbs[];
float pcs[];
float pds[];
float preyaws[];
resize(types, n); resize(parents, n); resize(axes, n); resize(dmodes, n);
resize(joins, n); resize(depths, n); resize(lens, n); resize(speeds, n);
resize(phases, n); resize(ratios, n); resize(lmins, n); resize(lmaxs, n);
resize(pas, n); resize(pbs, n); resize(pcs, n); resize(pds, n); resize(preyaws, n);
for (int i = 0; i < n; i++) {
    types[i]   = point(0, "part_type", i);
    parents[i] = point(0, "parent_id", i);
    axes[i]    = point(0, "axis", i);
    dmodes[i]  = point(0, "drive_mode", i);
    joins[i]   = point(0, "join_mode", i);
    depths[i]  = point(0, "depth", i);
    lens[i]    = point(0, "length", i);
    speeds[i]  = point(0, "speed", i);
    phases[i]  = point(0, "phase", i);
    ratios[i]  = point(0, "ratio", i);
    lmins[i]   = point(0, "limit_min", i);
    lmaxs[i]   = point(0, "limit_max", i);
    pas[i]     = point(0, "pa", i);
    pbs[i]     = point(0, "pb", i);
    pcs[i]     = point(0, "pc", i);
    pds[i]     = point(0, "pd", i);
    preyaws[i] = point(0, "pre_yaw", i);
}

// 計算結果を入れる配列（子は親の値をここから読む）
vector sout_pos[];
vector4 sout_ori[];
vector fpos[];
vector4 fori[];
float drv[];
float exts[];
float opens[];
resize(sout_pos, n); resize(sout_ori, n); resize(fpos, n); resize(fori, n);
resize(drv, n); resize(exts, n); resize(opens, n);

vector AXES[] = { {1, 0, 0}, {0, 1, 0}, {0, 0, 1} };   // axis 0 = X / 1 = Y / 2 = Z
vector4 QIDENT = {0, 0, 0, 1};                          // 回転なし

for (int i = 0; i < n; i++) {
    int par = parents[i];
    vector  pp  = par < 0 ? set(0, 0, 0) : sout_pos[par];   // 親の出力ソケットの位置
    vector4 pq  = par < 0 ? QIDENT : sout_ori[par];         // 親の出力ソケットの向き
    float   din = par < 0 ? 0.0 : drv[par];                 // 親から流れてくる駆動角
    string ty = types[i];
    float ph = phases[i];
    float sp = speeds[i];
    float wt = 360.0 * sp * T + ph;                         // 1 秒で speed 回転する角度（度）
    vector ax = AXES[clamp(axes[i], 0, 2)];

    vector4 ql = QIDENT;          // このパーツのローカル回転
    vector off = set(0, 0, 0);    // ローカルのずれ（offset だけが使う）
    float ext = 0.0;              // 伸びる量（piston / prismatic）
    float dout = din;             // 子へ流す駆動角（既定は素通し = Through）
    float oa = 0.0;               // グリッパの開き角

    if (ty == "branch") {
        ql = q_axis(preyaws[i], set(0, 1, 0));
    } else if (ty == "motor_rot") {
        float ang = pas[i] * wt;
        ql = q_axis(ang, ax);
        dout = joins[i] == 1 ? din + ang : ang;
    } else if (ty == "motor_osc") {
        float w = pas[i] > 0.5 ? (2.0 * abs(frac(wt / 360.0) * 2.0 - 1.0) - 1.0)
                               : sin(radians(wt));
        float ang = pbs[i] * w;
        ql = q_axis(ang, ax);
        dout = joins[i] == 1 ? din + ang : ang;
    } else if (ty == "servo") {
        float ang = clamp(pas[i] + pbs[i] * sin(radians(360.0 * sp * pcs[i] * T + ph)),
                          lmins[i], lmaxs[i]);
        ql = q_axis(ang, ax);
        dout = ang;
    } else if (ty == "piston") {
        ext = pas[i] * (0.5 - 0.5 * cos(radians(wt)));
    } else if (ty == "hinge") {
        float ang;
        if (pds[i] > 0.5) {
            // 駆動消費（d=1）: 上流の駆動角をそのまま関節角に使う。
            // 累積角なのでクランプしない（v0.3 の修正。クランプすると limit に張り付く）
            ang = din;
        } else {
            ang = pas[i] + (pcs[i] > 0 ? pbs[i] * sin(radians(360.0 * sp * pcs[i] * T + ph)) : 0.0);
            ang = clamp(ang, lmins[i], lmaxs[i]);
        }
        ql = q_axis(ang, ax);
        if (dmodes[i] == 1) dout = 0.0;
    } else if (ty == "ball") {
        float ax_ = clamp(pas[i] + pcs[i] * sin(radians(wt)), lmins[i], lmaxs[i]);
        float ay_ = clamp(pbs[i] + pcs[i] * cos(radians(wt)), lmins[i], lmaxs[i]);
        ql = qmultiply(q_axis(ax_, set(1, 0, 0)), q_axis(ay_, set(0, 1, 0)));
        dout = 0.0;
    } else if (ty == "universal" || ty == "bent") {
        vector axv = set(cos(radians(pbs[i])), sin(radians(pbs[i])), 0);   // b = 折れる向き（度）
        ql = q_axis(pas[i], axv);                                          // a = 折れ角（度）
    } else if (ty == "twist") {
        ql = q_axis(pas[i] + pbs[i] * T, set(0, 0, 1));
    } else if (ty == "spring") {
        float lag = depths[i] * 30.0 / max(pas[i], 0.001);   // 根から遠いほど遅れる（点番号ではなく深さ）
        ql = q_axis(pbs[i] * sin(radians(wt) - radians(lag)), ax);
    } else if (ty == "prismatic") {
        float s = pcs[i] > 0 ? (0.5 - 0.5 * cos(radians(360.0 * sp * pcs[i] * T + ph))) : 1.0;
        ext = lerp(pas[i], pbs[i], s);
    } else if (ty == "offset") {
        off = set(pas[i], pbs[i], 0);
    } else if (ty == "wheel") {
        ql = q_axis(din * pas[i], ax);
    } else if (ty == "head") {
        float yaw = pas[i] * sin(radians(360.0 * sp * pcs[i] * T + ph));
        float pit = pbs[i] * sin(radians(360.0 * sp * pcs[i] * T * 0.7 + ph));
        ql = qmultiply(q_axis(yaw, set(0, 1, 0)), q_axis(pit, set(1, 0, 0)));
    } else if (ty == "gripper") {
        // 実装側の追加: 指の開き角（b=1 で sin で自動開閉）。指の造形は detail_pieces が読む
        oa = pas[i];
        if (pbs[i] > 0.5) oa = pas[i] * (0.5 + 0.5 * sin(radians(wt)));
    }
    // link / fixed / cap / base / foot: ローカル回転なし
    if (ty == "drill") ql = q_axis(din * pas[i] + 360.0 * sp * T * pas[i], set(0, 0, 1));

    if (dmodes[i] == 2) dout = din * ratios[i];                 // Gear: 変速
    if (dmodes[i] == 1 && ty != "hinge") dout = 0.0;            // Block: ここで止める

    vector4 fq = compose(pq, ql);                               // 親の向き × 自分の回転
    vector fp = pp + qrotate(pq, off);
    fpos[i] = fp;
    fori[i] = fq;
    sout_pos[i] = fp + qrotate(fq, set(0, 0, lens[i] + ext));   // 出力ソケット = ローカル +Z に len 先
    sout_ori[i] = fq;
    drv[i] = dout;
    exts[i] = ext;
    opens[i] = oa;
}

for (int i = 0; i < n; i++) {
    setpointattrib(0, "frame_pos", i, fpos[i]);
    setpointattrib(0, "frame_orient", i, fori[i]);
    setpointattrib(0, "socket_pos", i, sout_pos[i]);
    setpointattrib(0, "drive_angle", i, drv[i]);
    setpointattrib(0, "ext", i, exts[i]);
    setpointattrib(0, "open_angle", i, opens[i]);
}
'''

# ----------------------------------------------------------------------------
# 3. frame_decompose（Point Wrangle）… 実装パケット §6 v0.3
# ----------------------------------------------------------------------------
DECOMPOSE_VEX = r'''// frame_decompose（Point Wrangle）
// ソルバの答え（frame_pos / frame_orient）を、Copy to Points が読む標準の属性に写すだけです。
// pscale は使いません。大きさは v@scale（XYZ 別々のスケール）で渡します。
@P = v@frame_pos;
@orient = p@frame_orient;
float r = f@radius;
if (i@scale_mode == 1) {
    // 伸びるパーツ（link など）: 太さは rad、長さ（Z）は len + ext
    float L = f@length + f@ext;
    v@scale = set(r, r, max(L, 0.001));
} else {
    // 固定サイズのパーツ（motor など）: 太さ rad だけで大きさが決まる（len では伸びない）
    v@scale = set(r, r, r);
}
if (i@has_geo == 0) v@scale = set(0, 0, 0);
s@piece = s@part_type;
'''

# ----------------------------------------------------------------------------
# 4. detail_pieces（Point Wrangle）… 実装側の追加（仕様の所有権表は壊さない）
# ----------------------------------------------------------------------------
PIECES_VEX = r'''// detail_pieces（Point Wrangle）… 実装側で足した見た目用の部品
// 1) 固定サイズのパーツ（モーターや関節）は len を伸ばしても形が伸びないので、
//    次のソケットまでを細い「軸（rod）」でつなぎます。
// 2) グリッパに指を 2 本足して、ソルバが出した open_angle だけ開きます。
string NO_ROD[] = {"base", "branch", "cap", "gripper", "drill", "head", "wheel", "foot"};
if (i@has_geo == 1) {
    float r = f@radius;
    float L = f@length + f@ext;
    vector4 q = p@orient;
    if (i@scale_mode == 0 && L > r * 1.2 && find(NO_ROD, s@part_type) < 0) {
        int np = addpoint(0, @ptnum);                 // 今の点の属性をまるごと写した新しい点
        setpointattrib(0, "piece", np, "rod");
        setpointattrib(0, "name", np, s@name + "_rod");
        setpointattrib(0, "scale", np, set(r * 0.45, r * 0.45, L));
    }
    if (s@part_type == "gripper") {
        float oa = f@open_angle;
        for (int side = -1; side <= 1; side += 2) {
            int np = addpoint(0, @ptnum);
            setpointattrib(0, "P", np, @P + qrotate(q, set(0, side * r * 0.55, r * 0.8)));
            // 指の付け根で X 軸まわりに開く（+Y 側の指は +Y へ、-Y 側の指は -Y へ）
            setpointattrib(0, "orient", np, qmultiply(q, quaternion(radians(-side * oa), {1, 0, 0})));
            setpointattrib(0, "piece", np, "finger");
            setpointattrib(0, "name", np, s@name + (side < 0 ? "_finger_R" : "_finger_L"));
        }
    }
}
'''

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
    tokens = ["none"] + [k for k, _, _ in PRESETS]
    labels = ["（選ぶとレシピ欄を上書きします）"] + ["%s  %s" % (k, t) for k, t, _ in PRESETS]
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

    copy = sub.createNode("copytopoints", "copy_parts")
    copy.setInput(0, tpl)
    copy.setInput(1, pieces)
    sp(copy, "useidattrib", 1)
    sp(copy, "idattrib", "piece")
    sp(copy, "pack", 0)
    copy.parm("resettargetattribs").pressButton()
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
        min_num_inputs=0, max_num_inputs=0, ignore_external_references=True)
    d = node.type().definition()
    d.setParmTemplateGroup(hda_parm_templates())
    node.removeSpareParms()
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
    obj = hou.node("/obj")
    obj.layoutChildren()
    sticky(PLAYGROUND_NOTE, (-12, 3), (9, 4.5))
    sticky(TEST_NOTE, (-12, -2.5), (9, 3.2))


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
    parts = []
    for i in range(n):
        parts.append(dict(fp=fp[i], fo=fo[i], sp=sp_[i], parent=par[i], type=ty[i], len=ln[i],
                          ext=ex[i], pa=pa[i], pb=pb[i], drive=drv[i]))
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
        if p["parent"] >= 0:
            par = parts[p["parent"]]
            off = (p["pa"], p["pb"], 0.0) if p["type"] == "offset" else (0.0, 0.0, 0.0)
            expect = tuple(a + b for a, b in zip(par["sp"], qrot(par["fo"], off)))
            worst = max(worst, vlen(vsub(p["fp"], expect)))
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
    for label, recipe in [("%s %s" % (k, t_), r) for k, t_, r in PRESETS] + variants:
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
        m.node("copy_parts").geometryAtFrame(1)
        sop_err = m.node("copy_parts").errors() or m.node("socket_solver").errors()
        c.check(worst < 1e-4 and not sop_err, "動く: " + label,
                "パーツ %d 個, ソケット契約のずれ最大 %.1e, 先端の移動 最大 %.2f" % (len(first), worst, moved))

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

    # ギャラリー: 20 本を 1 枚ずつ撮って 5 × 4 に並べる
    tile, cols = (384, 256), 5
    sheet = Image.new("RGB", (tile[0] * cols, (tile[1] + 34) * 4), (236, 238, 242))
    try:
        from PIL import ImageDraw, ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 19)
    except Exception:
        font = None
    for i, (key, title, _) in enumerate(PRESETS):
        pth = "/obj/preset%s" % key
        cc, dd = fit([pth], span, tile[0] / float(tile[1]), margin=1.05)
        shoot("_tile", tile, cc, dd, 24, 50, pth + ground, frame=37)
        img = Image.open(IMG_DIR + "/_tile.png")
        x, y = (i % cols) * tile[0], (i // cols) * (tile[1] + 34)
        sheet.paste(img, (x, y + 34))
        if font is not None:
            ImageDraw.Draw(sheet).text((x + 10, y + 5), "%s  %s" % (key, title), fill=(40, 42, 48), font=font)
    sheet.save(IMG_DIR + "/gallery.png")
    os.remove(IMG_DIR + "/_tile.png")
    print("image: gallery")
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
    if "render" in sys.argv[1:]:
        render_docs()
    print("verify fails:", fails)


if __name__ == "__main__":
    main()
