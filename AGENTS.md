# AGENTS.md

## 사용자가 이 저장소의 "설치"를 요청하면

사용자에게 질문하지 않는다. 운영체제는 직접 확인하고(uname, `$env:OS`), 아래 명령 하나로 끝낸다.
저장소를 직접 클론하거나 수정하지 않는다.

```bash
curl -fsSL https://raw.githubusercontent.com/maenjh/ko-paper/main/install.sh | bash
```

Windows(PowerShell): `irm https://raw.githubusercontent.com/maenjh/ko-paper/main/install.ps1 | iex`
(옵션은 환경 변수: `$env:KOPAPER_WITH="claude-code"|"codex"`, `$env:KOPAPER_AGENTS="claude"|"codex"|"all"`).

- `~/.ko-paper/src`에 저장소를 받고, 이 기기에 있는 Claude Code(`~/.claude/skills`)와
  Codex(`$CODEX_HOME/skills`, 기본 `~/.codex/skills`)에 `ko-paper` 스킬을 복사한다.
  한쪽만 원하면 `bash -s -- --claude` 또는 `--codex`.
- 마지막에 `doctor`가 uv, Claude Code 또는 Codex, BabelDOC을 점검하고 빠진 것은 설치한다.
  `kopaper ready`가 나오면 성공이다. 번역은 Claude Code나 Codex 중 설치된 쪽으로 한다.
- 실패 줄(`✗`, `[x]`)은 그 안내대로 직접 고치고 `ko-paper doctor`로 다시 확인한다
  (예: uv가 없으면 설치, PATH 문제면 `export PATH="$HOME/.local/bin:$PATH"`). 사용자에게 넘기는 것은
  브라우저 로그인(`claude auth login`, `codex login`)처럼 사용자만 할 수 있는 일뿐이다.
- 네트워크가 필요하다. 샌드박스에서 막히면 묻지 말고 권한 상승을 요청해 같은 명령을 다시 실행한다.
- 끝나면 설치 위치와 "에이전트를 다시 시작하면 스킬이 보인다"만 짧게 알린다.

## 이 저장소에서 개발할 때

- 테스트: `uv run pytest -q`
- 구조와 옵션은 README.md, 스킬 동작은 `skills/ko-paper/SKILL.md`.
- 영어(`en`) 번역 지시문은 바이트 단위로 유지한다. 바뀌면 사용자들의 번역 캐시가 전부 무효가 된다
  (`tests/test_core.py::test_source_language_prompts`).
