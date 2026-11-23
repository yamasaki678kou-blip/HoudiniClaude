# recipe_parser v1.2 - Python SOP
# レシピ文字列を読んで、パーツ 1 個 = 点 1 個 にします。親 → 子の順に点を並べ、親子を線でつなぎます。
#
# v1.2（回転モーター系 5 種の仕様 v0.5 §9.1）で増えたこと:
#   - リスト   ratio=[1,-0.8,0.5]     （括弧の深さを見ながら分割する）
#   - 文字列   form=disc / output=carrier
#   - 名前付きキー（パーツごとに「読む」と宣言したものだけ。それ以外は警告）
#   - 回転系 5 種（coax / planetary / gimbal / crank / turbine）を原始パーツの列に分解（desugar）
#   - パーツ数の内訳（80% で警告、256 でエラー）、形のバリアント数（16 で警告、32 でエラー）
# リストと文字列はここで使い切り、点の属性にはしません（形を決めるものは geo_id にたたむ）。
import math
import re

node = hou.pwd()
geo = node.geometry()
geo.clear()

recipe = node.evalParm("recipe")
global_speed = node.evalParm("global_speed")

# ---------------------------------------------------------------------------
# 原始パーツ（Phase1）と、分解の中だけで使う内部パーツ
# ---------------------------------------------------------------------------
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
    "offset": dict(pa=2.0, pb=0.0),  # 横ずれは rad 単位（元の 0.3 = 根の太さ 0.15 の 2 倍）
    "bent": dict(pa=30.0, pb=0.0),
    "splitter": dict(pa=2.0, pb=45.0, pc=0.0),
    "gripper": dict(len=0.3, pa=25.0, pb=0.0),
    "wheel": dict(len=0.2, pa=1.0),
    "foot": dict(len=0.2),
    "drill": dict(len=0.4, pa=1.0),
    "head": dict(len=0.3, pa=30.0, pb=10.0, pc=1.0),
    "cap": dict(len=0.15),
    # 内部パーツ（レシピには書けない）
    "branch": dict(len=0.0),
    "restore": dict(len=0.0),
    "gimbal_frame": dict(len=0.0),
    "crank_rod": dict(len=0.0),
    "crank_slider": dict(len=0.0),
}
INTERNAL_ONLY = set(["branch", "restore", "gimbal_frame", "crank_rod", "crank_slider"])
NO_GEO = set(["branch", "restore"])

# 回転系 5 種: 「読む」と宣言したキーと既定値。型は 'f' 数値 / 'l' リスト / 's' 文字列 / 'fl' 数値かリスト / 'sl' 文字列かリスト
ROTARY = {
    "coax": {  # R-01 同軸スタックローター
        "layers": ("f", 3), "ratio": ("fl", None), "ratio_list": ("l", None), "phase_list": ("l", None),
        "layer_gap": ("fl", 0.35), "radius_step": ("f", 0.85), "form": ("sl", "disc"),
        "geo_form": ("sl", None), "geo_form_list": ("l", None), "form_list": ("l", None),
        "disc_holes": ("f", 6), "spoke_count": ("f", 5), "teeth": ("f", 24), "blade_count": ("f", 4),
        "twist_root": ("f", 40.0), "twist_tip": ("f", 15.0), "stack_mode": ("s", "cumulative"),
        "mesh": ("f", 0), "curve": ("f", -1),
    },
    "turbine": {  # R-05 タービンローター
        "blade_count": ("f", 5), "blade_len": ("f", 3.5), "width": ("fl", None), "width_curve": ("l", None),
        "twist_root": ("f", 40.0), "twist_tip": ("f", 15.0), "sweep": ("f", 0.0), "lean": ("f", 0.0),
        "section_form": ("s", "sym"), "curve": ("f", 0), "pitch_anim": ("f", 0.0), "hub_form": ("s", "spinner"),
        "hub_r": ("f", 1.0), "hub_h": ("f", 1.2), "shroud": ("f", 0), "shroud_gap": ("f", 0.3),
    },
    "gimbal": {  # R-03 ジンバルローター
        "mode": ("s", "follow"), "axis_order": ("s", "zxy"), "axis_enable": ("fl", None),
        "angle_list": ("l", None), "freq_list": ("l", None), "phase_list": ("l", None),
        "frame_form_list": ("sl", None), "frame_form": ("s", "ring"), "tube_rad": ("f", 0.18),
        "payload_form": ("s", "socket"), "target": ("fl", None), "hold": ("l", None),
    },
    "crank": {  # R-04 クランク＆偏心ローター
        "eccentric": ("f", 0.8), "rod_len": ("f", 3.0), "guide_offset": ("f", 0.0), "output_axis": ("f", 2),
        "pin_count": ("f", 1), "pin_phase_list": ("l", None), "wheel_form": ("s", "spoke"),
        "spoke_count": ("f", 5), "counterweight": ("f", 1), "hole_pattern": ("f", 0),
    },
    "planetary": {  # R-02 遊星ギアモーター
        "module": ("f", 0.2), "sun_teeth": ("f", 12), "planet_teeth": ("f", 0), "planet_count": ("f", 3),
        "output": ("s", "carrier"), "tooth_profile": ("f", 1), "helical_angle": ("f", 0.0),
        "housing_window": ("f", 4), "carrier_form": ("s", "tri"), "thickness": ("f", 1.0),
        "housing_curve": ("f", -1),
    },
}
ALIASES = {"mrot": "motor_rot", "mosc": "motor_osc", "uni": "universal",
           "slide": "prismatic", "endcap": "cap",
           "coax_stack": "coax", "stack": "coax", "planet": "planetary", "planetary_gear": "planetary",
           "gimbal_rotor": "gimbal", "crank_rotor": "crank", "eccentric_rotor": "crank",
           "fan": "turbine", "propeller": "turbine", "prop": "turbine"}
