# AGENTS.md

## 사용자가 이 저장소의 "설치"를 요청하면

스킬 설치는 저장소를 직접 다루지 않고 설치 스크립트 하나로 끝낸다.

```bash
curl -fsSL https://raw.githubusercontent.com/maenjh/ko-paper/main/install.sh | bash
```

Windows(PowerShell): `irm https://raw.githubusercontent.com/maenjh/ko-paper/main/install.ps1 | iex`
(옵션은 환경 변수: `$env:KOPAPER_WITH="claude-code"|"codex"`, `$env:KOPAPER_AGENTS="claude"|"codex"|"all"`).

- `~/.ko-paper/src`에 저장소를 받고, 이 기기에 있는 Claude Code(`~/.claude/skills`)와
  Codex(`$CODEX_HOME/skills`, 기본 `~/.codex/skills`)에 `ko-paper` 스킬을 복사한다.
  한쪽만 원하면 `bash -s -- --claude` 또는 `--codex`.
- 마지막에 `doctor`가 uv, Claude Code 또는 Codex, BabelDOC을 점검하고 빠진 것은 설치한다.
  `✓ kopaper ready`가 나오면 성공이다. 번역은 Claude Code나 Codex 중 설치된 쪽으로 한다. `✗` 줄은 사용자에게 그대로 전한다.
- 네트워크가 필요하다. 샌드박스에서 막히면 권한 상승을 요청한다.
- 설치가 끝나면 에이전트를 다시 시작해야 스킬이 보인다고 알린다.

## 이 저장소에서 개발할 때

- 테스트: `uv run pytest -q`
- 구조와 옵션은 README.md, 스킬 동작은 `skills/ko-paper/SKILL.md`.
- 영어(`en`) 번역 지시문은 바이트 단위로 유지한다. 바뀌면 사용자들의 번역 캐시가 전부 무효가 된다
  (`tests/test_core.py::test_source_language_prompts`).
