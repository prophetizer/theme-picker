import unittest

from picker import colour as c

WHITE, BLACK = (255, 255, 255), (0, 0, 0)


def close(a, b, places=1):
    return all(abs(x - y) < 10 ** -places for x, y in zip(a, b))


class StopParsing(unittest.TestCase):
    def test_hex_lengths(self):
        self.assertEqual(c.stops("#abc"), [(0xaa, 0xbb, 0xcc)])
        self.assertEqual(c.stops("#aabbcc"), [(0xaa, 0xbb, 0xcc)])
        # 4 and 8 digits carry alpha: kept when at least half opaque.
        self.assertEqual(c.stops("#abcd"), [(0xaa, 0xbb, 0xcc)])
        self.assertEqual(c.stops("#aabbcc80"), [(0xaa, 0xbb, 0xcc)])     # 0x80/255 = 0.502
        self.assertEqual(c.stops("#aabbcc7f"), [])                       # 0x7f/255 = 0.498
        (rgb, a), = c.stops_alpha("#aabbcc33")
        self.assertEqual(rgb, (0xaa, 0xbb, 0xcc))
        self.assertAlmostEqual(a, 0x33 / 255)

    def test_hex_needs_a_word_boundary(self):
        # Five hex digits is no colour at all, not a 3-digit one plus junk.
        self.assertEqual(c.stops("#abcde"), [])

    def test_rgb_and_rgba(self):
        self.assertEqual(c.stops("rgb(10, 20, 30)"), [(10.0, 20.0, 30.0)])
        self.assertEqual(c.stops("rgb(10 20 30)"), [(10.0, 20.0, 30.0)])
        self.assertEqual(c.stops("rgba(10, 20, 30, 0.4)"), [])
        self.assertEqual(c.stops("rgba(10, 20, 30, .6)"), [(10.0, 20.0, 30.0)])
        (rgb, a), = c.stops_alpha("rgb(1 2 3 / 60%)")
        self.assertEqual((rgb, round(a, 3)), ((1.0, 2.0, 3.0), 0.6))

    def test_rgb_percentages(self):
        (rgb,) = c.stops("rgb(100%, 50%, 0%)")
        self.assertTrue(close(rgb, (255, 127.5, 0)))
        self.assertEqual(c.stops("rgba(0%, 0%, 0%, 40%)"), [])

    def test_hsl_and_hsla(self):
        (rgb,) = c.stops("hsl(120, 100%, 50%)")
        self.assertTrue(close(rgb, (0, 255, 0)))
        (rgb,) = c.stops("hsl(240deg 100% 50%)")
        self.assertTrue(close(rgb, (0, 0, 255)))
        (rgb,) = c.stops("hsl(480, 100%, 50%)")                  # hue wraps
        self.assertTrue(close(rgb, (0, 255, 0)))
        self.assertEqual(c.stops("hsla(0, 100%, 50%, 0.2)"), [])
        (rgb, a), = c.stops_alpha("hsla(0deg 100% 50% / 20%)")
        self.assertTrue(close(rgb, (255, 0, 0)))
        self.assertAlmostEqual(a, 0.2)

    def test_channels_are_clamped(self):
        self.assertEqual(c.stops("rgb(300, 0, 0)"), [(255.0, 0.0, 0.0)])

    def test_gradient_stops_in_order(self):
        self.assertEqual(c.stops("linear-gradient(90deg, #000 0%, #fff 100%)"), [BLACK, WHITE])

    def test_bare_triple(self):
        # theme.park's --accent-color is a bare "R, G, B"; not a CSS colour
        # on its own, so it has its own pattern.
        self.assertEqual(c.TRIPLE.fullmatch("48, 164, 108").groups(), ("48", "164", "108"))
        self.assertEqual(c.stops("48, 164, 108"), [])


class VarExpansion(unittest.TestCase):
    def test_inline_var_references(self):
        d = c.decls("""
            --a: #ffffff;
            --b: var(--a);
            --c: var(--missing, #000000);
            --g: linear-gradient(90deg, var(--a) 0%, var(--b) 100%);
            --deep: var(--b);
        """)
        self.assertEqual(d["--b"], "#ffffff")
        self.assertEqual(d["--c"], "#000000")
        self.assertEqual(d["--g"], "linear-gradient(90deg, #ffffff 0%, #ffffff 100%)")
        self.assertEqual(d["--deep"], "#ffffff")

    def test_self_reference_terminates(self):
        d = c.decls("--loop: var(--loop);")
        self.assertIn("--loop", d)                      # bounded, no RecursionError


