# 오늘의 시장

환율, 미국 국채 금리, 금과 원유 선물을 매일 한 번 갱신해서 보여주는 정적
대시보드입니다. GitHub Actions가 하루 두 번 데이터를 받아 `data/` 아래 JSON에
쌓고, GitHub Pages로 배포합니다. iPad에서는 Safari로 열고 **홈 화면에 추가**하면
앱처럼 사용할 수 있습니다.

- 서버, 데이터베이스, API 키가 필요 없습니다.
- 30일 / 90일 / 1년 / 3년 추이 차트, 전일 대비 등락, 다크 모드를 지원합니다.
- 모든 차트가 하나의 기간 선택 버튼으로 함께 움직입니다.
- 원/엔은 **100엔 기준**으로 표시합니다.

## 표시 항목

| 구분 | 항목 | 출처 |
| --- | --- | --- |
| 환율 | 원/달러(USD/KRW), 원/엔(100엔, JPY/KRW) | Yahoo Finance → ECB 기준환율 |
| 미국 국채 | 5년물, 10년물, 30년물 par yield(%) | 미국 재무부 |
| 원자재 선물 | 금(GC), WTI 원유(CL), 브렌트 원유(OIL) | Sina Finance → Eastmoney |

- 국채 금리는 미국 재무부가 고시하는 **par yield**입니다.
- 선물 가격은 최근월물 연속 계약의 **종가**이며, 진행 중인 당일 세션은
  제외합니다.
- ETF나 현물 대체 지표는 사용하지 않습니다.

## 구조

```
.github/workflows/daily-rates.yml  # 매일 11:30 KST 실행, 데이터 커밋, Pages 배포
data/rates.json                    # 누적된 일별 환율
data/yields.json                   # 누적된 미국 국채 5/10/30년 금리
data/futures.json                  # 누적된 금/WTI/브렌트 선물 종가
site/                              # 정적 대시보드 (index.html, app.js, styles.css)
src/financial_report/              # 수집/병합 CLI
tests/                             # 단위 테스트
```

세 데이터 파일은 각각 약 3년치를 보관합니다. 한 그룹의 출처가 실패해도 기존
파일은 그대로 유지되며, 화면에는 마지막 데이터와 함께 **갱신 지연** 배지가
표시됩니다.

## 로컬에서 실행

```bash
# 1) 환율 받아오기 (처음 실행 시 최근 3년 남짓을 채웁니다)
uv run financial-report fetch --data data/rates.json

# 2) 국채 금리와 선물 받아오기
uv run financial-report fetch-markets --data-dir data

# 3) 미리보기
mkdir -p site/data
cp data/rates.json data/yields.json data/futures.json site/data/
python3 -m http.server 8000 -d site
```

브라우저에서 <http://localhost:8000> 을 엽니다. Yahoo가 차단된 네트워크라면
경고가 출력되고 Frankfurter 데이터로 대체됩니다.

유용한 옵션:

```bash
uv run financial-report fetch --dry-run          # 파일을 쓰지 않고 결과만 확인
uv run financial-report fetch --source frankfurter
uv run financial-report fetch --days 1200        # 3년치를 한 번에 채우기/갱신
uv run financial-report fetch --force            # 최신 데이터여도 강제 갱신
```

`fetch-markets`는 그룹 단위로 동작합니다.

```bash
uv run financial-report fetch-markets --group yields       # 국채만
uv run financial-report fetch-markets --group futures      # 선물만
uv run financial-report fetch-markets --days 1200 --force  # 3년치 백필
uv run financial-report fetch-markets --dry-run            # 결과만 확인
uv run financial-report fetch-markets --skip-if-fresh 180  # 3시간 내 갱신됐으면 건너뜀
```

기존에 1년치만 있던 데이터에 3년치를 더하려면 각각 한 번만 실행하면 됩니다.

```bash
uv run financial-report fetch --data data/rates.json --source frankfurter --days 1200 --force
uv run financial-report fetch-markets --data-dir data --days 1200 --force
```

