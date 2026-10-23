"""Plan a recipe's ``scene`` block: terrain heights and layer weights, scattered models and plants, foliage cover, a
grass density grid, structures with their props, and camera paths, all in Unity world metres. Unity then only builds,
lights and renders what is planned here (``unity_natural_scene``). From the 2026-10-23 moorland prototype.

Scene coordinates are metres within the dressed area (x east, z north); heights in the spec are above the ground.
"""
import math

import numpy as np

STILL_SIZE = (1600, 900)
FRAME_SIZE = (1280, 720)


def _lerp(a, b, t):
    return a + (b - a) * t


def inverse_lerp(a, b, value):
    """0 at a, 1 at b, clamped; a may be larger than b."""
    return np.clip((np.asarray(value, dtype=np.float64) - a) / (b - a), 0.0, 1.0)


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _hash(ix, iz, seed):
    h = (ix * 374761393 + iz * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def value_noise(x, z, seed=0):
    x, z = np.asarray(x, dtype=np.float64), np.asarray(z, dtype=np.float64)
    ix, iz = np.floor(x).astype(np.int64), np.floor(z).astype(np.int64)
    u, v = smoothstep(x - ix), smoothstep(z - iz)
    a, b = _hash(ix, iz, seed), _hash(ix + 1, iz, seed)
    c, d = _hash(ix, iz + 1, seed), _hash(ix + 1, iz + 1, seed)
    return _lerp(_lerp(a, b, u), _lerp(c, d, u), v)


def fbm(x, z, octaves, scale, seed=0):
    """Fractal noise in [0, 1]: octaves of value noise, each at twice the frequency and half the weight."""
    total, amplitude, norm = 0.0, 1.0, 0.0
    for octave in range(octaves):
        total = total + amplitude * value_noise(np.asarray(x) * scale + 37.1 * octave,
                                                np.asarray(z) * scale + 11.7 * octave, seed + octave)
        norm += amplitude
        amplitude *= 0.5
        scale *= 2
    return total / norm


class Terrain:
    """The heightmap, in normalised heights (0..1 of terrain height) on a res x res grid over the whole terrain."""

    def __init__(self, scene, resolution=1025):
        t = scene["terrain"]
        self.spec, self.size, self.dressed, self.height = t, float(t["size"]), float(t["dressed"]), float(t["height"])
        self.offset = (self.size - self.dressed) / 2
        self.res = resolution
        self.structures = scene.get("structures", [])
        axis = np.arange(self.res) / (self.res - 1) * self.size - self.offset
        x, z = np.meshgrid(axis, axis)  # rows are z, as Unity's TerrainData.SetHeights expects
        heights = self.natural(x, z)
        for structure in self.structures:
            sx, sz = structure["at"]
            inner, outer = structure.get("flatten", [0, 0])
            if not outer:
                continue
            plateau = float(self.natural(np.array(sx), np.array(sz)))
            structure["_plateau"] = plateau
            level = smoothstep(inverse_lerp(outer, inner, np.hypot(x - sx, z - sz)))
            heights = _lerp(heights, plateau, level)
            floor = structure.get("floor")
            if floor:  # ground sinks under floor tiles: at grass level the terrain drew over their domed tops
                for cx, cz in floor["cells"]:
                    inside = (np.abs(x - sx - cx) < 1.45) & (np.abs(z - sz - cz) < 1.45)
                    heights[inside] = plateau - 0.3 / self.height
        self.heights = np.clip(heights, 0.0, 1.0)

    def path_x(self, z):
        path = self.spec.get("path")
        return path["x"] + path["swing"] * np.sin(2 * np.pi * np.asarray(z) / self.dressed) if path else None

    def path_distance(self, x, z):
        if not self.spec.get("path"):
            return np.full(np.shape(x), np.inf)
        return np.abs(np.asarray(x) - self.path_x(z))

    def natural(self, x, z):
        noise = self.spec.get("noise", {})
        h = noise.get("amplitude", 0.2) * fbm(x + self.offset, z + self.offset, noise.get("octaves", 5),
                                              noise.get("scale", 0.025))
        for hill in self.spec.get("hills", []):
            (hx, hz), (rx, rz) = hill["at"], hill["radius"]
            k = np.exp(-(((x - hx) / rx) ** 2 + ((z - hz) / rz) ** 2))
            h = h + hill["height"] * k * (0.8 + 0.2 * fbm(x + self.offset, z + self.offset, 3, 0.1, seed=7))
        if self.spec.get("path"):
            width = self.spec["path"].get("width", 4)
            h = _lerp(h, h * 0.92, inverse_lerp(width, 1.0, self.path_distance(x, z)))
        return h

    def ground(self, x, z):
        """Ground height in metres at scene coordinates, bilinear like Unity's Terrain.SampleHeight."""
        gx = (np.asarray(x, dtype=np.float64) + self.offset) / self.size * (self.res - 1)
        gz = (np.asarray(z, dtype=np.float64) + self.offset) / self.size * (self.res - 1)
        gx, gz = np.clip(gx, 0, self.res - 1.001), np.clip(gz, 0, self.res - 1.001)
        ix, iz = gx.astype(int), gz.astype(int)
        fx, fz = gx - ix, gz - iz
        h = self.heights
        top = _lerp(h[iz, ix], h[iz, ix + 1], fx)
        bottom = _lerp(h[iz + 1, ix], h[iz + 1, ix + 1], fx)
        return _lerp(top, bottom, fz) * self.height

    def world(self, x, z):
        return float(x) + self.offset, float(z) + self.offset

    def slope_degrees(self, size):
        """Slope on a size x size grid, from the heightmap's gradient."""
        step = self.size / (self.res - 1)
        gz, gx = np.gradient(self.heights * self.height, step)
        slope = np.degrees(np.arctan(np.hypot(gx, gz)))
        index = np.round(np.linspace(0, self.res - 1, size)).astype(int)
        return slope[np.ix_(index, index)]


def layer_weights(scene, terrain, size=1024):
    """Each layer's weight on a size x size grid over the terrain. The first layer is the base; slope rules claim
    first, then path rules, then patches, each from what earlier rules left."""
    layers = scene["terrain"]["layers"]
    axis = np.arange(size) / (size - 1) * terrain.size - terrain.offset
    x, z = np.meshgrid(axis, axis)
    distance = terrain.path_distance(x, z)
    slope = terrain.slope_degrees(size)
    weights = np.zeros((size, size, len(layers)))
    remaining = np.ones((size, size))
    for kind in ("slope", "path", "patches"):
        for index, layer in enumerate(layers[1:], start=1):
            if kind not in layer:
                continue
            if kind == "slope":
                rule = inverse_lerp(*layer["slope"], slope)
            elif kind == "path":
                rule = inverse_lerp(*layer["path"], distance)
            else:
                patches = layer["patches"]
                rule = (fbm(x + terrain.offset, z + terrain.offset, 3, patches["scale"], seed=11) - patches["above"]) * 4
                if layer.get("path_edge"):
                    near, far, amount = layer["path_edge"]
                    rule = rule + inverse_lerp(near, far, distance) * amount
                rule = np.clip(rule, 0, 1)
            weights[..., index] = rule * remaining
            remaining = remaining * (1 - rule)
    weights[..., 0] = np.clip(1 - weights[..., 1:].sum(-1), 0, 1)
    return weights


def _catmull_rom(points, k, t):
    p = lambda i: np.asarray(points[min(max(i, 0), len(points) - 1)], dtype=np.float64)
    a, b, c, d = p(k - 1), p(k), p(k + 1), p(k + 2)
    return 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t + (-a + 3 * b - 3 * c + d) * t ** 3)


