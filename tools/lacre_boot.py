"""Startup shim for running Lacre's tools (genlayer-py 0.16.3) and this project's tools, without
changing Lacre's code:
- trusts the operating system certificate store (truststore): some antivirus products intercept
  HTTPS with their own root, which the OS has and certifi does not;
- sends its own User-Agent: the Bradbury RPC is behind Cloudflare, which answers 403 to the default
  requests User-Agent ("python-requests/...");
- loads local machine paths from `local.env` at the repository root (not published; see
  `local.env.example`) into the environment, without overriding variables already set.

As a module: `import lacre_boot` before genlayer_py. As a launcher for another script:
    python tools/lacre_boot.py <script.py> [arguments...]
"""
import os
import runpy
import sys
from pathlib import Path

LOCAL_ENV = Path(__file__).resolve().parents[1] / "local.env"
if LOCAL_ENV.exists():
    for _line in LOCAL_ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip().strip("\"'"))

import truststore  # noqa: E402

truststore.inject_into_ssl()

import requests  # noqa: E402
import requests.sessions  # noqa: E402
import requests.utils  # noqa: E402

USER_AGENT = "tenet-tools/1 (genlayer-py)"
_default_headers = requests.utils.default_headers


def _headers():
    headers = _default_headers()
    headers["User-Agent"] = USER_AGENT
    return headers


requests.utils.default_headers = _headers
requests.sessions.default_headers = _headers

if __name__ == "__main__":
    target = sys.argv[1]
    sys.argv = sys.argv[1:]
    runpy.run_path(target, run_name="__main__")
