# Plan: Project Integrity Alignment

이 계획서는 프로젝트의 핵심 의존성, 설정 예시, 그리고 유지보수용 스크립트들을 현재의 **모듈 조립식(Modular Assembly)** 설계와 **Composition 패턴**에 맞게 동기화하여 프로젝트의 전반적인 정합성을 확보하는 것을 목표로 합니다.

## 1. 개요
- **기능명**: project-integrity-alignment
- **목표**: 시스템 설계 변경 사항을 주변 인프라 파일(의존성, 설정, 유틸리티)에 전파하여 운영 안정성 확보.

## 2. 요구사항
1. **의존성 동기화**: `src/` 코드에서 실제 사용 중인 패키지(pydantic 등)를 `requirements.txt` 및 `pyproject.toml`에 반영.
2. **설정 예시 최적화**: `configs/examples/` 내의 구형(INI) 파일을 제거하고, 최신 모듈 조립식 설정을 보여주는 YAML 템플릿으로 갱신.
3. **유지보수 스크립트 현행화**: `scripts/archived/` 내의 주요 스크립트들을 최신 데이터 수집기 설계(Composition 패턴) 및 로그 포맷에 맞게 업데이트.

## 3. 작업 범위
- `requirements.txt`, `pyproject.toml`
- `configs/examples/README.md`, `trading_config.yaml.example`
- `scripts/archived/*.py` (주요 파일 5종)

## 4. 검증 계획
- `requirements.txt` 기반 패키지 설치 가능 여부 (가상 확인)
- YAML 설정 예시의 문법 및 구조 정확성 확인
- 업데이트된 스크립트의 임포트 및 초기화 로직 정합성 검토
