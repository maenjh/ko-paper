"""Run install.sh and the skill wrapper end to end in a fake HOME with stub uv/claude/babeldoc."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

STUBS = {
    # uv sync → a fake kopaper that echoes its arguments; other uv calls succeed silently.
    "uv": '#!/bin/sh\nif [ "$1" = sync ]; then mkdir -p .venv/bin; '
          'printf \'#!/bin/sh\\necho "kopaper $*"\\n\' > .venv/bin/kopaper; chmod +x .venv/bin/kopaper; fi\n',
    "claude": "#!/bin/sh\nexit 0\n",  # `claude auth status` → logged in
    "babeldoc": "#!/bin/sh\nexit 0\n",
}


def run(cmd, env, **kw):
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60, **kw)


@pytest.fixture
def sandbox(tmp_path):
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
