# variant_builder - Python SOP
# 回転系パーツの「形のバリアント」を、geo_id ごとに 1 回だけ作ります（バリアント単位のループ）。
#   入力 1: パーサの出力（時間で変わらないので、ここは 1 回しか計算されない）
#   入力 2: 第2入力を読み分けたもの（断面カーブ sections / 差し替えメッシュ meshes）
# 各バリアントのパラメータは、同じ geo_id を持つ最初の点の geo_* 属性から読みます（仕様 §8）。
# 出力: piece = geo_id + "_housing" / "_rotor" / "_blade" のパック済みプリミティブ。
# 形はすべて「回転軸 = ローカル +Z、原点 = 入力ソケット、長さの単位 = 太さ rad」で作ります。
import math

node = hou.pwd()
geo = node.geometry()
geo.clear()
ins = node.inputs()
src = ins[0].geometry()
shapes = ins[1].geometry() if len(ins) > 1 and ins[1] is not None else None

TAU = 2.0 * math.pi
PA = math.radians(20.0)  # 圧力角


# ---------------------------------------------------------------------------
# 小さなメッシュ道具（点と面を貯めて、最後に hou.Geometry にする）
# ---------------------------------------------------------------------------
class Mesh(object):
    def __init__(self):
        self.P, self.C, self.F = [], [], []

    def pt(self, p, c):
        self.P.append((float(p[0]), float(p[1]), float(p[2])))
        self.C.append(c)
        return len(self.P) - 1

    def face(self, idx):
        self.F.append(tuple(idx))

    def to_geo(self):
        g = hou.Geometry()
        g.addAttrib(hou.attribType.Point, "Cd", (1.0, 1.0, 1.0))
        if not self.P:
            return g
        pts = g.createPoints(self.P)
        flat = []
        for c in self.C:
            flat.extend(c)
        g.setPointFloatAttribValues("Cd", flat)
        g.createPolygons([tuple(pts[i] for i in f) for f in self.F])
        return g


def xf(p, rot=None, t=(0.0, 0.0, 0.0)):
    x, y, z = p
    if rot is not None:
        a, b, c = rot  # 3 本の列ベクトル（ローカル x, y, z がどこへ行くか）
        x, y, z = (a[0] * p[0] + b[0] * p[1] + c[0] * p[2],
                   a[1] * p[0] + b[1] * p[1] + c[1] * p[2],
                   a[2] * p[0] + b[2] * p[1] + c[2] * p[2])
    return (x + t[0], y + t[1], z + t[2])


def strip(m, rings, col, closed=True, cap0=False, cap1=False):
    """同じ点数のリング（点列）を順につないで筒にする"""
    ids = [[m.pt(p, col) for p in r] for r in rings]
    n = len(rings[0])
    seg = n if closed else n - 1
    for a, b in zip(ids[:-1], ids[1:]):
        for i in range(seg):
            j = (i + 1) % n
            m.face((a[i], a[j], b[j], b[i]))
    if cap0:
        m.face(tuple(reversed(ids[0])))
    if cap1:
        m.face(tuple(ids[-1]))
    return ids


def circle(r, z, n, a0=0.0, a1=TAU, closed=True):
    cnt = n if closed else n + 1
    return [(r * math.cos(a0 + (a1 - a0) * i / n), r * math.sin(a0 + (a1 - a0) * i / n), z) for i in range(cnt)]


def cyl(m, r, z0, z1, col, n=24, rot=None, t=(0.0, 0.0, 0.0)):
    rings = [[xf(p, rot, t) for p in circle(r, z, n)] for z in (z0, z1)]
    strip(m, rings, col, cap0=True, cap1=True)


def cone(m, r0, r1, z0, z1, col, n=24, rot=None, t=(0.0, 0.0, 0.0)):
    rings = [[xf(p, rot, t) for p in circle(max(r, 1e-3), z, n)] for r, z in ((r0, z0), (r1, z1))]
    strip(m, rings, col, cap0=True, cap1=True)


def box(m, center, size, col, rot=None, t=(0.0, 0.0, 0.0)):
    cx, cy, cz = center
    sx, sy, sz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    c = [(cx + dx * sx, cy + dy * sy, cz + dz * sz) for dz in (-1, 1) for dy in (-1, 1) for dx in (-1, 1)]
    ids = [m.pt(xf(p, rot, t), col) for p in c]
    for f in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
        m.face(tuple(ids[i] for i in f))


def seg_box(m, p0, p1, w, h, col, up=(0.0, 0.0, 1.0)):
    """p0 → p1 の角棒（太さ w × h）"""
    d = [p1[i] - p0[i] for i in range(3)]
    L = math.sqrt(sum(x * x for x in d)) or 1e-6
    ex = [x / L for x in d]
    ey = cross(up, ex)
    if norm(ey) < 1e-6:
        ey = cross((1.0, 0.0, 0.0), ex)
    ey = unit(ey)
    ez = cross(ex, ey)
    mid = [(p0[i] + p1[i]) / 2.0 for i in range(3)]
    box(m, (0.0, 0.0, 0.0), (L, w, h), col, rot=(ex, ey, ez), t=mid)


