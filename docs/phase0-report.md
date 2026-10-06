# Phase 0 검증 보고서

일자: 2026-10-06
결론: **GO.** 구독제 Claude + BabelDOC 조합으로 레이아웃 보존 번역이 실제로 동작한다. 표와 인라인 수식 일부만 Phase 1~3에서 보강하면 된다.

## 1. 구성

```
babeldoc 0.5.24 --openai --openai-base-url http://127.0.0.1:8787/v1 --openai-model sonnet
      │
      ▼
kopaper-proxy (src/kopaper/proxy/server.py, FastAPI)
      │  claude -p --output-format json --model sonnet --system-prompt <번역용>
      │           --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence
      ▼
Claude Code 2.1.290 (구독 로그인)
```

실행 방법:

```bash
uv sync && .venv/bin/kopaper-proxy        # 127.0.0.1:8787
babeldoc --files paper.pdf --lang-in en --lang-out ko \
  --openai --openai-base-url http://127.0.0.1:8787/v1 --openai-api-key dummy --openai-model sonnet \
  --qps 4 --pool-max-workers 4 --no-watermark --save-auto-extracted-glossary --output out/
```

## 2. 호출 오버헤드 실측 (한 문장 번역, sonnet)

| 설정 | 호출당 입력 토큰 | 결과 |
|---|---|---|
| 기본 `claude -p` | 약 37,000 | 정상 |
| `--system-prompt` + `--tools ""` | 약 5,400 | 정상 |
| 위 + `--strict-mcp-config --setting-sources ""` | **약 850** | 정상 (채택) |
| `--bare` | - | 실패: 구독 로그인을 읽지 못함 |

호출당 고정 오버헤드를 약 1/40로 줄였다.

## 3. 논문 번역 실측

| 논문 | 페이지 | 호출 수 | 입력 토큰 | 출력 토큰 | 소요 시간 |
|---|---|---|---|---|---|
| SDV UX (CHI EA '26, 그림 4·표 1) | 8 | 96 | 193K | 40K | 182초 |
| Cold-start Rec (IEEE, 수식 포함) | 4 | 44 | 96K | 23K | 96초 |

- 페이지당 약 **12회 호출, 약 30K 토큰, 약 22초**. 30페이지 논문이면 약 360회, 약 90만 토큰, 약 11분으로 추정된다.
- 위 토큰에는 BabelDOC의 자동 용어 추출이 포함되어 있다(전체의 약 27%).
- 호출 지연 중앙값 6.3초, 최대 18초. 동시 4개로 실행했다.
- BabelDOC이 이미 여러 문단을 한 요청에 묶어 보낸다. 계획에 있던 별도 코얼레싱 레이어는 필요 없다.
- 한도 초과나 실패 응답은 0건이었다.

## 4. 품질 점검

**잘 된 것**
- 그림, 표 테두리, 페이지 구조, 2단 레이아웃이 원본과 동일하게 유지된다. 페이지별 이미지 수가 원본과 같다.
- 제목, 초록, 본문, 절 제목, 그림 캡션이 원래 위치에 한글로 들어간다.
- 인용 번호 [10], [14-16]이 보존된다.
- 논문체 '-다' 종결로 자연스럽게 번역된다.
- 자동 용어집이 합리적이다(예: auxiliary loss → 보조 손실, warm item → 웜 아이템).

**문제**
1. **표 셀 번역 불완전.** Male, High, None, Age, Role 같은 한 단어 셀이 영문으로 남는다. `--translate-table-text`를 켜도 같다.
2. **표 행 겹침.** 한글 셀 내용이 길어져 아래 행과 겹친다.
3. **용어 일관성이 실행마다 다름.** 같은 "Actor"가 한 번은 "행위자", 다른 실행에서는 "배우"로 번역되었다. 용어집을 실행마다 새로 뽑기 때문이다.
4. **인라인 수식 일부 손상.** 수식이 문장 중간에 있을 때 `$`, `%` 같은 깨진 기호가 남거나 수식 조각 순서가 어긋나는 경우가 있다. 디스플레이 수식은 대체로 유지된다.
5. 저자 소속 블록 줄바꿈이 어색하다. 그림 내부 텍스트는 번역되지 않는다(BabelDOC 설계상 정상).

## 5. Phase 1 반영 사항

- 프록시에 표 셀처럼 짧은 입력도 번역하도록 지시하는 시스템 프롬프트를 추가하고, 짧은 셀 누락이 줄어드는지 비교한다.
- 논문별 자동 용어집을 저장하고, 같은 논문 재번역과 같은 분야 논문에서 `--glossary-files`로 재사용한다. 분야 기본 용어집과 병합한다.
- 인라인 수식은 `--add-formula-placehold-hint`와 프롬프트의 플레이스홀더 보존 규칙을 강화해 재측정한다.
- 표 행 겹침은 BabelDOC 한계로 보고, dual 출력으로 원문 대조를 기본 제공한다. Phase 3에서 표 영역만 원문 유지하는 후처리를 검토한다.
- 기본 모델은 sonnet을 유지한다. 품질 비교용으로 opus 1회 실행을 Phase 1에 넣는다.

## 6. 산출물

- `data/out/sdv/sdv.no_watermark.ko.mono.pdf`, `...dual.pdf`
- `data/out/coldstart/coldstart.no_watermark.ko.mono.pdf`, `...dual.pdf`, `...glossary.csv`
- `data/proxy_usage.jsonl` 호출 로그
