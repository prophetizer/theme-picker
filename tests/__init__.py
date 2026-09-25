"""Test suite: `python3 -m unittest` from the repo root. stdlib only (plus the
PyYAML the picker already needs).

Before anything imports picker, point it at a throwaway theme-switcher
directory and switch ntfy off. picker/config.py and picker/ntfy.py read these
at import, and inside the container the real values are set -- without this a
test run there could touch live state or send a notification.
"""

import atexit
import os
import shutil
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="picker-tests-")
atexit.register(shutil.rmtree, _SANDBOX, ignore_errors=True)
os.environ["THEME_SWITCHER_DIR"] = _SANDBOX
os.environ["PICKER_CONFIG"] = os.path.join(_SANDBOX, "picker.yml")     # absent: never the real one
os.environ["DOMAIN"] = "example.test"
for _var in ("NTFY_URL", "NTFY_TOPIC", "NTFY_TOKEN_FILE"):
    os.environ.pop(_var, None)