def panel(m, r0, r1, a0, a1, z0, z1, col, segs=6):
    """円筒座標の曲がった板（r0〜r1, 角度 a0〜a1, 高さ z0〜z1）"""
    def ring(r, z):
        return [(r * math.cos(a0 + (a1 - a0) * i / segs), r * math.sin(a0 + (a1 - a0) * i / segs), z)
                for i in range(segs + 1)]
    loops = [ring(r1, z0), ring(r1, z1), ring(r0, z1), ring(r0, z0)]
    ids = [[m.pt(p, col) for p in l] for l in loops]
    for k in range(4):
        a, b = ids[k], ids[(k + 1) % 4]
        for i in range(segs):
            m.face((a[i], a[i + 1], b[i + 1], b[i]))
    m.face(tuple(ids[k][0] for k in range(4)))
    m.face(tuple(ids[k][segs] for k in reversed(range(4))))


def annulus(m, r0, r1, z0, z1, col, n=32):
    panel(m, r0, r1, 0.0, TAU, z0, z1, col, segs=n)


def torus(m, R, r, col, ex, ey, n_major=32, n_minor=10, t=(0.0, 0.0, 0.0)):
    ez = cross(ex, ey)
    rings = []
    for i in range(n_major):
        a = TAU * i / n_major
        c = [R * (math.cos(a) * ex[k] + math.sin(a) * ey[k]) for k in range(3)]
        rad = [math.cos(a) * ex[k] + math.sin(a) * ey[k] for k in range(3)]
        rings.append([tuple(t[k] + c[k] + r * (math.cos(TAU * j / n_minor) * rad[k] + math.sin(TAU * j / n_minor) * ez[k])
                            for k in range(3)) for j in range(n_minor)])
    rings.append(rings[0])
    ids = [[m.pt(p, col) for p in rr] for rr in rings[:-1]]
    ids.append(ids[0])
    for a, b in zip(ids[:-1], ids[1:]):
        for j in range(n_minor):
            jj = (j + 1) % n_minor
            m.face((a[j], b[j], b[jj], a[jj]))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(sum(x * x for x in a))


def unit(a):
    n = norm(a) or 1e-9
    return tuple(x / n for x in a)


AX = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def axis_rot(axis_index):
    """ローカル +Z を指定軸へ向ける回転（列ベクトル 3 本）"""
    if axis_index == 2:
        return AX
    if axis_index == 0:
        return ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
    return ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))


# ---------------------------------------------------------------------------
# 歯形（R-01 の gear 層と R-02 で共用。寸法はモジュール基準）
# テンプレートの約束: 歯の中心がローカル角度 0（+X）。内歯車も同じ。位相は焼かない。
# 噛み合う相手が分かっている時（R-02）は、相手の歯が通る場所を数値で調べて、そこにかかる分だけ歯を細くする。
# = 歯車を「相手の歯で削る」のと同じ考え方。歯先の逃がしと、歯数が少ない時の根元の切り下げ（アンダーカット）が自然にできる。
# ---------------------------------------------------------------------------
import numpy as np

FLANK = 10  # 歯面 1 本あたりの点の数 - 1


def inv(a):
    return np.tan(a) - a


class GearSpec(object):
    def __init__(self, z, m_, profile, internal=False):
        self.z, self.m, self.internal = int(z), float(m_), internal
        self.rp = self.z * self.m / 2.0
        self.tau = TAU / self.z
        rb = self.rp * math.cos(PA)
        tau, rp = self.tau, self.rp

        def hw_inv(rho):
            rc = np.maximum(rho, rb * 1.0001)
            return tau / 4.0 + inv(PA) - inv(np.arccos(rb / rc))

        if profile == 1:
            ext = hw_inv                      # インボリュート近似
        else:
            # 台形近似: インボリュートのピッチ円の点と歯先の点を結ぶ、まっすぐな歯面
            r_t = rp + self.m
            k = (hw_inv(r_t) - hw_inv(rp)) / (r_t - rp)
            h0 = hw_inv(rp)
            ext = lambda rho: h0 + (np.asarray(rho, dtype=float) - rp) * k
        if internal:
            self.r_root, self.r_tip = rp + 1.25 * self.m, rp - self.m
            self.hw = lambda rho: tau / 2.0 - ext(rho)   # 内歯車の歯 = 外歯車の歯溝の形
        else:
            self.r_root, self.r_tip = rp - 1.25 * self.m, rp + self.m
            self.hw = ext

    def radii(self):
        return [self.r_root + (self.r_tip - self.r_root) * i / FLANK for i in range(FLANK + 1)]

    def material(self, x, y):
        """点（この歯車の座標）が歯車の中身かどうか。numpy の配列で一度に調べる"""
        rho = np.hypot(x, y)
        d = np.abs((np.arctan2(y, x) + self.tau / 2.0) % self.tau - self.tau / 2.0)
        w = self.hw(np.clip(rho, min(self.r_root, self.r_tip), max(self.r_root, self.r_tip)))
        if self.internal:
            return (rho >= self.r_root) | ((rho >= self.r_tip) & (d <= w))
        return (rho <= self.r_root) | ((rho <= self.r_tip) & (d <= w))


