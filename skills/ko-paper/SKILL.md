---
name: ko-paper
description: Translate an academic paper PDF (English by default; also German, French, Spanish, Italian, Portuguese, Dutch, Russian, Japanese, Chinese) into Korean while keeping figures, tables, equations and page layout in place (BabelDOC for layout, Claude for translation). Produces a Korean-only PDF and a side-by-side original/Korean PDF next to the input. Use when the user hands over a paper or reading PDF and wants it in Korean — "이 논문 번역해줘", "이 논문 해줘", "한글로 바꿔줘", "PDF 번역", "논문 한글본", "영어 논문 한국어로", "독일어 논문 번역", "리딩 번역", "translate this paper to Korean". Not for summarising a paper, translating plain text in chat, or translating out of Korean.
---

# ko-paper — 레이아웃을 유지하는 논문 → 한국어 번역

논문 PDF(기본 영어, 다른 언어는 `-l`로 지정)를 그림·표·수식 위치를 그대로 둔 한글 PDF로 바꾼다. 레이아웃은 BabelDOC이,
번역은 사용자의 Claude Code 로그인(`claude -p`) 또는 Codex 로그인(`codex exec`)이 맡는다. 번역은 전부 사용자의 컴퓨터에서
돌고, 사용자 본인의 Claude 사용량을 쓴다.

모든 명령은 이 스킬 폴더의 래퍼로 실행한다. 래퍼가 저장소 위치를 찾고, 처음 실행할 때
BabelDOC 설치와 `uv sync`를 알아서 한다.

```bash
K="<이 스킬의 base directory>/scripts/kopaper.sh"
```

Windows에서 셸이 PowerShell이면(Codex 등) 같은 인자로 `kopaper.ps1`을 쓴다:
`powershell -NoProfile -ExecutionPolicy Bypass -File "<base directory>\scripts\kopaper.ps1" translate "C:\path\paper.pdf"`.
Windows의 Claude Code는 Git Bash로 실행하므로 `kopaper.sh` 그대로 된다.

## 절차

1. **입력 확인.** 경로가 실제 PDF인지 보고, 페이지 수를 알 수 있으면 예상 시간과 함께 알린다
   (`pdfinfo`, macOS면 `mdls -name kMDItemNumberOfPages`). **원문 언어를 정한다.** 사용자가
   말했으면 그 언어, 아니면 첫 페이지 텍스트를 보고 판단한다. 영어가 아니면 `-l <코드>`를 붙인다.
2. **처음이면 점검.** `"$K" doctor`. 실패 메시지(uv 없음, claude 없음)는 그대로 사용자에게
   전하고 설치 방법을 안내한다. 사용자의 셸 설정을 임의로 바꾸지 않는다.
3. **번역 실행 — 백그라운드로.** 30쪽 논문에 5~10분 걸린다.
   ```bash
   "$K" translate "/path/to/paper.pdf"
   ```
   실행했다고 말하고, 완료 알림을 기다린다. 결과를 미리 지어내지 않는다.
4. **완료 보고.** 출력 끝의 요약 줄과 경로를 읽어 알린다.
   - `<이름>.ko.pdf` 한글본, `<이름>.ko.dual.pdf` 원문 병기본 (입력 파일 옆)
   - 호출 수·오류 수·토큰, 참고문헌을 원문으로 되돌린 페이지
   - 가능하면 결과 PDF 한두 쪽의 텍스트를 뽑아 실제로 한글이 들어갔는지 확인하고, 확인한
     범위만 말한다.

진행 상황을 물으면: 실행 출력 파일, 그리고 `$KOPAPER_DATA/jobs/<paper_id>/<시각>/`의 로그와
`$KOPAPER_DATA/proxy_usage.jsonl`(호출마다 한 줄, `ts`가 epoch 초)을 본다.

## 자주 쓰는 옵션

