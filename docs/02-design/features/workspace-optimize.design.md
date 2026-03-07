# PDCA Design: Workspace Optimization (workspace-optimize)

- **Date:** 2026-03-07
- **Version:** 1.0.0
- **Status:** Design
- **Parent Plan:** [workspace-optimize.plan.md](../01-plan/features/workspace-optimize.plan.md)
- **Author:** Gemini CLI (Architect)

## 1. 아키텍처 개요 (Architecture Overview)
본 설계는 ict_2025 프로젝트의 LLM 컨텍스트 활용 효율성을 극대화하기 위해 불필요한 데이터를 '격리(Archive)'하고 '무시(Ignore)'하는 메커니즘을 정의합니다. 특히 `src/` 디렉토리의 무결성을 최우선으로 하며, 테스트 및 임시 데이터만 최적화 대상으로 한정합니다.

### 1.1. 최적화 메커니즘 (Optimization Mechanism)
1.  **Isolation (격리):** `temp/`, `scripts/` 중 1회성 파일을 전용 아카이브 디렉토리로 이동.
2.  **Exclusion (제외):** `.llmignore` 및 `.cursorrules`를 통해 LLM이 대용량/구버전 파일을 로드하지 않도록 필터링.
3.  **Protection (보호):** `src/` 디렉토리는 무시 대상에서 명시적으로 제외(White-list)하여 프로젝트 핵심 로직 참조 보장.

## 2. 기술 사양 (Technical Specifications)

### 2.1. 컨텍스트 무시 설정 (`.llmignore` / `.geminiignore`)
다음 패턴을 컨텍스트 무시 파일에 등록하여 기본적으로 로딩되지 않도록 합니다:
```text
# Fixed Ignored Directories
logs/
backups/
.venv/
__pycache__/
*.pyc

# Archived Scripts and Documents
scripts/archived/
docs/**/archived/

# Specific Large Tests (Exclude >1000 LOC, >1 week old)
# Implementation note: Specific filenames will be listed here after discovery in 'do' phase
tests/test_order_execution.py  # ~2,100 LOC
tests/core/test_trading_engine.py # ~1,500 LOC
# (And other large tests identified in plan phase)
```

### 2.2. 파일 아카이브 구조 (Archive Structure)
| 원본 경로 (Source) | 이동 경로 (Target) | 사유 (Reason) |
| :--- | :--- | :--- |
| `temp/*.md` | `docs/01-plan/features/archived/` | 리팩토링 설계 문서 보존 및 루트 정리 |
| `scripts/*.py` | `scripts/archived/` | 1회성 검증 스크립트(Binance mainnet test 등) 격리 |
| `src/` | **N/A (보존)** | **프로젝트 핵심 로직 - 이동/삭제 절대 금지** |

### 2.3. LLM 지침 설계 (LLM Context Instructions)
`.cursorrules` 또는 `CLAUDE.md`에 다음 지침을 추가합니다:
- "By default, large tests (>1000 LOC) and archived scripts are ignored to optimize token usage."
- "If you need to analyze specific tests, explicitly ask to read the file."
- "Never ignore files under the `src/` directory."

## 3. 워크플로우 및 시퀀스 (Workflow & Sequence)
1.  **(Discovery):** `tests/` 및 `scripts/` 내 1,000라인 이상 + 1주일 이전 수정 파일 최종 리스트업.
2.  **(Migration):** `temp/` 문서 및 `scripts/` 내 1회성 파일 이동 (Git history 보존).
3.  **(Configuration):** `.llmignore` (또는 프로젝트용 무시 파일) 생성 및 규칙 적용.
4.  **(Instruction):** `.cursorrules` 또는 `CLAUDE.md`에 컨텍스트 활용 지침 업데이트.
5.  **(Verification):** 정리 후 워크스페이스 LOC 재측정 및 컨텍스트 로딩 속도 확인.

## 4. 제약 사항 및 보안 (Constraints & Security)
- **Constraint-1:** `src/` 내의 어떠한 파일도 이동, 삭제, 무시 처리하지 않는다. (사용자 요구사항 준수)
- **Constraint-2:** 모든 파일 이동은 `git mv` 또는 유사한 방식으로 Git 히스토리를 유지해야 한다.
- **Security-1:** `.env` 및 민감 정보는 기존 `.gitignore` 규칙을 엄격히 따르며, 이번 최적화 과정에서 노출되지 않도록 한다.

## 5. 테스트 및 검증 전략 (Testing & Verification)
- **LOC Reduction Check:** `wc -l`를 사용하여 정리 전/후의 '컨텍스트 가시 LOC' 변화 측정. (목표: 30% 이상 감소)
- **Core Accessibility Check:** `src/` 내의 핵심 파일(`trading_engine.py`, `trade_coordinator.py` 등)이 여전히 검색 및 읽기 가능한지 확인.
- **LLM Reasoning Test:** 최적화된 워크스페이스 환경에서 LLM이 핵심 로직을 여전히 정확히 분석하는지 샘플 질문으로 테스트.

---
*Next Phase Recommendation: `/pdca do workspace-optimize`*
