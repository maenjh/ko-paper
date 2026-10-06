# ko-paper 개발 계획

영문 논문 PDF를 넣으면 **레이아웃·figure·수식·표를 그대로 유지한 채 본문만 한글로 바뀐 PDF**를 돌려주는 개인용 소규모 서비스.
번역 엔진은 **Claude 구독제(Claude Code 로그인)** 를 백엔드로 사용한다.

작성일: 2026-10-06

---

## 1. 목표와 범위

| 항목 | 결정 |
|---|---|
| 입력 | 영문 논문 PDF (텍스트 레이어가 있는 일반 PDF. 스캔본은 2차 범위) |
| 출력 | ① 한글 단일본(mono) ② 영문/한글 교차 병기본(dual) 두 가지 |
| 유지 대상 | figure, 표, 수식, 캡션 위치, 페이지 구조, 참고문헌 |
| 번역 위치 | 원래 영문 문단 자리에 한글 문단이 들어감 (레이아웃 보존 번역) |
| 사용자 | 본인 1명 (로컬 실행). 다중 사용자 공개 서비스는 범위 밖 |
| LLM | Claude (구독제). API 키 방식으로도 전환 가능하게 추상화 |

---

## 2. 핵심 설계 결정

### 2-1. 레이아웃 보존 엔진은 직접 만들지 않고 BabelDOC을 쓴다

현재 머신에 이미 설치되어 있는 **BabelDOC 0.5.24** (pdf2zh 2.x의 엔진)이 정확히 이 문제를 푼다.

- DocLayout-YOLO로 문단/figure/표/수식 영역을 분류
- 수식·figure·표는 그대로 두고 **텍스트 문단만 추출 → 번역 → 같은 자리에 재조판**
- 한글 폰트 자동 처리, 글자 수 변화에 따른 폰트 크기·줄바꿈 자동 조정
- mono / dual 출력, 용어집(glossary) 자동 추출·주입, 커스텀 시스템 프롬프트 지원
- **`--openai-base-url` 옵션으로 OpenAI 호환 엔드포인트를 번역기로 꽂을 수 있음**

직접 PyMuPDF로 "텍스트 블록 redact → 한글 insert" 파이프라인을 만드는 것은 수식 판별, 다단 문단 병합, 폰트 폴백 등에서 몇 달치 작업이 된다. BabelDOC을 먼저 쓰고, 부족한 부분만 후처리로 보강하는 것이 현실적이다.

### 2-2. "Claude 구독제"는 Claude Code headless 모드를 OpenAI 호환 프록시로 감싸서 연결한다

Claude 구독(Pro/Max)은 API 키를 주지 않는다. 대신 로컬에 로그인된 **Claude Code CLI의 `claude -p` (headless)** 가 구독 한도 안에서 모델을 호출한다. 이미 검증됨:

```bash
claude -p "Reply with exactly: OK" --output-format json --model sonnet
# → {"stop_reason":"end_turn", "usage":{...}, "result":"OK", ...}
```

따라서 구조는 다음과 같다.

```
[웹 UI / CLI]
     │ PDF 업로드
     ▼
[ko-paper 오케스트레이터]  ── babeldoc 실행 (--openai --openai-base-url http://127.0.0.1:8787/v1)
     │                                   │
     │                                   ▼
     │                      [claude-proxy]  POST /v1/chat/completions
     │                                   │   → 프롬프트 조립 → `claude -p --output-format json`
     │                                   │   → 응답을 OpenAI chat.completion JSON으로 변환
     │                                   ▼
     │                            Claude (구독제, 로컬 로그인)
     ▼
[출력: paper.ko.mono.pdf / paper.ko.dual.pdf]
```

프록시는 **`TranslatorBackend` 인터페이스** 뒤에 두어, 환경변수 하나로 `claude-code`(구독) ↔ `anthropic-api`(API 키, `claude-opus-5-5`) 를 바꿀 수 있게 한다.