| 상황 | 옵션 |
|---|---|
| 영어가 아닌 논문 | `-l de` (de 독일어, fr 프랑스어, es 스페인어, it 이탈리아어, pt 포르투갈어, nl 네덜란드어, ru 러시아어, ja 일본어, zh 중국어) |
| 일부 페이지만 | `-p 1-3,5` |
| 한글본만 / 병기본만 | `--mono-only` / `--dual-only` |
| 품질 우선 | `-m opus` (기본 `sonnet`) |
| 내 용어집 우선 적용 | `-g terms.csv` (`source,target,tgt_lng`) |
| 출력 폴더 지정 | `-o out/` |
| 여러 편 | 파일을 여러 개 넘긴다. 한 편씩 차례로 번역한다 |
| 번역 후 교정 한 번 더 | `--review` (사용량 약 2배) |
| 스캔본 | `--ocr` (실험 기능, 품질 낮음 — 먼저 사용자에게 알린다) |
| 분야 용어집 끄기 | `-d none` |

같은 논문을 다시 번역하면 저장된 용어집과 번역 캐시를 재사용해 빠르고 싸다. 용어를
새로 뽑게 하려면 `--reextract-glossary`.

## 번역 백엔드와 Codex

- 래퍼가 백엔드를 고른다: `claude`가 있으면 Claude Code, 없고 `codex`만 있으면 Codex.
  사용자가 원하면 `KOPAPER_BACKEND=codex` 또는 `claude-code`를 앞에 붙여 바꾼다.
- 둘 다 없으면 `doctor`가 알려 준다. 그 메시지를 전하고 둘 중 하나를 설치·로그인하도록 안내한다.
  Anthropic API 키가 있으면 `KOPAPER_BACKEND=anthropic-api`도 된다.
- Codex 백엔드는 호출마다 입력 토큰이 더 붙어 느리다(샘플 기준 약 2배). 사용자가 묻거나
  긴 논문이면 미리 알린다.
- 첫 설치(`uv sync`, BabelDOC 설치)와 번역 호출은 네트워크가 필요하다. Codex 샌드박스에서
  막히면 권한 상승을 요청해 같은 명령을 다시 실행한다.

## 업데이트

`"$K" update` — install.sh로 설치한 경우 최신 버전을 받아 스킬을 갱신한다. 플러그인으로
설치했으면 Claude Code의 `/plugin`에서 업데이트한다.

## 웹 UI

여러 편을 끌어다 놓고 진행률을 보거나 용어집을 고쳐 다시 번역하고 싶어 하면:

```bash
"$K" serve --open      # http://127.0.0.1:8787/
```

서버는 127.0.0.1에만 열린다. 오래 떠 있는 프로세스이므로 백그라운드로 띄운다.

## 지켜야 할 것

- **원문 그대로 둘 것을 바꾸지 않는다.** 참고문헌은 Claude에 보내지 않고 원본으로 되돌린다.
  `--translated-refs`는 사용자가 원할 때만 쓴다.
- **공개 서비스로 띄우지 않는다.** 기본 백엔드는 사용자 개인 Claude 구독이다. 남에게 번역을
  제공하려 하면 `KOPAPER_BACKEND=anthropic-api`(API 키, 종량제)가 필요하다고 알린다.
- **텍스트 레이어가 없는 PDF**(스캔본)면 번역 전에 멈추고 알려 준다. 그 메시지를 전하고
  `--ocr`로 갈지 사용자에게 묻는다.
- 결과물은 사용자의 개인 학습용이다. 번역본을 어딘가에 올리거나 공유하는 작업은 사용자가
  요청할 때만, 원저작물의 저작권을 언급하고 한다.

## 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `KOPAPER_DATA` | `~/.ko-paper/data` | 캐시·용어집·작업 로그 (래퍼 기준) |
| `KOPAPER_BACKEND` | 설치된 CLI로 자동 | `claude-code`, `codex`, `anthropic-api`(`ANTHROPIC_API_KEY`, `uv sync --extra api`) |
| `KOPAPER_PORT` | `8787` | 로컬 프록시 포트 |
| `KOPAPER_MAX_CONCURRENCY` | `4` | 동시 Claude 호출 수 |
| `KOPAPER_HOME` | 스킬 폴더 기준 저장소 | 저장소를 다른 곳에 두었을 때 |
