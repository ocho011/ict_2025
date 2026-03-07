# PDCA Plan: Workspace Optimization (workspace-optimize)

- **Date:** 2026-03-07
- **Version:** 1.0.0
- **Status:** Planning
- **Author:** Gemini CLI (Architect)

## 1. 개요 (Overview)
ict_2025 프로젝트가 모놀리식 구조에서 컴포저블(조립식) 전략 아키텍처로 리팩토링됨에 따라, 임시 파일, 중복 스크립트, 구 버전 테스트 코드가 누적되었습니다. 이들은 LLM 컨텍스트 토큰을 불필요하게 소모(약 4.6만 라인 이상)하여 추론 효율을 저하시킵니다. 본 플랜은 워크스페이스를 최적화하여 컨텍스트 토큰 소모를 30-50% 절감하는 것을 목표로 합니다.

## 2. 목표 (Goals)
- **컨텍스트 토큰 소모 30-50% 절감 (약 1.5만 - 2.3만 라인 제외)**
- **불필요한 임시 파일 및 스크립트 아카이빙**
- **LLM 컨텍스트 관리를 위한 `.llmignore` (또는 프로젝트 특화 설정) 도입**
- **아키텍처 문서의 정식 문서화 (`temp/` -> `docs/`)**

## 3. 현황 분석 (Current State Analysis)
| 영역 (Directory) | 현재 LOC (추정) | 상태 분석 |
| :--- | :--- | :--- |
| `src/core/`, `src/execution/` | ~10,000 | 핵심 로직 (보존 필수) |
| `src/strategies/modules/` | ~5,000 | 컴포저블 전략 핵심 (보존 필수) |
| `tests/` | ~30,000 | 거대 테스트 파일(2,000+ LOC) 산재, 구 버전 포함 |
| `scripts/` | ~1,000 | 1회성 검증 스크립트 및 유틸리티 혼재 |
| `temp/` | ~500 | 아키텍처 리팩토링 임시 문서 |
| `logs/`, `backups/`, `.venv/` | N/A | LLM 컨텍스트에서 제외되어야 할 대용량/임시 데이터 |

## 4. 최적화 전략 (Optimization Strategy)
### 4.1. 문서 및 스크립트 아카이빙 (Archiving)
- **(A1) 문서 이동:** `temp/*.md` 및 `.txt` 파일을 `docs/02-design/features/archived/`로 이동.
- **(A2) 스크립트 정리:** `scripts/` 내 1회성 스크립트(`test_binance_mainnet.py` 등)를 `scripts/archived/`로 이동.

### 4.2. 컨텍스트 필터링 (Ignore Settings)
- **(I1) `.llmignore` 생성:** LLM이 기본적으로 로드하지 않을 디렉토리 명시.
  - `tests/` (전체 또는 구 버전)
  - `scripts/archived/`
  - `logs/`, `backups/`, `temp/`
  - `.venv/`, `__pycache__/`
- **(I2) `.cursorrules` (또는 프로젝트용 설정) 연동:** 특정 컨텍스트에서만 파일을 읽도록 가이드라인 작성.

### 4.3. 테스트 코드 최적화 (Tests Optimization)
- **(T1) 대형 테스트 제외:** 1,000라인 이상의 대형 테스트 파일 중 1주일(2/28) 이전 수정된 파일을 컨텍스트 로딩에서 제외.
- **(T2) 중복 테스트 식별:** 컴포저블 아키텍처와 호환되지 않는 구 모놀리식 테스트 식별 및 아카이빙.

## 5. 예상 결과 및 검증 (Expected Outcomes & Verification)
- **토큰 절감:** 전체 LOC 기준 약 40% (2.3만 라인) 이상 제외 성공 여부 확인.
- **추론 속도 향상:** LLM의 파일 분석 및 코드 생성 속도 개선 체감.
- **검증 방법:** `du -sh` 및 `wc -l`를 통한 정리 후 가시적 LOC 감소 확인.

## 6. PDCA Status (JSON Preview)
```json
{
  "primaryFeature": "workspace-optimize",
  "phase": "plan",
  "requirements": [
    "Reduce context token by 30-50%",
    "Implement .llmignore or similar context management",
    "Archive/Move temp/ docs and one-off scripts",
    "Categorize and ignore/exclude old/large tests (>1 week old)"
  ],
  "targetLOCReduction": "15,000 - 23,000 lines",
  "risks": {
    "Risk-1": "Necessary core files might be ignored",
    "Mitigation": "Strictly preserve src/core, execution, and strategies/modules"
  }
}
```

---
*Next Phase Recommendation: `/pdca design workspace-optimize`*
