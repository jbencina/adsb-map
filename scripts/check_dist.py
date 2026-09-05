"""Reject incomplete distributions before uploading them to PyPI."""

import os
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path


def check_dist(dist: Path) -> None:
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Expected exactly one wheel and one sdist")

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        assets = [name for name in names if name.startswith("adsb/static/")]
        if (
            "adsb/static/index.html" not in assets
            or not any(name.endswith(".js") for name in assets)
            or not any(name.endswith(".css") for name in assets)
        ):
            raise ValueError("Wheel must contain the frontend HTML, JavaScript, and CSS")
        metadata_path = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(wheel.read(metadata_path).decode())
        if metadata["License-Expression"] != "GPL-3.0-or-later":
            raise ValueError("Wheel must declare the SPDX license expression")
        if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
            raise ValueError("Wheel is missing LICENSE")
        ref = os.environ.get("GITHUB_REF", "")
        if ref.startswith("refs/tags/v") and metadata["Version"] != ref.removeprefix("refs/tags/v"):
            raise ValueError("Distribution version does not match the release tag")

        with tarfile.open(sdists[0]) as sdist:
            members = {name.split("/", 1)[1]: name for name in sdist.getnames() if "/" in name}
            required = {
                "frontend/package.json",
                "frontend/bun.lock",
                "frontend/index.html",
                "frontend/vite.config.js",
                "frontend/src/App.jsx",
                "scripts/check_dist.py",
                "scripts/smoke_wheel.py",
                "justfile",
                "pytest.ini",
                "tox.ini",
                "uv.lock",
                ".bun-version",
                "LICENSE",
            }
            if missing := required - members.keys():
                raise ValueError(f"Source distribution is missing: {sorted(missing)}")
            if any(
                name.startswith(("frontend/node_modules/", "frontend/dist/")) for name in members
            ):
                raise ValueError("Source distribution includes frontend build/cache directories")
            for name in assets:
                if name not in members:
                    raise ValueError(f"Source distribution is missing {name}")
                with sdist.extractfile(members[name]) as source:
                    if source.read() != wheel.read(name):
                        raise ValueError(f"Frontend asset differs between wheel and sdist: {name}")
            with sdist.extractfile(members["PKG-INFO"]) as source:
                source_metadata = Parser().parsestr(source.read().decode())
            if source_metadata["Version"] != metadata["Version"]:
                raise ValueError("Wheel and sdist versions differ")

    print(f"Validated frontend assets, source files, license, and version {metadata['Version']}")


if __name__ == "__main__":
    check_dist(Path(sys.argv[1]))
