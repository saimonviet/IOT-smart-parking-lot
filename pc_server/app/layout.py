"""Sơ đồ bãi xe: ROI từng ô, đồ thị đường đi, tìm ô trống gần nhất và hướng dẫn rẽ.

Hai hệ tọa độ:
  - "frame": ảnh camera — "roi" của từng ô (vùng cắt cho bộ nhận diện)
  - "map"  : sơ đồ nhìn từ trên xuống — "nodes", "decor" và khung "map" {x,y,w,h,rot} của từng ô.
    Ô không có "map" thì lấy khung bao của ROI (layout cũ, hai hệ trùng nhau).
"""
import heapq
import json
import math
import re
import shutil

from . import config

NODE_RE = re.compile(r"^[A-Za-z0-9_]{1,12}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9-]{1,6}$")  # không dấu để hiện được trên OLED
KEYS = ("frame", "map", "entrance", "exit", "nodes", "edges", "slots", "decor")


class Layout:
    def __init__(self, path=config.LAYOUT_PATH, data=None):
        if data is None:
            data = json.loads(open(path, encoding="utf-8").read())
        self.data = data
        self.frame_w = data["frame"]["width"]
        self.frame_h = data["frame"]["height"]
        self.nodes = {k: tuple(v) for k, v in data["nodes"].items()}
        self.entrance = data["entrance"]
        self.exit = data["exit"]
        self.slots = {s["id"]: s for s in data["slots"]}
        self.slot_ids = sorted(self.slots)
        # cạnh của đồ thị làn đường: "edges" [[a, b], ...] hoặc (kiểu cũ) "lane" là một làn thẳng
        edges = data.get("edges") or list(zip(data["lane"], data["lane"][1:]))
        self.adj = {n: [] for n in self.nodes}
        for a, b in edges:
            d = self._dist(a, b)
            self.adj[a].append((b, d))
            self.adj[b].append((a, d))

    def label(self, sid):
        return self.slots[sid].get("label", str(sid))

    def _dist(self, a, b):
        (x1, y1), (x2, y2) = self.nodes[a], self.nodes[b]
        return math.hypot(x2 - x1, y2 - y1)

    def slot_center(self, sid):
        """Tâm ô trên sơ đồ (cùng hệ tọa độ với các nút đường đi)."""
        m = self.slots[sid].get("map")
        if m:
            return (m["x"] + m["w"] / 2, m["y"] + m["h"] / 2)
        roi = self.slots[sid]["roi"]
        return (sum(p[0] for p in roi) / len(roi), sum(p[1] for p in roi) / len(roi))

    def _dijkstra(self, src):
        dist = {src: 0.0}
        prev = {}
        pq = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, 1e18):
                continue
            for v, w in self.adj[u]:
                nd = d + w
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        return dist, prev

    def nearest_free(self, free_ids):
        """Trả về (slot_id, route) của ô trống gần cổng vào nhất, hoặc None."""
        if not free_ids:
            return None
        dist, prev = self._dijkstra(self.entrance)
        best = None
        for sid in free_ids:
            s = self.slots[sid]
            cx, cy = self.slot_center(sid)
            nx, ny = self.nodes[s["node"]]
            total = dist.get(s["node"], 1e18) + math.hypot(cx - nx, cy - ny)
            key = (round(total, 3), sid)
            if best is None or key < best[0]:
                best = (key, sid)
        sid = best[1]
        path = [self.slots[sid]["node"]]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        return sid, self.describe_route(sid, path)

    def describe_route(self, sid, path):
        """Chuyển đường đi thành các bước rẽ + nội dung hiển thị cho OLED."""
        pts = [self.nodes[n] for n in path]
        pts.append(self.slot_center(sid))
        # hướng ban đầu: từ cổng vào đi vào làn
        heading = (1.0, 0.0)
        if len(pts) > 1 and pts[1] != pts[0]:
            heading = _unit(pts[0], pts[1])
        # mỗi thao tác = (số nút đi thẳng qua trước đó, hướng rẽ)
        moves, straight = [], 0
        for i in range(1, len(pts) - 1):
            nxt = _unit(pts[i], pts[i + 1])
            cross = heading[0] * nxt[1] - heading[1] * nxt[0]
            dot = heading[0] * nxt[0] + heading[1] * nxt[1]
            if abs(cross) < 0.3 and dot > 0:
                straight += 1
            else:
                moves.append((straight, "right" if cross > 0 else "left"))
                straight = 0
            heading = nxt
        if straight or not moves:  # đi thẳng vào ô ở cuối
            moves.append((straight, "straight"))
        word = {"left": "Re TRAI", "right": "Re PHAI", "straight": "Di thang"}
        lines = [(f"Thang {n}, " if n and t != "straight" else "") + word[t] for n, t in moves]
        if moves[-1][1] == "straight":
            lines[-1] = "Di thang vao o"
        steps = [{"straight": n, "turn": t} for n, t in moves]
        label = self.label(sid)
        return {
            "slot": sid,
            "label": label,
            "path": path,
            "points": [[round(x, 1), round(y, 1)] for x, y in pts],  # tọa độ đường đi trên sơ đồ (vẽ lên TFT)
            "steps": steps,
            "arrow": moves[0][1],
            "oled": {"title": f"O {label}", "lines": lines, "arrow": moves[0][1]},
        }

    def screen(self):
        """Sơ đồ rút gọn gửi cho Pi vẽ lên màn TFT. Ô xếp theo id, khớp thứ tự trạng thái trong tin "state"."""
        m = self.data.get("map") or {"width": self.frame_w, "height": self.frame_h}
        slots = []
        for sid in self.slot_ids:
            s = self.slots[sid]
            b = s.get("map")
            if not b:
                xs, ys = [p[0] for p in s["roi"]], [p[1] for p in s["roi"]]
                b = {"x": min(xs), "y": min(ys), "w": max(xs) - min(xs), "h": max(ys) - min(ys)}
            slots.append({"id": sid, "label": self.label(sid), "box": [b["x"], b["y"], b["w"], b["h"], b.get("rot", 0)]})
        return {"width": m["width"], "height": m["height"], "entrance": self.entrance, "exit": self.exit,
                "nodes": {k: list(v) for k, v in self.nodes.items()},
                "edges": self.data.get("edges") or [list(e) for e in zip(self.data["lane"], self.data["lane"][1:])],
                "slots": slots, "decor": self.data.get("decor", {})}

    def public(self):
        return {
            "frame": {"width": self.frame_w, "height": self.frame_h},
            "map": self.data.get("map") or {"width": self.frame_w, "height": self.frame_h},
            "entrance": self.entrance, "exit": self.exit,
            "nodes": {k: list(v) for k, v in self.nodes.items()},
            "edges": self.data.get("edges") or [list(e) for e in zip(self.data["lane"], self.data["lane"][1:])],
            "slots": self.data["slots"],
            "decor": self.data.get("decor", {}),
        }


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