SLOT_ALIAS = {"a": "pa", "b": "pb", "c": "pc", "d": "pd"}  # レシピは a〜d、内部は pa〜pd（pa〜pd も既知キー）
COMMON = dict(len=1.0, axis=2, speed=1.0, phase=0.0, drive=0, ratio=1.0,
              join=0, limit_min=-180.0, limit_max=180.0, seed=0)
ROOT_RAD = 0.15
MAX_PARTS = 256
WARN_PARTS = int(MAX_PARTS * 0.8)   # 205
MAX_VARIANTS = 32
WARN_VARIANTS = 16
SCALE_MODE = {"link": 1, "offset": 1, "bent": 1, "prismatic": 1, "piston": 1}
TAGS = {"motor_rot": "motor_rotary", "motor_osc": "motor_osc", "servo": "servo",
        "hinge": "joint_hinge", "ball": "joint_ball", "universal": "joint_universal",
        "prismatic": "joint_slide", "twist": "joint_twist", "spring": "joint_spring",
        "gripper": "effector_gripper", "wheel": "effector_wheel",
        "drill": "effector_tool", "head": "effector_head",
        "coax": "rotor_coax", "planetary": "rotor_planetary", "gimbal": "rotor_gimbal",
        "crank": "rotor_crank", "turbine": "rotor_turbine"}
VALID_KEYS = set(COMMON) | set(["rad", "pa", "pb", "pc", "pd"])
AXIS_NAMES = {"x": 0, "y": 1, "z": 2}


def fail(msg):
    raise hou.NodeError(msg)


warnings = []


def warn(msg):
    warnings.append(msg)


# ---------------------------------------------------------------------------
# 1. 字句: > [ ] | と「パーツ名(...)」。( ) の中は括弧の深さを数えて 1 個のトークンにする
# ---------------------------------------------------------------------------
def tokenize(s):
    toks, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch in ">[]|":
            toks.append(ch)
            i += 1
            continue
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", s[i:])
        if not m:
            fail("parse error / 読めない文字があります: %r" % s[i:i + 20])
        j = i + m.end()
        while j < n and s[j].isspace():
            j += 1
        if j < n and s[j] == "(":
            depth, k = 0, j
            while k < n:
                if s[k] == "(":
                    depth += 1
                elif s[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if depth != 0:
                fail("parse error / ( が閉じていません: %s" % s[i:i + 30])
            toks.append(s[i:i + m.end()] + s[j:k + 1])
            i = k + 1
        else:
            toks.append(m.group(0))
            i = j
    return toks


def split_top(text):
    """カンマで区切る。ただし [ ] の中のカンマでは区切らない（v1.2 の分割器）"""
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth < 0:
                fail("bad list / ] が多すぎます: %s" % text)
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if depth != 0:
        fail("bad list / [ が閉じていません: %s" % text)
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def to_scalar(v):
    try:
        return float(v)
    except ValueError:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_\-]*$", v):
            return v
        fail("bad value / 数値でも名前でもありません: %s" % v)


def parse_value(v):
    v = v.strip()
    if v.startswith("["):
        if not v.endswith("]"):
            fail("bad list / [ ] の形にしてください: %s" % v)
        return [to_scalar(x) for x in split_top(v[1:-1])]
    if v == "":
        fail("bad value / 値が空です")
    return to_scalar(v)


def parse_part_token(tok):
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\((.*)\))?$", tok, re.S)
    raw = m.group(1)
    name = ALIASES.get(raw, raw)
    if (name not in DEFAULTS and name not in ROTARY) or name in INTERNAL_ONLY:
        fail("unknown part / 知らないパーツ名です: %s" % raw)
    declared = ROTARY.get(name, {})
    explicit, opts = {}, {}
    if m.group(2):
        for kv in split_top(m.group(2)):
            if kv.count("=") < 1:
                fail("bad parameter / 「名前=値」の形で書いてください: %s(%s)" % (name, kv))
            k, v = kv.split("=", 1)
            k = SLOT_ALIAS.get(k.strip(), k.strip())
            if not v.strip():
                fail("bad value / 数値ではありません: %s(%s)" % (name, kv))
            val = parse_value(v)
            if k in declared:
                kind = declared[k][0]
                if isinstance(val, list) and "l" not in kind:
                    fail("%s の %s にはリストは書けません" % (name, k))
                if isinstance(val, str) and "s" not in kind:
                    fail("bad value / 数値ではありません: %s(%s)" % (name, kv))
                opts[k] = val
            elif k in VALID_KEYS:
                if isinstance(val, (list, str)):
                    fail("bad value / 数値ではありません: %s(%s)" % (name, kv))
                explicit[k] = val
            else:
                warn("unknown key / 使われないキーです: %s(%s)" % (name, k))
    return name, explicit, opts