def trim_against(A, B, a, kind, clear=0.04):
    """A の歯の半幅（半径ごと）を、噛み合っている間ずっと B にかからない大きさまで細くする。
    kind: 'ext' = 外歯車どうし（B の中心は (a, 0)）、'pr' = A が遊星で B がリング（B の中心は (-a, 0)）、
          'rp' = A がリングで B が遊星（B の中心は (a, 0)）。
    噛み合いの式は R-02 の位相計算と同じ（u_A + u_B = 1/2、内歯車は u_r - u_p = 1/2）。"""
    W = math.pi / 2.0 if kind == "pr" else math.asin(min(1.0, (B.r_tip + B.m) / a)) + A.tau
    step = A.tau / 40.0
    tA = np.arange(-W, W + step, step)
    uA = -np.degrees(tA) * A.z / 360.0
    if kind == "ext":
        tB, cx = np.radians(180.0 - (0.5 - uA) * 360.0 / B.z), a
    elif kind == "pr":
        tB, cx = np.radians(-(uA + 0.5) * 360.0 / B.z), -a
    else:
        tB, cx = np.radians(-(uA - 0.5) * 360.0 / B.z), a
    c, s = np.cos(-tB)[:, None], np.sin(-tB)[:, None]
    phis = np.arange(0.0, A.tau / 2.0, A.tau / 400.0)
    out = {}
    for rho in A.radii():
        blocked = np.zeros(len(phis), dtype=bool)
        for sgn in (1.0, -1.0):
            ang = sgn * phis[None, :] + tA[:, None]
            wx, wy = rho * np.cos(ang) - cx, rho * np.sin(ang)
            blocked |= B.material(wx * c - wy * s, wx * s + wy * c).any(axis=0)
        idx = np.nonzero(blocked)[0]
        allowed = float(phis[idx[0]]) if len(idx) else A.tau / 2.0
        out[rho] = min(float(A.hw(rho)), allowed - clear * A.m / rho)
    return out


def gear_outline(spec, hwmap=None):
    tau = spec.tau
    lo, hi = 0.03 * tau, 0.47 * tau
    rs = spec.radii()
    hw = [min(max(float(hwmap[r]) if hwmap else float(spec.hw(r)), lo), hi) for r in rs]
    pts = []
    for k in range(spec.z):
        c = k * tau
        for r, w in zip(rs, hw):
            pts.append((r * math.cos(c - w), r * math.sin(c - w)))
        for r, w in zip(reversed(rs), reversed(hw)):
            pts.append((r * math.cos(c + w), r * math.sin(c + w)))
        a = c + tau / 2.0
        pts.append((spec.r_root * math.cos(a), spec.r_root * math.sin(a)))
    return pts


def rotate2(p, a):
    return (p[0] * math.cos(a) - p[1] * math.sin(a), p[0] * math.sin(a) + p[1] * math.cos(a))


def ext_gear(m, spec, hwmap, thick, helix, col, z0=0.0, hand=1):
    out, rp, rt = gear_outline(spec, hwmap), spec.rp, spec.r_tip
    layers = 3 if abs(helix) > 1e-6 else 1
    tw = hand * thick * math.tan(math.radians(helix)) / rp if helix else 0.0
    rings = []
    for li in range(layers + 1):
        zz = z0 + thick * li / layers
        a = tw * li / layers
        rings.append([rotate2(p, a) + (zz,) for p in out])
    ids = strip(m, rings, col)
    for li, zz in ((0, z0), (layers, z0 + thick)):
        c = m.pt((0.0, 0.0, zz), col)
        ring = ids[li]
        n = len(ring)
        for i in range(n):
            j = (i + 1) % n
            m.face((c, ring[j], ring[i]) if li == 0 else (c, ring[i], ring[j]))
    return rp, rt


def int_gear(m, spec, hwmap, thick, helix, rim, col, z0=0.0, hand=-1):
    inner, rp = gear_outline(spec, hwmap), spec.rp
    r_out = spec.r_root + rim
    layers = 3 if abs(helix) > 1e-6 else 1
    tw = hand * thick * math.tan(math.radians(helix)) / rp if helix else 0.0
    rin, rout = [], []
    for li in range(layers + 1):
        zz = z0 + thick * li / layers
        a = tw * li / layers
        ring = [rotate2(p, a) + (zz,) for p in inner]
        rin.append(ring)
        rout.append([(r_out * math.cos(math.atan2(p[1], p[0])), r_out * math.sin(math.atan2(p[1], p[0])), p[2])
                     for p in ring])
    ii = strip(m, list(reversed(rin)), col)[::-1]   # 歯の面は内向きが表なので、下から上の順を逆にして張る
    oo = strip(m, rout, col)
    n = len(inner)
    for li in (0, layers):
        for i in range(n):
            j = (i + 1) % n
            f = (ii[li][i], ii[li][j], oo[li][j], oo[li][i])
            m.face(f if li == 0 else tuple(reversed(f)))
    return r_out


# ---------------------------------------------------------------------------
# ブレード（R-05 と R-01 の blades 層で共用）
# ---------------------------------------------------------------------------
def airfoil(form, n=14):
    """弦方向 x: 0〜1、厚み方向 y。閉じた点列（同じ点数）"""
    xs = [0.5 - 0.5 * math.cos(math.pi * i / (n - 1)) for i in range(n)]
    up, lo = [], []
    for x in xs:
        if form == "flat":
            t = 0.025
        else:
            t = 5 * 0.12 * (0.2969 * math.sqrt(x) - 0.126 * x - 0.3516 * x * x + 0.2843 * x ** 3 - 0.1036 * x ** 4)
            t = max(t, 0.004)
        cam = 0.06 * 4 * x * (1 - x) if form == "camber" else 0.0
        up.append((x, cam + t))
        lo.append((x, cam - t))
    return up + list(reversed(lo))[1:-1]