### 2-3. 구독제 사용 시 반드시 알아둘 점

1. **약관**: Claude 구독의 Claude Code 사용은 **본인 개인 사용**을 전제로 한다. 본인 로컬에서 본인 논문을 번역하는 용도는 괜찮지만, 이 서비스를 남에게 열어 주거나 배포하면 약관 위반이 된다. 공개 서비스로 키우려면 `anthropic-api` 백엔드(종량제)로 전환해야 한다. 코드에 이 스위치를 처음부터 넣는 이유가 이것이다.
2. **호출당 오버헤드**: 위 테스트에서 "OK" 한 단어 답변에 입력 약 37K 토큰(Claude Code 기본 시스템 프롬프트 + 도구 정의)이 캐시 생성으로 잡혔다. 문단 수백 개를 각각 호출하면 구독 한도를 빨리 소진한다. 대책은 §5 참고.
3. **레이트 리밋**: Max 플랜 5시간 윈도우 한도 기준. 한 편(30페이지, 문단 400개) 기준으로 호출 수와 토큰을 Phase 0에서 실측한다.
4. **병렬 호출**: BabelDOC의 `--qps`, `--pool-max-workers` 로 동시성을 제어. 프록시에서도 세마포어로 상한을 건다.

---

## 3. 구성 요소

### 3-1. `claude-proxy/` — OpenAI 호환 → Claude Code 브리지 (Python, FastAPI)

- 엔드포인트: `POST /v1/chat/completions` (BabelDOC이 쓰는 최소 서브셋), `GET /v1/models`
- 요청 처리:
  - `messages[]` 의 system/user 를 하나의 프롬프트로 합침
  - `claude -p <prompt> --output-format json --model <model> --system-prompt <번역 전용 프롬프트> --disallowedTools ... --max-turns 1` 서브프로세스 실행
  - 결과 JSON의 `result` 를 `choices[0].message.content` 로 매핑, `usage` 매핑
- 동시성: `asyncio.Semaphore(N)`, 실패 시 지수 백오프 재시도(한도 초과 메시지 감지)
- 캐시: `(모델, 프롬프트 해시)` → 응답 SQLite 캐시. 같은 논문 재번역/재시도 시 호출 0
- 백엔드 추상화:
  ```
  class TranslatorBackend(Protocol):
      async def complete(self, system: str, user: str, model: str) -> str
  ClaudeCodeBackend   # subprocess claude -p (구독)
  AnthropicAPIBackend # anthropic SDK, claude-opus-5-5, adaptive thinking, streaming
  ```
- 로깅: 호출 수, 토큰, 소요시간을 작업별로 집계 (한도 관리용)

### 3-2. `pipeline/` — 번역 작업 오케스트레이션

- `translate_pdf(src, out_dir, opts) -> JobResult`
- 내부에서 `babeldoc` CLI(또는 Python API)를 호출:
  ```
  babeldoc --files paper.pdf --lang-in en --lang-out ko \
    --openai --openai-base-url http://127.0.0.1:8787/v1 --openai-api-key dummy \
    --openai-model sonnet \
    --custom-system-prompt "$(cat prompts/translate_ko.txt)" \
    --glossary-files glossary/cs.csv \
    --qps 2 --pool-max-workers 4 \
    --no-watermark --primary-font-family sans-serif \
    --output out/<job_id>/
  ```
- 사전 단계(선택): 논문 앞부분(초록·서론)을 한 번 읽혀 **용어집 자동 생성** → BabelDOC의 glossary로 주입 (BabelDOC 자체 자동 추출 기능과 비교 후 하나 선택)
- 후처리(선택): 한글 폰트 임베딩 확인, 메타데이터(title) 한글화, 파일명 규칙
- 진행률: BabelDOC의 `--report-interval` 출력을 파싱해 단계/퍼센트로 변환

### 3-3. `web/` — 최소 웹 UI (FastAPI + HTMX 또는 단일 HTML)

