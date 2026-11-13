# exaone-skill

**Claude가 코드 리뷰를 하면, LG AI연구원의 K-EXAONE 2.5가 한 번 더 봐서 놓친 문제를 찾아 주는 Claude Code 플러그인입니다.**

![흐름도](docs/flow.svg)

## 도입

### 한 줄 요약
한 사람이 검토하면 놓치는 게 생깁니다. 그래서 **다른 회사에서 만든 AI(EXAONE)에게 두 번째로 검토를 맡깁니다.**

### 어떻게 동작하나요? (쉽게)
1. **Claude가 먼저 리뷰합니다.** 숙제를 먼저 채점하는 선생님 역할입니다.
2. **EXAONE이 그 결과를 받아 다시 봅니다.** 두 번째 선생님이 첫 번째 선생님이 놓친 오답을 찾고, 잘못 채점한 곳에는 `[DISPUTE]`로 반론합니다.
3. **Claude가 두 의견을 합칩니다.** EXAONE의 지적이 맞는지 코드를 직접 보고 확인한 뒤, 출처를 `(Claude)`, `(EXAONE)`, `(both)`로 표시해 하나의 목록으로 만듭니다.

EXAONE 호출이라는 단순 반복 작업은 비용이 싼 **Haiku 모델이 대신 실행**합니다. 메인 Claude는 판단에만 집중합니다.

### EXAONE이 응답하지 않으면?
**리뷰는 멈추지 않습니다.** EXAONE은 보조 역할이기 때문입니다. 서버가 혼잡하면 5초 간격으로 5번까지 다시 시도하고, 그래도 안 되면 Claude 리뷰만으로 결과를 냅니다. 이때 결과 맨 위에 `EXAONE 보강 실패 (사유)`를 한 줄로 표시합니다.

### 꼭 알아둘 점
- **코드가 외부로 전송됩니다.** diff와 변경된 파일이 `api.exaone.ai`로 갑니다. 그래서 "exaone" 또는 "엑사원"이라고 **직접 말했을 때만** 동작합니다.
- **하루 호출 한도는 데이터 이용 동의 여부에 따라 다릅니다.**

  | EXAONE 계정 설정: "AI 모델 학습 및 서비스 개선을 위한 이용 기록 분석" | 하루 호출 한도 |
  |---|---|
  | 미동의 | **100회/일** |
  | 동의 | **86,400회/일** |

  동의하면 보낸 코드가 **모델 학습에 쓰일 수 있습니다.** 회사 코드라면 정책을 먼저 확인하세요. (설정 위치: 마이 프로필 > 동의 및 알림 관리. 한도는 2026-11-12에 응답 헤더 `x-day-rate-limit`로 확인했습니다.)
- **Exacode와는 다른 서비스입니다.** EXAONE(`api.exaone.ai`)과 LG 사내 Exacode는 API, 키, 설정이 모두 다릅니다. 이 플러그인은 EXAONE만 사용하며, 실패해도 다른 모델로 자동 전환하지 않습니다.

## 설치