# ---------------------------------------------------------------------------
# 2. パーツの登録
# ---------------------------------------------------------------------------
parts = []          # dict(name, params, parent, depth, internal, geo_id, geo, flags, origin)
origin_labels = []  # レシピに書いた順のパーツ名（上限エラーの内訳用）
current_origin = [-1]


def add_part(name, explicit, parent, internal=0, geo_id="", geo_attrs=None, housing=0, rotor=0,
             shaft=0, at_socket=0, hidden=False, aux=(0.0, 0.0, 0.0)):
    if len(parts) >= MAX_PARTS:
        counts = {}
        for p in parts:
            counts[p["origin"]] = counts.get(p["origin"], 0) + 1
        detail = ", ".join("%s: %d 個" % (origin_labels[o] if o >= 0 else "?", c)
                           for o, c in sorted(counts.items(), key=lambda kv: -kv[1])[:8])
        fail("too many parts / パーツは %d 個までです（分解後に数えます）。内訳: %s" % (MAX_PARTS, detail))
    prm = dict(COMMON)
    prm.update(DEFAULTS.get(name, {}))
    explicit = dict(explicit)
    if "rad" in explicit:
        prm["rad"] = explicit.pop("rad")
    elif parent >= 0:
        prm["rad"] = parts[parent]["params"]["rad"]
    else:
        prm["rad"] = ROOT_RAD
    prm.update(explicit)
    depth = 0 if parent < 0 else parts[parent]["depth"] + 1
    parts.append(dict(name=name, params=prm, parent=parent, depth=depth, internal=internal,
                      geo_id=geo_id, geo=geo_attrs or {}, housing=housing, rotor=rotor, shaft=shaft,
                      at_socket=at_socket, hidden=hidden or name in NO_GEO, aux=aux,
                      origin=current_origin[0]))
    return len(parts) - 1


def fnum(x):
    """geo_id 用の数値の書き方（決定論的: 同じ値なら同じ文字列）"""
    x = round(float(x), 3)
    if abs(x - round(x)) < 1e-9:
        s = "%d" % int(round(x))
    else:
        s = ("%.3f" % x).rstrip("0").rstrip(".")
    return s.replace("-", "m").replace(".", "p")


def opt(opts, name, key, idx=None):
    v = opts.get(key)
    if v is None:
        v = ROTARY[name][key][1]
    return v


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def nums(v, name, key):
    out = []
    for x in as_list(v):
        if isinstance(x, str):
            fail("%s の %s は数値のリストにしてください: %s" % (name, key, x))
        out.append(float(x))
    return out


def extend(lst, n, rule):
    lst = list(lst)
    while len(lst) < n:
        lst.append(rule(len(lst), lst))
    return lst[:n]


# ---------------------------------------------------------------------------
# 3. desugar（回転系 5 種を原始パーツの列にする）。戻り値 = 本線が続くパーツの番号
# ---------------------------------------------------------------------------
LAYER_FORMS = ("disc", "ring", "gear", "blades", "cage", "mesh")


def layer_geo(form, opts):
    """R-01 の 1 層ぶんの形。geo_id は形 + 形を決める数値だけ（rad と位相は入れない）"""
    if form not in LAYER_FORMS:
        fail("coax の form は %s のどれかです: %s" % (" / ".join(LAYER_FORMS), form))
    if form == "disc":
        h = int(opt(opts, "coax", "disc_holes"))
        return "layer_disc_h%d" % h, {"holes": h}
    if form == "ring":
        s = int(opt(opts, "coax", "spoke_count"))
        return "layer_ring_s%d" % s, {"spokes": s}
    if form == "gear":
        z = int(opt(opts, "coax", "teeth"))
        if z < 6:
            fail("coax の teeth は 6 以上にしてください")
        return "layer_gear_z%d" % z, {"teeth": z}
    if form == "blades":
        n = int(opt(opts, "coax", "blade_count"))
        tr, tt = float(opt(opts, "coax", "twist_root")), float(opt(opts, "coax", "twist_tip"))
        cv = int(opt(opts, "coax", "curve"))
        gid = "layer_blades_n%d_tr%s_tt%s" % (n, fnum(tr), fnum(tt)) + ("_c%d" % cv if cv >= 0 else "")
        return gid, {"blade_count": n, "twist_root": tr, "twist_tip": tt, "curve": cv}
    if form == "cage":
        b = int(opt(opts, "coax", "spoke_count")) + 3
        return "layer_cage_b%d" % b, {"bars": b}
    k = int(opt(opts, "coax", "mesh"))
    return "layer_mesh_k%d" % k, {"mesh": k}