- 페이지 1개: 드래그&드롭 업로드 → 옵션(mono/dual, 모델, 용어집) → 진행률 바 → 다운로드 링크 2개
- 작업 큐: 단일 프로세스 `asyncio` 큐 + SQLite 작업 테이블 (`queued/running/done/failed`)
- 저장: `data/jobs/<job_id>/{input.pdf, out/, log.txt, meta.json}`
- 인증 없음(로컬 전용, `127.0.0.1` 바인딩). 외부 노출 금지

### 3-4. `cli/` — 웹 없이 바로 쓰는 명령

```bash
kopaper translate paper.pdf            # 기본: mono+dual
kopaper translate paper.pdf --mono-only --model opus
kopaper serve                          # 프록시 + 웹 UI 동시 기동
```

---

## 4. 번역 품질 전략

| 문제 | 대책 |
|---|---|
| 학술 용어 일관성 | 용어집(CSV) 주입. 분야별 기본 용어집(cs/ml, bio, hci) 동봉. 작업마다 자동 추출 용어집 저장 후 재사용 |
| 수식·변수·인용 번호 | BabelDOC이 `{v1}` 같은 플레이스홀더로 보호. 시스템 프롬프트에 "플레이스홀더·수식·인용·URL·고유명사는 절대 변경 금지" 명시 |
| 한글이 영문보다 길어져 넘침 | BabelDOC 자동 축소. 추가로 프롬프트에 "원문보다 1.1배 이내 길이" 지시 |
| 번역투 | 시스템 프롬프트에 논문체 한국어 지침(피동 남용 금지, 명사구 나열 금지, 전문용어는 "한글(영문)" 1회 병기) |
| 캡션/표 제목 | BabelDOC 기본 처리. 표 본문은 `--translate-table-text` 로 선택 |
| 참고문헌 | 번역하지 않음(프롬프트 + 레이아웃 라벨로 제외) |
| 검수 | dual 출력으로 원문 대조. 필요 시 2차 패스: "번역 검토" 프롬프트로 문단 재검 (옵션) |

---

## 5. 구독 한도 최적화 (중요)

1. **시스템 프롬프트 교체**: `--system-prompt` 로 Claude Code 기본 프롬프트를 번역 전용 짧은 프롬프트로 대체, `--disallowedTools` 로 도구 정의 제거 → 호출당 수십 K 토큰 오버헤드를 수 K 이하로. Phase 0에서 실측 확인.
2. **문단 묶음 호출**: (Phase 0 결과: BabelDOC이 이미 여러 문단을 묶어 보내므로 불필요) BabelDOC은 문단 단위로 요청을 보낸다. 프록시에 **코얼레싱 레이어**를 두어 100~300ms 동안 들어온 요청을 모아 `[{"id":1,"text":...}, ...]` 형태로 한 번에 번역시키고 id별로 분배 (Phase 3). 호출 수를 1/10 이하로 줄일 수 있다.
3. **모델 선택**: 기본 `sonnet` (속도·한도 효율), 품질 우선 시 `opus`. 용어집 추출은 한 번만 하므로 opus.
4. **캐시**: 동일 문단 재호출 0.
5. **페이지 분할**: 긴 논문은 `--max-pages-per-part` 로 나누어 실패 시 부분 재시도.

---

## 6. 단계별 로드맵

### Phase 0 — 검증 (반나절)
- [x] `babeldoc`을 OpenAI 호환 프록시에 붙여 기본 동작 확인 (`--lang-out ko`, 한글 폰트 렌더 확인)
- [x] `claude -p` 오버헤드 실측: `--system-prompt --tools "" --strict-mcp-config --setting-sources ""` 로 37K → 850 토큰
- [x] 8페이지·4페이지 논문 end-to-end: 호출 수, 토큰, 소요시간, 결과 PDF 품질 기록
- [x] 결과를 `docs/phase0-report.md` 에 남김 → **GO**