## GitHub Pages 배포

1. GitHub에서 **공개 저장소**를 만듭니다. (예: `financial-report`)
2. 이 폴더에서:

   ```bash
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<사용자명>/financial-report.git
   git push -u origin main
   ```

3. 저장소 **Settings → Pages → Build and deployment → Source**에서
   **GitHub Actions**를 선택합니다.
4. **Actions** 탭 → `Daily market data` → **Run workflow**를 한 번 실행합니다.
   첫 push 시점에는 Pages 설정이 없어 배포가 한 번 실패할 수 있습니다. 3번을
   마친 뒤 다시 실행하면 됩니다. 첫 실행이 끝나면
   `https://<사용자명>.github.io/financial-report/` 가 열립니다.
5. iPad Safari에서 주소를 열고 **공유 → 홈 화면에 추가**를 누릅니다.

이후에는 평일 11:30 KST에 자동으로 갱신됩니다. Actions가 지연되면 12:30 KST
재시도가 실행되고, 이미 갱신된 경우에는 건너뜁니다. 워크플로는 세 데이터 파일을
모두 커밋하고 `_site/data/`에 복사한 뒤 Pages로 배포합니다.

## 데이터에 대해

- **환율**: Yahoo Finance의 시장 환율입니다. 한국은행/은행의 매매기준율과는 몇 원
  차이가 날 수 있습니다. Yahoo가 응답하지 않으면 ECB 기준환율(Frankfurter)을
  사용하며, 화면 하단에 표시됩니다. 두 출처가 섞여 있을 수 있고, 최근 값은
  마지막으로 성공한 출처를 따르며 과거 구간은 당시 수집된 값이 유지됩니다.
- **미국 국채**: 미국 재무부 일별 금리 CSV를 사용합니다. 미국 공휴일에는 새
  고시가 없어 직전 값이 유지됩니다. 2026-11-11은 재향군인의 날이라 최신 값이
  11-10입니다.
- **원자재 선물**: Sina Finance의 최근월물 연속 계약 종가를 우선 사용하고,
  실패하면 Eastmoney의 연속 계약으로 전환합니다. 두 출처의 값은 소수점 단위까지
  일치하는 것을 확인했습니다. 당일 진행 중인 세션은 제외하므로 최신 값은 직전
  거래일 종가입니다.
- 시장 휴장일이나 출처 장애로 새 값이 없으면 직전 데이터가 유지되고, 96시간
  이상 갱신되지 않은 그룹에는 **갱신 지연** 배지가 표시됩니다.
- 모든 값은 참고용이며 실제 거래 가격과 다를 수 있습니다.

## 문제 해결

**Yahoo가 `429 Too Many Requests`를 반환하는 경우**
Yahoo의 비공식 API는 공유 IP에 대해 요청을 제한합니다. 자동으로 재시도하고
Frankfurter로 전환하므로 화면은 계속 동작합니다. GitHub Actions 러너에서는
대부분 정상적으로 수집됩니다.

**Eastmoney가 `502`를 반환하는 경우**
Eastmoney는 호스트별로 간헐적으로 차단됩니다. 수집기는 `push2his` →
`push2delay` → `push2` 순서로 호스트를 바꿔가며 재시도하고, 모두 실패하면
Sina 데이터를 유지합니다.

**Actions가 멈춘 경우**
GitHub는 저장소에 60일간 변경이 없으면 예약 워크플로를 비활성화합니다. 이
프로젝트는 매일 데이터를 커밋하므로 보통 해당되지 않지만, Actions 탭에서
비활성화되었다면 `Enable workflow`를 누르고 한 번 수동 실행하세요.

**데이터를 강제로 갱신하고 싶은 경우**
Actions → `Daily market data` → **Run workflow**에서 `force`를 체크합니다.

## 개발

```bash
uv run python -m unittest discover -s tests -v
uvx ruff check src tests
```

의존성은 없으며 Python 3.14 표준 라이브러리만 사용합니다.