def flythrough(scene, terrain):
    """Per-frame camera positions and look targets (world metres) along a Catmull-Rom path through the keys; the
    camera never drops within 1.2 m of the ground."""
    fly = scene["cameras"].get("flythrough")
    if not fly:
        return []
    keys = fly["keys"]
    frames = int(round(fly["seconds"] * fly["fps"]))
    positions = [(k["from"][0], k["from"][1], k["from"][2]) for k in keys]
    targets = [(k["to"][0], k["to"][1], k["to"][2]) for k in keys]
    out = []
    for f in range(frames):
        u = f / max(frames - 1, 1) * (len(keys) - 1)
        k = min(int(u), len(keys) - 2)
        t = float(smoothstep(u - k)) * 0.35 + (u - k) * 0.65
        (px, ph, pz), (lx, lh, lz) = _catmull_rom(positions, k, t), _catmull_rom(targets, k, t)
        ground = float(terrain.ground(px, pz))
        (wx, wz), (tx, tz) = terrain.world(px, pz), terrain.world(lx, lz)
        # Every frame names its field of view: without one, Unity rendered the 2026-10-23 live flythrough at 0 degrees,
        # 360 frames of flat colour.
        out.append({"name": f"frame_{f:04d}", "fov": fly.get("fov", 50), "from": [wx, ground + max(ph, 1.2), wz],
                    "to": [tx, float(terrain.ground(lx, lz)) + lh, tz]})
    return out