def desugar_coax(prm, opts, parent):
    n = int(opt(opts, "coax", "layers"))
    if n < 1 or n > 16:
        fail("coax の layers は 1〜16 です（%d）" % n)
    ratios = nums(opts.get("ratio_list", opts.get("ratio")), "coax", "ratio")
    ratios = extend(ratios, n, lambda i, l: (-1.0) ** i * (1.0 + 0.4 * i))  # 足りない層は「別速度」になる既定
    phases = extend(nums(opts.get("phase_list"), "coax", "phase_list"), n, lambda i, l: 0.0)
    gaps = extend(nums(opt(opts, "coax", "layer_gap"), "coax", "layer_gap"), n, lambda i, l: l[-1] if l else 0.35)
    forms = as_list(opts.get("form_list") or opts.get("geo_form_list") or opts.get("geo_form") or opt(opts, "coax", "form"))
    forms = extend([str(f) for f in forms], n, lambda i, l: l[-1])
    step = float(opt(opts, "coax", "radius_step"))
    mode = opt(opts, "coax", "stack_mode")
    mode = {"0": "cumulative", "1": "independent"}.get(str(mode).split(".")[0], str(mode))
    if mode not in ("cumulative", "independent"):
        fail("coax の stack_mode は cumulative / independent（0 / 1）です: %s" % mode)
    rad0 = prm["rad"]
    sp, ph = prm["speed"], prm["phase"]
    last, prev_r, prev_p = parent, 0.0, 0.0
    for i in range(n):
        gid, g = layer_geo(forms[i], opts)
        if mode == "cumulative":
            lsp, lph = sp * ratios[i], ph + phases[i]
        else:
            # independent: 全層が同じ Z 軸まわりなので回転は可換。
            # 「親の回転を打ち消して自前の回転を足す」= 速さと位相の差分で 1 個の motor_rot にまとまる
            lsp, lph = sp * (ratios[i] - prev_r), (ph + phases[i]) - prev_p
            prev_r, prev_p = ratios[i], ph + phases[i]
        last = add_part("motor_rot", dict(len=gaps[i], speed=lsp, phase=lph, axis=2, pa=1.0,
                                          rad=rad0 * step ** i), last,
                        geo_id=gid, geo_attrs=g, housing=1, rotor=1, shaft=1)
    # 復元ノード: desugar が変えた rad を、出力ソケットで元に戻す（仕様 §0.2）
    return add_part("restore", dict(len=0.0, rad=rad0), last)


def desugar_turbine(prm, opts, parent, explicit):
    n = int(opt(opts, "turbine", "blade_count"))
    if n < 1 or n > 24:
        fail("turbine の blade_count は 1〜24 です")
    widths = nums(opts.get("width_curve", opts.get("width")), "turbine", "width") or [1.0, 0.5]
    widths = extend(widths, 2, lambda i, l: l[-1])[:3] if len(widths) < 3 else widths[:3]
    blen = float(opt(opts, "turbine", "blade_len"))
    tr, tt = float(opt(opts, "turbine", "twist_root")), float(opt(opts, "turbine", "twist_tip"))
    sw, le = float(opt(opts, "turbine", "sweep")), float(opt(opts, "turbine", "lean"))
    sec = str(opt(opts, "turbine", "section_form"))
    if sec not in ("flat", "sym", "camber", "curve"):
        fail("turbine の section_form は flat / sym / camber / curve です: %s" % sec)
    hub = str(opt(opts, "turbine", "hub_form"))
    if hub not in ("cyl", "sphere", "spinner"):
        fail("turbine の hub_form は cyl / sphere / spinner です: %s" % hub)
    hub_r, hub_h = float(opt(opts, "turbine", "hub_r")), float(opt(opts, "turbine", "hub_h"))
    shroud, gap = int(opt(opts, "turbine", "shroud")), float(opt(opts, "turbine", "shroud_gap"))
    cv = int(opt(opts, "turbine", "curve"))
    pitch = float(opt(opts, "turbine", "pitch_anim"))
    if n % 2 == 0:
        warn("turbine: blade_count は奇数がおすすめです（偶数は見た目が単調になりがち。機能の制約ではありません）")
    gid = "turbine_%s_n%d_l%s_w%s_tr%s_tt%s_sw%s_le%s_%s_hr%s_hh%s_sh%d" % (
        hub, n, fnum(blen), "-".join(fnum(w) for w in widths), fnum(tr), fnum(tt), fnum(sw), fnum(le),
        sec + (str(cv) if sec == "curve" else ""), fnum(hub_r), fnum(hub_h), shroud)
    if shroud:
        gid += "_g%s" % fnum(gap)
    g = {"blade_count": n, "blade_len": blen, "twist_root": tr, "twist_tip": tt, "sweep": sw, "lean": le,
         "hub_r": hub_r, "hub_h": hub_h, "shroud": shroud, "shroud_gap": gap, "curve": cv,
         "pitch_anim": pitch, "nwidth": len(widths)}
    for i, w in enumerate(widths):
        g["width%d" % i] = w
    hub_len = max(hub_h, 1.0) + (1.6 * hub_r if hub == "spinner" else 0.0)
    ln = explicit.get("len", hub_len * prm["rad"])
    return add_part("motor_rot", dict(len=ln, speed=prm["speed"], phase=prm["phase"], axis=2, pa=1.0), parent,
                    geo_id=gid, geo_attrs=g, housing=1, rotor=1)


GIMBAL_R = (3.2, 2.6, 2.0)   # 外・中・内のリング半径（rad 単位）