def curve_section(k, n=26):
    """第2入力の断面カーブ k 番を、弦 0〜1 に正規化して同じ点数に取り直す"""
    if shapes is None:
        return None
    prims = [p for p in shapes.prims() if p.attribValue("role") == "section"]
    if k < 0 or k >= len(prims):
        return None
    pts = [v.point().position() for v in prims[k].vertices()]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w = (max(xs) - min(xs)) or 1.0
    q = [((p[0] - min(xs)) / w, (p[1] - (max(ys) + min(ys)) / 2.0) / w) for p in pts]
    q.append(q[0])
    seg = [math.hypot(q[i + 1][0] - q[i][0], q[i + 1][1] - q[i][1]) for i in range(len(q) - 1)]
    total = sum(seg) or 1.0
    out, acc, j = [], 0.0, 0
    for i in range(n):
        d = total * i / n
        while j < len(seg) - 1 and acc + seg[j] < d:
            acc += seg[j]
            j += 1
        f = (d - acc) / (seg[j] or 1.0)
        out.append((q[j][0] + (q[j + 1][0] - q[j][0]) * f, q[j][1] + (q[j + 1][1] - q[j][1]) * f))
    return out


def ramp(vals, s):
    if len(vals) == 1:
        return vals[0]
    x = s * (len(vals) - 1)
    i = min(int(x), len(vals) - 2)
    return vals[i] + (vals[i + 1] - vals[i]) * (x - i)


def sec_yz(section, c, tw, dy, dz):
    """断面の各点の (接線方向 y, 軸方向 z)。翼弦は回転面から tw ねじれ、弦の 30% の位置を中心に回す"""
    return [(dy + (x - 0.3) * c * math.cos(tw) - y * c * math.sin(tw),
             dz + (x - 0.3) * c * math.sin(tw) + y * c * math.cos(tw)) for x, y in section]


def fit_chord(section, rho, c_want, tw, dy, n_blades, hub_r):
    """弦の長さを、次の 2 つを満たすまで自動で短くする（二分探索）
      1) その半径での羽根の角度の幅が、羽根の間隔（360° / 枚数）の 85% 以下 = 隣の羽根に当たらない
      2) ハブの中にある断面は、ハブの円柱からはみ出さない = 根元がハブに埋まる"""
    def ok(c):
        ys = [p[0] for p in sec_yz(section, c, tw, dy, 0.0)]
        if math.atan2(max(ys), rho) - math.atan2(min(ys), rho) > 0.85 * TAU / n_blades:
            return False
        if rho < hub_r and max(abs(v) for v in ys) > math.sqrt(max((0.97 * hub_r) ** 2 - rho * rho, 0.0)):
            return False
        return True
    if ok(c_want):
        return c_want
    lo, hi = 0.0, c_want
    for _ in range(30):
        mid = (lo + hi) / 2.0
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return lo


def blade_plan(n_blades, rho0, rho1, widths, tw0, tw1, sweep, lean, section, hub_r, steps=8):
    """断面ごとの (半径, 弦, ねじれ, 後退で横にずれる量, 前傾で軸方向にずれる量)"""
    plan = []
    for i in range(steps + 1):
        s = i / float(steps)
        rho = rho0 + (rho1 - rho0) * s
        tw = math.radians(tw0 + (tw1 - tw0) * s)
        dy = (rho - rho0) * math.tan(math.radians(sweep))
        dz = (rho - rho0) * math.tan(math.radians(lean))
        plan.append((rho, fit_chord(section, rho, ramp(widths, s), tw, dy, n_blades, hub_r), tw, dy, dz))
    return plan


def hub_fit(plan, section, hub_h):
    """根元の断面がハブの高さに収まるよう、ハブの高さと羽根の中心の高さを決める"""
    rho, c, tw, dy, dz = plan[0]
    zs = [p[1] for p in sec_yz(section, c, tw, dy, dz)]
    h = max(hub_h, (max(zs) - min(zs)) + 0.3)
    return h, (h - (max(zs) + min(zs))) / 2.0


def blade(m, plan, section, z_c, col):
    """+X 方向に伸びる羽根 1 枚"""
    rings = [[(rho, y, z_c + z) for y, z in sec_yz(section, c, tw, dy, dz)] for rho, c, tw, dy, dz in plan]
    strip(m, rings, col, cap0=True, cap1=True)


# ---------------------------------------------------------------------------
# バリアントごとの形
# ---------------------------------------------------------------------------
STEEL = (0.30, 0.32, 0.36)
LIGHT = (0.80, 0.82, 0.86)