class Compositing(unittest.TestCase):
    OVERLAY = ("linear-gradient(rgba(10, 10, 20, 0.85), rgba(10, 10, 20, 0.85)), "
               "linear-gradient(135deg, #ff5fa2 0%, #ffd166 100%) center center/cover no-repeat fixed")

    def test_layers_split_only_top_level_commas(self):
        ls = c.layers(self.OVERLAY)
        self.assertEqual(len(ls), 2)
        self.assertIn("rgba(10, 10, 20, 0.85)", ls[0])
        self.assertIn("#ffd166", ls[1])

    def test_layers_without_colour_are_dropped(self):
        self.assertEqual(len(c.layers("url(noise.png), #123456")), 1)

    def test_blackberry_overlay_comes_out_dark(self):
        bottom = c.stops(c.layers(self.OVERLAY)[-1])
        self.assertGreater(sum(map(c.lum, bottom)) / len(bottom), 0.35)   # the gradient alone is light
        shown = c.surface(self.OVERLAY)
        self.assertEqual(len(shown), 2)                                    # one per bottom stop
        for rgb in shown:
            self.assertLess(c.lum(rgb), 0.05)

    def test_single_layer_is_unchanged(self):
        self.assertEqual(c.surface("#ffffff"), [WHITE])
        self.assertEqual(c.surface("linear-gradient(#000, #fff)"), [BLACK, WHITE])

    def test_translucent_only_background_has_no_surface(self):
        self.assertEqual(c.surface("rgba(0, 0, 0, 0.2)"), [])
        self.assertEqual(c.surface(""), [])
        self.assertEqual(c.surface(None), [])


class Contrast(unittest.TestCase):
    def test_extremes(self):
        self.assertAlmostEqual(c.contrast(WHITE, BLACK), 21.0)
        self.assertAlmostEqual(c.contrast(BLACK, WHITE), 21.0)
        self.assertAlmostEqual(c.contrast((119, 119, 119), (119, 119, 119)), 1.0)

    def test_known_pairs(self):
        # #777 on white is the textbook "just fails AA" grey.
        self.assertAlmostEqual(c.contrast((0x77,) * 3, WHITE), 4.48, places=2)
        self.assertAlmostEqual(c.contrast((0x76,) * 3, WHITE), 4.54, places=2)

    def test_luminance(self):
        self.assertEqual(c.lum(BLACK), 0)
        self.assertAlmostEqual(c.lum(WHITE), 1.0)


class Families(unittest.TestCase):
    CASES = [
        ((255, 0, 0), "red"), ((255, 0, 40), "red"), ((255, 128, 0), "orange"),
        ((255, 220, 0), "yellow"), ((48, 164, 108), "green"), ((0, 200, 200), "cyan"),
        ((0, 0, 255), "blue"), ((0, 144, 255), "blue"), ((128, 0, 255), "purple"),
        ((255, 0, 200), "pink"), ((128, 128, 128), "neutral"), ((10, 5, 5), "neutral"),
        ((250, 248, 252), "neutral"), ((140, 130, 125), "neutral"),
    ]

    def test_buckets(self):
        for rgb, want in self.CASES:
            with self.subTest(rgb=rgb):
                self.assertEqual(c.family(rgb)[0], want)

    def test_neutral_has_no_hue(self):
        self.assertEqual(c.family((128, 128, 128)), ("neutral", 0.0))

    def test_every_family_has_a_swatch(self):
        names = {n for n, _ in c.FAMILIES}
        self.assertEqual(names, {want for _, want in self.CASES})


class HexHelpers(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(c.hex_rgb("#1a2b3c"), (0x1a, 0x2b, 0x3c))
        self.assertEqual(c.to_hex((0x1a, 0x2b, 0x3c)), "#1a2b3c")
        self.assertEqual(c.to_hex((10.4, 10.6, 255.0)), "#0a0bff")


if __name__ == "__main__":
    unittest.main()
