# Configuration Examples

이 디렉토리는 설정 파일 템플릿과 예제를 포함합니다. 현재 프로젝트는 **모듈 조립식(Modular Assembly)** 전략 설계를 채택하고 있습니다.

## 파일 설명

| 파일 | 용도 |
|------|------|
| `api_keys.ini.example` | API 키 설정 템플릿. 복사해서 `configs/api_keys.ini`로 사용 |
| `trading_config.yaml.example` | 모듈 조립식 거래 설정 템플릿 (YAML 형식). **강력 권장** |

## 사용 방법

### 1. API 키 설정
```bash
cp configs/examples/api_keys.ini.example configs/api_keys.ini
# api_keys.ini 파일을 열어 실제 API 키 입력
```

### 2. 거래 설정 (YAML 형식 - Composable Strategy)
```bash
cp configs/examples/trading_config.yaml.example configs/trading_config.yaml
# trading_config.yaml 파일을 열어 모듈별 설정 수정
```

## 모듈 조립식 전략(Modular Assembly)

현재 시스템은 4가지 핵심 모듈을 조합하여 전략을 구성합니다:

1.  **Entry (진입)**: 진입 시점과 방향을 결정 (예: `ict_optimal_entry`, `sma_entry`)
2.  **Stop Loss (손절)**: 손절 가격을 결정 (예: `zone_based_sl`, `fixed_percent_sl`)
3.  **Take Profit (익절)**: 목표 수익 가격을 결정 (예: `rr_take_profit`, `displacement_tp`)
4.  **Exit (청산)**: 진입 후 조건에 따른 동적 청산 결정 (예: `ict_dynamic_exit`, `null_exit`)

### 설정 계층 구조

- `defaults`: 모든 심볼에 적용되는 기본 모듈 구성입니다.
- `symbols`: 특정 심볼에 대해 기본값을 재정의하거나 특정 모듈만 교체할 수 있습니다.

## 참고

- `trading_config.yaml`은 프로젝트 루트 또는 `configs/` 디렉토리에 위치해야 합니다.
- 이전의 `.ini` 형식 거래 설정은 더 이상 권장되지 않으며, 복잡한 모듈 구성을 지원하지 않습니다.
- 새로운 모듈을 추가하려면 `src/strategies/modules/` 내에 구현하고 `@register_module`로 등록하세요.