def v_layer(gid, g):
    """R-01 の 1 層: housing = 軸受けの襟、rotor = 層の形"""
    form = gid.split("_")[1]
    h, r = Mesh(), Mesh()
    cyl(h, 0.95, -0.65, -0.3, STEEL)
    R, th = 4.0, 0.5
    if form == "disc":
        holes = int(g.get("holes", 6))
        col = (0.95, 0.55, 0.15)
        if holes <= 0:
            cyl(r, R, -th / 2, th / 2, col, n=40)
        else:
            annulus(r, 0.0001, 1.4, -th / 2, th / 2, col, n=24)
            annulus(r, 3.1, R, -th / 2, th / 2, col, n=48)
            pitch = TAU / holes
            for k in range(holes):
                a = k * pitch + pitch / 2.0
                panel(r, 1.35, 3.15, a - pitch * 0.2, a + pitch * 0.2, -th / 2, th / 2, col, segs=2)
    elif form == "ring":
        col = (0.18, 0.68, 0.74)
        annulus(r, 3.4, R, -th / 2, th / 2, col, n=48)
        cyl(r, 0.9, -th / 2, th / 2, col)
        n = int(g.get("spokes", 5))
        for k in range(n):
            a = TAU * k / n
            seg_box(r, (0.8 * math.cos(a), 0.8 * math.sin(a), 0.0), (3.5 * math.cos(a), 3.5 * math.sin(a), 0.0),
                    0.35, 0.3, col)
    elif form == "gear":
        z = int(g.get("teeth", 24))
        m_ = 2.0 * R / (z + 2)
        ext_gear(r, GearSpec(z, m_, 1), None, th, 0.0, (0.82, 0.64, 0.25), z0=-th / 2)
    elif form == "blades":
        n = int(g.get("blade_count", 4))
        tr, tt = g.get("twist_root", 40.0), g.get("twist_tip", 15.0)
        sec = curve_section(int(g.get("curve", -1))) if int(g.get("curve", -1)) >= 0 else None
        sec = sec or airfoil("sym")
        plan = blade_plan(n, 0.7, R, [1.4, 0.6], tr, tt, 0.0, 0.0, sec, 1.0)
        hub_h, z_c = hub_fit(plan, sec, 0.6)
        cyl(r, 1.0, -hub_h / 2, hub_h / 2, LIGHT)
        one = Mesh()
        blade(one, plan, sec, -hub_h / 2 + z_c, (0.92, 0.92, 0.95))
        # 羽根を n 枚に並べて焼く（層は剛体 1 個のまま）
        for k in range(n):
            a = TAU * k / n
            off = len(r.P)
            for p, c in zip(one.P, one.C):
                r.pt((p[0] * math.cos(a) - p[1] * math.sin(a), p[0] * math.sin(a) + p[1] * math.cos(a), p[2]), c)
            for f in one.F:
                r.face(tuple(i + off for i in f))
    elif form == "cage":
        col = (0.62, 0.42, 0.85)
        annulus(r, 3.5, R, -0.7, -0.45, col, n=40)
        annulus(r, 3.5, R, 0.45, 0.7, col, n=40)
        n = int(g.get("bars", 8))
        for k in range(n):
            a = TAU * k / n
            seg_box(r, (3.75 * math.cos(a), 3.75 * math.sin(a), -0.5), (3.75 * math.cos(a), 3.75 * math.sin(a), 0.5),
                    0.25, 0.25, col, up=(math.cos(a), math.sin(a), 0.0))
        for k in range(3):
            a = TAU * k / 3
            seg_box(r, (0.8 * math.cos(a), 0.8 * math.sin(a), -0.58), (3.6 * math.cos(a), 3.6 * math.sin(a), -0.58),
                    0.3, 0.22, col)
        cyl(r, 0.9, -0.7, -0.45, col)
    elif form == "mesh":
        return {"housing": h.to_geo(), "rotor": user_mesh(int(g.get("mesh", 0)))}
    return {"housing": h.to_geo(), "rotor": r.to_geo()}


def user_mesh(k):
    """第2入力の差し替えメッシュ k 番（つながった塊ごとに数える）"""
    g = hou.Geometry()
    if shapes is None:
        return g
    keep = [p for p in shapes.prims() if p.attribValue("role") == "mesh" and p.attribValue("role_index") == k]
    if not keep:
        return g
    g.merge(shapes)
    drop = [p for p in g.prims() if not (p.attribValue("role") == "mesh" and p.attribValue("role_index") == k)]
    g.deletePrims(drop, keep_points=False)
    if g.findPointAttrib("Cd") is None:
        g.addAttrib(hou.attribType.Point, "Cd", (0.8, 0.8, 0.8))
    return g


