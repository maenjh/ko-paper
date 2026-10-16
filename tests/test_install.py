"""Run install.sh and the skill wrapper end to end in a fake HOME with stub uv/claude/babeldoc."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

STUBS = {
    # A python that passes `-c "import ..."` (or fails with $FAKE_IMPORT_ERROR) and echoes `-m kopaper ...`.
    "fakepython": '#!/bin/sh\nif [ "$1" = -c ]; then [ -z "$FAKE_IMPORT_ERROR" ] || { echo "$FAKE_IMPORT_ERROR" >&2; exit 1; }; '
                  'exit 0; fi\nshift 2\necho "kopaper $*"\n',
    # uv sync → the venv gets fakepython; `uv tool dir` → a BabelDOC tool env with fakepython.
    "uv": '#!/bin/sh\nd="$(dirname "$0")"\n'
          'if [ "$1" = sync ]; then mkdir -p .venv/bin; cp "$d/fakepython" .venv/bin/python; fi\n'
          'if [ "$1 $2" = "tool dir" ]; then echo "$d/tools"; fi\n',
    "claude": "#!/bin/sh\nexit 0\n",  # `claude auth status` → logged in
    "babeldoc": "#!/bin/sh\nexit 0\n",
}


def run(cmd, env, **kw):
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60, **kw)


@pytest.fixture
def sandbox(tmp_path):
    if os.name == "nt":
        pytest.skip("install.sh is the macOS/Linux installer; CI checks install.ps1 on Windows")
    if not shutil.which("git"):
        pytest.skip("git required")
    # Snapshot the working tree (tracked + new files) as a git repo to install from.
    src = tmp_path / "repo"
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO,
                           capture_output=True, text=True, check=True).stdout.splitlines()
    for f in files:
        if (REPO / f).is_file():
            (src / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / f, src / f)
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    for c in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "snapshot"]):
        subprocess.run(git + c, cwd=src, check=True, capture_output=True)

    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in STUBS.items():
        (stubs / name).write_text(body)
        (stubs / name).chmod(0o755)
    (stubs / "tools" / "babeldoc" / "bin").mkdir(parents=True)
    shutil.copy2(stubs / "fakepython", stubs / "tools" / "babeldoc" / "bin" / "python")
    home = tmp_path / "home"
    (home / ".claude" / "skills" / "ko-paper").mkdir(parents=True)  # someone else's skill, must be backed up
    env = {"HOME": str(home), "PATH": f"{stubs}:{Path(shutil.which('git')).parent}:/usr/bin:/bin",
           "KOPAPER_REPO": str(src), "TERM": "dumb"}
    return home, env


def test_install_update_and_launcher(sandbox):
    home, env = sandbox
    r = run(["bash", str(REPO / "install.sh")], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "kopaper ready" in r.stdout

    skill = home / ".claude" / "skills" / "ko-paper"
    assert (skill / "SKILL.md").exists()
    assert (skill / ".kopaper-home").read_text().strip() == str(home / ".ko-paper" / "src")
    assert list(skill.parent.glob("ko-paper.backup-*")), "foreign skill folder was not backed up"
    assert not (home / ".codex").exists()  # no Codex on this machine → no Codex skill

    launcher = home / ".local" / "bin" / "ko-paper"
    r = run([str(launcher), "translate", "x.pdf", "-l", "de"], env)
    assert r.stdout.strip() == "kopaper translate x.pdf -l de", r.stderr
    r = run([str(launcher)], env)
    assert r.stdout.strip() == "kopaper serve --open"

    r = run([str(launcher), "update"], env)
    assert r.returncode == 0 and "kopaper ready" in r.stdout, r.stdout + r.stderr


def test_doctor_reports_missing_backend(sandbox, tmp_path):
    home, env = sandbox
    os.remove(tmp_path / "stubs" / "claude")
    r = run(["bash", str(REPO / "install.sh")], env)
    assert r.returncode != 0
    assert "neither Claude Code" in r.stderr and "--with-claude-code" in r.stdout


def test_update_keeps_chosen_agent(sandbox):
    home, env = sandbox
    env = {**env, "CODEX_HOME": str(home / ".codex")}
    assert run(["bash", str(REPO / "install.sh"), "--codex"], env).returncode == 0
    claude_skill = home / ".claude" / "skills" / "ko-paper"
    assert not (claude_skill / ".kopaper-home").exists()  # only the foreign folder from the fixture
    r = run([str(home / ".local" / "bin" / "ko-paper"), "update"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / ".codex" / "skills" / "ko-paper" / ".kopaper-home").exists()
    assert not (claude_skill / ".kopaper-home").exists(), "update installed into an agent the user did not pick"


@pytest.mark.parametrize("script", ["install.ps1", "skills/ko-paper/scripts/kopaper.ps1",
                                    "skills/ko-paper/scripts/html2pdf.ps1"])
def test_powershell_scripts_ascii_and_parse(script):
    path = REPO / script
    path.read_bytes().decode("ascii")  # Windows PowerShell 5.1 misreads non-ASCII in BOM-less files
    pwsh = shutil.which("pwsh") or os.environ.get("KOPAPER_TEST_PWSH")
    if not pwsh:
        pytest.skip("pwsh not installed")
    check = (f"$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$null,[ref]$e);"
             " if ($e) { $e | % { $_.Message }; exit 1 }")
    r = subprocess.run([pwsh, "-NoProfile", "-c", check], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_api_key_counts_as_logged_in(sandbox, tmp_path):
    home, env = sandbox
    (tmp_path / "stubs" / "claude").write_text("#!/bin/sh\nexit 1\n")  # `claude auth status` → not logged in
    r = run(["bash", str(REPO / "install.sh")], env)
    assert r.returncode != 0 and "claude auth login" in r.stderr
    r = run(["bash", str(REPO / "install.sh")], {**env, "ANTHROPIC_API_KEY": "sk-test"})
    assert r.returncode == 0 and "kopaper ready" in r.stdout, r.stdout + r.stderr


def test_installed_backend_is_kept(sandbox, tmp_path):
    home, env = sandbox
    (tmp_path / "stubs" / "codex").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "stubs" / "codex").chmod(0o755)
    r = run(["bash", str(REPO / "install.sh"), "--with-codex"], env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / ".ko-paper" / "backend").read_text().strip() == "codex"
    r = run([str(home / ".local" / "bin" / "ko-paper"), "doctor"], env)  # claude is installed and logged in too
    assert "backend:  codex" in r.stdout, r.stdout + r.stderr


def test_doctor_reports_blocked_native_module(sandbox):
    home, env = sandbox
    assert run(["bash", str(REPO / "install.sh")], env).returncode == 0
    err = ("ImportError: DLL load failed while importing _mupdf: "
           "An Application Control policy has blocked this file. (os error 4551)")
    r = run([str(home / ".local" / "bin" / "ko-paper"), "doctor"], {**env, "FAKE_IMPORT_ERROR": err})
    assert r.returncode == 1 and "kopaper ready" not in r.stdout
    assert "ko-paper could not load its compiled modules" in r.stderr and "Smart App Control" in r.stderr
    assert "Lite mode" in r.stderr
