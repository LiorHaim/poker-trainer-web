"""
Guards on the prebuilt stylesheet.

Tailwind used to come from cdn.tailwindcss.com, which ships a ~123KB JIT
compiler (407KB unpacked) and rebuilds the stylesheet in the browser on every
page load. It is now built once with `make css` and committed. The risk that
introduces is drift: add a utility class to the HTML, forget to rebuild, and
the style silently does not apply.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "static" / "index.html").read_text()
CSS = (ROOT / "static" / "app.css").read_text()

#: Utility prefixes worth checking. Enough to catch a forgotten rebuild
#: without trying to reimplement Tailwind's parser.
CHECKED_PREFIXES = ("bg-", "text-", "p-", "px-", "py-", "m-", "mt-", "mb-",
                    "flex", "grid", "rounded", "border", "gap-", "w-", "h-")


def used_classes():
    classes = set()
    for attr in re.findall(r'class="([^"]+)"', HTML):
        classes.update(attr.split())
    return classes


def test_the_cdn_is_gone():
    """Matches the script tag, not the bare hostname, which the comment mentions."""
    assert not re.search(r'<script[^>]+cdn\.tailwindcss\.com', HTML), (
        "the Tailwind CDN is back; it ships a JIT compiler to every visitor"
    )


def test_the_stylesheet_is_linked_and_present():
    assert '<link rel="stylesheet" href="/app.css">' in HTML
    assert len(CSS) > 5000, "app.css looks truncated"


def test_audio_is_not_preloaded():
    """160KB of sound effects used to download before the first card was dealt."""
    assert 'preload="auto"' not in HTML


@pytest.mark.parametrize("prefix", CHECKED_PREFIXES)
def test_utilities_used_in_the_markup_are_in_the_stylesheet(prefix):
    """Catches a forgotten `make css` after adding a class."""
    missing = sorted(
        cls for cls in used_classes()
        if cls.startswith(prefix)
        and not cls.startswith(("act-", "btn-", "seat-", "suit-"))
        # Tailwind escapes special characters in selectors; normalise before looking.
        and re.sub(r"([.:/\[\]()#%])", r"\\\1", cls) not in CSS
    )
    assert not missing, (
        f"these classes are in the markup but not in app.css - run `make css`: {missing}"
    )
