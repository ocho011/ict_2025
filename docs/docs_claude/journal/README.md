# 프로젝트 일지 (Project Journal)

이 디렉토리는 ICT Trading Bot 2025 프로젝트의 일일 진단 보고서와 리팩토링 일지를 관리합니다.

---

## 📁 디렉토리 구조

```
claudedocs/journal/
├── README.md                           # 이 파일
├── YYYY-MM-DD_diagnostic_report.md     # 일일 진단 보고서
├── YYYY-MM-DD_refactoring_log.md       # 일일 리팩토링 일지
└── archive/                            # 아카이브 (선택)
    └── YYYY-MM/
        └── 이전 월 보고서들
```

---

## 📝 파일 형식

### 진단 보고서 (`YYYY-MM-DD_diagnostic_report.md`)

**목적**: 시스템 상태, 버그, 성능을 분석하고 기록

**주요 섹션**:
- Executive Summary (요약)
- 분석 방법
- 정상 작동 컴포넌트
- 버그 분석
- 실행 통계
- 트레이딩 신호 분석
- 현재 설정
- 권장 조치사항
- 성능 메트릭
- 변경 이력

**작성 시점**: 주요 테스트 후, 버그 발견 시, 주간 리뷰 시

### 리팩토링 일지 (`YYYY-MM-DD_refactoring_log.md`)

**목적**: 코드 개선, 아키텍처 변경, 기술 부채 관리

**주요 섹션**:
- 리팩토링 목표
- 완료된 리팩토링
- 진행 중인 리팩토링
- 예정된 리팩토링
- 코드 메트릭
- 아키텍처 개선 아이디어
- 기술 부채
- 학습 노트
- 진행률 추적
- 회고

**작성 시점**: 리팩토링 전, 코드 리뷰 후, 스프린트 종료 시

---

## 🔄 워크플로우

### 일일 작업

1. **아침**: 이전 일지 검토
   ```bash
   # 최근 진단 보고서 확인
   cat claudedocs/journal/*_diagnostic_report.md | tail -100
   ```

2. **작업 중**: 주요 이벤트 기록
   - 버그 발견 → 진단 보고서에 추가
   - 리팩토링 완료 → 리팩토링 일지 업데이트

3. **저녁**: 일일 리뷰 및 요약
   - 진행 상황 업데이트
   - 다음 날 계획 수립

### 주간 작업

1. **월요일**: 주간 목표 설정
   - 리팩토링 일지에 주간 목표 작성
   - 우선순위 결정

2. **금요일**: 주간 회고
   - 완료된 작업 정리
   - 학습한 내용 기록
   - 다음 주 계획

### 월간 작업

1. **월말**: 아카이브
   ```bash
   # 이전 월 파일들을 archive/ 디렉토리로 이동
   mkdir -p claudedocs/journal/archive/2025-12
   mv claudedocs/journal/2025-12-*.md claudedocs/journal/archive/2025-12/
   ```

2. **월초**: 월간 요약 작성
   - 주요 성과 정리
   - 다음 월 계획

---

## 🛠️ 사용 방법

### 새로운 진단 보고서 작성

```bash
# 오늘 날짜로 새 진단 보고서 생성
cp claudedocs/journal/2025-12-26_diagnostic_report.md \
   claudedocs/journal/$(date +%Y-%m-%d)_diagnostic_report.md

# 편집
vim claudedocs/journal/$(date +%Y-%m-%d)_diagnostic_report.md
```

### 리팩토링 일지 업데이트

```bash
# 오늘 날짜 파일 열기 (없으면 생성)
vim claudedocs/journal/$(date +%Y-%m-%d)_refactoring_log.md
```

### 검색 및 분석

```bash
# 모든 에러 관련 기록 검색
grep -r "ERROR\|Bug\|버그" claudedocs/journal/

# 특정 날짜 범위 검색
ls claudedocs/journal/2025-12-2*_diagnostic_report.md

# 리팩토링 완료 건수 확인
grep -h "✅ 완료" claudedocs/journal/*_refactoring_log.md | wc -l
```

---

## 📊 메트릭 추적

### 시스템 건강도
```bash
# 최근 7일 에러율 추적
grep "에러: " claudedocs/journal/2025-12-*_diagnostic_report.md | tail -7
```

### 리팩토링 진행률
```bash
# 주간 완료 작업 수
grep "✅ 완료" claudedocs/journal/*_refactoring_log.md | \
  grep "2025-12-2[0-6]" | wc -l
```

### 코드 품질 트렌드
```bash
# 기술 부채 항목 수
grep "기술 부채:" claudedocs/journal/*_refactoring_log.md | wc -l
```

---

## 🎯 베스트 프랙티스

### DO (권장)

✅ **매일 작성**: 작은 변화도 기록
✅ **구체적 기록**: "버그 수정" 대신 "order_manager.py:1230 파싱 버그 수정"
✅ **메트릭 포함**: 숫자로 측정 가능한 지표 추가
✅ **스크린샷/로그**: 중요한 에러는 로그 발췌 포함
✅ **회고 작성**: 잘된 점, 개선할 점 명시
✅ **다음 단계**: 항상 다음 행동 계획 작성

### DON'T (지양)

❌ **모호한 표현**: "좀 나아짐", "거의 완료"
❌ **주관적 평가**: "코드가 예뻐졌다"
❌ **기록 누락**: "까먹었으니 나중에"
❌ **과도한 세부사항**: 모든 코드 라인 나열
❌ **감정적 표현**: "짜증난다", "어렵다"

---

## 📋 템플릿

### 빠른 시작: 진단 보고서

```markdown
# 프로젝트 진단 보고서

**날짜**: YYYY-MM-DD
**작성**: Your Name

## 📋 Executive Summary
- **전체 상태**: ✅/⚠️/❌
- **주요 발견사항**:

## 🔍 분석 결과
### 정상 작동
-

### 발견된 문제
-

## 💡 권장 조치
-
```

### 빠른 시작: 리팩토링 일지

```markdown
# 리팩토링 일지

**날짜**: YYYY-MM-DD

## 🔄 완료된 작업
- [x]

## 🚧 진행 중
- [ ]

## 📝 예정
- [ ]

## 💬 회고
### 잘된 점
-

### 개선할 점
-
```

---

## 🔗 관련 문서

- [프로젝트 README](../../README.md)
- [개발 가이드](../development_guide.md) (예정)
- [API 문서](../api_docs.md) (예정)

---

## 📞 문의

질문이나 제안사항이 있으시면:
- GitHub Issues 활용
- Pull Request 환영

---

**마지막 업데이트**: 2025-12-26
**관리자**: Claude Code
