import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from kopaper import glossary
from kopaper.proxy import server
from kopaper.proxy.backends import BackendError, Completion


def test_flatten_and_fence():
    sys_, user = server.flatten_messages([
        {"role": "system", "content": "S"},
        {"role": "user", "content": [{"type": "text", "text": "U1"}]},
    ])
    assert (sys_, user) == ("S", "U1")
    assert server.strip_fence('```json\n[{"id":0}]\n```') == '[{"id":0}]'
    assert server.strip_fence("plain") == "plain"


def test_glossary_merge_priority(tmp_path):
    user = [{"source": "Actor", "target": "행위자", "tgt_lng": ""}]
    domain = [{"source": "actor", "target": "배우", "tgt_lng": "ko"}, {"source": "trust", "target": "신뢰", "tgt_lng": "ko"}]
    merged = glossary.merge(user, domain, [{"source": "empty", "target": "", "tgt_lng": ""}])
    assert [(r["source"], r["target"]) for r in merged] == [("Actor", "행위자"), ("trust", "신뢰")]
    p = tmp_path / "g.csv"
    glossary.write(p, merged)
    assert glossary.read(p) == merged


class FakeBackend:
    name = "fake"

    def __init__(self, fail=None):
        self.calls = 0
        self.fail = fail

    async def complete(self, system, prompt, model):
        self.calls += 1
        if self.fail:
            raise BackendError(self.fail, "usage limit reached")
        return Completion("```json\n" + json.dumps([{"id": 0, "output": "안녕"}]) + "\n```", 10, 5)


@pytest.fixture
def client(monkeypatch, tmp_path):
    def make(fail=None):
        fb = FakeBackend(fail)
        monkeypatch.setattr(server, "make_backend", lambda name: fb)
        monkeypatch.setattr(server, "CACHE_DB", tmp_path / "c.sqlite")
        monkeypatch.setattr(server, "USAGE_LOG", tmp_path / "u.jsonl")
        return TestClient(server.create_app("fake")), fb
    return make


def test_proxy_cache_and_json(client):
    c, fb = client()
    body = {"model": "sonnet", "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": "translate"}]}
    r1 = c.post("/v1/chat/completions", json=body).json()
    r2 = c.post("/v1/chat/completions", json=body).json()
    assert json.loads(r1["choices"][0]["message"]["content"])[0]["output"] == "안녕"
    assert r1["choices"][0]["message"]["content"] == r2["choices"][0]["message"]["content"]
    assert fb.calls == 1  # second request served from cache


def test_proxy_rate_limit_maps_to_429(client):
    c, _ = client(fail=429)
    r = c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 429


def test_reference_restore_two_column(tmp_path):
    import pymupdf

    from kopaper.postprocess import find_reference_heading, restore_references

    def make(path, body_word, ref_word):
        doc = pymupdf.open()
        page = doc.new_page(width=600, height=800)
        for k in range(12):
            page.insert_text((40, 80 + k * 20), f"{body_word} line {k}", fontsize=9)
        page.insert_text((40, 420), "References", fontsize=11)
        for k in range(8):
            page.insert_text((40, 450 + k * 20), f"[{k + 1}] {ref_word} 2020.", fontsize=9)
        for k in range(12):
            page.insert_text((320, 80 + k * 20), f"[{k + 9}] {ref_word} 2021.", fontsize=9)
        doc.save(path)

    src, out = tmp_path / "src.pdf", tmp_path / "out.pdf"
    make(src, "English", "Author")
    make(out, "Korean", "Garbled")
    assert find_reference_heading(pymupdf.open(src))[0] == 0
    assert restore_references(src, out) == [1]
    text = pymupdf.open(out)[0].get_text()
    assert "Korean line 0" in text  # body above the heading stays translated
    assert "Garbled" not in text and "Author" in text  # bibliography comes from the original


def test_review_pass_and_shape_guard(client, monkeypatch):
    c, fb = client()
    outputs = iter(['[{"id": 0, "output": "초안"}]', '[{"id": 0, "output": "다듬은 번역"}]',
                    '[{"id": 0, "output": "초안"}]', '[{"id": 9, "output": "잘못된 id"}]'])

    async def complete(system, prompt, model):
        fb.calls += 1
        return Completion(next(outputs), 10, 5)

    fb.complete = complete
    msg = lambda t: {"model": "sonnet+review", "messages": [{"role": "user", "content": t}]}  # noqa: E731
    r = c.post("/v1/chat/completions", json=msg("a")).json()
    assert r["choices"][0]["message"]["content"] == '[{"id": 0, "output": "다듬은 번역"}]' and fb.calls == 2
    r = c.post("/v1/chat/completions", json=msg("b")).json()
    assert "초안" in r["choices"][0]["message"]["content"]  # review changed ids → draft kept


def test_source_language_prompts():
    import subprocess

    from kopaper.pipeline import Options, babeldoc_cmd, proxy_model, system_prompt
    from kopaper.postprocess import _HEADING

    # English stays byte-identical so existing translation caches keep hitting.
    orig = subprocess.run(["git", "show", "HEAD:prompts/translate_ko.txt"], capture_output=True, text=True).stdout
    if orig:
        assert system_prompt("en") == orig
    assert "German academic papers" in system_prompt("de") and "German caption labels" in system_prompt("de")
    assert server.BASE_SYSTEM.format(source="English").startswith("You are a professional translator of academic papers from English")

    assert proxy_model(Options()) == "sonnet"
    assert proxy_model(Options(lang_in="de", review=True)) == "sonnet@de+review"
    assert server.parse_model("sonnet@de+review") == ("sonnet", "German", True)
    assert server.parse_model("opus") == ("opus", "English", False)

    cmd = babeldoc_cmd(__import__("pathlib").Path("x.pdf"), __import__("pathlib").Path("out"), Options(lang_in="fr"), None, False)
    assert cmd[cmd.index("--lang-in") + 1] == "fr"
    for h in ("References", "Literaturverzeichnis", "LITERATUR", "Références", "参考文献", "5 Bibliografía"):
        assert _HEADING.match(h), h
    assert not _HEADING.match("references to prior work")