def v_turbine(gid, g):
    n = int(g["blade_count"])
    widths = [g.get("width%d" % i, 0.5) for i in range(int(g.get("nwidth", 2)))]
    hub_r = g["hub_r"]
    tr, tt = g["twist_root"], g["twist_tip"]
    hub_form = gid.split("_")[1]
    sec_name = gid.split("_")[9]
    if sec_name.startswith("curve"):
        sec = curve_section(int(g.get("curve", 0))) or airfoil("sym")
    else:
        sec = airfoil(sec_name)
    tip = hub_r + g["blade_len"]
    plan = blade_plan(n, 0.7 * hub_r, tip, widths, tr, tt, g["sweep"], g["lean"], sec, hub_r)
    hub_h, z_c = hub_fit(plan, sec, g["hub_h"])
    h, r, b = Mesh(), Mesh(), Mesh()
    # housing: 取り付けの襟（+ シュラウドと支柱）。回らない側
    cyl(h, hub_r * 0.75, -0.7, -0.05, STEEL)
    if int(g["shroud"]):
        ri = tip + g["shroud_gap"]
        annulus(h, ri, ri + 0.35, z_c - 0.9, z_c + 0.9, STEEL, n=64)
        for k in range(3):
            a = TAU * (k + 0.5) / 3
            seg_box(h, (hub_r * 0.7 * math.cos(a), hub_r * 0.7 * math.sin(a), -0.4),
                    (ri * math.cos(a), ri * math.sin(a), z_c - 0.9), 0.3, 0.3, STEEL)
    # rotor: ハブ（羽根の根元が埋まる高さに自動で伸ばす）
    hc = (0.86, 0.86, 0.9)
    cyl(r, hub_r, 0.0, hub_h, hc)
    if hub_form == "sphere":
        cone(r, hub_r, hub_r * 0.35, hub_h, hub_h + hub_r * 0.7, hc)
    elif hub_form == "spinner":
        cone(r, hub_r, 0.06, hub_h, hub_h + 1.6 * hub_r, hc)
    # blade: 1 枚（detail_pieces が blade_count 枚に並べる。ピッチの時間変化も付けられる）
    blade(b, plan, sec, z_c, (0.93, 0.56, 0.16))
    return {"housing": h.to_geo(), "rotor": r.to_geo(), "blade": b.to_geo()}


RING_COL = ((0.85, 0.28, 0.25), (0.30, 0.75, 0.40), (0.30, 0.45, 0.90))
RADII = (3.2, 2.6, 2.0)


def v_gring(gid, g):
    form = gid.split("_")[1]
    k, a, p = int(g["level"]), int(g["axis"]), int(g["plane"])
    tube = g["tube"]
    R = RADII[k]
    col = RING_COL[k]
    m = Mesh()
    ea, ep = AX[a], AX[p]
    if form == "ring":
        torus(m, R, tube, col, ea, ep)
    else:
        corners = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
        pts = [tuple(R * (u * ea[i] + v * ep[i]) for i in range(3)) for u, v in corners]
        sides = 4 if form == "square" else 3
        # U 字: 自分の軸（ea）の両端をつなぐ 3 辺だけ（+ep 側を開ける）
        order = [0, 1, 2, 3] if form == "square" else [1, 2, 3, 0]
        for s in range(sides):
            p0, p1 = pts[order[s]], pts[order[(s + 1) % 4]]
            seg_box(m, p0, p1, tube * 2, tube * 2, col, up=ep if s % 2 == 0 else ea)
    # 自分の回転軸の軸受（外側へ）と、内側のリングを支えるピン（ep 方向）
    for sgn in (1, -1):
        c = tuple(sgn * R * ea[i] for i in range(3))
        cyl(m, tube * 1.9, -tube * 1.6, tube * 1.6, STEEL, n=12, rot=axis_rot(a), t=c)
        inner = RADII[k + 1] if k < 2 else 1.05
        seg_box(m, tuple(sgn * inner * ep[i] for i in range(3)), tuple(sgn * R * ep[i] for i in range(3)),
                tube * 1.2, tube * 1.2, STEEL, up=ea)
    return {"rotor": m.to_geo()}


def v_gmount(gid, g):
    a0, tube = int(g["axis0"]), g["tube"]
    R0, zc = RADII[0], RADII[0] + 0.9
    m = Mesh()
    if a0 == 2:
        seg_box(m, (0.0, 0.0, 0.0), (0.0, 0.0, zc - R0 - tube * 1.6), 0.6, 0.6, STEEL)
        cyl(m, 0.5, -0.1, 0.4, STEEL)
    else:
        ea = AX[a0]
        zb = zc - R0 - 0.5
        w = R0 + 0.45
        seg_box(m, (0.0, 0.0, 0.0), (0.0, 0.0, zb), 0.6, 0.6, STEEL)
        e0 = tuple(-w * ea[i] for i in range(3))
        e1 = tuple(w * ea[i] for i in range(3))
        seg_box(m, (e0[0], e0[1], zb), (e1[0], e1[1], zb), 0.5, 0.5, STEEL)
        for e in (e0, e1):
            seg_box(m, (e[0], e[1], zb), (e[0], e[1], zc), 0.45, 0.45, STEEL)
    return {"housing": m.to_geo()}


def v_gpay(gid, g):
    form = gid.split("_")[1]
    p, tube = int(g["plane"]), g["tube"]
    m = Mesh()
    col = (0.98, 0.80, 0.20)
    if form == "plate":
        box(m, (0.0, 0.0, 0.0), (2.0, 2.0, 0.3), col)
        box(m, (0.0, 0.0, 0.3), (0.9, 0.9, 0.3), STEEL)
    elif form == "sphere":
        cyl(m, 1.0, -0.6, 0.6, col)
        cone(m, 1.0, 0.3, 0.6, 1.2, col)
        cone(m, 1.0, 0.3, -0.6, -1.2, col)
    else:
        cyl(m, 0.9, -0.5, 0.5, col)
        cyl(m, 0.55, 0.5, 0.95, STEEL)
    return {"housing": m.to_geo()}


def disc_to_x(p):
    """円盤の座標（軸 = Z、角度 0 = +X）を、クランクの座標（軸 = X、角度 0 = +Z、+90° = -Y）へ"""
    return (p[2], -p[1], p[0])


def map_mesh(m, fn):
    m.P = [fn(p) for p in m.P]
    return m