def desugar_gimbal(prm, opts, parent):
    order = str(opt(opts, "gimbal", "axis_order")).lower()
    if len(order) != 3 or sorted(order) != ["x", "y", "z"]:
        fail("gimbal の axis_order は x / y / z の並び替え（例 zxy）です: %s" % order)
    axes = [AXIS_NAMES[c] for c in order]
    mode = str(opt(opts, "gimbal", "mode"))
    mode = {"0": "follow", "1": "stabilize", "2": "track"}.get(mode.split(".")[0], mode)
    if mode not in ("follow", "stabilize", "track"):
        fail("gimbal の mode は follow / stabilize / track です: %s" % mode)
    en = opts.get("axis_enable")
    if en is None:
        enable = [1, 1, 1]
    elif isinstance(en, list):
        enable = extend([int(x) for x in nums(en, "gimbal", "axis_enable")], 3, lambda i, l: 1)
    else:
        bits = int(en)
        enable = [(bits >> k) & 1 for k in range(3)]
    amps = extend(nums(opts.get("angle_list"), "gimbal", "angle_list"), 3, lambda i, l: [30.0, 25.0, 20.0][i])
    freqs = extend(nums(opts.get("freq_list"), "gimbal", "freq_list"), 3, lambda i, l: [1.0, 1.3, 0.7][i])
    phs = extend(nums(opts.get("phase_list"), "gimbal", "phase_list"), 3, lambda i, l: [0.0, 90.0, 180.0][i])
    forms = as_list(opts.get("frame_form_list") or opt(opts, "gimbal", "frame_form"))
    forms = extend([str(f) for f in forms], 3, lambda i, l: l[-1])
    for f in forms:
        if f not in ("ring", "square", "u"):
            fail("gimbal の frame_form は ring / square / u です: %s" % f)
    tube = float(opt(opts, "gimbal", "tube_rad"))
    pay = str(opt(opts, "gimbal", "payload_form"))
    if pay not in ("plate", "sphere", "socket"):
        fail("gimbal の payload_form は plate / sphere / socket です: %s" % pay)
    tgt = opts.get("target")
    tindex, tvec = -1.0, (0.0, 0.0, 0.0)
    if isinstance(tgt, list):
        v = extend(nums(tgt, "gimbal", "target"), 3, lambda i, l: 0.0)
        tvec = (v[0], v[1], v[2])
    elif tgt is not None:
        tindex = float(int(tgt))
    if mode == "track" and tgt is None:
        tindex = 0.0
    hold = extend(nums(opts.get("hold"), "gimbal", "hold"), 3, lambda i, l: 0.0)
    if mode == "stabilize":
        tvec = (hold[0], hold[1], hold[2])
    if mode == "stabilize" and sum(enable) < 3:
        warn("gimbal: stabilize で無効な軸があります。無効な軸は follow のまま（成り行き）になります")
    mode_i = {"follow": 0, "stabilize": 1, "track": 2}[mode]
    zc = GIMBAL_R[0] + 0.9
    mount = add_part("fixed", dict(len=zc * prm["rad"]), parent,
                     geo_id="gmount_a%d_t%s" % (axes[0], fnum(tube)), geo_attrs={"axis0": axes[0], "tube": tube},
                     housing=1)
    last = mount
    for k in range(3):
        plane = axes[k + 1] if k < 2 else axes[0]   # リングの面 = 自分の軸と、1 つ内側の軸（内リングは残りの軸）
        gid = "gring_%s_l%d_a%d_p%d_t%s" % (forms[k], k, axes[k], plane, fnum(tube))
        last = add_part("gimbal_frame", dict(len=0.0, axis=axes[k], pa=amps[k], pb=freqs[k], pc=float(enable[k]),
                                             pd=float(k), speed=prm["speed"], phase=prm["phase"] + phs[k]),
                        last, geo_id=gid, geo_attrs={"level": k, "axis": axes[k], "plane": plane, "tube": tube},
                        rotor=1, aux=tvec)
        parts[last]["pe"] = float(mode_i)
        parts[last]["pf"] = tindex
    payload = add_part("fixed", dict(len=0.0), last,
                       geo_id="gpay_%s_p%d_t%s" % (pay, axes[0], fnum(tube)),
                       geo_attrs={"plane": axes[0], "tube": tube}, housing=1)
    return payload