**필요한 것:** Python 3, Claude Code CLI, EXAONE API 키 ([docs.exaone.ai](https://docs.exaone.ai)에서 발급)

```bash
git clone https://github.com/cakel/exaone-skill.git
cd exaone-skill
```

| OS | 명령 |
|---|---|
| Windows | `setup.bat` (또는 `.\setup.ps1`) |
| Linux / macOS / Git Bash | `./setup.sh` |

설치 스크립트가 하는 일은 다음과 같습니다.
1. 플러그인을 Claude Code에 등록합니다. 이미 설치돼 있으면 업데이트합니다.
2. API 키를 묻습니다. 입력 내용은 화면에 표시되지 않으며, `~/.exaone-skill/.env`에 저장됩니다.

설치가 끝나면 **Claude Code를 재시작**하세요.

<details>
<summary>설치 옵션 / 수동 설치</summary>

- 키 등록 건너뛰기: `-SkipKey` / `--skip-key`
- 기본 추론 강도 지정: `-Effort high` / `--effort high`
- 수동 설치 (Claude Code 안에서 실행):
  ```
  /plugin marketplace add <clone한 경로>
  /plugin install exaone-skill@exaone-skill-local
  ```
</details>

### 사용법
```
/exaone-skill:review                  # Claude 리뷰 + EXAONE 보강 (기본)
/exaone-skill:review --no-prior       # EXAONE 단독 리뷰
/exaone-skill:adversarial-review      # 설계와 가정에 대한 반론
/exaone-skill:consult 이 설계 괜찮아?   # 질문하기
/exaone-skill:setup --show            # 설정 확인
```
자연어로 "exaone 으로 리뷰 보강해줘"라고 해도 동작합니다.

## 참고

### 설정
설정 우선순위는 명령 옵션 > 환경변수 > `~/.exaone-skill/.env` > 기본값입니다. `.env` 값은 `/exaone-skill:setup`이나 `python scripts/setup.py --set-…`로 바꿀 수 있습니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `EXAONE_API_KEY` | (필수) | API 키 |
| `EXAONE_REASONING_EFFORT` | `medium` | 추론 강도: `low` / `medium` / `high` / `max` ([측정 근거](docs/MEASUREMENTS.md)) |
| `EXAONE_MAX_TOKENS` | `32768` | 출력 한도 (추론 토큰 포함) |
| `EXAONE_BUSY_WAIT` | `5` | 서버 혼잡(429) 시 재시도 간격(초) |
| `EXAONE_BUSY_RETRIES` | `5` | 서버 혼잡 시 최대 재시도 횟수 |
| `EXAONE_STREAM` | `1` | `0`이면 스트리밍을 끕니다 |

### 종료 코드 (`scripts/exaone_client.py`)
| 코드 | 의미 | 리뷰 진행 |
|---|---|---|
| 0 | 성공 | 결과 병합 |
| 2 | 키 또는 설정 오류 | 설정 안내 |
| 3 | HTTP 오류 (인증, 일일 한도 등) | Claude 단독 |
| 4 | 네트워크 오류 / 서버가 스트림을 끊음 | Claude 단독 |
| 5 | 입력이 너무 큼 | 나눠서 순차 실행 |
| 6 | 출력 잘림 / 빈 응답 | Claude 단독 |
| 7 | 서버 혼잡 (재시도 모두 실패) | Claude 단독 |

### 알려진 동작 (2026-11 관측)
- **속도:** 시간대에 따라 초당 5~31토큰으로 편차가 컸습니다. 작은 diff 하나에 1~6분 걸립니다.
- **서버 혼잡:** 요청을 1건씩만 보내도 429 `service is busy, too many concurrent requests(N)`가 수십 분간 이어진 적이 있습니다. 서버 쪽 혼잡이며, 이 429는 일일 한도에서 차감되지 않았습니다.
- **스트림 끊김:** `effort=high`에서 서버가 종료 신호 없이 스트림을 닫은 적이 있습니다. 이때 클라이언트는 exit 4로 끝납니다.
- **진행 표시:** 진행 상황, 소요 시간, 토큰 수, 남은 호출 횟수, `request_id`는 stderr에 출력됩니다.

### 파일 구성
| 경로 | 역할 |
|---|---|
| `SKILL.md` | Claude가 따르는 작업 절차 (Haiku runner, 결과 병합, 실패 처리) |
| `commands/*.md` | 슬래시 명령 |
| `scripts/exaone_client.py` | API 호출 (표준 라이브러리만 사용) |
| `scripts/setup.py` | 키와 설정 관리 |
| `setup.ps1` / `setup.bat` / `setup.sh` | 설치 스크립트 |

비공식 플러그인이며, LG AI연구원과는 관련이 없습니다. API 명세: <https://docs.exaone.ai/ko/docs/k-exaone-2.5>
