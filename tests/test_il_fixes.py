from types import SimpleNamespace as NS

from kopaper.il_fixes import merge_table_cells, skip_regions


def box(x, y, x2, y2):
    return NS(x=x, y=y, x2=x2, y2=y2)


def para(text, x, top, h=10, w=60, label="fallback_line"):
    ch = NS(box=box(x, top - h, x + w, top))
    comp = NS(pdf_character=None, pdf_line=NS(pdf_character=[ch]), pdf_same_style_characters=None, pdf_formula=None)
    return NS(unicode=text, box=box(x, top - h, x + w, top), layout_label=label, pdf_paragraph_composition=[comp])


def table_page(paragraphs):
    return NS(page_number=0, pdf_paragraph=paragraphs,
              page_layout=[NS(class_name="table", box=box(0, 0, 600, 800))])


def test_merges_multiline_cells_per_row():
    # 3 columns; row tops at 700 (header), 680, 640. Role column has wrapped lines.
    ps = [
        para("Actor", 50, 700), para("Age", 200, 700), para("Role", 400, 700),
        para("Father", 50, 680), para("42", 200, 680), para("Adult family", 400, 680),
        para("member; driver or", 400, 669), para("passenger", 400, 658),
        para("Mother", 50, 640), para("41", 200, 640), para("Adult family", 400, 640),
        para("member", 400, 629),
    ]
    page = table_page(ps)
    assert merge_table_cells(NS(page=[page])) == 3
    texts = [p.unicode for p in page.pdf_paragraph]
    assert "Adult family member; driver or passenger" in texts
    assert "Adult family member" in texts
    assert "Actor" in texts and "Father" in texts and "Mother" in texts
    merged = next(p for p in page.pdf_paragraph if p.unicode.startswith("Adult family member;"))
    assert merged.box.y == 648 and merged.box.y2 == 680  # spans its own row only


def test_single_line_tables_untouched():
    ps = [para(t, 50 + 100 * c, 700 - 20 * r) for r in range(3) for c, t in enumerate(["a", "b", "c"])]
    page = table_page(ps)
    assert merge_table_cells(NS(page=[page])) == 0 and len(page.pdf_paragraph) == 9


def test_skip_regions_blanks_reference_paragraphs():
    ref, body = para("[1] Ref 2020.", 50, 300), para("Conclusion text", 50, 600)
    page = NS(page_number=3, pdf_paragraph=[ref, body], page_layout=[])
    n = skip_regions(NS(page=[page]), [{"page": 3, "x0": 0, "x1": 300, "y0": 0, "y1": 400}])
    assert n == 1 and ref.unicode is None and body.unicode == "Conclusion text"


def test_stamped_verify_rehashes_only_when_the_file_changes(tmp_path):
    from kopaper.il_fixes import stamped_verify

    f = tmp_path / "font.ttf"
    f.write_bytes(b"abc")
    calls = []

    def full(path, sha):
        calls.append(sha)
        return sha == "good"

    assert stamped_verify(f, "bad", full) is False and calls == ["bad"]
    assert stamped_verify(f, "good", full) is True and calls == ["bad", "good"]
    assert stamped_verify(f, "good", full) is True and calls == ["bad", "good"]  # stamped: no rehash
    f.write_bytes(b"abcd")
    assert stamped_verify(f, "good", full) is True and calls == ["bad", "good", "good"]  # size changed: rehash
    assert stamped_verify(tmp_path / "missing", "good", full) is False and len(calls) == 3