def desugar_crank(prm, opts, parent, explicit):
    r = float(opt(opts, "crank", "eccentric"))
    L = float(opt(opts, "crank", "rod_len"))
    c = float(opt(opts, "crank", "guide_offset"))
    if r <= 0 or L <= r:
        fail("crank: rod_len は eccentric より長くしてください（eccentric=%g, rod_len=%g）" % (r, L))
    if abs(c) >= L - r:
        fail("crank: guide_offset は rod_len − eccentric より小さくしてください（成立条件 c < L − r: c=%g, L−r=%g）"
             % (c, L - r))
    ax = int(opt(opts, "crank", "output_axis"))
    if ax not in (1, 2):
        warn("crank: output_axis は 1（Y）か 2（Z）です。2 として扱います")
        ax = 2
    base_beta = 0.0 if ax == 2 else -90.0   # Z から X 軸まわりに -90° 回すと +Y
    npin = int(opt(opts, "crank", "pin_count"))
    if npin < 1 or npin > 6:
        fail("crank の pin_count は 1〜6 です")
    pph = extend(nums(opts.get("pin_phase_list"), "crank", "pin_phase_list"), npin,
                 lambda i, l: 360.0 * i / npin)
    spokes = int(opt(opts, "crank", "spoke_count"))
    cw = int(opt(opts, "crank", "counterweight"))
    holes = int(opt(opts, "crank", "hole_pattern"))
    form = str(opt(opts, "crank", "wheel_form"))
    if form not in ("disc", "spoke"):
        fail("crank の wheel_form は disc / spoke です: %s" % form)
    wheel_r = max(r * 1.5, r + 1.0)
    rel = [((p - pph[0]) % 360.0) for p in pph]   # ピン同士の角度差は「形」なので geo_id に入れる
    zc = wheel_r + 0.8
    base = add_part("fixed", dict(len=zc * prm["rad"]), parent,
                    geo_id="crbase_w%s" % fnum(wheel_r), geo_attrs={"wheel_r": wheel_r, "zc": zc}, housing=1)
    wid = "crwheel_%s_r%s_w%s_s%d_cw%d_h%d_p%s" % (form, fnum(r), fnum(wheel_r), spokes, cw, holes,
                                                  "-".join(fnum(x) for x in rel))
    wg = {"ecc": r, "wheel_r": wheel_r, "spokes": spokes, "cw": cw, "holes": holes, "npin": npin,
          "disc": 1 if form == "disc" else 0}
    for k, x in enumerate(rel):
        wg["pin%d" % k] = x
    if int(prm.get("pd", 0)) == 1:
        # d=1: 上流の駆動角をそのまま回転に使う（hinge の駆動消費と同じ）
        wheel = add_part("hinge", dict(len=0.0, axis=0, pd=1.0, phase=0.0), base, internal=1,
                         geo_id=wid, geo_attrs=wg, rotor=1)
    else:
        wheel = add_part("motor_rot", dict(len=0.0, axis=0, speed=prm["speed"], phase=prm["phase"] + pph[0], pa=1.0),
                         base, internal=1, geo_id=wid, geo_attrs=wg, rotor=1)
    x_min = math.sqrt((L - r) ** 2 - c * c)
    x_max = math.sqrt((L + r) ** 2 - c * c)
    for k in range(npin):
        beta = base_beta + 360.0 * k / npin   # ピン k のガイドの向き（2 ピンなら向かい合わせ = 水平対向）
        rid = add_part("crank_rod", dict(len=L * prm["rad"], pa=r, pb=L, pc=c, pd=rel[k], axis=0), wheel, internal=1,
                       geo_id="crrod_L%s" % fnum(L), geo_attrs={"L": L}, rotor=1)
        parts[rid]["pe"] = beta
    sid = "crslide_x%s_y%s_c%s" % (fnum(x_min), fnum(x_max), fnum(c))
    sg = {"x_min": x_min, "x_max": x_max, "c": c}
    main = None
    for k in list(range(1, npin)) + [0]:     # 本線（ピン 0 のスライダ）は最後に作る
        beta = base_beta + 360.0 * k / npin
        s = add_part("crank_slider", dict(len=x_min * prm["rad"], pa=r, pb=L, pc=c, pd=rel[k], axis=0), base,
                     internal=0 if k == 0 else 1, geo_id=sid, geo_attrs=sg, housing=1, rotor=1, at_socket=1)
        parts[s]["pe"] = beta
        parts[s]["pf"] = float(wheel)          # 回転角は車輪（wheel）の駆動角を読む
        if k == 0:
            main = s
    return main


def gear_ok(S, P, N):
    return (2 * P + 2 * S) % N == 0