def camera_path_samples(scene, count=600):
    """Ground positions the cameras pass through: the flythrough's path, and each still's camera. In the first
    render the tor still's camera stood inside a pine."""
    samples = [(s["from"][0], s["from"][2]) for s in scene["cameras"].get("stills", [])]
    fly = scene["cameras"].get("flythrough")
    if fly:
        keys = [(k["from"][0], k["from"][2]) for k in fly["keys"]]
        for n in range(count):
            u = n / (count - 1) * (len(keys) - 1)
            k = min(int(u), len(keys) - 2)
            samples.append(tuple(_catmull_rom(keys, k, u - k)))
    return np.array(samples).reshape(-1, 2)


def _pick(assets, rng):
    if isinstance(assets, dict):
        names, weights = list(assets), np.array(list(assets.values()), dtype=np.float64)
        return names[rng.choice(len(names), p=weights / weights.sum())]
    return assets[rng.integers(len(assets))]


def _position(entry, terrain, rng, index):
    if "area" in entry:
        x0, z0, x1, z1 = entry["area"]
        return rng.uniform(x0, x1), rng.uniform(z0, z1)
    if "cluster" in entry:
        (cx, cz), (sx, sz) = entry["cluster"]["at"], entry["cluster"]["spread"]
        return cx + (rng.random() - 0.5) * sx, cz + (rng.random() - 0.5) * sz
    if "around" in entry:
        around = entry["around"]
        (cx, cz), (rx, rz), (a0, a1) = around["at"], around["radius"], around.get("angles", [0, 2 * math.pi])
        if around.get("even"):
            angle = _lerp(a0, a1, index / max(entry["count"] - 1, 1)) + (rng.random() - 0.5) * 0.2
        else:
            angle = rng.uniform(a0, a1)
        sx, sz = around.get("spread", [0, 0])
        return cx + rx * math.sin(angle) + (rng.random() - 0.5) * sx, cz + rz * math.cos(angle) + (rng.random() - 0.5) * sz
    if "path_edge" in entry:
        edge = entry["path_edge"]
        z = rng.uniform(*edge["z"])
        side = -1 if rng.random() < 0.5 else 1
        return float(terrain.path_x(z)) + side * edge["offset"] + (rng.random() - 0.5) * edge.get("spread", 0), z
    raise ValueError(f"Scatter entry needs area, cluster, around or path_edge: {entry}")


def scatter(scene, terrain, rng):
    """Placements for each scatter entry; a placement that breaks a rule is dropped, not moved."""
    path = camera_path_samples(scene)
    camera_clear = scene.get("clear", {}).get("camera_path", 0)
    placements = []
    for entry in scene.get("scatter", []):
        for index in range(entry["count"]):
            asset = _pick(entry["assets"], rng)
            x, z = _position(entry, terrain, rng, index)
            yaw, scale = rng.uniform(0, 360), rng.uniform(*entry.get("scale", [1, 1]))
            if any(math.hypot(x - s["at"][0], z - s["at"][1]) < s.get("clear", 0) for s in terrain.structures):
                continue
            if camera_clear and len(path) and np.min(np.hypot(path[:, 0] - x, path[:, 1] - z)) < camera_clear:
                continue
            if entry.get("avoid_path") and float(terrain.path_distance(x, z)) < entry["avoid_path"]:
                continue
            if any(math.hypot(x - a["at"][0], z - a["at"][1]) < a["radius"] for a in entry.get("avoid", [])):
                continue
            wx, wz = terrain.world(x, z)
            placements.append({"asset": asset, "x": wx, "z": wz, "yaw": yaw, "scale": scale, "sink": entry.get("sink", 0)})
    return placements


