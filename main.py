#!/usr/bin/env python3
"""Neon Koi Ascending - make.fun coolest-art-01 entry.

A program that draws one piece of art and writes it to /output/entry.png:
a giant koi fish made of glowing circuitry swimming up through a night sky
past a full moon, over a lantern-lit village far below.

Pure Python 3.13 standard library (no network, no third-party packages),
fully deterministic: the same bytes come out on every run.
"""

import math
import os
import random
import struct
import zlib
from pathlib import Path

W = H = 1024
SEED = 20261113


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    return (
        int(lerp(c1[0], c2[0], t)),
        int(lerp(c1[1], c2[1], t)),
        int(lerp(c1[2], c2[2], t)),
    )


class Canvas:
    def __init__(self):
        self.buf = bytearray(W * H * 3)

    def _off(self, x, y):
        return (y * W + x) * 3

    def blend_px(self, x, y, color, alpha):
        if x < 0 or x >= W or y < 0 or y >= H or alpha <= 0.0:
            return
        o = self._off(x, y)
        buf = self.buf
        ia = 1.0 - alpha
        buf[o] = int(buf[o] * ia + color[0] * alpha)
        buf[o + 1] = int(buf[o + 1] * ia + color[1] * alpha)
        buf[o + 2] = int(buf[o + 2] * ia + color[2] * alpha)

    def fill_row(self, y, color):
        o = y * W * 3
        self.buf[o:o + W * 3] = bytes(color) * W

    def disc(self, cx, cy, r, color):
        """Opaque filled circle, fast slice fills."""
        r = int(r)
        cx = int(cx)
        cy = int(cy)
        buf = self.buf
        cr, cg, cb = color
        row = bytes((cr, cg, cb))
        for y in range(max(0, cy - r), min(H, cy + r + 1)):
            dy = y - cy
            dx = int(math.sqrt(max(0, r * r - dy * dy)))
            x0 = max(0, cx - dx)
            x1 = min(W, cx + dx + 1)
            if x1 > x0:
                o = (y * W + x0) * 3
                buf[o:o + (x1 - x0) * 3] = row * (x1 - x0)

    def disc_alpha(self, cx, cy, r, color, alpha):
        """Soft translucent disc (radial falloff)."""
        r = int(r)
        cx = int(cx)
        cy = int(cy)
        buf = self.buf
        cr, cg, cb = color
        for y in range(max(0, cy - r), min(H, cy + r + 1)):
            dy = y - cy
            dx = int(math.sqrt(max(0, r * r - dy * dy)))
            x0 = max(0, cx - dx)
            x1 = min(W, cx + dx + 1)
            for x in range(x0, x1):
                d = math.sqrt((x - cx) ** 2 + dy * dy) / r
                a = alpha * max(0.0, 1.0 - d * d)
                if a <= 0.01:
                    continue
                o = (y * W + x) * 3
                ia = 1.0 - a
                buf[o] = int(buf[o] * ia + cr * a)
                buf[o + 1] = int(buf[o + 1] * ia + cg * a)
                buf[o + 2] = int(buf[o + 2] * ia + cb * a)

    def thick_line(self, x0, y0, x1, y1, color, width, alpha=1.0):
        steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 1.5) + 1
        for i in range(steps + 1):
            t = i / steps
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            if alpha >= 1.0:
                self.disc(x, y, width / 2.0, color)
            else:
                self.disc_alpha(x, y, width / 2.0, color, alpha)

    def poly(self, points, color, alpha=1.0):
        """Scanline-filled polygon."""
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        y0 = max(0, int(min(ys)))
        y1 = min(H - 1, int(max(ys)) + 1)
        n = len(points)
        for y in range(y0, y1 + 1):
            xs = []
            for i in range(n):
                x1, y1p = points[i]
                x2, y2p = points[(i + 1) % n]
                if (y1p <= y < y2p) or (y2p <= y < y1p):
                    t = (y - y1p) / (y2p - y1p)
                    xs.append(x1 + t * (x2 - x1))
            if len(xs) < 2:
                continue
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                xa = max(0, int(xs[k]))
                xb = min(W, int(xs[k + 1]) + 1)
                if xb <= xa:
                    continue
                if alpha >= 1.0:
                    o = (y * W + xa) * 3
                    self.buf[o:o + (xb - xa) * 3] = bytes(color) * (xb - xa)
                else:
                    for x in range(xa, xb):
                        self.blend_px(x, y, color, alpha)

    def png_bytes(self):
        raw = bytearray()
        stride = W * 3
        for y in range(H):
            raw.append(0)
            raw += self.buf[y * stride:(y + 1) * stride]
        comp = zlib.compress(bytes(raw), 6)

        def chunk(kind, data):
            c = struct.pack(">I", len(data)) + kind + data
            return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", comp)
            + chunk(b"IEND", b"")
        )