### Phase 1 — CLI MVP (2~3일)
- [x] `claude-proxy` 구현 (FastAPI, 세마포어, 429 전달, SQLite 캐시, 백엔드 추상화)
- [x] `pipeline.translate_pdf` + `kopaper translate` CLI
- [x] 번역 시스템 프롬프트 v1, 기본 용어집(cs/ml)
- [x] 표 짧은 셀 누락, 인라인 수식 깨짐, 용어 불일치 해결 → `docs/phase1-report.md`
- [x] 논문 3편 수동 품질 점검 → 참고문헌 깨짐 발견, 원본 복원 후처리 추가
- [ ] API 백엔드 실제 호출 검증 (API 키 필요)

### Phase 2 — 웹 UI (2일)
- [x] 업로드/옵션/진행률/다운로드 단일 페이지
- [x] 작업 큐 + 작업 이력 목록 (취소·삭제 포함)
- [x] `kopaper serve` 로 프록시+웹 동시 기동, `127.0.0.1` 전용 → `docs/phase2-report.md`

### Phase 3 — 품질·효율 (지속)
- [x] ~~코얼레싱(문단 묶음) 레이어~~ → BabelDOC이 이미 묶어 보내 불필요 (Phase 0)
- [x] 용어집 자동 추출 → 저장 → 재사용, 웹 편집 후 부분 재번역
- [x] 참고문헌을 번역 요청에서 제외
- [x] 표 셀 병합으로 행 겹침 해결
- [x] 스캔 PDF 감지, Tesseract OCR 실험 기능 (품질 낮아 기본 꺼짐)
- [x] 사용량 표시 (로컬 측정. 구독 잔여 한도는 확인 불가)
- [ ] 2차 검토 패스 옵션 (미착수)
→ `docs/phase3-report.md`

---

## 7. 기술 스택

- Python 3.12, `uv` 패키지 관리 (이미 설치됨)
- BabelDOC 0.5.24 (설치됨), PyMuPDF (후처리)
- FastAPI + uvicorn (프록시·웹), HTMX + 정적 HTML (UI), SQLite (작업·캐시)
- Claude Code CLI 2.1.x (구독 백엔드), `anthropic` SDK (API 백엔드, 모델 `claude-opus-5-5`)
- 폰트: BabelDOC 번들 폰트 우선. 품질 불만족 시 Pretendard/Noto Sans KR 지정

## 8. 제안 디렉터리 구조

```
ko-paper/
├── PLAN.md
├── pyproject.toml
├── src/kopaper/
│   ├── proxy/        # OpenAI 호환 서버, backends/{claude_code.py, anthropic_api.py}, cache.py
│   ├── pipeline/     # babeldoc 래퍼, 진행률 파서, 후처리
│   ├── web/          # FastAPI 앱, templates/, static/
│   └── cli.py
├── prompts/translate_ko.txt, glossary_extract.txt
├── glossary/cs_ml.csv, hci.csv
├── data/jobs/        # (gitignore)
└── docs/phase0-report.md
```

## 9. 리스크와 대응

| 리스크 | 대응 |
|---|---|
| Claude Code 업데이트로 `-p` 출력 포맷 변경 | 프록시의 파서를 한 곳에 격리, `--output-format json` 스키마 테스트 추가 |
| 구독 한도 소진 | 사용량 집계·경고, 한도 초과 시 작업 일시정지 후 자동 재개, API 백엔드로 수동 전환 |
| BabelDOC이 특정 논문 레이아웃을 깨뜨림 | dual 출력으로 원문 보존, 실패 페이지만 `--max-pages-per-part` 로 재시도, 이슈 트래킹 |
| 2단 레이아웃·각주·긴 수식 혼합 문단 | 프롬프트 플레이스홀더 보호 강화, 검수 단계에서 수동 보정 |
| 약관(다중 사용자 노출) | 로컬 바인딩 고정, README에 개인 사용 전제 명시, 배포 시 API 백엔드 필수 |
