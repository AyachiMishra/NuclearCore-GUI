"""The formatted PDF report.

Checks the structural promises a reader depends on -- a resolved table of
contents, working internal links, page numbers, and an outline -- rather than
just that bytes were produced.
"""

from __future__ import annotations

import io

import pytest

pypdf = pytest.importorskip("pypdf")

from s3dash.web.pdfreport import build_pdf  # noqa: E402


@pytest.fixture(scope="module")
def pdfs(parsed) -> dict:
    return {key: build_pdf(result.payload, step=0) for key, result in parsed.items()}


def _reader(blob: bytes):
    return pypdf.PdfReader(io.BytesIO(blob))


def _flatten(outline, depth: int = 0) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for item in outline:
        if isinstance(item, list):
            out.extend(_flatten(item, depth + 1))
        else:
            out.append((depth, str(item.title)))
    return out


class TestDocument:
    def test_is_a_valid_pdf(self, pdfs):
        for key, blob in pdfs.items():
            assert blob.startswith(b"%PDF-"), key
            assert len(_reader(blob).pages) > 1, key

    def test_has_a_cover_and_contents(self, pdfs):
        text = _reader(pdfs["apr_c2"]).pages[1].extract_text()
        assert "Contents" in text

    def test_every_page_is_numbered(self, pdfs):
        reader = _reader(pdfs["beavrs"])
        # The cover deliberately carries no page number; the body pages do.
        for i, page in enumerate(reader.pages[1:], start=2):
            assert f"Page {i}" in page.extract_text(), i

    def test_document_metadata_is_set(self, pdfs):
        meta = _reader(pdfs["apr_c2"]).metadata
        assert meta.title and "case_002495" in meta.title
        assert meta.author


class TestNavigation:
    def test_outline_mirrors_the_sections(self, pdfs):
        titles = [t for _, t in _flatten(_reader(pdfs["apr_c2"]).outline)]
        for expected in ("1. Run summary", "2. Core map", "3. Depletion progression",
                         "5. Core inventory", "6. Diagnostics", "7. Provenance"):
            assert any(t.startswith(expected) for t in titles), expected

    def test_outline_is_nested(self, pdfs):
        depths = {d for d, _ in _flatten(_reader(pdfs["apr_c2"]).outline)}
        assert len(depths) > 1, "sub-sections should sit below their parent"

    def test_contents_does_not_list_itself(self, pdfs):
        titles = [t for _, t in _flatten(_reader(pdfs["apr_c2"]).outline)]
        assert "Contents" not in titles

    def test_internal_links_exist(self, pdfs):
        """A table of contents whose entries do not jump anywhere is decoration."""
        reader = _reader(pdfs["apr_c2"])
        annots = 0
        for page in reader.pages:
            for a in page.get("/Annots") or []:
                obj = a.get_object()
                if obj.get("/Subtype") == "/Link":
                    annots += 1
        assert annots >= 5, f"expected linked contents entries, found {annots}"

    def test_toc_page_numbers_resolved(self, pdfs):
        """multiBuild must converge; unresolved entries render as '0'."""
        text = _reader(pdfs["beavrs"]).pages[1].extract_text()
        assert "Run summary" in text
        digits = [ln for ln in text.splitlines() if ln.strip().endswith("0")]
        assert "1. Run summary" not in "".join(digits)


class TestContent:
    def test_reports_the_real_geometry(self, pdfs):
        assert "17×15" not in _reader(pdfs["apr_c2"]).pages[0].extract_text()
        cover = _reader(pdfs["beavrs"]).pages[0].extract_text()
        assert "15×15" in cover
        assert "12 axial nodes" in cover

    def test_states_termination(self, pdfs):
        for key, blob in pdfs.items():
            assert "Normal Termination" in _reader(blob).pages[0].extract_text(), key

    def test_every_depletion_step_is_tabulated(self, parsed, pdfs):
        text = "".join(p.extract_text() for p in _reader(pdfs["apr_c2"]).pages)
        steps = len(parsed["apr_c2"].payload["depletion"])
        assert steps == 31
        # Spot-check the first, a middle and the last step's exposure.
        for row in (0, steps // 2, steps - 1):
            d = parsed["apr_c2"].payload["depletion"][row]
            assert f'{d["keff"]:,.5f}' in text, d["step"]

    def test_symmetry_violations_are_detailed(self, pdfs):
        text = "".join(p.extract_text() for p in _reader(pdfs["apr_c2"]).pages)
        assert "Symmetry check" in text
        assert "quadrant exposures" in text

    def test_clean_run_omits_symmetry_section(self, pdfs):
        text = "".join(p.extract_text() for p in _reader(pdfs["beavrs"]).pages)
        assert "failing groups" not in text

    def test_axial_section_only_for_3d(self, pdfs):
        assert "4. Axial distribution" in "".join(
            p.extract_text() for p in _reader(pdfs["beavrs"]).pages)
        assert "4. Axial distribution" not in "".join(
            p.extract_text() for p in _reader(pdfs["apr_c2"]).pages)

    def test_equivalent_assemblies_is_explained(self, pdfs):
        text = "".join(p.extract_text() for p in _reader(pdfs["apr_c2"]).pages)
        assert "height-weighted" in text


class TestDegradation:
    def test_renders_without_state_points(self, parsed):
        payload = dict(parsed["apr_c2"].payload)
        payload["statePoints"] = []
        payload["depletion"] = []
        blob = build_pdf(payload)
        assert blob.startswith(b"%PDF-")

    def test_renders_without_diagnostics(self, parsed):
        payload = dict(parsed["beavrs"].payload)
        payload["diagnostics"] = []
        text = "".join(p.extract_text() for p in _reader(build_pdf(payload)).pages)
        assert "No diagnostics were reported" in text

    def test_unknown_step_falls_back_to_the_first(self, parsed):
        blob = build_pdf(parsed["apr_c2"].payload, step=9999)
        assert blob.startswith(b"%PDF-")