def _weight_at(weights, terrain, layer, x, z):
    size = weights.shape[0]
    j = np.clip(np.round((np.asarray(x) + terrain.offset) / terrain.size * (size - 1)).astype(int), 0, size - 1)
    i = np.clip(np.round((np.asarray(z) + terrain.offset) / terrain.size * (size - 1)).astype(int), 0, size - 1)
    return weights[i, j, layer]


def cover(scene, terrain, weights, rng, margin=10):
    """Foliage card placements within the dressed area and a margin, grouped by foliage."""
    groups = []
    lo, hi = -margin, terrain.dressed + margin
    for entry in scene.get("cover", []):
        items = []
        for _ in range(entry["count"] * 12):
            if len(items) >= entry["count"]:
                break
            x, z = rng.uniform(lo, hi), rng.uniform(lo, hi)
            if "min_weight" in entry and _weight_at(weights, terrain, 0, x, z) < entry["min_weight"]:
                continue
            noise = entry.get("noise")
            if noise and fbm(x, z, 2, noise["scale"], seed=noise.get("seed", 21)) < noise["above"]:
                continue
            near = entry.get("near")
            if near and math.hypot(x - near["at"][0], z - near["at"][1]) > near["radius"]:
                continue
            if entry.get("avoid_path") and float(terrain.path_distance(x, z)) < entry["avoid_path"]:
                continue
            if any(math.hypot(x - s["at"][0], z - s["at"][1]) < s.get("cover_clear", s.get("clear", 0))
                   for s in terrain.structures):
                continue
            if rng.random() > entry.get("fraction", 1.0):
                continue
            wx, wz = terrain.world(x, z)
            items.append([wx, float(terrain.ground(x, z)), wz, rng.uniform(0, 360), rng.uniform(*entry["size"])])
        groups.append({"foliage": entry["foliage"], "aspect": entry.get("aspect", 1.0), "items": items})
    return groups


def grass_density(scene, terrain, weights, cell=0.5, margin=10):
    """Blades per square metre on a grid over the dressed area and a margin: dense near each still's camera,
    thinning with distance, only on the base layer, and never on the path or under floor tiles."""
    grass = scene.get("grass")
    if not grass:
        return None
    lo = -margin
    count = int((terrain.dressed + 2 * margin) / cell)
    axis = lo + (np.arange(count) + 0.5) * cell
    x, z = np.meshgrid(axis, axis)
    spots = np.array([(s["from"][0], s["from"][2]) for s in scene["cameras"].get("stills", [])] or [(0, 0)])
    nearest = np.min(np.hypot(x[..., None] - spots[:, 0], z[..., None] - spots[:, 1]), axis=-1)
    near, far = grass["density"]
    density = _lerp(near, far, inverse_lerp(*grass.get("fade", [10, 60]), nearest))
    base = _weight_at(weights, terrain, 0, x, z)
    density = np.where(base >= 0.5, density * base, 0.0)
    density[terrain.path_distance(x, z) < 1.3] = 0
    for structure in terrain.structures:
        floor = structure.get("floor")
        for cx, cz in (floor or {}).get("cells", []):
            density[(np.abs(x - structure["at"][0] - cx) < 1.55) & (np.abs(z - structure["at"][1] - cz) < 1.55)] = 0
    ox, oz = terrain.world(lo, lo)
    return {"origin": [ox, oz], "cell": cell, "size": count, "density": density.astype(np.float32)}


