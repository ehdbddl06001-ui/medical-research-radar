# 메디 리서치 레이더

의사과학자·연구 인턴 공고, 의료 AI 해커톤·공모전, WHO·PhysioNet 새 데이터를
**핸드폰 앱 하나에서 모아 보고, 새 소식은 푸시 알림으로 받는** 도구입니다.
PC를 켜 둘 필요가 없습니다. GitHub 서버가 3시간마다 대신 확인합니다.

```
 GitHub Actions (3시간마다)                     핸드폰
 ┌──────────────────────────┐      푸시      ┌──────────────────┐
 │ monitor.py               │ ─────────────▶ │ ntfy 앱 (알림)     │
 │  19개 사이트·API·뉴스 확인 │   ntfy.sh      │   └ 누르면 원문/앱  │
 │  → docs/data/items.json  │                │                  │
 └────────────┬─────────────┘                │ 메디 리서치 레이더 │
              │ 배포                          │ (홈 화면 웹앱)     │
              ▼                               │  · 분류·검색      │
      GitHub Pages ───────────────────────▶  │  · 마감 임박 D-day │
      https://<아이디>.github.io/<저장소>/     │  · ★ 저장, 오프라인 │
                                              └──────────────────┘
```

## 왜 이 구조인가
- **앱스토어 앱 대신 웹앱(PWA):** iPhone·Android 둘 다 '홈 화면에 추가'로 일반 앱처럼 쓰고, 심사나 설치 파일이 필요 없습니다. 고치면 바로 반영됩니다.
- **푸시는 ntfy 앱:** 무료이고 가입이 필요 없습니다. 웹앱 자체 푸시는 iPhone 제약이 많아 검증된 ntfy를 씁니다. 알림을 누르면 원문이 열리고, '앱에서 보기' 버튼을 누르면 이 앱이 열립니다.
- **수집은 GitHub Actions:** 공개 저장소에서는 무료입니다. PC가 꺼져 있어도 돌아갑니다.

## 확인하는 곳 (19곳)

| 분류 | 출처 | 무엇을 |
|---|---|---|
| 연구·인턴 | 한국코크란 | 메타분석·체계적 문헌고찰 워크숍, 학생연구 모집 |
| | 의협 교육센터 · 대한의사협회 | 교육·프로그램 모집, 연구자 공모 |
| | 서울대 의대 | 학생연구·장학·워크숍 공지 |
| | 한국보건산업진흥원 | 융합형 의사과학자 양성사업, 연수생 모집 |
| | 뉴스·연구기회 | 의사과학자, 의대생 모집, 메타분석 교육 등 8개 검색어 |
| AI·해커톤 | 대한의료인공지능학회 | 학회·워크숍 개최 안내 |
| | 위비티 공모전 | 과학·IT·논문 공모전 중 의료·데이터 관련 |
| | Devpost | 해외 헬스·의료 해커톤 (모집 중인 것만) |
| | Grand Challenge | 의료영상 AI 챌린지 (마감 남은 것만) |
| | GitHub 의료 AI | 최근 30일 새로 뜬 의료 AI 저장소 (별 20~30개 이상) |
| | MONAI 릴리스 | 의료영상 AI 프레임워크 새 버전 |
| | 뉴스·AI해커톤 | 의료 AI 해커톤·경진대회 모집 기사 |
| 데이터·WHO | WHO 질병발생소식 | Disease Outbreak News |
| | WHO 뉴스 | 데이터·보고서·지침 관련 뉴스 |
| | WHO GHO | Global Health Observatory에 **새로 생긴 지표** |
| | PhysioNet | 새로 공개된 의료 데이터셋·새 버전 |
| | AI Hub | 학습용 데이터 개방·해커톤 공지 |
| | 뉴스·의료데이터 | 보건의료 데이터 공개·개방 기사 |

Kaggle과 데이콘은 자동 접속을 막아 두어서 뉴스 검색으로 대신 잡습니다.

## 설치 (처음 한 번, 약 10분)

### 1. GitHub에 올리기
이 폴더를 **공개(Public)** 저장소로 올립니다. 비공개 저장소의 Pages는 유료입니다.
올라가는 내용은 공개된 공고 제목과 링크뿐이고, 푸시 토픽은 비밀값으로 따로 보관합니다.

