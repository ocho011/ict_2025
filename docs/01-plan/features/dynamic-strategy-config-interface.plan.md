# PDCA Plan: 동적 전략 Config 인터페이스 설계 및 UI 연동

**작성일**: 2026년 3월 1일
**상태**: Plan 승인 대기 중
**분석 근거**: `docs/03-analysis/strategy_architecture_report_20260226.md`
**선행 계획**: `hierarchical_injection_plan_20260226.md` (본 계획이 확장·대체)
**브랜치**: `feature/strategy_architecture`

---

## 0. 인터뷰 결과 요약 (의사결정 로그)

| # | 결정 항목 | 선택 | 근거 |
|---|----------|------|------|
| 1 | UI 조립 범위 | **완전 동적 모듈 조립** | Entry/SL/TP/Exit 4개 모듈을 UI에서 개별 선택·조합 |
| 2 | Config 소스 | **YAML 단독** | INI 의존성 완전 제거, TradingConfigHierarchical 승격 |
| 3 | Hot Reload | **완전 Hot Reload** | 전략 종류 변경까지 런타임에 가능 |
| 4 | UI 통신 | **콜백/이벤트 패턴** | EventDispatcher 활용, ConfigUpdateEvent |
| 5 | 포지션 안전 | **포지션 정리 후 전환** | 열린 포지션 close → 새 전략 적용 |
| 6 | 모듈 등록 | **데코레이터 기반 자동 등록** | @register_module 데코레이터 |
| 7 | 스키마 검증 | **Pydantic 스키마** | Cold Path에서만 사용, 성능 영향 없음 |

---

## 1. 목적 (Goal)

**현재 문제 (분석 보고서 핵심)**:
- `trading_config.ini`의 평면적 구조로 모든 심볼에 동일 전략 강제 (1:N Relay)
- `module_config_builder.py`의 하드코딩된 빌더(`_build_ict_config`)로 모듈 자유 조합 불가
- `TradingConfigHierarchical`이 존재하지만 `TradingEngine`에서 실제 소비되지 않음
- UI에서 전략 파라미터를 동적으로 변경할 인터페이스 부재

**목표**:
- 심볼별 독립적 전략 모듈 조립 및 주입 (Injection) 아키텍처 완성
- UI에서 모듈 선택 → 파라미터 튜닝 → 런타임 Hot Reload까지 전체 파이프라인 구현
- INI 의존성 완전 제거, YAML을 유일한 Canonical Source로 확립

---

## 2. 3단계 로드맵

### Phase 1: 인터페이스 확장 — 모듈 레지스트리 & 스키마 시스템

**목표**: 각 모듈이 자신을 선언하고 UI가 발견할 수 있는 기반 구축

**작업 항목**:

| ID | 작업 | 산출물 |
|----|------|--------|
| 1.1 | **ModuleRegistry 싱글톤** 구현 | `src/strategies/module_registry.py` |
| 1.2 | **@register_module 데코레이터** 구현 | `src/strategies/decorators.py` |
| 1.3 | **모듈별 Pydantic ParamSchema** 정의 | 각 모듈에 `param_schema()` classmethod 추가 |
| 1.4 | 기존 모듈에 데코레이터 적용 | `ICTEntryDeterminer`, `ZoneBasedStopLoss` 등 |
| 1.5 | **ModuleRegistry.get_available_modules()** | 카테고리별 사용 가능 모듈 목록 반환 |
| 1.6 | **ModuleRegistry.get_param_schema(category, name)** | 특정 모듈의 Pydantic 스키마 반환 |

**핵심 인터페이스 설계**:

```python
# src/strategies/module_registry.py
from typing import Dict, Type, List
from pydantic import BaseModel

class ModuleInfo:
    name: str
    category: str  # 'entry' | 'stop_loss' | 'take_profit' | 'exit'
    cls: Type
    param_schema: Type[BaseModel]
    description: str

class ModuleRegistry:
    """싱글톤 모듈 레지스트리 — 데코레이터로 자동 등록"""
    _instance = None
    _modules: Dict[str, Dict[str, ModuleInfo]] = {}

    def register(self, category: str, name: str, cls, param_schema, description="")
    def get_available_modules(self, category: str) -> List[ModuleInfo]
    def get_param_schema(self, category: str, name: str) -> Type[BaseModel]
    def create_module(self, category: str, name: str, params: dict) -> object
```

