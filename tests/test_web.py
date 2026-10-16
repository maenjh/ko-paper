import threading
from pathlib import Path

from fastapi.testclient import TestClient

from kopaper import pipeline
from kopaper.web import app as webapp
from kopaper.web.jobs import JobManager


def fake_translate(src, out_dir, opts, on_progress=None, cancel=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    mono = out_dir / f"{src.stem}.ko.pdf"
    mono.write_bytes(b"%PDF-1.4 fake")
    on_progress("Translate Paragraphs", 50.0)
    return pipeline.Result(
        paper_id="x", job_dir=out_dir, mono_pdf=mono, dual_pdf=None, paper_glossary=None,
        restored_ref_pages=[3], ocr_applied=False, seconds=1.0, calls=2, cache_hits=0, errors=0,
        input_tokens=10, output_tokens=5, returncode=0)


def make(tmp_path, translate=fake_translate):
    mgr = JobManager(db_path=tmp_path / "j.sqlite", work_dir=tmp_path / "web", translate=translate)
    app = webapp.create_web_app(mgr, start_worker=False, backend="claude-code")
    return TestClient(app, base_url="http://127.0.0.1"), mgr


def test_upload_run_download(tmp_path, monkeypatch):
    monkeypatch.setattr("kopaper.proxy.server.make_backend", lambda name: object())
    c, mgr = make(tmp_path)
    assert c.get("/").status_code == 200
    assert "cs_ml" in c.get("/api/options").json()["domains"]

    r = c.post("/api/jobs", files={"file": ("../My Paper.pdf", b"%PDF-1.7 x", "application/pdf")},
               data={"model": "sonnet", "output": "mono", "domain": "cs_ml", "pages": "1-2"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued" and job["name"] == "My Paper.pdf"  # path parts stripped

    assert mgr.run_next()
    job = c.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "done" and job["result"]["restored_ref_pages"] == [3]
    d = c.get(f"/api/jobs/{job['id']}/files/mono")
    assert d.status_code == 200 and d.content.startswith(b"%PDF")
    assert c.get(f"/api/jobs/{job['id']}/files/dual").status_code == 404

    assert c.delete(f"/api/jobs/{job['id']}").json() == {"ok": True}
    assert c.get("/api/jobs").json() == []


def test_rejects_bad_input(tmp_path, monkeypatch):
    monkeypatch.setattr("kopaper.proxy.server.make_backend", lambda name: object())
    c, _ = make(tmp_path)
    up = lambda data, **form: c.post("/api/jobs", files={"file": ("a.pdf", data, "application/pdf")}, data=form)
    assert up(b"not a pdf").status_code == 400
    assert up(b"%PDF x", model="gpt").status_code == 400
    assert up(b"%PDF x", pages="1;rm").status_code == 400
    assert up(b"%PDF x", domain="../../etc").status_code == 400


def test_cancel_queued_and_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("kopaper.proxy.server.make_backend", lambda name: object())

    def boom(*a, **k):
        raise RuntimeError("babeldoc missing")

    c, mgr = make(tmp_path, translate=boom)
    a = c.post("/api/jobs", files={"file": ("a.pdf", b"%PDF x", "application/pdf")}).json()
    b = c.post("/api/jobs", files={"file": ("b.pdf", b"%PDF x", "application/pdf")}).json()
    assert c.get(f"/api/jobs/{b['id']}").json()["queue_position"] == 2
    assert c.post(f"/api/jobs/{b['id']}/cancel").json()["status"] == "cancelled"
    assert mgr.run_next()
    failed = c.get(f"/api/jobs/{a['id']}").json()
    assert failed["status"] == "failed" and "babeldoc missing" in failed["error"]
    assert not mgr.run_next()  # cancelled job is not picked up


def test_glossary_edit_retry_and_usage(tmp_path, monkeypatch):
    monkeypatch.setattr("kopaper.proxy.server.make_backend", lambda name: object())
    from kopaper import glossary as gl

    monkeypatch.setattr(gl, "PAPER_GLOSSARY_DIR", tmp_path)
    c, mgr = make(tmp_path)
    job = c.post("/api/jobs", files={"file": ("p.pdf", b"%PDF-1.7 y", "application/pdf")}).json()
    pid = job["options"]["paper_id"]
    assert c.get(f"/api/papers/{pid}/glossary").status_code == 404
    gl.write(gl.paper_path(pid), [{"source": "actor", "target": "배우", "tgt_lng": ""}])
    g = c.get(f"/api/papers/{pid}/glossary").json()
    assert g["edited"] is False and g["entries"][0]["target"] == "배우"

    r = c.put(f"/api/papers/{pid}/glossary", json={"entries": [{"source": "actor", "target": "행위자"}, {"source": " ", "target": "x"}]})
    assert r.json()["count"] == 1
    g = c.get(f"/api/papers/{pid}/glossary").json()
    assert g["edited"] is True and g["entries"][0]["target"] == "행위자"
    assert c.put(f"/api/papers/{pid}/glossary", json={"entries": [{"source": "a\nb", "target": "x"}]}).status_code == 400
    assert c.get("/api/papers/../glossary").status_code in (400, 404)

    assert c.post(f"/api/jobs/{job['id']}/retry").status_code == 409  # still queued
    mgr.run_next()
    again = c.post(f"/api/jobs/{job['id']}/retry").json()
    assert again["status"] == "queued" and again["options"]["paper_id"] == pid and again["id"] != job["id"]

    assert c.delete(f"/api/papers/{pid}/glossary").json() == {"ok": True}
    assert c.get(f"/api/papers/{pid}/glossary").json()["edited"] is False
    u = c.get("/api/usage").json()
    assert set(u) >= {"h5", "d7", "limited_now"}


def test_build_glossary_priority(tmp_path, monkeypatch):
    from kopaper import glossary as gl

    monkeypatch.setattr(gl, "PAPER_GLOSSARY_DIR", tmp_path)
    gl.write(gl.paper_path("abc"), [{"source": "trust", "target": "믿음", "tgt_lng": ""},
                                    {"source": "actor", "target": "배우", "tgt_lng": ""}])
    opts = pipeline.Options(domain="cs_ml")
    path, reuse = pipeline.build_glossary("abc", opts, tmp_path / "g.csv")
    rows = {r["source"]: r["target"] for r in gl.read(path)}
    assert reuse and rows["trust"] == "신뢰" and rows["actor"] == "배우"  # domain beats auto
    gl.write(gl.user_path("abc"), [{"source": "trust", "target": "신뢰감", "tgt_lng": ""}])
    path, reuse = pipeline.build_glossary("abc", opts, tmp_path / "g.csv")
    rows = {r["source"]: r["target"] for r in gl.read(path)}
    assert rows["trust"] == "신뢰감" and "actor" not in rows  # user edit beats domain, replaces auto


def test_all_calls_failed_marks_job_failed(tmp_path, monkeypatch):
    monkeypatch.setattr("kopaper.proxy.server.make_backend", lambda name: object())

    def failed(src, out_dir, opts, on_progress=None, cancel=None):
        res = fake_translate(src, out_dir, opts, on_progress, cancel)
        res.calls, res.errors = 0, 7
        return res

    c, mgr = make(tmp_path, translate=failed)
    jid = c.post("/api/jobs", files={"file": ("p.pdf", b"%PDF-1.7 x", "application/pdf")}).json()["id"]
    assert mgr.run_next()
    job = c.get(f"/api/jobs/{jid}").json()
    assert job["status"] == "failed" and "7회" in job["error"]


def test_cancelled_job_is_not_started(tmp_path, monkeypatch):
    monkeypatch.setattr("kopaper.proxy.server.make_backend", lambda name: object())
    ran = []
    c, mgr = make(tmp_path, translate=lambda *a, **k: ran.append(1))
    jid = c.post("/api/jobs", files={"file": ("p.pdf", b"%PDF-1.7 x", "application/pdf")}).json()["id"]
    mgr.cancel(jid)
    mgr._run(jid)  # the worker picked the row just before the cancel landed
    assert not ran and c.get(f"/api/jobs/{jid}").json()["status"] == "cancelled"