# ---------------------------------------------------------------- chỉnh sơ đồ từ giao diện quản lý
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _pt(p):
    return isinstance(p, (list, tuple)) and len(p) == 2 and all(_num(v) for v in p)


def _size_ok(f):
    return isinstance(f, dict) and all(_num(f.get(k)) and f[k] > 0 for k in ("width", "height"))


def _area(poly):
    return abs(sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly)))) / 2


def validate(data):
    """Kiểm tra sơ đồ do quản lý gửi lên. Trả về (lỗi, cảnh báo); còn lỗi thì không lưu."""
    errors, warnings = [], []
    if not isinstance(data, dict):
        return ["Dữ liệu sơ đồ không hợp lệ"], []
    if not _size_ok(data.get("frame")):
        errors.append("Khung ảnh camera (frame) cần width/height dương")
    if data.get("map") is not None and not _size_ok(data["map"]):
        errors.append("Khung sơ đồ (map) cần width/height dương")

    nodes = data.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        errors.append("Chưa có nút đường đi nào")
        nodes = {}
    for name, p in nodes.items():
        if not NODE_RE.match(str(name)):
            errors.append(f"Tên nút '{name}' chỉ gồm chữ, số, '_' (tối đa 12 ký tự)")
        if not _pt(p):
            errors.append(f"Tọa độ nút {name} không hợp lệ")
    for key, txt in (("entrance", "cổng vào"), ("exit", "cổng ra")):
        if data.get(key) not in nodes:
            errors.append(f"Chưa chọn nút {txt}")

    adj = {n: set() for n in nodes}
    edges = data.get("edges")
    if not isinstance(edges, list):
        errors.append("Danh sách làn đường (edges) không hợp lệ")
        edges = []
    for e in edges:
        if not (isinstance(e, (list, tuple)) and len(e) == 2 and e[0] in nodes and e[1] in nodes and e[0] != e[1]):
            errors.append(f"Làn đường {e} nối tới nút không tồn tại")
            continue
        adj[e[0]].add(e[1])
        adj[e[1]].add(e[0])

    slots = data.get("slots")
    if not isinstance(slots, list) or not slots:
        errors.append("Bãi phải có ít nhất 1 ô")
        slots = []
    ids, labels, todo, outside = set(), set(), [], []
    fw, fh = (data["frame"]["width"], data["frame"]["height"]) if _size_ok(data.get("frame")) else (0, 0)
    for s in slots:
        if not isinstance(s, dict):
            errors.append("Có ô không hợp lệ")
            continue
        sid = s.get("id")
        name = str(s.get("label", sid))
        tag = f"Ô {name}"
        if not isinstance(sid, int) or isinstance(sid, bool) or sid < 1:
            errors.append(f"{tag}: id phải là số nguyên dương")
        elif sid in ids:
            errors.append(f"Trùng id ô {sid}")
        ids.add(sid)
        if not LABEL_RE.match(name):
            errors.append(f"{tag}: tên ô chỉ gồm chữ không dấu, số, '-' (tối đa 6 ký tự)")
        elif name in labels:
            errors.append(f"Trùng tên ô {name}")
        labels.add(name)
        if s.get("node") not in nodes:
            errors.append(f"{tag}: chưa gắn với nút đường đi")
        roi = s.get("roi")
        if not (isinstance(roi, list) and len(roi) >= 3 and all(_pt(p) for p in roi)):
            errors.append(f"{tag}: vùng camera (ROI) cần ít nhất 3 điểm")
        elif _area(roi) < 50:
            errors.append(f"{tag}: vùng camera (ROI) quá nhỏ")
        elif fw and any(not (-1 <= x <= fw + 1 and -1 <= y <= fh + 1) for x, y in roi):
            outside.append(name)
        m = s.get("map")
        if m is not None and not (isinstance(m, dict) and all(_num(m.get(k)) for k in ("x", "y", "w", "h"))
                                  and m["w"] > 0 and m["h"] > 0 and _num(m.get("rot", 0))):
            errors.append(f"{tag}: khung trên sơ đồ không hợp lệ")
        if s.get("roi_todo"):
            todo.append(name)

    if data.get("entrance") in nodes:
        seen, stack = {data["entrance"]}, [data["entrance"]]
        while stack:
            for v in adj[stack.pop()]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        cut = [str(s.get("label", s.get("id"))) for s in slots
               if isinstance(s, dict) and s.get("node") in nodes and s["node"] not in seen]
        if cut:
            errors.append(f"Không có làn đường từ cổng vào tới ô: {', '.join(cut)}")
        if data.get("exit") in nodes and data["exit"] not in seen:
            warnings.append("Cổng ra chưa nối với cổng vào bằng làn đường")

    if todo:
        warnings.append(f"{len(todo)} ô chưa vẽ vùng camera (đang dùng vùng tạm, nhận diện sẽ sai): {', '.join(todo)}")
    if outside:
        warnings.append(f"Vùng camera nằm ngoài khung ảnh: {', '.join(outside)}")
    if len(slots) > config.LED_COUNT:
        warnings.append(f"Bãi có {len(slots)} ô nhưng Raspberry Pi chỉ có {config.LED_COUNT} đèn LED "
                        f"— các ô sau ô thứ {config.LED_COUNT} (xếp theo id) sẽ không có đèn")
    return errors, warnings


def save(data):
    """Ghi sơ đồ (chỉ các khóa đã biết) ra file, giữ bản trước ở layout.prev.json."""
    clean = {k: data[k] for k in KEYS if k in data}
    path = config.LAYOUT_PATH
    if path.exists():
        shutil.copyfile(path, path.with_name(path.stem + ".prev.json"))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return clean
