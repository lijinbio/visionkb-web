#!/usr/bin/env python3
"""Download the aiscientist-skills release zip, verify it, and extract one skill (standard library only).

Checks: the zip's SHA-256 equals its line in the release's SHA256SUMS, and equals --zip-sha256 when given (the
digest pinned in the Dockerfile). Then extracts skills/<path>/ to --out and checks SKILL.md exists.

  python scripts/fetch_skill.py --version 0.2.1 --zip-sha256 <sha> --out /opt/visionkb-web/skill
"""

import argparse
import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPO = "lijinbio/aiscientist-skills"
SKILL = "skills/knowledge-graph/answer-eye-questions-with-visionkb-kg"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True, help="release version without v, e.g. 0.2.1")
    p.add_argument("--zip-sha256", default="", help="expected SHA-256 of the zip (pinned)")
    p.add_argument("--skill", default=SKILL, help="path of the skill folder inside the zip")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--base", default=f"https://github.com/{REPO}/releases/download")
    a = p.parse_args()
    name = f"aiscientist-skills-{a.version}.zip"
    base = f"{a.base}/v{a.version}"
    sums = fetch(f"{base}/SHA256SUMS").decode()
    listed = {ln.split()[1].lstrip("*"): ln.split()[0] for ln in sums.splitlines() if len(ln.split()) == 2}
    if name not in listed:
        sys.exit(f"{name} is not listed in SHA256SUMS")
    data = fetch(f"{base}/{name}")
    digest = hashlib.sha256(data).hexdigest()
    if digest != listed[name]:
        sys.exit(f"{name}: sha256 {digest} != SHA256SUMS {listed[name]}")
    if a.zip_sha256 and digest != a.zip_sha256:
        sys.exit(f"{name}: sha256 {digest} != pinned {a.zip_sha256}")
    prefix = a.skill.strip("/") + "/"
    n = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            rel = PurePosixPath(info.filename[len(prefix) :])
            if rel.is_absolute() or ".." in rel.parts:
                sys.exit(f"unsafe path in zip: {info.filename}")
            target = a.out.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
            n += 1
    skill_md = a.out / "SKILL.md"
    if not skill_md.is_file():
        sys.exit(f"no SKILL.md under {a.skill}")
    md = skill_md.read_bytes()
    print(
        f"{name} sha256 {digest} (SHA256SUMS ok{', pin ok' if a.zip_sha256 else ''}); {n} files; "
        f"SKILL.md {len(md)} bytes sha256 {hashlib.sha256(md).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