```python
# src/strategies/decorators.py
def register_module(category: str, name: str, description: str = ""):
    """데코레이터: 클래스를 ModuleRegistry에 자동 등록"""
    def decorator(cls):
        ModuleRegistry.get_instance().register(category, name, cls, cls.ParamSchema, description)
        return cls
    return decorator
```

```python
# 적용 예시: src/strategies/ict/entry.py
@register_module('entry', 'ict_entry', description='ICT 기반 진입 결정자')
class ICTEntryDeterminer(EntryDeterminer):
    class ParamSchema(BaseModel):
        active_profile: str = "balanced"
        swing_lookback: int = 10
        ltf_interval: str = "5m"
        mtf_interval: str = "1h"
        htf_interval: str = "4h"
        fvg_min_gap_percent: float = 0.1
        ob_min_strength: float = 0.5
        use_killzones: bool = True
```

**완료 기준**:
- [ ] `ModuleRegistry.get_available_modules('entry')` 호출 시 등록된 Entry 모듈 목록 반환
- [ ] 각 모듈의 `ParamSchema`로 유효성 검증 동작 확인
- [ ] 기존 테스트 전체 통과 (회귀 없음)

---

### Phase 2: Config 동적화 — YAML 승격 & Dynamic Assembler

**목표**: INI 제거, YAML 기반 심볼별 모듈 조립, Hot Reload 파이프라인

**작업 항목**:

| ID | 작업 | 산출물 |
|----|------|--------|
| 2.1 | **YAML 스키마 확장** — 모듈 단위 조립 명세 | `configs/trading_config.yaml` 신규 포맷 |
| 2.2 | **INI 로딩 코드 제거** — ConfigManager에서 INI 의존성 완전 삭제 | `config_manager.py` 수정 |
| 2.3 | **DynamicAssembler** 구현 — YAML 명세 → StrategyModuleConfig 동적 조립 | `src/strategies/dynamic_assembler.py` |
| 2.4 | **TradingEngine 와이어링 변경** — hierarchical_config 직접 소비 | `trading_engine.py` Step 4.5 수정 |
| 2.5 | **ConfigUpdateEvent** 정의 및 EventDispatcher 연동 | `src/events/config_events.py` |
| 2.6 | **StrategyHotReloader** 구현 — 이벤트 수신 → 포지션 정리 → 전략 교체 | `src/core/strategy_hot_reloader.py` |
| 2.7 | **getDynamicParamsFromUI() Hook** 구현 | `src/config/ui_config_hook.py` |

**YAML 신규 포맷**:

```yaml
# configs/trading_config.yaml (확장된 포맷)
defaults:
  strategy: ict_strategy
  risk_reward_ratio: 2.0
  stop_loss_percent: 1.5

symbols:
  BTCUSDT:
    enabled: true
    modules:                          # 신규: 모듈 단위 조립 명세
      entry:
        type: ict_entry
        params:
          active_profile: aggressive
          htf_interval: "4h"
      stop_loss:
        type: zone_based_sl
        params:
          min_sl_percent: 0.5
          max_sl_percent: 2.0
      take_profit:
        type: displacement_tp
        params:
          risk_reward_ratio: 2.5
      exit:
        type: ict_exit
        params:
          trailing_distance: 0.3
  ETHUSDT:
    enabled: true
    modules:
      entry:
        type: sma_entry
        params:
          period: 20
      stop_loss:
        type: percentage_sl
        params:
          stop_loss_percent: 1.0
      take_profit:
        type: rr_take_profit
        params:
          risk_reward_ratio: 3.0
      exit:
        type: null_exit
```

**getDynamicParamsFromUI() Hook 설계 (Mockup)**:

