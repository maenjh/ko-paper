# ko-paper

영문 논문 PDF를 그림·표·수식 위치를 유지한 채 한글 PDF로 번역한다.
레이아웃 처리는 [BabelDOC](https://github.com/funstory-ai/BabelDOC), 번역은 Claude가 맡는다.

> 기본 백엔드는 로컬에 로그인된 Claude Code(Claude 구독)다. **본인 개인 사용 전용**이다.
> 다른 사람에게 서비스로 열려면 `KOPAPER_BACKEND=anthropic-api`(API 키, 종량제)로 바꿔야 한다.

## 준비

- Claude Code 로그인 (`claude` 실행 후 `/login`)
- BabelDOC: `uv tool install babeldoc`
- 이 프로젝트: `uv sync` (API 백엔드도 쓰려면 `uv sync --extra api`)

## 웹 UI

```bash
.venv/bin/kopaper serve --open    # http://127.0.0.1:8787/ 을 브라우저로 연다
```

- PDF를 끌어다 놓으면 대기열에 들어가고 한 편씩 차례대로 번역한다.
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
| `KOPAPER_DATA` | `./data` | 작업·캐시·로그 위치 |
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