def desugar_planetary(prm, opts, parent):
    m = float(opt(opts, "planetary", "module"))
    S = int(opt(opts, "planetary", "sun_teeth"))
    P = int(opt(opts, "planetary", "planet_teeth"))
    N = int(opt(opts, "planetary", "planet_count"))
    if S < 6 or N < 1 or N > 8:
        fail("planetary: sun_teeth は 6 以上、planet_count は 1〜8 です")
    asked = P
    if P <= 0:
        P = S
    if not gear_ok(S, P, N):
        for d in (1, -1, 2, -2):
            if P + d >= 6 and gear_ok(S, P + d, N):
                P = P + d
                break
    if not gear_ok(S, P, N):
        fail("planetary: 遊星 %d 個を等間隔に置ける歯数が見つかりません（S=%d, P=%d）。sun_teeth か planet_count を変えてください"
             % (N, S, P))
    if asked > 0 and P != asked:
        warn("planetary: 等間隔に置くため planet_teeth を %d → %d に変えました（(R+S) が遊星数で割り切れる条件）" % (asked, P))
    R = 2 * P + S
    # 遊星どうしが重ならないか（外径で判定）
    a = m * (S + P) / 2.0
    if N > 1 and 2 * a * math.sin(math.pi / N) <= m * (P + 2) * 1.02:
        fail("planetary: 遊星 %d 個では隣どうしがぶつかります。planet_count を減らすか sun_teeth を増やしてください" % N)
    out = str(opt(opts, "planetary", "output"))
    if out not in ("carrier", "ring", "sun"):
        fail("planetary の output は carrier / ring / sun です: %s" % out)
    prof = int(opt(opts, "planetary", "tooth_profile"))
    hel = float(opt(opts, "planetary", "helical_angle"))
    win = int(opt(opts, "planetary", "housing_window"))
    cform = str(opt(opts, "planetary", "carrier_form"))
    if cform not in ("tri", "cross", "disc"):
        fail("planetary の carrier_form は tri / cross / disc です: %s" % cform)
    t = float(opt(opts, "planetary", "thickness"))
    hcurve = int(opt(opts, "planetary", "housing_curve"))
    sp, ph = prm["speed"], prm["phase"]
    k_c = float(S) / float(R + S)                          # キャリア / 太陽（リング固定）
    theta_m = 180.0 / S if P % 2 == 1 else 0.0             # P が奇数の時はリングと合わせるため太陽を半ピッチずらす
    if out == "ring":
        sp_c, ph_c = 0.0, 0.0                              # リング出力: キャリア固定に組み替える
        sp_r, ph_r = -sp * S / float(R), -ph * S / float(R)
    else:
        sp_c, ph_c = sp * k_c, ph * k_c
        sp_r, ph_r = 0.0, 0.0
    sp_s, ph_s = sp, ph + theta_m
    gbase = {"module": m, "thick": t, "profile": prof, "helix": hel}

    def gear_id(kind, z, hand):
        return "pg%s_z%d_m%s_t%s_p%d_h%s" % (kind, z, fnum(m), fnum(t), prof, fnum(hel * hand))

    r_case = m * (R / 2.0 + 1.25) + 0.6 * m * 4 + 0.35
    base = add_part("fixed", dict(len=0.0), parent,
                    geo_id="pgcase_r%s_t%s_w%d_c%d" % (fnum(r_case), fnum(t), win, hcurve),
                    geo_attrs={"r_case": r_case, "thick": t, "windows": win, "curve": hcurve}, housing=1)
    ring = add_part("motor_rot", dict(len=0.0, speed=sp_r, phase=ph_r, pa=1.0), base, internal=0 if out == "ring" else 1,
                    geo_id=gear_id("ring", R, -1), geo_attrs=dict(gbase, teeth=R, internal=1, hand=-1), rotor=1)
    sun = add_part("motor_rot", dict(len=0.0, speed=sp_s, phase=ph_s, pa=1.0), base, internal=0 if out == "sun" else 1,
                   geo_id=gear_id("sun", S, 1), geo_attrs=dict(gbase, teeth=S, internal=0, hand=1), rotor=1)
    carrier = add_part("motor_rot", dict(len=0.0, speed=sp_c, phase=ph_c, pa=1.0), base,
                       internal=0 if out == "carrier" else 1,
                       geo_id="pgcarrier_%s_n%d_a%s_t%s" % (cform, N, fnum(a), fnum(t)),
                       geo_attrs={"n": N, "orbit": a, "thick": t, "form": {"tri": 0, "cross": 1, "disc": 2}[cform],
                                  "pr": m * (P / 2.0)}, rotor=1)
    sigma = ph_s - ph_c                                     # 1 フレーム目の太陽の相対角（キャリアから見て）
    rel_speed = -(float(S) / P) * (sp_s - sp_c)             # 遊星の自転（キャリアから見た角速度）
    if out == "ring":
        sigma = ph_s
    for i in range(N):
        beta = 360.0 * i / N
        off = add_part("offset", dict(len=0.0, pa=a * math.cos(math.radians(beta)),
                                      pb=a * math.sin(math.radians(beta))), carrier, internal=1, hidden=True)
        # 噛み合い位相は自転パーツの phase だけに入れる（形には焼かない、geo_id にも入れない）
        psi0 = beta * (1.0 + float(S) / P) + 180.0 - 180.0 / P - sigma * float(S) / P
        add_part("motor_rot", dict(len=0.0, speed=rel_speed, phase=psi0, pa=1.0), off, internal=1,
                 geo_id=gear_id("planet", P, -1), geo_attrs=dict(gbase, teeth=P, internal=0, hand=-1), rotor=1)
    member = {"carrier": carrier, "ring": ring, "sun": sun}[out]
    return add_part("fixed", dict(len=(t + 1.0) * prm["rad"]), member,
                    geo_id="pgshaft_t%s" % fnum(t), geo_attrs={"thick": t}, rotor=1)


DESUGAR = {"coax": desugar_coax, "turbine": desugar_turbine, "gimbal": desugar_gimbal,
           "crank": desugar_crank, "planetary": desugar_planetary}


# ---------------------------------------------------------------------------
# 4. 構文（splitter と枝は v1.1 のまま）
# ---------------------------------------------------------------------------
def place(name, explicit, opts, last):
    if name not in ROTARY:
        return add_part(name, explicit, last), add_part
    # 回転系: 自分の rad / speed / phase などを解決してから分解する
    prm = dict(COMMON)
    prm.update(explicit)
    prm["rad"] = explicit.get("rad", parts[last]["params"]["rad"] if last >= 0 else ROOT_RAD)
    if "rad" in explicit and last >= 0 and abs(explicit["rad"] - parts[last]["params"]["rad"]) > 1e-12:
        pass
    fn = DESUGAR[name]
    if name in ("turbine", "crank"):
        out = fn(prm, opts, last, explicit)
    else:
        out = fn(prm, opts, last)
    return out, None


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
        name, explicit, opts = parse_part_token(tok)
        origin_labels.append("%s(#%d)" % (name, len(origin_labels) + 1))
        current_origin[0] = len(origin_labels) - 1
        if name in ROTARY:
            idx, _ = place(name, explicit, opts, last)
            pos += 1
            last = idx
            continue
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
                fail("splitter(a=%d) なのに枝が %d 本あります" % (n, len(branch_ids)))
            for k, bidx in enumerate(branch_ids):
                parts[bidx]["params"]["pre_yaw"] = spread * (k - (n - 1) / 2.0)
            return pos, idx
        last = idx
    return pos, last


