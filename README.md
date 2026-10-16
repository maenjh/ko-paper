# ko-paper

논문 PDF(기본 영어, 독일어·프랑스어·일본어 등 10개 언어)를 그림·표·수식 위치를 유지한 채 한글 PDF로 번역한다.
레이아웃 처리는 [BabelDOC](https://github.com/funstory-ai/BabelDOC), 번역은 Claude가 맡는다.
Claude Code나 Codex에 스킬로 설치하면 "이 논문 번역해줘" 한마디로 쓸 수 있다.

> **각자 자기 컴퓨터에서, 자기 Claude 계정으로 쓰는 도구다.** 기본 백엔드는 로컬에 로그인된
> Claude Code(`claude -p`)라서 번역에 쓰는 사용량은 실행한 사람의 구독에서 나간다.
> 이 백엔드로 서버를 띄워 다른 사람에게 번역을 제공하면 안 된다. 그런 용도라면
> `KOPAPER_BACKEND=anthropic-api`(API 키, 종량제)를 쓴다. 웹 UI도 항상 127.0.0.1에만 열린다.

## 스킬로 설치 (권장)

준비물: [Claude Code](https://claude.com/claude-code) 로그인, [uv](https://docs.astral.sh/uv/), git.
BabelDOC과 Python 의존성은 처음 실행할 때 자동으로 설치된다. Codex에서 쓰더라도 번역 호출은
Claude Code(`claude -p`)로 가므로 Claude Code 로그인이 필요하다.

**에이전트에게 맡기기** — Claude Code나 Codex에 이렇게 말하면 된다.

```text
https://github.com/maenjh/ko-paper 스킬 설치해줘
```

> **설치를 맡은 AI 에이전트에게:** 아래 명령 하나를 실행한다. 이 기기에 있는 Claude Code
> (`~/.claude/skills`)와 Codex(`~/.codex/skills`) 모두에 스킬을 설치하고 필요한 도구를 점검한다.
> 결과 끝의 `✓ kopaper ready` 줄을 확인하고, 실패 줄(`✗`)이 있으면 그 내용을 사용자에게 전한다.
> 설치 후에는 에이전트를 다시 시작해야 스킬이 보인다.
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/maenjh/ko-paper/main/install.sh | bash
> ```

**플러그인으로** (Claude Code)

```text
/plugin marketplace add maenjh/ko-paper
/plugin install ko-paper@ko-paper
```

**스크립트로** (`~/.ko-paper/src`에 받고, 찾은 에이전트마다 스킬을 복사)

```bash
curl -fsSL https://raw.githubusercontent.com/maenjh/ko-paper/main/install.sh | bash
# 한쪽에만:  ... | bash -s -- --claude   또는   ... | bash -s -- --codex
```

다시 실행하거나 스킬 폴더의 `scripts/kopaper.sh update`를 실행하면 최신 버전으로 갱신된다.

**Claude 앱**: 데스크톱 앱의 Code 탭은 Claude Code와 같은 `~/.claude/skills`를 쓰므로 위 방법으로
설치하면 그대로 보인다. claude.ai 일반 채팅은 원격 샌드박스에서 돌아 내 컴퓨터의 PDF와
BabelDOC에 접근할 수 없어 지원하지 않는다.

설치 후 Claude Code에서 PDF 경로와 함께 요청하면 된다.

```text
~/Downloads/attention.pdf 이 논문 번역해줘
1~3쪽만 한글본으로 뽑아줘
~/Downloads/aufsatz.pdf 독일어 논문인데 한글로 번역해줘
```

결과는 입력 파일 옆에 `<이름>.ko.pdf`(한글본)와 `<이름>.ko.dual.pdf`(원문 병기본)로 생긴다.
스킬로 실행할 때 캐시·용어집·작업 로그는 `~/.ko-paper/data`에 쌓인다.

## 직접 설치 (CLI·웹 UI)

- Claude Code 로그인 (`claude` 실행 후 `/login`)
- BabelDOC: `uv tool install babeldoc`
- 이 저장소: `uv sync` (API 백엔드도 쓰려면 `uv sync --extra api`)

## 웹 UI

```bash
.venv/bin/kopaper serve --open    # http://127.0.0.1:8787/ 을 브라우저로 연다
```

- PDF를 끌어다 놓으면 대기열에 들어가고 한 편씩 차례대로 번역한다.
- 원문 언어(영어, 독일어, 프랑스어 등)를 고를 수 있다. 출력은 항상 한국어다.
- 단계 이름, 진행률, 경과 시간, 남은 시간 추정이 실시간으로 표시된다.
- 완료되면 한글본 보기, 한글본·병기본·용어집 받기가 가능하다. 진행 중 취소, 완료 후 삭제, 다시 번역도 된다.
- **용어집 편집**: 완료된 작업에서 이 논문의 용어집을 열어 고치고 "저장 후 다시 번역"을 누르면, 바뀐 용어가 들어간 문단만 다시 번역된다.
- 머리글에 최근 5시간 동안 ko-paper가 보낸 Claude 호출 수와 토큰이 보인다. 한도에 걸리면 경고가 뜨고 자동으로 재시도한다. 구독의 남은 한도 자체는 Claude가 공개하지 않아 표시할 수 없다.
- 서버는 항상 127.0.0.1에만 열린다. 외부에 노출하지 않는다.
- 작업 기록은 `data/web_jobs.sqlite`, 파일은 `data/web/<작업 ID>/`에 남는다. 서버를 재시작하면 진행 중이던 작업은 실패로 표시된다.

## CLI

```bash
.venv/bin/kopaper translate paper.pdf                # paper.ko.pdf + paper.ko.dual.pdf (입력 옆에 생성)
.venv/bin/kopaper translate a.pdf b.pdf -o out/      # 여러 편, 출력 폴더 지정
.venv/bin/kopaper translate paper.pdf -p 1-3 --mono-only
.venv/bin/kopaper translate paper.pdf -m opus        # 모델 변경 (sonnet 기본)
.venv/bin/kopaper translate aufsatz.pdf -l de        # 독일어 논문 (원문 언어, 기본 en)
.venv/bin/kopaper translate paper.pdf -g my_terms.csv  # 내 용어집 (최우선)
.venv/bin/kopaper serve --proxy-only                 # 프록시만 실행 (127.0.0.1:8787)
```

프록시가 떠 있지 않으면 `translate`가 자동으로 띄운다.

## 용어집

CSV 형식은 `source,target,tgt_lng`이다. 충돌 시 우선순위는 다음과 같다.

1. `-g`로 넘긴 사용자 용어집
2. 웹에서 고친 논문별 용어집 `data/glossaries/<paper_id>.user.csv` (있으면 자동 추출 용어집 대신 쓴다)
3. 분야 용어집 `glossary/<domain>.csv` (`-d`로 선택, 기본 `cs_ml`)
4. 논문별 자동 추출 용어집 `data/glossaries/<paper_id>.csv`

자동 추출 시 학회·기관·출판사 이름처럼 원문 그대로 둬야 할 고유명사는 걸러 낸다.

논문을 처음 전체 번역할 때 BabelDOC이 용어를 자동 추출해 저장한다. 같은 파일을 다시 번역하면 이 용어집을 재사용하고 추출 단계를 건너뛴다. 용어가 실행마다 바뀌지 않고, 토큰도 약 30% 줄어든다. 일부 페이지만 번역한 실행의 용어는 저장하지 않는다.

## 레이아웃 보정

BabelDOC 위에 다음 보정을 더한다. 모두 `src/kopaper/babeldoc_launcher.py`와 `il_fixes.py`, `postprocess.py`에 있다.

- **수식 폰트**: Cambria Math를 수식으로 취급해 깨진 변수 기호를 원래 모양으로 둔다.
- **참고문헌**: 영문 원본에서 참고문헌 영역을 찾아 Claude에 보내지 않고, 결과 PDF에서는 원본으로 되돌린다.
- **표 셀**: 여러 줄짜리 셀을 한 문단으로 합쳐 번역하고, 셀 안에서만 줄바꿈해 아래 행과 겹치지 않게 한다.
- **스캔본**: 텍스트 레이어가 없는 PDF는 번역 전에 멈추고 알려 준다. `--ocr`(웹은 고급 설정)로 Tesseract OCR 후 번역할 수 있지만 품질이 낮은 실험 기능이다.

## 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `KOPAPER_BACKEND` | `claude-code` | `claude-code` 또는 `anthropic-api` |
| `KOPAPER_PORT` | `8787` | 프록시 포트 |
| `KOPAPER_MAX_CONCURRENCY` | `4` | 동시 Claude 호출 수 |
| `KOPAPER_EFFORT` | `medium` | API 백엔드의 effort |
| `KOPAPER_EXTRA_MATH_FONTS` | Cambria Math | 수식으로 취급할 폰트 이름 정규식 |
| `KOPAPER_DATA` | `./data` (스킬은 `~/.ko-paper/data`) | 작업·캐시·로그 위치 |
| `KOPAPER_MERGE_TABLE_CELLS` | `1` | `0`이면 표 셀 병합을 끈다 |
| `KOPAPER_TABLE_LINE_SKIP` | `1.15` | 표 셀 안 줄 간격 |

## 구조

```
웹 UI / kopaper translate ─► 작업 큐 ─► BabelDOC (babeldoc_launcher.py로 수식 폰트 보정)
                        │ OpenAI 형식 요청
                        ▼
                 kopaper proxy (FastAPI, SQLite 캐시, 사용량 로그)
                        │
              ┌─────────┴─────────┐
        claude -p (구독)     Anthropic API (claude-opus-5-5 / claude-sonnet-5-5)
```

작업마다 `data/jobs/<paper_id>/<시각>/`에 명령, 로그, 결과 요약이 남는다.

## 라이선스

[AGPL-3.0-or-later](LICENSE). ko-paper는 AGPL-3.0인 BabelDOC의 내부 모듈을 불러와 패치해 쓰므로
같은 라이선스를 따른다. 수정한 버전을 배포하거나 네트워크 서비스로 제공하면 소스도 공개해야 한다.

번역 대상 논문의 저작권은 원저자와 출판사에 있다. 번역본은 개인 학습용으로 쓰고,
재배포하기 전에 원문의 라이선스를 확인한다.
