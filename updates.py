"""Update check against GitHub Releases. Read-only: it never installs anything by itself.

The launcher shows a banner when a newer version exists. If the person clicks
Update, the new installer is downloaded to a temp file, its SHA-256 is checked
against the release's SHA256SUMS.txt, and only then is it started.
"""

import hashlib
import json
import os
import re
import tempfile
import urllib.request

import lol_coach

INSTALLER_NAME = "MacroGoblin-Setup.exe"
SUMS_NAME = "SHA256SUMS.txt"


def parse_version(text):
    numbers = re.findall(r"\d+", str(text or ""))[:3]
    return tuple(int(n) for n in numbers) + (0,) * (3 - len(numbers)) if numbers else (0, 0, 0)


def latest_release(timeout=6):
    """{'version', 'url', 'installer', 'sums', 'notes'} for the newest release, or None."""
    req = urllib.request.Request(lol_coach.RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "MacroGoblin/%s" % lol_coach.__version__,
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.load(response)
    assets = {asset.get("name"): asset.get("browser_download_url") for asset in data.get("assets") or []}
    return {
        "version": (data.get("tag_name") or "").lstrip("v"),
        "url": data.get("html_url") or lol_coach.REPO_URL + "/releases/latest",
        "installer": assets.get(INSTALLER_NAME),
        "sums": assets.get(SUMS_NAME),
        "notes": data.get("body") or "",
    }


def newer_than_current(release):
    return bool(release) and parse_version(release["version"]) > parse_version(lol_coach.__version__)


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "MacroGoblin/%s" % lol_coach.__version__})
    return urllib.request.urlopen(req, timeout=timeout)


def download_installer(release, progress=None):
    """Download and verify the installer. Returns its path. Raises on any mismatch."""
    if not release or not release.get("installer") or not release.get("sums"):
        raise RuntimeError("This release has no installer to download.")
    with _get(release["sums"], timeout=15) as response:
        sums = response.read().decode("utf-8", "replace")
    expected = None
    for line in sums.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == INSTALLER_NAME:
            expected = parts[0].lower()
    if not expected:
        raise RuntimeError("No checksum published for the installer.")
    target = os.path.join(tempfile.gettempdir(), "MacroGoblin-Setup-%s.exe" % release["version"])
    digest = hashlib.sha256()
    with _get(release["installer"]) as response, open(target + ".part", "wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / float(total))
    if digest.hexdigest().lower() != expected:
        os.remove(target + ".part")
        raise RuntimeError("Download failed its checksum. Nothing was installed.")
    os.replace(target + ".part", target)
    return target
