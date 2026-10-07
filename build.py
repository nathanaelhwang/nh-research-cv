# /// script
# requires-python = ">=3.11"
# dependencies = ["pymupdf"]
# ///
"""Convert the research CV PDF into a pixel-faithful static HTML page (index.html).

Usage: uv run build.py path/to/Nathanael_Hwang_ResearchCV_YYYYMMDD.pdf

pdf2htmlEX renders every glyph with the PDF's own embedded fonts at the PDF's exact
positions; non-text graphics (rules) become an SVG background so they stay sharp at any
zoom. Its bundled viewer JavaScript is stripped: its link handler is broken for
internal links (it reads the attribute from the click target, which is the inner overlay
div). Internal links are rewritten to plain anchors placed at each destination's exact
coordinates, so the table of contents works natively, without JavaScript.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import pymupdf

ZOOM = 1.5
APPIMAGE_URL = (
    "https://github.com/pdf2htmlEX/pdf2htmlEX/releases/download/continuous/"
    "pdf2htmlEX-0.18.8.rc2-master-20200820-ubuntu-20.04-x86_64.AppImage"
)
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pdf2htmlEX"


def pdf2htmlex_cmd() -> list[str]:
    """Locate pdf2htmlEX, or fetch and extract the official AppImage into the user cache."""
    if exe := shutil.which("pdf2htmlEX"):
        return [exe]
    root = CACHE / "squashfs-root"
    if not root.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        appimage = CACHE / "pdf2htmlEX.AppImage"
        urllib.request.urlretrieve(APPIMAGE_URL, appimage)
        appimage.chmod(0o755)
        subprocess.run([appimage, "--appimage-extract"], cwd=CACHE, check=True, capture_output=True)
    data = root / "usr/local/share/pdf2htmlEX"
    return [str(root / "AppRun"), "--data-dir", str(data), "--poppler-data-dir", str(data / "poppler")]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def convert(pdf: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [*pdf2htmlex_cmd(), "--zoom", str(ZOOM), "--process-outline", "0", "--bg-format", "svg",
             "--dest-dir", tmp, str(pdf), "index.html"],
            check=True, capture_output=True,
        )
        return (Path(tmp) / "index.html").read_text(encoding="utf-8")


def internal_link_slugs(doc: pymupdf.Document) -> list[str]:
    """Anchor names for the internal links (explicit or named destinations), in document order."""
    slugs = []
    for page in doc:
        for link in page.get_links():
            if link["kind"] in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED):
                slugs.append(slugify(page.get_textbox(link["from"])))
    return slugs


def postprocess(html: str, doc: pymupdf.Document) -> str:
    # Drop the viewer JavaScript; the page is fully static.
    html, n = re.subn(r"<script>.*?</script>\s*", "", html, flags=re.S)
    assert n == 3, f"expected 3 pdf2htmlEX scripts, found {n}"
    # Viewer-only chrome: empty outline sidebar and the JS loading spinner.
    html, n = re.subn(r'<div id="sidebar">\s*<div id="outline">\s*</div>\s*</div>\s*', "", html)
    assert n == 1, "sidebar markup not found"
    html, n = re.subn(r'<div class="loading-indicator">.*?</div>\s*', "", html, flags=re.S)
    assert n == 1, "loading indicator markup not found"

    # pdf2htmlEX leaves <title> empty; use the PDF's own title, as a PDF viewer would.
    html = html.replace("<title></title>", f"<title>{doc.metadata['title']}</title>", 1)

    # Rewrite internal links to named anchors at the exact destination coordinates.
    slugs = iter(internal_link_slugs(doc))
    anchors: dict[int, list[str]] = {}

    def relink(m: re.Match) -> str:
        page_no, kind, x, y, _ = json.loads(m.group(1))
        assert kind == "XYZ", kind
        slug = next(slugs)
        top = (doc[page_no - 1].rect.height - y) * ZOOM
        anchor = f'<span id="{slug}" style="position:absolute;left:{x * ZOOM:g}px;top:{top:g}px"></span>'
        if anchor not in anchors.setdefault(page_no, []):
            anchors[page_no].append(anchor)
        return f'<a class="l" href="#{slug}">'

    html = re.sub(r"""<a class="l" href="#pf[0-9a-f]+" data-dest-detail='([^']*)'>""", relink, html)
    assert next(slugs, None) is None, "internal link count mismatch between PDF and HTML"

    for page_no, spans in anchors.items():
        opener = f'<div id="pf{page_no:x}" class="pf w0 h0" data-page-no="{page_no:x}">'
        assert opener in html, opener
        html = html.replace(opener, opener + "".join(spans), 1)
    return html


def main() -> None:
    pdf = Path(sys.argv[1])
    doc = pymupdf.open(pdf)
    out = Path(__file__).with_name("index.html")
    out.write_text(postprocess(convert(pdf), doc), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