```python
# src/config/ui_config_hook.py
from dataclasses import dataclass
from typing import Dict, Optional
from pydantic import BaseModel

@dataclass(frozen=True)
class UIConfigUpdate:
    """UI에서 전달되는 설정 변경 요청"""
    symbol: str
    module_category: str          # 'entry' | 'stop_loss' | 'take_profit' | 'exit'
    module_type: Optional[str]    # None이면 파라미터만 변경
    params: Dict                  # Pydantic 스키마로 검증될 파라미터

class UIConfigHook:
    """UI ↔ Config 연동 Hook"""

    def __init__(self, config_manager, module_registry, event_dispatcher):
        self._config_manager = config_manager
        self._registry = module_registry
        self._dispatcher = event_dispatcher

    def get_dynamic_params_from_ui(self, symbol: str) -> Dict:
        """현재 심볼의 전체 모듈 구성 및 파라미터를 UI용 dict로 반환"""
        symbol_config = self._config_manager.get_symbol_config(symbol)
        result = {}
        for category in ['entry', 'stop_loss', 'take_profit', 'exit']:
            module_spec = symbol_config.modules.get(category, {})
            module_type = module_spec.get('type')
            schema = self._registry.get_param_schema(category, module_type)
            result[category] = {
                'type': module_type,
                'params': module_spec.get('params', {}),
                'schema': schema.model_json_schema() if schema else None,
                'available_modules': [
                    {'name': m.name, 'description': m.description}
                    for m in self._registry.get_available_modules(category)
                ]
            }
        return result

    def apply_config_update(self, update: UIConfigUpdate) -> bool:
        """UI에서 받은 설정 변경을 검증 후 적용"""
        # 1. Pydantic 스키마로 파라미터 검증 (Cold Path)
        schema = self._registry.get_param_schema(
            update.module_category,
            update.module_type or self._get_current_type(update.symbol, update.module_category)
        )
        validated = schema(**update.params)

        # 2. YAML 업데이트
        self._config_manager.update_symbol_module(
            update.symbol, update.module_category,
            update.module_type, validated.model_dump()
        )

        # 3. ConfigUpdateEvent 발행 → StrategyHotReloader가 수신
        self._dispatcher.dispatch(ConfigUpdateEvent(
            symbol=update.symbol,
            category=update.module_category,
            module_type=update.module_type,
            params=validated.model_dump(),
            requires_strategy_rebuild=(update.module_type is not None)
        ))
        return True
```

**StrategyHotReloader 핵심 로직**:

```python
# src/core/strategy_hot_reloader.py
class StrategyHotReloader:
    """ConfigUpdateEvent 수신 → 포지션 정리 → 전략 교체"""

    async def on_config_update(self, event: ConfigUpdateEvent):
        symbol = event.symbol

        if event.requires_strategy_rebuild:
            # 전략 종류 변경 → 포지션 정리 후 전환
            await self._close_positions(symbol, reason="strategy_hot_reload")
            new_strategy = self._assembler.assemble_for_symbol(symbol)
            self._engine.replace_strategy(symbol, new_strategy)
        else:
            # 파라미터만 변경 → 실시간 반영
            self._engine.update_strategy_params(symbol, event.params)
```

**완료 기준**:
- [ ] INI 로딩 코드 완전 제거, YAML만으로 시스템 부팅 성공
- [ ] BTCUSDT=ICT, ETHUSDT=SMA 다른 전략으로 독립 작동 로그 확인
- [ ] UI Hook을 통한 파라미터 변경 → 이벤트 발행 → 전략 교체 E2E 동작
- [ ] Hot Reload 시 열린 포지션 정리 후 새 전략 적용 확인

---

### Phase 3: 테스트 & 검증

**목표**: 전체 파이프라인 검증, 회귀 테스트, 성능 벤치마크

**작업 항목**:

