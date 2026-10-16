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
        return TestClient(server.create_app("fake"), base_url="http://127.0.0.1"), fb
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
    import hashlib

    from kopaper.pipeline import Options, babeldoc_cmd, proxy_model, system_prompt
    from kopaper.postprocess import _HEADING

    # English stays byte-identical to the original prompt so existing translation caches keep hitting.
    assert hashlib.sha256(system_prompt("en").encode()).hexdigest() == "1a43cbad06dc4098c63e0098c3f943a5e1e22bb09cf842301e396da4d955f902"
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


@pytest.mark.skipif(__import__("os").name == "nt", reason="the fake codex is a /bin/sh script")
def test_codex_backend_parses_events(tmp_path, monkeypatch):
    from kopaper.proxy import backends

    fake = tmp_path / "codex"
    fake.write_text(
        "#!/bin/sh\ncat > /dev/null\n"
        "echo '{\"type\":\"thread.started\"}'\n"
        "echo '{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"번역문\"}}'\n"
        "echo '{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":120,\"output_tokens\":7}}'\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("KOPAPER_CODEX_BIN", str(fake))
    c = asyncio.run(backends.CodexBackend().complete("SYS", "hello", "sonnet"))
    assert (c.text, c.input_tokens, c.output_tokens) == ("번역문", 120, 7)

    with pytest.raises(BackendError) as e:
        backends.parse_codex_events('{"type":"turn.failed","error":{"message":"usage limit reached"}}')
    assert e.value.status == 429


def test_proxy_rejects_other_sites(client):
    c, fb = client()
    body = {"messages": [{"role": "user", "content": "x"}]}
    assert c.post("/v1/chat/completions", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("http://evil.example/v1/chat/completions", json=body).status_code == 403  # DNS rebinding
    assert c.post("/v1/chat/completions", json=body, headers={"Origin": "http://localhost:8787"}).status_code == 200
    assert fb.calls == 1


def test_usage_counts_only_this_run(client, monkeypatch, tmp_path):
    from kopaper import pipeline

    c, _ = client()
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    tmp_path.joinpath("proxy_usage.jsonl").unlink(missing_ok=True)
    monkeypatch.setattr(server, "USAGE_LOG", tmp_path / "proxy_usage.jsonl")
    for key, text in (("kopaper-a-1", "one"), ("kopaper-b-2", "two"), ("kopaper-a-1", "three")):
        c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": text}]},
               headers={"Authorization": f"Bearer {key}"})
    assert pipeline.usage_since(0, "kopaper-a-1")["calls"] == 2
    assert pipeline.usage_since(0)["calls"] == 3


def test_limit_regex_and_foreign_appendix():
    from kopaper.postprocess import _APPENDIX
    from kopaper.proxy.backends import _LIMIT_RE

    assert _LIMIT_RE.search("Rate limit exceeded") and _LIMIT_RE.search("usage limit reached") and _LIMIT_RE.search("HTTP 529")
    for msg in ("failed to generate a response", "could not separate", "context limit exceeded"):
        assert not _LIMIT_RE.search(msg), msg
    for h in ("Appendix A", "Anhang A: Beweise", "Annexe A", "Apéndice A", "付録 A", "Приложение А"):
        assert _APPENDIX.match(h), h


def test_echo_backend_answers_babeldoc_formats():
    from kopaper.proxy.backends import ECHO_MARK, echo_answer

    example = '[{"id": 0, "input": "example"}]'
    batch = 'Example:\n' + example + '\nInput:\n' + json.dumps([{"id": 0, "input": "Hello {v1}"}, {"id": 1, "input": "World"}])
    assert json.loads(echo_answer(batch)) == [{"id": 0, "output": ECHO_MARK + "Hello {v1}"}, {"id": 1, "output": ECHO_MARK + "World"}]
    assert echo_answer("translate it into ko. Input:\n\nSome text") == ECHO_MARK + "Some text"
    assert echo_answer("Rules...\n\nNow translate the following text:\n\nA paragraph.") == ECHO_MARK + "A paragraph."
    assert echo_answer("You are an expert multilingual terminologist. Extract key terms...") == "[]"


def test_progress_bar_lines_unicode_and_ascii():
    from kopaper.pipeline import _BAR

    for line in ("Translate Paragraphs (1/1)          ━━━━━╸━━━━━ 20/54   0:00:12 0:00:30",
                 "Translate Paragraphs (1/1)          -----------  20/54   0:00:12 0:00:30",  # Windows
                 "translate                           -- ---------- 33/100 0:00:12 0:00:30"):
        m = _BAR.match(line)
        assert m and m["name"].strip() in ("Translate Paragraphs (1/1)", "translate"), line
        assert (int(m["done"]), int(m["total"])) in ((20, 54), (33, 100))