def bez(p0, p1, p2, t):
    u = 1.0 - t
    return (
        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    )


def bez3(p0, p1, p2, p3, t):
    u = 1.0 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
    )


def draw_sky(cv, rng):
    stops = [
        (0.0, (7, 11, 31)),
        (0.39, (13, 19, 48)),
        (0.68, (20, 28, 66)),
        (1.0, (38, 32, 72)),
    ]
    for y in range(H):
        t = y / (H - 1)
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0]:
                f = (t - stops[i][0]) / (stops[i + 1][0] - stops[i][0])
                cv.fill_row(y, lerp_color(stops[i][1], stops[i + 1][1], f))
                break
    # nebula glows
    for (cx, cy, r, col, a) in [
        (250, 220, 260, (90, 70, 160), 0.10),
        (850, 650, 300, (30, 120, 140), 0.08),
        (500, 150, 200, (140, 60, 120), 0.06),
    ]:
        cv.disc_alpha(cx, cy, r, col, a)
    # stars
    for _ in range(320):
        x = rng.uniform(0, W)
        y = rng.uniform(0, 880)
        b = rng.uniform(0.25, 1.0)
        s = 1 if rng.random() < 0.8 else 2
        col = (int(255 * b), int(250 * b), int(235 * b))
        cv.disc(x, y, s, col)
        if rng.random() < 0.04:
            cv.thick_line(x - 6, y, x + 6, y, col, 1)
            cv.thick_line(x, y - 6, x, y + 6, col, 1)


def draw_moon(cv, rng):
    cx, cy, r = 695, 255, 185
    for rr, a in [(320, 0.05), (260, 0.07), (215, 0.09)]:
        cv.disc_alpha(cx, cy, rr, (190, 205, 240), a)
    cv.disc(cx, cy, r, (237, 240, 247))
    cv.disc_alpha(cx - 28, cy - 30, r - 14, (255, 255, 255), 0.35)
    for _ in range(22):
        a = rng.uniform(0, 2 * math.pi)
        d = rng.uniform(0, r * 0.82)
        x = cx + math.cos(a) * d
        y = cy + math.sin(a) * d
        cr = rng.uniform(6, 22)
        cv.disc_alpha(x, y, cr, (199, 204, 217), rng.uniform(0.25, 0.5))
    # bright rim on the upper-left edge
    for i in range(14):
        a = math.pi * (0.62 + 0.30 * i / 13)
        x = cx + math.cos(a) * (r - 4)
        y = cy + math.sin(a) * (r - 4)
        cv.disc_alpha(x, y, 7, (255, 255, 255), 0.5)