| ID | 작업 | 산출물 |
|----|------|--------|
| 3.1 | **ModuleRegistry 단위 테스트** | `tests/test_module_registry.py` |
| 3.2 | **DynamicAssembler 단위 테스트** — 유효/무효 조합 검증 | `tests/test_dynamic_assembler.py` |
| 3.3 | **UIConfigHook 통합 테스트** — get/apply 시나리오 | `tests/test_ui_config_hook.py` |
| 3.4 | **StrategyHotReloader 통합 테스트** — 포지션 정리 → 전략 교체 | `tests/test_strategy_hot_reloader.py` |
| 3.5 | **회귀 테스트** — 기존 백테스트 결과 100% 일치 검증 | 기존 테스트 스위트 |
| 3.6 | **성능 벤치마크** — Hot Reload 지연, 메모리 영향 측정 | `tests/benchmarks/` |
| 3.7 | **YAML 마이그레이션 스크립트** — 기존 INI → 신규 YAML 자동 변환 | `scripts/migrate_ini_to_yaml.py` |

**성능 검증 기준** (CLAUDE.md 기준 준수):

| 메트릭 | 목표값 | 비고 |
|--------|--------|------|
| Hot Reload 지연 | < 500ms (포지션 정리 제외) | 전략 교체 자체의 지연 |
| Pydantic 검증 | < 5ms per call | Cold Path만 사용 |
| ModuleRegistry 조회 | < 100μs | O(1) dict lookup |
| 메모리 증가 | < 5MB | 레지스트리 + 스키마 캐시 |

---

## 3. 변경 영향도 분석

### 신규 생성 파일

| 파일 | 설명 | Phase |
|------|------|-------|
| `src/strategies/module_registry.py` | 모듈 레지스트리 싱글톤 | 1 |
| `src/strategies/decorators.py` | @register_module 데코레이터 | 1 |
| `src/strategies/dynamic_assembler.py` | YAML → StrategyModuleConfig 동적 조립 | 2 |
| `src/config/ui_config_hook.py` | UI ↔ Config 연동 Hook | 2 |
| `src/events/config_events.py` | ConfigUpdateEvent 정의 | 2 |
| `src/core/strategy_hot_reloader.py` | 이벤트 → 포지션 정리 → 전략 교체 | 2 |
| `scripts/migrate_ini_to_yaml.py` | INI → YAML 마이그레이션 | 3 |
| `tests/test_module_registry.py` | 레지스트리 단위 테스트 | 3 |
| `tests/test_dynamic_assembler.py` | 조립기 단위 테스트 | 3 |
| `tests/test_ui_config_hook.py` | UI Hook 통합 테스트 | 3 |
| `tests/test_strategy_hot_reloader.py` | Hot Reloader 통합 테스트 | 3 |

### 수정 대상 파일 (diff 예상)

| 파일 | 변경 내용 | 예상 diff |
|------|----------|-----------|
| `src/utils/config_manager.py` | INI 로딩 제거, YAML 전용화, `get_symbol_config()` 추가, `update_symbol_module()` 추가 | ~150줄 삭제, ~80줄 추가 |
| `src/config/symbol_config.py` | `SymbolConfig`에 `modules: Dict` 필드 추가, `ModuleSpec` dataclass 추가 | ~40줄 추가 |
| `src/core/trading_engine.py` | Step 4.5 와이어링 변경: `DynamicAssembler` 사용, `StrategyHotReloader` 등록 | ~60줄 수정 |
| `src/strategies/module_config_builder.py` | `_STRATEGY_REGISTRY` → `ModuleRegistry`로 마이그레이션 또는 폐기 | ~100줄 삭제 |
| `src/strategies/__init__.py` | `StrategyFactory.create_composed()` → `DynamicAssembler` 위임 | ~20줄 수정 |
| `src/strategies/ict/__init__.py` | `_build_ict_config` 빌더 → 데코레이터 기반 자동 등록으로 전환 | ~30줄 수정 |
| `src/strategies/ict/entry.py` | `@register_module` 데코레이터 추가, `ParamSchema` 내부 클래스 추가 | ~25줄 추가 |
| `src/strategies/ict/exit.py` | `@register_module` 데코레이터 추가, `ParamSchema` 추가 | ~20줄 추가 |
| `src/strategies/ict/pricing/zone_based_sl.py` | `@register_module` 추가, `ParamSchema` 추가 | ~15줄 추가 |
| `src/strategies/ict/pricing/displacement_tp.py` | `@register_module` 추가, `ParamSchema` 추가 | ~15줄 추가 |
| `src/pricing/base.py` | `PercentageStopLoss`, `RiskRewardTakeProfit`에 데코레이터 추가 | ~20줄 추가 |
| `src/entry/base.py` | `EntryDeterminer` ABC에 `ParamSchema` 추상 속성 추가 검토 | ~5줄 추가 |
| `configs/trading_config.yaml` | 모듈 단위 조립 명세로 포맷 확장 | ~50줄 수정 |
| `configs/trading_config.ini` | **삭제 또는 deprecated 마킹** | 파일 삭제 |