def structures(scene, terrain, rng):
    """Structure pieces, floor tiles, rubble and props in world metres; Unity turns, aligns and grounds them."""
    planned = []
    for structure in terrain.structures:
        sx, sz = structure["at"]
        floor_y = structure.get("_plateau", float(terrain.natural(np.array(sx), np.array(sz)))) * terrain.height
        cx, cz = terrain.world(sx, sz)
        pieces = []
        for piece in structure.get("pieces", []):
            (edge, value), = (piece.get("align") or {"": 0}).items()  # one edge, such as max_z: 6
            pieces.append({"model": piece["model"], "x": cx + piece["at"][0], "z": cz + piece["at"][1],
                           "yaw": 0.0 if piece.get("turn") == "auto" else float(piece.get("turn", 0)),
                           "auto": piece.get("turn") == "auto", "align": edge,
                           "align_value": (cx if edge.endswith("x") else cz) + value})
        floor = structure.get("floor")
        for fx, fz in (floor or {}).get("cells", []):
            pieces.append({"model": floor["model"], "x": cx + fx, "z": cz + fz, "yaw": 90.0 * ((fx + fz + 9) % 4),
                           "auto": False, "align": "", "align_value": 0, "floor": True})
        rubble = []
        spec = structure.get("rubble")
        if spec:
            x0, z0, x1, z1 = spec["area"]
            for _ in range(spec["count"]):
                rubble.append({"model": _pick(spec["models"], rng), "x": cx + rng.uniform(x0, x1),
                               "z": cz + rng.uniform(z0, z1), "yaw": rng.uniform(0, 360), "scale": rng.uniform(*spec["scale"])})
        props = [{"model": p["model"], "x": cx + p["at"][0], "z": cz + p["at"][1], "y": floor_y + p.get("above_floor", 0),
                  "height": p["height"], "yaw": float(p.get("turn", 0))} for p in structure.get("props", [])]
        planned.append({"id": structure["id"], "x": cx, "z": cz, "floor_y": floor_y, "pieces": pieces, "rubble": rubble,
                        "props": props})
    return planned


def stills(scene, terrain):
    out = []
    for still in scene["cameras"].get("stills", []):
        (fx, fh, fz), (tx, th, tz) = still["from"], still["to"]
        out.append({"name": still["name"], "fov": still.get("fov", 50),
                    "from": [terrain.world(fx, fz)[0], float(terrain.ground(fx, fz)) + fh, terrain.world(fx, fz)[1]],
                    "to": [terrain.world(tx, tz)[0], float(terrain.ground(tx, tz)) + th, terrain.world(tx, tz)[1]]})
    return out


def validate_scene(scene, child_ids):
    """Fail early on a scene block that names unknown children or misses required parts."""
    if not isinstance(scene, dict):
        raise ValueError("Recipe scene must be a mapping")

    def walk(value, where):
        # YAML 1.1 reads keys such as on, off, yes and no as true or false: a prop's "on" height was silently lost.
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, bool):
                    raise ValueError(f"Recipe scene key at {where} reads as {key}; quote it or rename it")
                walk(item, f"{where}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{where}[{index}]")
    walk(scene, "scene")
    for key in ("terrain", "cameras"):
        if key not in scene:
            raise ValueError(f"Recipe scene needs {key}")
    layers = scene["terrain"].get("layers") or []
    if not layers:
        raise ValueError("Recipe scene terrain needs at least one layer")
    plants = scene.get("plants", {})
    named = {layer["surface"] for layer in layers}
    for plant in plants.values():
        named |= {plant["bark"], *plant["foliage"]}
    for entry in scene.get("cover", []):
        named.add(entry["foliage"])
    if scene.get("grass", {}).get("layer") and scene["grass"]["layer"] not in {layer["surface"] for layer in layers}:
        raise ValueError(f"Recipe scene grass layer {scene['grass']['layer']!r} is not a terrain layer")
    for structure in scene.get("structures", []):
        named |= {piece["model"] for piece in structure.get("pieces", [])}
        named |= {prop["model"] for prop in structure.get("props", [])}
        named |= set((structure.get("rubble") or {}).get("models", []))
        if structure.get("floor"):
            named.add(structure["floor"]["model"])
    for entry in scene.get("scatter", []):
        named |= {name for name in entry["assets"] if name not in plants}
    unknown = sorted(named - set(child_ids))
    if unknown:
        raise ValueError(f"Recipe scene names unknown children: {', '.join(unknown)}")
    return scene