recipe = re.sub(r"#[^\n]*", "", recipe)
toks = tokenize(recipe)
if toks:
    end, _ = parse_chain(toks, 0, -1)
    if end < len(toks):
        fail("extra tokens / ここから先が読めません（splitter の後ろには続けられません）: %s"
             % " ".join(toks[end:end + 3]))
if not parts:
    add_part("base", {}, -1)

# パーツ数の警告（80%）と、形のバリアント数の上限
if len(parts) >= WARN_PARTS:
    counts = {}
    for p in parts:
        counts[p["origin"]] = counts.get(p["origin"], 0) + 1
    warn("parts / パーツが %d 個（上限 %d）。内訳: %s" % (len(parts), MAX_PARTS, ", ".join(
        "%s: %d 個" % (origin_labels[o] if o >= 0 else "?", c)
        for o, c in sorted(counts.items(), key=lambda kv: -kv[1])[:8])))
variants = sorted(set(p["geo_id"] for p in parts if p["geo_id"]))
if len(variants) > MAX_VARIANTS:
    fail("variants / 形の種類が %d 個あります（上限 %d）: %s" % (len(variants), MAX_VARIANTS, ", ".join(variants[:6])))
if len(variants) > WARN_VARIANTS:
    warn("variants / 形の種類が %d 個あります（%d を超えると重くなります）" % (len(variants), WARN_VARIANTS))

# ---------------------------------------------------------------------------
# 5. 属性を書く（所有権表 §4: ここで書いた属性を、ソルバ以降が読む）
# ---------------------------------------------------------------------------
geo.addAttrib(hou.attribType.Global, "global_speed", 1.0)
geo.setGlobalAttribValue("global_speed", float(global_speed))
for nm in ("part_type", "tag", "name", "geo_id"):
    geo.addAttrib(hou.attribType.Point, nm, "")
for nm, dv in [("parent_id", -1), ("order", 0), ("depth", 0), ("axis", 2),
               ("drive_mode", 0), ("join_mode", 0), ("scale_mode", 0), ("has_geo", 1),
               ("internal", 0), ("piece_housing", 0), ("piece_rotor", 0), ("shaft", 0), ("rotor_at_socket", 0)]:
    geo.addAttrib(hou.attribType.Point, nm, dv)
for nm in ("length", "radius", "speed", "phase", "ratio",
           "limit_min", "limit_max", "pa", "pb", "pc", "pd", "pe", "pf", "pre_yaw", "pre_pitch"):
    geo.addAttrib(hou.attribType.Point, nm, 0.0)
geo.addAttrib(hou.attribType.Point, "aux_vec", (0.0, 0.0, 0.0))
geo_keys = sorted(set(k for p in parts for k in p["geo"]))
for k in geo_keys:
    geo.addAttrib(hou.attribType.Point, "geo_" + k, 0.0)

points = []
for i, p in enumerate(parts):
    pt = geo.createPoint()
    prm = p["params"]
    pt.setAttribValue("part_type", p["name"])
    pt.setAttribValue("tag", TAGS.get(p["name"], ""))
    pt.setAttribValue("name", "part%d_%s" % (i, p["name"]))
    pt.setAttribValue("geo_id", p["geo_id"])
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
    pt.setAttribValue("scale_mode", 0 if p["geo_id"] else SCALE_MODE.get(p["name"], 0))
    pt.setAttribValue("has_geo", 0 if p["hidden"] else 1)
    pt.setAttribValue("internal", int(p["internal"]))
    pt.setAttribValue("piece_housing", int(p["housing"]))
    pt.setAttribValue("piece_rotor", int(p["rotor"]))
    pt.setAttribValue("shaft", int(p["shaft"]))
    pt.setAttribValue("rotor_at_socket", int(p["at_socket"]))
    for k in ("pa", "pb", "pc", "pd", "pre_yaw", "pre_pitch"):
        pt.setAttribValue(k, float(prm.get(k, 0.0)))
    pt.setAttribValue("pe", float(p.get("pe", 0.0)))
    pt.setAttribValue("pf", float(p.get("pf", 0.0)))
    pt.setAttribValue("aux_vec", tuple(float(x) for x in p["aux"]))
    for k, v in p["geo"].items():
        pt.setAttribValue("geo_" + k, float(v))
    points.append(pt)

for i, p in enumerate(parts):
    if p["parent"] >= 0:
        poly = geo.createPolygon(False)
        poly.addVertex(points[p["parent"]])
        poly.addVertex(points[i])

for msg in warnings:
    try:
        node.addWarning(msg)
    except Exception:
        pass