def draw_village(cv, rng):
    # warm horizon glow behind the hills
    for y in range(860, 940, 4):
        cv.disc_alpha(512, y, 520, (255, 170, 90), 0.012)
    # far hill
    pts = [(0, 1024)]
    for x in range(0, W + 1, 32):
        pts.append((x, 905 + 26 * math.sin(x / 260.0 + 0.7)))
    pts.append((W, 1024))
    cv.poly(pts, (10, 15, 36))
    # near hill
    pts = [(0, 1024)]
    for x in range(0, W + 1, 32):
        pts.append((x, 950 + 20 * math.sin(x / 190.0 + 2.1)))
    pts.append((W, 1024))
    cv.poly(pts, (8, 11, 28))
    # warm windows, clustered into village groups
    for (gx, gy, n) in [(150, 965, 22), (430, 975, 26),
                        (700, 960, 20), (900, 972, 24)]:
        for _ in range(n):
            x = gx + rng.uniform(-70, 70)
            y = gy + rng.uniform(-14, 22)
            w = rng.choice([2, 3, 3, 4])
            col = rng.choice([(255, 202, 106), (255, 179, 71),
                              (255, 220, 150)])
            cv.disc(x, y, w, col)
            if rng.random() < 0.3:
                cv.disc_alpha(x, y, w + 5, col, 0.25)
    # roof silhouettes: dark house bodies with lit roof edges + windows
    for (rx, ry, rw, rh) in [(120, 948, 70, 26), (430, 958, 86, 30),
                             (700, 944, 64, 24), (880, 956, 78, 28)]:
        cv.poly([(rx + 6, ry), (rx + rw - 6, ry),
                 (rx + rw - 6, ry + 20), (rx + 6, ry + 20)], (5, 8, 20))
        cv.poly([(rx, ry), (rx + rw / 2, ry - rh), (rx + rw, ry)],
                (6, 9, 22))
        cv.thick_line(rx, ry, rx + rw / 2, ry - rh, (255, 190, 90), 2)
        cv.thick_line(rx + rw / 2, ry - rh, rx + rw, ry,
                      (255, 190, 90), 2)
        for _ in range(3):
            cv.disc(rx + rng.uniform(12, rw - 12), ry + rng.uniform(4, 15),
                    2, (255, 202, 106))
    # low mist, kept faint so it never reads as a shape
    for y in range(905, 950, 4):
        cv.disc_alpha(512, y, 400, (180, 190, 230), 0.006)
    # low mist
    for y in range(900, 960, 3):
        cv.disc_alpha(512, y, 480, (180, 190, 230), 0.012)


def koi_path(t):
    return bez3((250, 850), (360, 720), (560, 600), (720, 330), t)


def koi_width(t):
    base = max(24.0, 28 + 72 * math.sin(math.pi * (0.12 + 0.88 * t)) ** 1.15)
    return base + 30 * t * t * t


