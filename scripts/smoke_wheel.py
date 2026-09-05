"""Run outside the checkout, using a fresh environment containing the wheel."""

from importlib.metadata import version

from fastapi.testclient import TestClient

import adsb
from adsb.ui import STATIC_DIR, create_ui_app, frontend_is_bundled

assert adsb.__version__ == version("adsb-map")
assert frontend_is_bundled()
with TestClient(create_ui_app("http://127.0.0.1:8000")) as client:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert client.get("/config.js").status_code == 200
    for asset in (STATIC_DIR / "assets").iterdir():
        if asset.suffix in {".js", ".css"}:
            assert client.get(f"/assets/{asset.name}").status_code == 200
print(f"Installed adsb-map {adsb.__version__}: CLI package and bundled UI are usable")