저장소 **Settings → Pages → Source** 를 **GitHub Actions** 로 바꿉니다.

### 2. 핸드폰 푸시 연결
```bash
python monitor.py --setup-phone
```
- 핸드폰에 **ntfy** 앱 설치 → + → *Subscribe to topic* → 나온 토픽 이름 입력
- 저장소 **Settings → Secrets and variables → Actions → New repository secret**
  이름 `NTFY_TOPIC`, 값은 같은 토픽 이름
- 토픽은 이 PC의 `.ntfy_topic` 파일에만 저장되고 GitHub에는 올라가지 않습니다. `config.yaml` 의 `topic:` 은 비워 두세요.

### 3. 첫 실행
저장소 **Actions → radar → Run workflow**. 1~2분 뒤 앱 주소가 나옵니다:
`https://<아이디>.github.io/<저장소>/`

그 주소를 `config.yaml` 의 `app.url` 에 넣으면 푸시의 '앱에서 보기' 버튼이 이 앱을 엽니다.

### 4. 핸드폰 홈 화면에 추가
- **iPhone:** Safari로 앱 주소 열기 → 공유 → *홈 화면에 추가*
- **Android:** Chrome으로 열기 → 메뉴 → *앱 설치*

## 앱 화면
- **새 소식:** 게시일 순. 분류 칩(연구·인턴 / AI·해커톤 / 데이터·WHO)과 검색으로 거르고, 지난번 이후 새로 들어온 글에는 NEW가 붙습니다.
- **마감 임박:** 제목이나 API에서 마감일을 읽은 공고만 D-day 순으로 보여 줍니다. 7일 안에 마감하는 공고 수가 탭에 빨간 숫자로 뜹니다.
- **저장함:** ☆를 누른 글. 원래 목록에서 사라져도 남습니다 (이 기기에만 저장).
- **알림·출처:** 푸시 설정 방법과 각 출처의 수집 상태. 사이트 구조가 바뀌어 실패하면 '확인 실패'로 표시됩니다.

## 키워드·출처 고치기
모두 `config.yaml` 에서 합니다. 고친 뒤 PC에서 결과를 먼저 확인하세요.
```bash
python monitor.py --dry-run
```
```bash
python monitor.py --dry-run --only 위비티
```
- `categories.*.push: false`: 그 분류는 앱에만 쌓이고 푸시는 오지 않습니다 (예: WHO 소식이 너무 많을 때).
- `filter: true` + `include` / `exclude`: 제목·기관명에 들어간 단어로 거릅니다.
- `require`: 제목에 반드시 있어야 하는 단어 (뉴스를 '모집·공고' 기사로 좁힐 때).

새 출처 유형은 네 가지입니다.

| type | 쓰는 곳 | 필수 항목 |
|---|---|---|
| `html` | 일반 게시판 | `url`, `item`(글 한 줄 선택자). 링크가 javascript면 `id_regex` + `link` |
| `rss` | RSS/Atom 피드 (GitHub 릴리스 포함) | `url` |
| `json` | 공개 API | `url`, `items`(목록 위치), `id`·`title`·`link` 템플릿 (`{필드명}`) |
| `google_news` | 뉴스 검색 | `queries` |

예시: 다른 저장소의 새 릴리스 받기
```yaml
  - name: nnU-Net 릴리스
    category: ai
    type: rss
    url: "https://github.com/MIC-DKFZ/nnUNet/releases.atom"
    max_age_days: 120
```

## PC에서 직접 돌리기 (선택)
GitHub 없이 푸시만 받고 싶으면 `install_task.ps1` 로 윈도우 작업 스케줄러에 등록할 수 있습니다.
이 경우 앱 화면은 없고, PC가 켜져 있을 때만 확인합니다.

## 파일
- `monitor.py` 수집기 · `config.yaml` 설정
- `docs/` 핸드폰 앱 (index.html, app.js, sw.js, manifest, icons) · `docs/data/items.json` 앱 데이터
- `data/seen.json` 이미 본 글 기록 (지우면 다음 실행 때 기준선을 다시 잡고, 그때는 푸시를 보내지 않음)
- `.github/workflows/radar.yml` 3시간마다 수집·배포
