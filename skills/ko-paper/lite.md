# 간이 모드 (lite) — BabelDOC 없이 에이전트가 직접 번역

BabelDOC을 쓸 수 없을 때 쓴다. 대표적인 경우는 Windows Smart App Control이 PyMuPDF 같은
컴파일된 모듈을 막아 `doctor`가 실패할 때다. 사용자가 "빨리", "간단히", "설치 없이"를 원할 때도 쓴다.
아무것도 설치하지 않고, 지금 실행 중인 에이전트가 직접 번역한다. `claude -p`나 `codex login`은 따로 필요 없다.

결과물은 **원문 구조(제목·문단·표·캡션·수식)를 살린 한글 PDF**다. 원문 레이아웃(2단, 페이지 위치)과 그림
이미지는 유지하지 않는다. 시작할 때 사용자에게 이 차이를 한 줄로 알린다. 레이아웃 유지본이 필요하면
BabelDOC이 동작하는 환경에서 일반 모드로 번역하면 된다는 것도 함께 알린다. Windows에서
Smart App Control 때문에 간이 모드로 왔다면 그 환경은 WSL이다(README의 "Windows Smart App Control" 참고).

`S` = 이 스킬 폴더의 `scripts` 경로.

## 1. 원문 읽기

- **Claude Code**: Read 도구로 PDF를 직접 읽는다. 20쪽이 넘으면 `pages`로 나눠 읽는다(한 번에 최대 20쪽).
- **그 밖의 에이전트(Codex 등)**: 순수 Python 추출 스크립트를 쓴다. 컴파일된 모듈이 없어 SAC에 막히지 않는다.
  ```bash
  uv run --no-project --with pypdf python "$S/extract_text.py" paper.pdf > paper.txt
  # uv가 없으면: python -m pip install --user pypdf && python "$S/extract_text.py" paper.pdf > paper.txt
  ```
  `--pages 1-10`으로 나눠 뽑을 수 있다. 페이지마다 `===== page N / M =====` 줄이 붙는다.
  2단 논문은 단 순서가 섞여 나올 수 있으니 문맥으로 바로잡는다.

긴 논문은 10쪽 안팎씩 나눠 **읽기 → 번역 → HTML에 이어 쓰기**를 반복한다. 전체를 한꺼번에 들고 있지 않는다.

## 2. 번역 규칙

- 격식체 학술 문어체 "-다"로 쓴다("제안한다", "보여 준다"). "-습니다", "-요"는 쓰지 않는다.
- 능동문을 쓰고 번역투를 피한다("~에 의해", "~되어진다", "~를 가지다", 명사 나열).
- 원문에 없는 영어 병기를 덧붙이지 않는다. 한국 연구자가 영어로 쓰는 용어는 영어로 둔다
  (LLM, Transformer, BERT, 데이터셋·모델 이름).
- 저자 이름, 소속 고유명사, 제품·데이터셋·학회 이름은 원문 그대로 둔다.
- 표의 머리글과 셀, 짧은 단어까지 빠짐없이 번역한다("Male" → "남성", "None" → "없음").
- 캡션 라벨은 "그림 3", "표 1"로 옮긴다. 다른 언어의 라벨(Abbildung, Tableau 등)도 같다.
- 수식, 변수, 기호, 인용 표시([3], (Smith et al., 2020)), URL, DOI, 코드는 바꾸지 않는다.
- **참고문헌은 번역하지 않고 원문 그대로 옮긴다.**
- 원문이 영어가 아니어도 같은 규칙으로 한국어로 옮긴다.

## 3. HTML 쓰기

`$S/lite_template.html`을 복사해 `<원본 이름>.ko.lite.html`(원본 PDF 옆)로 만든다. `TITLE`과
`<!-- CONTENT -->`만 바꾸고 스타일은 그대로 둔다. 쓰는 요소는 아래뿐이다.

```html
<h1>번역한 제목</h1>
<p class="orig-title">Original Title</p>
<p class="meta">저자 · 소속</p>
<p class="note">ko-paper 간이 모드 번역본. 원문 레이아웃과 그림은 원본 PDF를 참고한다.</p>
<div class="abstract"><p><b>초록</b> — ...</p></div>
<h2>1 서론</h2>   <h3>1.1 ...</h3>   <p>...</p>
<div class="page">원문 p.3</div>                       <!-- 원문 페이지가 바뀌는 곳 -->
<div class="figure"><span class="where">[그림 1 — 원문 p.2 참고]</span>
  <p class="caption"><b>그림 1:</b> 번역한 캡션</p></div>
<p class="eq">C = P(accept | correct) − P(accept | incorrect) &nbsp; (1)</p>
<table><thead><tr><th>...</th></tr></thead><tbody><tr><td>...</td></tr></tbody></table>
<div class="refs"><h2>참고문헌</h2><p>[1] 원문 그대로 ...</p></div>
```

`<`, `>`, `&`는 HTML 문자 참조로 바꾼다.

## 4. PDF 만들기

이미 설치된 Edge나 Chrome으로 인쇄한다.

```bash
"$S/html2pdf.sh" paper.ko.lite.html paper.ko.lite.pdf                      # macOS, Linux, Git Bash
powershell -NoProfile -ExecutionPolicy Bypass -File "$S\html2pdf.ps1" paper.ko.lite.html paper.ko.lite.pdf   # Windows PowerShell
```

이 단계는 브라우저를 띄우므로 **에이전트 샌드박스(Codex 등)에서는 막힌다**(macOS에서 `Abort trap`·종료 코드 134,
`the browser did not write`). 그때는 수동 인쇄로 넘기지 말고, 묻지 말고 권한 상승을 요청해 같은 명령을
샌드박스 밖에서 다시 실행한다. 브라우저 자체를 찾지 못할 때만 HTML 경로를 알려 주고
"브라우저로 열어 PDF로 인쇄"하라고 안내한다.

## 5. 보고

`<이름>.ko.lite.pdf`와 `.html`의 경로, 번역한 페이지 범위를 알린다. 마지막에 "간이 모드라 원문 레이아웃과
그림은 유지되지 않음"을 한 줄로 덧붙인다.
