"""The self-contained HTML bundle.

The bundler flattens ES modules into one script. That transformation is easy
to get subtly wrong -- the first attempt collided on a private `$` helper that
two modules both declared -- so these tests check the emitted JavaScript is
actually valid and self-sufficient, not merely that a file was produced.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from s3dash.bundle import build
from tests.conftest import SAMPLES, samples_available

CODE_BLOCK_RE = re.compile(r"<script>(.*?)</script>", re.S)

pytestmark = pytest.mark.skipif(
    not samples_available(),
    reason="bundling needs a listing to embed (see README)",
)


@pytest.fixture(scope="module")
def bundled() -> str:
    return build([SAMPLES / "case_002495.out", SAMPLES / "9074.out"])


def _code_block(html: str) -> str:
    blocks = CODE_BLOCK_RE.findall(html)
    code = [b for b in blocks if "__def(" in b]
    assert code, "no bundled code block found"
    return code[0]


class TestStructure:
    def test_is_one_complete_document(self, bundled):
        assert bundled.lstrip().lower().startswith("<!doctype html>")
        assert bundled.rstrip().endswith("</html>")

    def test_css_and_js_are_inlined(self, bundled):
        assert "<style>" in bundled
        assert 'href="/static' not in bundled
        assert 'src="/static' not in bundled
        assert 'type="module"' not in bundled

    def test_has_no_external_references(self, bundled):
        for token in ("http://", "https://", "cdn.", "unpkg", "jsdelivr"):
            assert token not in bundled, token

    def test_no_leftover_module_syntax(self, bundled):
        code = _code_block(bundled)
        assert not re.search(r"^\s*import\s", code, re.M)
        assert not re.search(r"^\s*export\s", code, re.M)


class TestEmittedJavaScript:
    def test_every_module_is_registered(self, bundled):
        code = _code_block(bundled)
        for name in ("api.js", "state.js", "coremap.js", "views.js", "charts.js",
                     "panels.js", "app.js"):
            assert f"__def('{name}'" in code, name

    def test_entry_point_is_invoked(self, bundled):
        assert "__req('app.js')" in _code_block(bundled)

    def test_modules_keep_separate_scopes(self, bundled):
        """Several modules declare their own top-level `$` helper. Flattening
        them into one scope makes the whole bundle a syntax error."""
        code = _code_block(bundled)
        assert code.count("const $ =") > 1, "fixture assumption: more than one $ helper"

    @pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
    def test_bundle_parses_as_valid_javascript(self, bundled, tmp_path):
        js = tmp_path / "bundle.js"
        js.write_text(_code_block(bundled), encoding="utf-8")
        result = subprocess.run(
            ["node", "--check", str(js)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
    def test_embedded_data_parses_as_json(self, bundled, tmp_path):
        blocks = CODE_BLOCK_RE.findall(bundled)
        data = [b for b in blocks if b.startswith("window.__S3_BUNDLE__")][0]
        js = tmp_path / "data.js"
        js.write_text(data, encoding="utf-8")
        assert subprocess.run(["node", "--check", str(js)]).returncode == 0


class TestEmbeddedData:
    def test_every_requested_listing_is_embedded(self, bundled):
        assert '"case_002495.out"' in bundled
        assert '"9074.out"' in bundled

    def test_raw_lines_travel_with_the_payload(self, bundled):
        """The section viewer and text search read raw listing lines, so they
        must be embedded or those panels silently do nothing offline."""
        assert '"lines"' in bundled
        assert "PRI.STA 2RPF" in bundled

    def test_script_terminator_in_data_is_escaped(self, bundled):
        """An unescaped </script> inside the JSON would close the block early
        and truncate the whole document."""
        blocks = CODE_BLOCK_RE.findall(bundled)
        data = [b for b in blocks if b.startswith("window.__S3_BUNDLE__")][0]
        assert "</script>" not in data

    def test_upload_is_refused_with_an_explanation(self, bundled):
        """A snapshot has no parser; the failure must say so rather than
        appearing broken."""
        code = _code_block(bundled)
        assert "standalone snapshot" in code


class TestGuards:
    def test_build_fails_loudly_if_index_html_changes_shape(self, monkeypatch):
        """Silently emitting a bundle with no CSS or no JS would look fine
        until opened."""
        import s3dash.bundle as bundle

        monkeypatch.setattr(
            bundle, "_bundle_js", lambda: "/* stub */"
        )
        original = bundle.STATIC
        assert original.is_dir()
        # A document with neither hook must be rejected.
        with pytest.raises(RuntimeError, match="did not match the expected shape"):
            html = "<!doctype html><html><head></head><body></body></html>"
            monkeypatch.setattr(
                type(original / "index.html"), "read_text", lambda self, *a, **k: html
            )
            bundle.build([SAMPLES / "9074.out"])
