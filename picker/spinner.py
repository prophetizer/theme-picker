"""Standard-library CSS filter solver for Petio's spinner: a verbatim copy of
theme-park-themes' tools/spinner_spsa.py (itself a port of the editor's
solveFilter in web/app.js). Seeded from the colour, so a colour always gets
the same filter.
"""
import math
import random
import sys


def _clamp(v):
    return 255.0 if v > 255 else 0.0 if v < 0 else v


class _Colour:
    def __init__(self, r, g, b):
        self.set(r, g, b)

    def set(self, r, g, b):
        self.r, self.g, self.b = _clamp(r), _clamp(g), _clamp(b)

    def mul(self, m):
        r, g, b = self.r, self.g, self.b
        self.r = _clamp(r * m[0] + g * m[1] + b * m[2])
        self.g = _clamp(r * m[3] + g * m[4] + b * m[5])
        self.b = _clamp(r * m[6] + g * m[7] + b * m[8])

    def hue_rotate(self, a):
        a = a / 180 * math.pi
        s, c = math.sin(a), math.cos(a)
        self.mul([0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715, 0.072 - c * 0.072 + s * 0.928,
                  0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.140, 0.072 - c * 0.072 - s * 0.283,
                  0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715, 0.072 + c * 0.928 + s * 0.072])

    def sepia(self, v):
        self.mul([0.393 + 0.607 * (1 - v), 0.769 - 0.769 * (1 - v), 0.189 - 0.189 * (1 - v),
                  0.349 - 0.349 * (1 - v), 0.686 + 0.314 * (1 - v), 0.168 - 0.168 * (1 - v),
                  0.272 - 0.272 * (1 - v), 0.534 - 0.534 * (1 - v), 0.131 + 0.869 * (1 - v)])

    def saturate(self, v):
        self.mul([0.213 + 0.787 * v, 0.715 - 0.715 * v, 0.072 - 0.072 * v,
                  0.213 - 0.213 * v, 0.715 + 0.285 * v, 0.072 - 0.072 * v,
                  0.213 - 0.213 * v, 0.715 - 0.715 * v, 0.072 + 0.928 * v])

    def linear(self, sl, ic=0.0):
        self.r = _clamp(self.r * sl + ic * 255)
        self.g = _clamp(self.g * sl + ic * 255)
        self.b = _clamp(self.b * sl + ic * 255)

    def invert(self, v):
        self.r = _clamp((v + self.r / 255 * (1 - 2 * v)) * 255)
        self.g = _clamp((v + self.g / 255 * (1 - 2 * v)) * 255)
        self.b = _clamp((v + self.b / 255 * (1 - 2 * v)) * 255)

    def hsl(self):
        r, g, b = self.r / 255, self.g / 255, self.b / 255
        mx, mn = max(r, g, b), min(r, g, b)
        h = s = 0.0
        l = (mx + mn) / 2
        if mx != mn:
            d = mx - mn
            s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
            if mx == r:
                h = (g - b) / d + (6 if g < b else 0)
            elif mx == g:
                h = (b - r) / d + 2
            else:
                h = (r - g) / d + 4
            h /= 6
        return h * 100, s * 100, l * 100


def solve_filter(hexcol):
    """The filter chain for '#rrggbb', in the editor's exact output format."""
    h = hexcol.lstrip("#").lower()
    if len(h) != 6 or any(ch not in "0123456789abcdef" for ch in h):
        raise ValueError(f"not a #rrggbb colour: {hexcol!r}")
    t = _Colour(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    th = t.hsl()
    col = _Colour(0, 0, 0)
    rng = random.Random(h)

    def loss(f):
        col.set(255, 255, 255)
        col.invert(f[0] / 100)
        col.sepia(f[1] / 100)
        col.saturate(f[2] / 100)
        col.hue_rotate(f[3] * 3.6)
        col.linear(f[4] / 100)
        col.linear(f[5] / 100, -(0.5 * f[5] / 100) + 0.5)
        ch = col.hsl()
        return (abs(col.r - t.r) + abs(col.g - t.g) + abs(col.b - t.b)
                + abs(ch[0] - th[0]) + abs(ch[1] - th[1]) + abs(ch[2] - th[2]))

    def fix(v, i):
        mx = 7500 if i == 2 else 200 if i in (4, 5) else 100
        if i == 3:
            if v > mx:
                v = math.fmod(v, mx)
            elif v < 0:
                v = mx + math.fmod(v, mx)
            return v
        return min(mx, max(0, v))

    def spsa(A, a, c, vals, iters):
        vals = list(vals)
        best, best_l = None, math.inf
        for k in range(iters):
            ck = c / (k + 1) ** (1 / 6)
            d = [1 if rng.random() > 0.5 else -1 for _ in range(6)]
            hi = [vals[i] + ck * d[i] for i in range(6)]
            lo = [vals[i] - ck * d[i] for i in range(6)]
            ld = loss(hi) - loss(lo)
            for i in range(6):
                vals[i] = fix(vals[i] - a[i] / (A + k + 1) * ld / (2 * ck) * d[i], i)
            l = loss(vals)
            if l < best_l:
                best, best_l = list(vals), l
        return best, best_l

    best, best_l = None, math.inf
    for _run in range(4):
        if best_l <= 1:
            break
        wide, wide_l = None, math.inf
        for _ in range(3):
            if wide_l <= 25:
                break
            v, l = spsa(5, [60, 180, 18000, 600, 1.2, 1.2], 15, [50, 20, 3750, 50, 100, 100], 1000)
            if l < wide_l:
                wide, wide_l = v, l
        a1 = wide_l + 1
        v, l = spsa(wide_l, [0.25 * a1, 0.25 * a1, a1, 0.25 * a1, 0.2 * a1, 0.2 * a1], 2, wide, 500)
        if l < best_l:
            best, best_l = v, l
    # JavaScript's Math.round: halves round up, not to even.
    r = lambda i, m=1: int(math.floor(best[i] * m + 0.5))
    return (f"invert({r(0)}%) sepia({r(1)}%) saturate({r(2)}%) hue-rotate({r(3, 3.6)}deg) "
            f"brightness({r(4)}%) contrast({r(5)}%)")

