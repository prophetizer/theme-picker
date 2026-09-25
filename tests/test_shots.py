import os

from picker import shots
from tests.support import SandboxCase


class ShotGuard(SandboxCase):
    def setUp(self):
        super().setUp()
        self.thumbs = shots.SHOT_DIR / "thumbs"
        self.full = shots.SHOT_DIR / "per-app"
        self.thumbs.mkdir(parents=True)
        self.full.mkdir(parents=True)
        (self.thumbs / "dozzle_nord.jpg").write_bytes(b"jpg")
        (self.full / "dozzle_nord.png").write_bytes(b"png")
        # Something a traversal would like to reach.
        (self.dir / "config.env").write_text("secret")

    def test_serves_real_captures(self):
        f, ctype = shots.shot_file("/shots/thumb/dozzle_nord.jpg")
        self.assertEqual((f.read_bytes(), ctype), (b"jpg", "image/jpeg"))
        f, ctype = shots.shot_file("/shots/full/dozzle_nord.png")
        self.assertEqual((f.read_bytes(), ctype), (b"png", "image/png"))

    def test_refuses(self):
        for path in (
            "/shots/thumb/../config.env",                  # traversal
            "/shots/thumb/../../config.env",
            "/shots/thumb/..%2f..%2fconfig.env",           # encoded traversal (paths are never unquoted)
            "/shots/thumb/%2e%2e_x.jpg",
            "/shots/thumb/dozzle_nord.png",                # wrong extension for the kind
            "/shots/full/dozzle_nord.jpg",
            "/shots/thumb/dozzle_nord.jpg.png",
            "/shots/thumb/dozzle_nord",
            "/shots/other/dozzle_nord.jpg",                # wrong kind
            "/shots/thumbs/dozzle_nord.jpg",               # the directory name is not a kind
            "/shots/thumb/x/dozzle_nord.jpg",              # extra segments
            "/shots/thumb/dozzle_nord.jpg/anything",
            "/shots/thumb/",
            "/shots/thumb/Dozzle_nord.jpg",                # upper case is not a capture name
            "/shots/thumb/dozzle.jpg",                     # no <app>_<theme>
            "/shots/thumb/dozzle_dracula.jpg",             # well formed, but no such file
        ):
            with self.subTest(path=path):
                self.assertIsNone(shots.shot_file(path))

    def test_refuses_a_symlink_out_of_the_directory(self):
        os.symlink(self.dir / "config.env", self.thumbs / "evil_x.jpg")
        self.assertIsNone(shots.shot_file("/shots/thumb/evil_x.jpg"))

    def test_index_needs_both_sizes_and_follows_app_order(self):
        for app in ("guacamole", "zzz-extra", "forgejo"):
            (self.thumbs / f"{app}_nord.jpg").write_bytes(b"")
            (self.full / f"{app}_nord.png").write_bytes(b"")
        (self.thumbs / "grafana_nord.jpg").write_bytes(b"")          # no full size: left out
        self.assertEqual(shots.screenshot_index(),
                         {"nord": ["dozzle", "forgejo", "guacamole", "zzz-extra"]})