def draw_koi(cv, rng):
    steps = 110
    pts = [koi_path(i / steps) for i in range(steps + 1)]
    # neon halo
    for i in range(0, steps + 1, 4):
        t = i / steps
        x, y = pts[i]
        cv.disc_alpha(x, y, koi_width(t) * 1.55, (53, 224, 230), 0.05)
        cv.disc_alpha(x, y, koi_width(t) * 1.25, (255, 92, 168), 0.04)
    # body: overlapping discs, colour shifts tail -> head
    for i in range(steps + 1):
        t = i / steps
        x, y = pts[i]
        col = lerp_color(
            lerp_color((13, 70, 88), (16, 150, 160), min(1.0, t * 1.6)),
            (24, 130, 128), max(0.0, (t - 0.6) / 0.4) * 0.5)
        cv.disc(x, y, koi_width(t), col)
    # belly highlight (gold, lower edge) and back shade
    for i in range(0, steps + 1, 2):
        t = i / steps
        x, y = pts[i]
        w = koi_width(t)
        cv.disc_alpha(x + w * 0.18, y + w * 0.42, w * 0.30,
                      (242, 182, 68), 0.35)
        cv.disc_alpha(x - w * 0.22, y - w * 0.40, w * 0.45,
                      (6, 24, 48), 0.45)
    # scales: staggered rows inside the body, small and close in tone
    for row in range(30):
        t = 0.08 + 0.85 * row / 29
        x, y = koi_path(t)
        w = koi_width(t)
        offs = [-0.5, -0.25, 0.0, 0.25, 0.5]
        if row % 2:
            offs = [-0.38, -0.13, 0.13, 0.38]
        for o in offs:
            sx = x + o * w * 1.5
            sy = y + o * w * 0.9
            shade = rng.choice([(22, 170, 178), (14, 130, 140),
                                (30, 190, 196)])
            cv.disc_alpha(sx, sy, max(4.0, w * 0.10), shade, 0.55)
    # circuit traces along the body
    for lat, col in [(-0.30, (255, 215, 106)), (0.05, (55, 224, 230)),
                     (0.32, (255, 215, 106))]:
        prev = None
        for i in range(6, steps - 4, 7):
            t = i / steps
            x, y = koi_path(t)
            w = koi_width(t)
            p = (x + lat * w * 1.4, y + lat * w * 0.8)
            if prev is not None:
                cv.thick_line(prev[0], prev[1], p[0], p[1], col, 3)
            prev = p
        # chip squares on the trace
        for i in range(14, steps - 4, 23):
            t = i / steps
            x, y = koi_path(t)
            w = koi_width(t)
            qx = x + lat * w * 1.4
            qy = y + lat * w * 0.8
            cv.poly([(qx - 6, qy - 6), (qx + 6, qy - 6),
                     (qx + 6, qy + 6), (qx - 6, qy + 6)], col)
    # tail ribbons flowing down-left from the tail tip
    tx, ty = pts[0]
    for (dx, dy, col, wd) in [(-260, 90, (55, 224, 230), 22),
                              (-210, 180, (255, 92, 168), 18),
                              (-300, 10, (255, 207, 92), 15)]:
        mx, my = tx + dx * 0.55, ty + dy * 0.55 + 40
        ex, ey = tx + dx, ty + dy
        for i in range(30):
            t = i / 29
            x, y = bez((tx, ty), (mx, my), (ex, ey), t)
            cv.disc_alpha(x, y, wd * (1 - t * 0.7),
                          col, 0.75 * (1 - t * 0.55))
    # pectoral fin: slim swept-back fin hugging the lower body edge
    mx, my = koi_path(0.48)
    w = koi_width(0.48)
    bx, by = mx + w * 0.15, my + w * 0.55
    tipx, tipy = mx - w * 0.75, my + w * 1.45
    fin = [(bx, by),
           (bx + w * 0.45, by + w * 0.55),
           (tipx + w * 0.25, tipy - w * 0.15),
           (tipx, tipy),
           (bx - w * 0.25, by + w * 0.85)]
    cv.poly(fin, (55, 224, 230), 0.5)
    cv.thick_line(bx, by, tipx, tipy, (255, 150, 200), 2)
    cv.thick_line(bx + w * 0.1, by + w * 0.2,
                  tipx + w * 0.15, tipy - w * 0.1, (200, 240, 245), 1)
    # dorsal ridge: low glowing beads along the back edge
    for i in range(20, 62, 3):
        t = i / steps
        x, y = pts[i]
        w = koi_width(t)
        cv.disc_alpha(x - w * 0.55, y - w * 0.72, w * 0.16,
                      (55, 224, 230), 0.6)
    # head + eye: a rounder, bigger head than the body taper alone gives
    hx, hy = koi_path(0.97)
    hw = koi_width(0.97)
    cv.disc(hx - hw * 0.1, hy + hw * 0.08, hw * 1.02, (20, 140, 148))
    cv.disc_alpha(hx - hw * 0.1, hy + hw * 0.08, hw * 0.7,
                  (40, 190, 195), 0.5)
    ex, ey = hx + hw * 0.30, hy - hw * 0.32
    cv.disc(ex, ey, 20, (255, 215, 106))
    cv.disc(ex, ey, 12, (8, 14, 26))
    cv.disc(ex - 4, ey - 4, 4, (255, 255, 255))
    # mouth curve under the eye
    cv.thick_line(hx + hw * 0.55, hy + hw * 0.30,
                  hx + hw * 0.80, hy + hw * 0.10, (10, 40, 60), 3)
    # barbels drooping from the mouth
    cv.thick_line(hx + hw * 0.55, hy + hw * 0.35,
                  hx + hw * 0.95, hy + hw * 1.05, (255, 215, 106), 3)
    cv.thick_line(hx + hw * 0.45, hy + hw * 0.50,
                  hx + hw * 0.70, hy + hw * 1.15, (255, 215, 106), 2)
    # sparkles around the koi
    for _ in range(46):
        t = rng.uniform(0, 1)
        x, y = koi_path(t)
        w = koi_width(t)
        sx = x + rng.uniform(-1.6, 1.6) * w
        sy = y + rng.uniform(-1.6, 1.6) * w
        col = rng.choice([(255, 255, 255), (55, 224, 230),
                          (255, 207, 92)])
        r = rng.uniform(2, 7)
        cv.thick_line(sx - r, sy, sx + r, sy, col, 1)
        cv.thick_line(sx, sy - r, sx, sy + r, col, 1)


def main():
    rng = random.Random(SEED)
    cv = Canvas()
    draw_sky(cv, rng)
    draw_moon(cv, rng)
    draw_village(cv, rng)
    draw_koi(cv, rng)
    data = cv.png_bytes()
    out_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "entry.png"
    target.write_bytes(data)
    print(f"wrote {target} ({len(data)} bytes, {W}x{H})")


if __name__ == "__main__":
    main()
