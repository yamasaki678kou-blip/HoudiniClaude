# classify_shapes - Python SOP
# HDA の第2入力を 3 つの役に読み分けます（仕様 v0.5 §0.3、精査 v0.5 §2.1）。
#   断面カーブ sections : R-05 の羽根の断面、R-02 のハウジング外形など（curve=番号 で選ぶ）
#   差し替えメッシュ meshes : coax(form=mesh, mesh=番号) の層の形
#   ターゲット点 targets : R-03 gimbal(mode=track) の狙う点（target=番号）
# 決め方:
#   1. グループがあればそれに従う（プリミティブグループ sections / meshes、ポイントグループ targets）
#   2. どのグループにも入っていないものは、形で決める（型では決めない。カーブも面も同じ Poly なので）
#        開いたポリゴン（ポリライン）・NURBS / Bezier カーブ = 断面
#        閉じたポリゴン = メッシュ（つながった塊ごとに 1 個）
#        どのプリミティブにも属さない点 = ターゲット
node = hou.pwd()
geo = node.geometry()

geo.addAttrib(hou.attribType.Prim, "role", "")
geo.addAttrib(hou.attribType.Prim, "role_index", -1)
geo.addAttrib(hou.attribType.Point, "target_index", -1)

g_sec = geo.findPrimGroup("sections")
g_mesh = geo.findPrimGroup("meshes")
g_tgt = geo.findPointGroup("targets")
sec_set = set(p.number() for p in g_sec.prims()) if g_sec else set()
mesh_set = set(p.number() for p in g_mesh.prims()) if g_mesh else set()

CURVES = (hou.primType.NURBSCurve, hou.primType.BezierCurve)
sections, meshes = [], []
for prim in geo.prims():
    n = prim.number()
    if n in sec_set:
        role = "section"
    elif n in mesh_set:
        role = "mesh"
    elif prim.type() in CURVES:
        role = "section"
    elif prim.type() == hou.primType.Polygon:
        role = "mesh" if prim.isClosed() else "section"
    else:
        role = ""
    prim.setAttribValue("role", role)
    if role == "section":
        prim.setAttribValue("role_index", len(sections))
        sections.append(prim)
    elif role == "mesh":
        meshes.append(prim)

# メッシュはつながった塊ごとに番号を付ける（点を共有する面は同じ塊）
parent = {}


def find(a):
    while parent.get(a, a) != a:
        parent[a] = parent.get(parent[a], parent[a])
        a = parent[a]
    return a


for prim in meshes:
    pts = [v.point().number() for v in prim.vertices()]
    for p in pts:
        parent.setdefault(p, p)
    for p in pts[1:]:
        ra, rb = find(pts[0]), find(p)
        if ra != rb:
            parent[rb] = ra
order = {}
for prim in meshes:
    root = find(prim.vertices()[0].point().number())
    if root not in order:
        order[root] = len(order)
    prim.setAttribValue("role_index", order[root])

# ターゲット点
used = set()
for prim in geo.prims():
    for v in prim.vertices():
        used.add(v.point().number())
k = 0
for pt in geo.points():
    is_t = (g_tgt is not None and pt in g_tgt.points()) if g_tgt else (pt.number() not in used)
    if is_t:
        pt.setAttribValue("target_index", k)
        k += 1