def v_crwheel(gid, g):
    r, W = g["ecc"], g["wheel_r"]
    m = Mesh()
    col, dark = (0.55, 0.58, 0.64), (0.25, 0.26, 0.30)
    th = 0.5
    if int(g.get("disc", 0)):
        holes = int(g.get("holes", 0))
        if holes > 0:
            annulus(m, 0.0001, 0.8, -th / 2, th / 2, col)
            annulus(m, W - 0.6, W, -th / 2, th / 2, col, n=48)
            pitch = TAU / holes
            for k in range(holes):
                a = k * pitch + pitch / 2
                panel(m, 0.75, W - 0.55, a - pitch * 0.22, a + pitch * 0.22, -th / 2, th / 2, col, segs=2)
        else:
            cyl(m, W, -th / 2, th / 2, col, n=48)
    else:
        annulus(m, W - 0.55, W, -th / 2 - 0.1, th / 2 + 0.1, col, n=48)
        cyl(m, 0.8, -th / 2, th / 2, col)
        n = int(g.get("spokes", 5))
        for k in range(n):
            a = TAU * (k + 0.5) / n
            seg_box(m, (0.7 * math.cos(a), 0.7 * math.sin(a), 0.0), ((W - 0.5) * math.cos(a), (W - 0.5) * math.sin(a), 0.0),
                    0.3, 0.3, col)
    npin = int(g.get("npin", 1))
    for k in range(npin):
        a = math.radians(g.get("pin%d" % k, 0.0))
        c = (r * math.cos(a), r * math.sin(a))
        cyl(m, 0.45, -th / 2, th / 2 + 0.05, dark, n=16, t=(c[0], c[1], 0.0))
        cyl(m, 0.22, th / 2, th / 2 + 0.95, LIGHT, n=12, t=(c[0], c[1], 0.0))
        if k == 0 and r < W - 0.7:
            seg_box(m, (0.0, 0.0, 0.0), (c[0], c[1], 0.0), 0.7, th + 0.1, col)
    if int(g.get("cw", 1)):
        a = math.radians(g.get("pin0", 0.0)) + math.pi
        panel(m, W * 0.42, W * 0.92, a - 0.95, a + 0.95, -th / 2 - 0.15, th / 2 + 0.15, dark, segs=10)
    cyl(m, 0.3, -1.3, th / 2, LIGHT, n=12)   # 軸
    return {"rotor": map_mesh(m, disc_to_x).to_geo()}


def v_crbase(gid, g):
    W, zc = g["wheel_r"], g["zc"]
    m = Mesh()
    # 入力ソケットから車輪の中心まで、車輪の -X 側を通るフレーム
    seg_box(m, (0.0, 0.0, 0.0), (-1.6, 0.0, 0.0), 0.7, 0.7, STEEL)
    seg_box(m, (-1.6, 0.0, 0.0), (-1.6, 0.0, zc), 0.7, 0.9, STEEL, up=(0.0, 1.0, 0.0))
    cyl(m, 0.75, 0.3, 1.3, STEEL, rot=axis_rot(0), t=(-1.6, 0.0, zc))
    return {"housing": m.to_geo()}


def v_crrod(gid, g):
    L = g["L"]
    m = Mesh()
    col = (0.80, 0.30, 0.25)
    x = 0.55  # 車輪の横（ピンの上）を通す
    seg_box(m, (x, 0.0, 0.35), (x, 0.0, L - 0.35), 0.18, 0.55, col, up=(0.0, 1.0, 0.0))
    seg_box(m, (x, 0.0, 0.35), (x, 0.0, L - 0.35), 0.4, 0.12, col, up=(0.0, 1.0, 0.0))
    for zz in (0.0, L):
        cyl(m, 0.42, x - 0.2, x + 0.2, col, n=16, rot=axis_rot(0), t=(0.0, 0.0, zz))
    return {"rotor": m.to_geo()}


def v_crslide(gid, g):
    x0, x1 = g["x_min"], g["x_max"]
    h, r = Mesh(), Mesh()
    for y in (-0.55, 0.55):
        seg_box(h, (0.55, y, x0 - 0.6), (0.55, y, x1 + 0.6), 0.25, 0.2, STEEL, up=(1.0, 0.0, 0.0))
    box(r, (0.55, 0.0, 0.0), (0.7, 0.9, 0.8), (0.95, 0.75, 0.20))
    return {"housing": h.to_geo(), "rotor": r.to_geo()}


def v_gear(gid, g):
    kind = gid.split("_")[0]
    z, m_, th = int(g["teeth"]), g["module"], g["thick"]
    prof, hel, hand = int(g["profile"]), g["helix"], int(g.get("hand", 1))
    me, mi = int(g.get("mate_ext", 0)), int(g.get("mate_int", 0))
    m = Mesh()
    if kind == "pgring":
        A = GearSpec(z, m_, prof, internal=True)
        hw = trim_against(A, GearSpec(me, m_, prof), m_ * (z - me) / 2.0, "rp") if me else None
        int_gear(m, A, hw, th, hel, 2.4 * m_, (0.55, 0.58, 0.64), hand=-1)
    else:
        A = GearSpec(z, m_, prof)
        hw = None
        if me:
            hw = trim_against(A, GearSpec(me, m_, prof), m_ * (z + me) / 2.0, "ext")
        if mi:
            h2 = trim_against(A, GearSpec(mi, m_, prof, internal=True), m_ * (mi - z) / 2.0, "pr")
            hw = dict((r, min(hw[r], h2[r])) for r in h2) if hw else h2
        col = (0.85, 0.66, 0.22) if kind == "pgsun" else (0.75, 0.55, 0.30)
        ext_gear(m, A, hw, th, hel, col, hand=hand)
        cyl(m, 0.35 if kind == "pgplanet" else 0.5, -0.6 if kind == "pgsun" else 0.0, th + 0.12, LIGHT, n=12)
    return {"rotor": m.to_geo()}