### 영향 받지 않는 파일 (변경 없음)

- `src/strategies/composable.py` — 내부 로직 변경 없음, 주입받는 인터페이스 동일
- `src/strategies/base.py` — BaseStrategy ABC 변경 없음
- `src/models/module_requirements.py` — ModuleRequirements 변경 없음
- `src/strategies/buffer_manager.py` — 버퍼 관리 변경 없음

---

## 4. 위험 요소 및 대응

| 위험 | 영향 | 확률 | 대응 |
|------|------|------|------|
| INI 제거 시 기존 설정 유실 | 높음 | 낮음 | 마이그레이션 스크립트 제공 (Phase 3.7) |
| Hot Reload 중 Race Condition | 높음 | 중간 | asyncio Lock + 포지션 정리 완료 대기 |
| 모듈 조합 호환성 (A의 Entry + B의 SL 충돌) | 중간 | 중간 | 모듈 호환성 매트릭스 정의 + 검증 로직 |
| Pydantic 스키마의 Hot Path 유입 | 높음 | 낮음 | Cold Path 강제: UI 입력 시에만 검증, 런타임은 dataclass |
| 대규모 리팩토링으로 회귀 발생 | 높음 | 중간 | Phase별 점진 적용, 각 Phase 완료 시 전체 테스트 |

---

## 5. 의존 관계 및 순서

```
Phase 1.1 (ModuleRegistry) ──┐
Phase 1.2 (데코레이터)       ──┤
                              ├──→ Phase 1.4 (기존 모듈 적용)
Phase 1.3 (ParamSchema)     ──┘
                                      │
Phase 1.5, 1.6 (조회 API) ←──────────┘
         │
         ▼
Phase 2.1 (YAML 확장) ──→ Phase 2.2 (INI 제거) ──→ Phase 2.4 (Engine 와이어링)
         │
Phase 2.3 (DynamicAssembler) ──→ Phase 2.4
         │
Phase 2.5 (ConfigUpdateEvent) ──→ Phase 2.6 (HotReloader) ──→ Phase 2.7 (UI Hook)
                                                                      │
                                                                      ▼
                                                               Phase 3 (테스트)
```

---

## 6. 성공 기준 (Plan 전체)

- [ ] `ModuleRegistry`에 최소 6개 모듈 등록 (Entry 2, SL 2, TP 2, Exit 2)
- [ ] YAML에서 심볼별 독립 모듈 조립 → 시스템 정상 부팅 → 독립 작동 확인
- [ ] `getDynamicParamsFromUI(symbol)` 호출 → 모듈 목록/스키마/현재값 반환
- [ ] `apply_config_update()` → ConfigUpdateEvent → Hot Reload → 전략 교체 E2E
- [ ] Hot Reload 지연 < 500ms (포지션 정리 제외)
- [ ] 기존 백테스트 결과 100% 회귀 없음
- [ ] INI 파일 의존성 코드 0줄

---

## 7. 다음 단계

- [ ] **본 Plan 승인 후** → `docs/02-design/features/dynamic-strategy-config-interface.design.md` 상세 설계서 작성 (autopilot 자동 전환)
- [ ] 설계서에 포함할 항목: 클래스 다이어그램, 시퀀스 다이어그램, 모듈 호환성 매트릭스, YAML 스키마 JSON Schema
