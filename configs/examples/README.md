# Configuration Examples

이 디렉토리는 설정 파일 템플릿과 예제를 포함합니다.

## 파일 설명

| 파일 | 용도 |
|------|------|
| `api_keys.ini.example` | API 키 설정 템플릿. 복사해서 `configs/api_keys.ini`로 사용 |
| `trading_config.ini.example` | 거래 설정 템플릿 (INI 형식). 복사해서 `configs/trading_config.ini`로 사용 |
| `trading_config.yaml.example` | 거래 설정 템플릿 (YAML 형식). 계층적 심볼별 설정 지원 |
| `dynamic_exit_examples.yaml` | Issue #43 동적 청산 설정 예제. `trading_config.yaml` 작성 시 참고 |

## 사용 방법

### 1. API 키 설정
```bash
cp configs/examples/api_keys.ini.example configs/api_keys.ini
# api_keys.ini 파일을 열어 실제 API 키 입력
```

### 2. 거래 설정 (INI 형식)
```bash
cp configs/examples/trading_config.ini.example configs/trading_config.ini
# trading_config.ini 파일을 열어 설정 수정
```

### 3. 거래 설정 (YAML 형식 - 권장)
```bash
cp configs/examples/trading_config.yaml.example configs/trading_config.yaml
# trading_config.yaml 파일을 열어 설정 수정
# YAML 형식은 심볼별 개별 설정을 지원합니다
```

## 참고

- `trading_config.yaml`이 있으면 INI 형식보다 우선 사용됩니다
- 동적 청산 설정은 `dynamic_exit_examples.yaml`을 참고하여 `trading_config.yaml`에 추가하세요