def v_pgcarrier(gid, g):
    n, a, th, form, pr = int(g["n"]), g["orbit"], g["thick"], int(g["form"]), g["pr"]
    m = Mesh()
    col = (0.30, 0.45, 0.80)
    z0, z1 = th + 0.15, th + 0.5
    if form == 2:
        cyl(m, a + 0.7, z0, z1, col, n=40)
    else:
        arms = n if form == 0 else max(n, 4)
        cyl(m, 0.9, z0, z1, col)
        for k in range(n):
            ang = TAU * k / n
            seg_box(m, (0.0, 0.0, (z0 + z1) / 2), (a * math.cos(ang), a * math.sin(ang), (z0 + z1) / 2),
                    0.9, z1 - z0, col)
            cyl(m, 0.65, z0, z1, col, n=16, t=(a * math.cos(ang), a * math.sin(ang), 0.0))
    for k in range(n):
        ang = TAU * k / n
        c = (a * math.cos(ang), a * math.sin(ang), 0.0)
        cyl(m, 0.28, 0.0, z1 + 0.15, LIGHT, n=12, t=c)          # 遊星ピン
        cyl(m, 0.45, z1, z1 + 0.2, STEEL, n=6, t=c)              # ボルト頭
    return {"rotor": m.to_geo()}


def v_pgcase(gid, g):
    rc, th, win, cv = g["r_case"], g["thick"], int(g["windows"]), int(g.get("curve", -1))
    m = Mesh()
    z0, z1 = -0.35, th + 0.25
    prof = None
    if cv >= 0:
        sec = curve_section(cv, n=24)
        if sec:
            prof = sec
    if prof:
        # 断面カーブを回転体にして外形だけ差し替える（x = 太さ方向、y = 高さ方向）
        rings = []
        for x, y in prof:
            rr = rc + 0.15 + x * 0.6
            zz = z0 + (y + 0.5) * (z1 - z0)
            rings.append([(rr * math.cos(TAU * i / 48), rr * math.sin(TAU * i / 48), zz) for i in range(48)])
        strip(m, rings + [rings[0]], STEEL)
    elif win <= 0:
        annulus(m, rc, rc + 0.3, z0, z1, STEEL, n=64)
    else:
        pitch = TAU / win
        for k in range(win):
            a = k * pitch
            panel(m, rc, rc + 0.3, a, a + pitch * 0.45, z0, z1, STEEL, segs=6)
            panel(m, rc, rc + 0.3, a + pitch * 0.45, a + pitch, z0, z0 + 0.3, STEEL, segs=6)
            panel(m, rc, rc + 0.3, a + pitch * 0.45, a + pitch, z1 - 0.3, z1, STEEL, segs=6)
    annulus(m, 0.7, rc + 0.3, z0 - 0.3, z0, STEEL, n=64)   # 背板
    return {"housing": m.to_geo()}


def v_pgshaft(gid, g):
    th = g["thick"]
    m = Mesh()
    cyl(m, 0.6, th + 0.5, th + 1.0, LIGHT, n=16)
    return {"rotor": m.to_geo()}


BUILDERS = {"layer": v_layer, "turbine": v_turbine, "gring": v_gring, "gmount": v_gmount, "gpay": v_gpay,
            "crwheel": v_crwheel, "crbase": v_crbase, "crrod": v_crrod, "crslide": v_crslide,
            "pgring": v_gear, "pgsun": v_gear, "pgplanet": v_gear, "pgcarrier": v_pgcarrier,
            "pgcase": v_pgcase, "pgshaft": v_pgshaft}

# ---------------------------------------------------------------------------
# geo_id ごとに 1 回だけ作ってパックする
# ---------------------------------------------------------------------------
geo.addAttrib(hou.attribType.Prim, "piece", "")
geo.addAttrib(hou.attribType.Prim, "geo_id", "")
first = {}
if src.findPointAttrib("geo_id") is not None:
    gattrs = [a.name() for a in src.pointAttribs() if a.name().startswith("geo_") and a.name() != "geo_id"]
    for pt in src.points():
        gid = pt.attribValue("geo_id")
        if gid and gid not in first:
            first[gid] = dict((a[4:], pt.attribValue(a)) for a in gattrs)
for gid in sorted(first):
    kind = gid.split("_")[0]
    fn = BUILDERS.get(kind)
    if fn is None:
        raise hou.NodeError("variant / 作り方を知らない形です: %s" % gid)
    for suffix, g in sorted(fn(gid, first[gid]).items()):
        prim = geo.createPacked("PackedGeometry")
        prim.setEmbeddedGeometry(g.freeze())
        prim.setAttribValue("piece", gid + "_" + suffix)
        prim.setAttribValue("geo_id", gid)
