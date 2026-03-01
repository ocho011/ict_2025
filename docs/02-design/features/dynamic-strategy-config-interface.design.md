# Design: 동적 전략 Config 인터페이스 설계 및 UI 연동

**작성일**: 2026년 3월 1일
**상태**: Design 검토 중
**Plan 참조**: `docs/01-plan/features/dynamic-strategy-config-interface.plan.md`
**브랜치**: `feature/strategy_architecture`

---

## 1. 아키텍처 개요

### 1.1. 현재 구조 (AS-IS)

```
trading_config.ini ──→ ConfigManager._load_trading_config()
                           │
                           ▼
                      TradingConfig (flat dataclass)
                           │
                           ▼ strategy_name (global, 1개)
                      build_module_config()
                           │
                           ▼ _STRATEGY_REGISTRY[name] → builder()
                      StrategyModuleConfig
                           │
                           ▼ 모든 심볼에 동일 적용
                      StrategyFactory.create_composed()
                           │
                           ▼
                      ComposableStrategy (per-symbol, but same config)
```

**문제점**: 1:N Relay — 모든 심볼이 동일한 전략·파라미터 강제

### 1.2. 목표 구조 (TO-BE)

```
trading_config.yaml ──→ ConfigManager._load_hierarchical_config()
     (Canonical)            │
                            ▼
                      TradingConfigHierarchical
                            │
                            ├─ get_symbol_config("BTCUSDT") → SymbolConfig (modules 포함)
                            │       │
                            │       ▼
                            │  DynamicAssembler.assemble_for_symbol()
                            │       │
                            │       ├─ ModuleRegistry.create('entry', 'ict_entry', params)
                            │       ├─ ModuleRegistry.create('stop_loss', 'zone_based_sl', params)
                            │       ├─ ModuleRegistry.create('take_profit', 'displacement_tp', params)
                            │       └─ ModuleRegistry.create('exit', 'ict_exit', params)
                            │       │
                            │       ▼
                            │  StrategyModuleConfig (BTC 전용)
                            │       │
                            │       ▼
                            │  ComposableStrategy (BTC 전용)
                            │
                            ├─ get_symbol_config("ETHUSDT") → SymbolConfig (다른 modules)
                            │       │
                            │       ▼  ... (ETH 전용 조립)
                            │
                            └─ UIConfigHook ←──── UI (ConfigUpdateEvent)
                                    │
                                    ▼
                              StrategyHotReloader
                                    │
                                    ├─ close_positions(symbol)
                                    └─ replace_strategy(symbol, new)
```

---

## 2. 핵심 클래스 설계

### 2.1. ModuleRegistry — 모듈 레지스트리 싱글톤

**파일**: `src/strategies/module_registry.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel


class ModuleCategory:
    """모듈 카테고리 상수"""
    ENTRY = "entry"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    EXIT = "exit"

    ALL = [ENTRY, STOP_LOSS, TAKE_PROFIT, EXIT]


@dataclass(frozen=True)
class ModuleInfo:
    """등록된 모듈의 메타 정보"""
    name: str                           # 'ict_entry', 'zone_based_sl' 등
    category: str                       # ModuleCategory 값
    cls: Type                           # 실제 클래스 (ICTEntryDeterminer 등)
    param_schema: Type[BaseModel]       # Pydantic 파라미터 스키마
    description: str = ""               # UI 표시용 설명
    compatible_with: Dict[str, List[str]] = field(default_factory=dict)
    # 예: {"stop_loss": ["zone_based_sl", "percentage_sl"]}


class ModuleRegistry:
    """
    싱글톤 모듈 레지스트리.

    데코레이터(@register_module)로 자동 등록.
    UI에서 사용 가능한 모듈 목록, 스키마 조회, 인스턴스 생성 담당.

    Thread Safety: 등록은 import 시점(싱글스레드), 조회는 읽기 전용이므로 안전.
    """
    _instance: Optional[ModuleRegistry] = None
    _modules: Dict[str, Dict[str, ModuleInfo]]  # {category: {name: ModuleInfo}}

    def __init__(self):
        self._modules = {cat: {} for cat in ModuleCategory.ALL}

    @classmethod
    def get_instance(cls) -> ModuleRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """테스트용 싱글톤 리셋"""
        cls._instance = None

    def register(
        self,
        category: str,
        name: str,
        cls_type: Type,
        param_schema: Type[BaseModel],
        description: str = "",
        compatible_with: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """모듈 등록. 중복 시 경고 후 덮어쓰기."""
        if category not in ModuleCategory.ALL:
            raise ValueError(f"Invalid category: {category}. Must be one of {ModuleCategory.ALL}")

        info = ModuleInfo(
            name=name,
            category=category,
            cls=cls_type,
            param_schema=param_schema,
            description=description,
            compatible_with=compatible_with or {},
        )
        self._modules[category][name] = info

    def get_available_modules(self, category: str) -> List[ModuleInfo]:
        """특정 카테고리의 사용 가능 모듈 목록 반환"""
        return list(self._modules.get(category, {}).values())

    def get_module_info(self, category: str, name: str) -> Optional[ModuleInfo]:
        """특정 모듈의 정보 반환"""
        return self._modules.get(category, {}).get(name)

    def get_param_schema(self, category: str, name: str) -> Optional[Type[BaseModel]]:
        """특정 모듈의 Pydantic 파라미터 스키마 반환"""
        info = self.get_module_info(category, name)
        return info.param_schema if info else None

    def create_module(self, category: str, name: str, params: dict) -> Any:
        """
        모듈 인스턴스 생성.

        1. ModuleInfo 조회
        2. Pydantic 스키마로 params 검증 (Cold Path)
        3. validated params로 인스턴스 생성

        Args:
            category: 모듈 카테고리
            name: 모듈 이름
            params: 파라미터 dict (Pydantic으로 검증됨)

        Returns:
            모듈 인스턴스 (EntryDeterminer, StopLossDeterminer 등)
        """
        info = self.get_module_info(category, name)
        if info is None:
            raise ValueError(
                f"Module '{name}' not found in category '{category}'. "
                f"Available: {[m.name for m in self.get_available_modules(category)]}"
            )

        # Cold Path: Pydantic 검증
        validated = info.param_schema(**params)
        return info.cls.from_validated_params(validated)

    def get_all_modules_summary(self) -> Dict[str, List[Dict[str, Any]]]:
        """UI용 전체 모듈 요약. 카테고리별 이름/설명/스키마 반환."""
        result = {}
        for category in ModuleCategory.ALL:
            result[category] = [
                {
                    "name": info.name,
                    "description": info.description,
                    "schema": info.param_schema.model_json_schema(),
                    "compatible_with": info.compatible_with,
                }
                for info in self._modules[category].values()
            ]
        return result

    def validate_combination(
        self, entry: str, stop_loss: str, take_profit: str, exit_module: str
    ) -> List[str]:
        """
        모듈 조합 호환성 검증.

        Returns:
            경고 메시지 리스트. 빈 리스트면 호환 OK.
        """
        warnings = []
        entry_info = self.get_module_info(ModuleCategory.ENTRY, entry)
        if entry_info and entry_info.compatible_with:
            for cat, allowed in entry_info.compatible_with.items():
                actual = {"stop_loss": stop_loss, "take_profit": take_profit, "exit": exit_module}.get(cat)
                if actual and actual not in allowed:
                    warnings.append(
                        f"Entry '{entry}' recommends {cat} in {allowed}, but '{actual}' selected."
                    )
        return warnings
```

### 2.2. @register_module 데코레이터

**파일**: `src/strategies/decorators.py`

```python
from typing import Dict, List, Optional, Type
from pydantic import BaseModel


def register_module(
    category: str,
    name: str,
    description: str = "",
    compatible_with: Optional[Dict[str, List[str]]] = None,
):
    """
    클래스 데코레이터: ModuleRegistry에 자동 등록.

    사용법:
        @register_module('entry', 'ict_entry', description='ICT 진입')
        class ICTEntryDeterminer(EntryDeterminer):
            class ParamSchema(BaseModel):
                active_profile: str = "balanced"
                ...

            @classmethod
            def from_validated_params(cls, params: ParamSchema) -> 'ICTEntryDeterminer':
                return cls.from_config(params.model_dump())

    요구사항:
        - 클래스에 ParamSchema (Pydantic BaseModel) 내부 클래스 필수
        - from_validated_params(cls, params) classmethod 필수
    """
    def decorator(cls):
        # ParamSchema 존재 확인
        if not hasattr(cls, 'ParamSchema'):
            raise AttributeError(
                f"{cls.__name__} must define 'ParamSchema' inner class "
                f"(Pydantic BaseModel) for @register_module"
            )
        if not issubclass(cls.ParamSchema, BaseModel):
            raise TypeError(
                f"{cls.__name__}.ParamSchema must inherit from pydantic.BaseModel"
            )

        # from_validated_params 존재 확인
        if not hasattr(cls, 'from_validated_params'):
            raise AttributeError(
                f"{cls.__name__} must define 'from_validated_params(cls, params)' "
                f"classmethod for @register_module"
            )

        # 레지스트리에 등록 (lazy import로 순환 참조 방지)
        from src.strategies.module_registry import ModuleRegistry
        ModuleRegistry.get_instance().register(
            category=category,
            name=name,
            cls_type=cls,
            param_schema=cls.ParamSchema,
            description=description,
            compatible_with=compatible_with,
        )

        # 원본 클래스 반환 (래핑 없음)
        return cls

    return decorator
```

### 2.3. ParamSchema 적용 예시 — 기존 모듈 확장

#### ICTEntryDeterminer

```python
# src/strategies/ict/entry.py (추가 부분만)
from pydantic import BaseModel, Field
from src.strategies.decorators import register_module

@register_module(
    'entry', 'ict_entry',
    description='ICT(Inner Circle Trader) 기반 진입 결정자',
    compatible_with={
        'stop_loss': ['zone_based_sl', 'percentage_sl'],
        'take_profit': ['displacement_tp', 'rr_take_profit'],
        'exit': ['ict_exit', 'null_exit'],
    }
)
class ICTEntryDeterminer(EntryDeterminer):
    class ParamSchema(BaseModel):
        active_profile: str = Field("balanced", description="ICT 프로필 (strict/balanced/aggressive)")
        swing_lookback: int = Field(10, ge=5, le=50, description="스윙 탐색 범위")
        ltf_interval: str = Field("5m", description="Low Timeframe 인터벌")
        mtf_interval: str = Field("1h", description="Mid Timeframe 인터벌")
        htf_interval: str = Field("4h", description="High Timeframe 인터벌")
        fvg_min_gap_percent: float = Field(0.1, ge=0.01, le=1.0, description="FVG 최소 갭 %")
        ob_min_strength: float = Field(0.5, ge=0.1, le=1.0, description="Order Block 최소 강도")
        use_killzones: bool = Field(True, description="킬존 시간대 필터 사용")

    @classmethod
    def from_validated_params(cls, params: ParamSchema) -> 'ICTEntryDeterminer':
        """Pydantic 검증된 params로 인스턴스 생성"""
        return cls.from_config(params.model_dump())
```

#### ZoneBasedStopLoss

```python
# src/strategies/ict/pricing/zone_based_sl.py (추가 부분만)
@register_module(
    'stop_loss', 'zone_based_sl',
    description='FVG/OB 존 기반 손절가 결정자'
)
class ZoneBasedStopLoss(StopLossDeterminer):
    class ParamSchema(BaseModel):
        buffer_percent: float = Field(0.1, ge=0.01, le=0.5, description="존 경계 버퍼 %")
        min_sl_percent: float = Field(0.5, ge=0.1, le=2.0, description="최소 SL 거리 %")
        max_sl_percent: float = Field(2.0, ge=0.5, le=5.0, description="최대 SL 거리 %")
        fallback_sl_percent: float = Field(1.0, ge=0.1, le=3.0, description="폴백 SL %")

    @classmethod
    def from_validated_params(cls, params: ParamSchema) -> 'ZoneBasedStopLoss':
        return cls(**params.model_dump())
```

#### PercentageStopLoss / RiskRewardTakeProfit

```python
# src/pricing/stop_loss/percentage.py
@register_module('stop_loss', 'percentage_sl', description='고정 비율 손절가')
class PercentageStopLoss(StopLossDeterminer):
    class ParamSchema(BaseModel):
        stop_loss_percent: float = Field(1.0, ge=0.1, le=5.0, description="손절 비율 %")

    @classmethod
    def from_validated_params(cls, params: ParamSchema) -> 'PercentageStopLoss':
        return cls(stop_loss_percent=params.stop_loss_percent)

# src/pricing/take_profit/risk_reward.py
@register_module('take_profit', 'rr_take_profit', description='리스크/리워드 비율 기반 익절가')
class RiskRewardTakeProfit(TakeProfitDeterminer):
    class ParamSchema(BaseModel):
        risk_reward_ratio: float = Field(2.0, ge=1.0, le=10.0, description="RR 비율")

    @classmethod
    def from_validated_params(cls, params: ParamSchema) -> 'RiskRewardTakeProfit':
        return cls(risk_reward_ratio=params.risk_reward_ratio)
```

### 2.4. DynamicAssembler — 동적 전략 조립기

**파일**: `src/strategies/dynamic_assembler.py`

```python
"""
YAML 심볼 설정 → StrategyModuleConfig 동적 조립.

module_config_builder.py의 하드코딩 빌더를 대체.
ModuleRegistry에서 모듈을 이름으로 조회하여 동적 생성.
"""
import logging
from typing import Dict, List, Optional, Tuple

from src.config.symbol_config import SymbolConfig
from src.pricing.base import StrategyModuleConfig
from src.strategies.module_registry import ModuleCategory, ModuleRegistry

logger = logging.getLogger(__name__)

# 카테고리별 기본 모듈 (modules 블록이 없는 심볼용 폴백)
_DEFAULT_MODULES = {
    ModuleCategory.ENTRY: ("sma_entry", {}),
    ModuleCategory.STOP_LOSS: ("percentage_sl", {}),
    ModuleCategory.TAKE_PROFIT: ("rr_take_profit", {}),
    ModuleCategory.EXIT: ("null_exit", {}),
}


class DynamicAssembler:
    """
    심볼별 StrategyModuleConfig 동적 조립.

    SymbolConfig.modules dict를 읽어 ModuleRegistry에서 모듈을 생성하고
    StrategyModuleConfig로 번들링.
    """

    def __init__(self, registry: Optional[ModuleRegistry] = None):
        self._registry = registry or ModuleRegistry.get_instance()

    def assemble_for_symbol(
        self, symbol_config: SymbolConfig
    ) -> Tuple[StrategyModuleConfig, Optional[List[str]], float]:
        """
        심볼 설정으로부터 StrategyModuleConfig 동적 조립.

        Args:
            symbol_config: SymbolConfig (modules dict 포함)

        Returns:
            (StrategyModuleConfig, intervals, min_rr_ratio)
        """
        modules_spec = getattr(symbol_config, 'modules', None) or {}

        # 4개 모듈 생성
        entry = self._create_module(
            ModuleCategory.ENTRY,
            modules_spec.get('entry', {}),
            symbol_config.symbol,
        )
        stop_loss = self._create_module(
            ModuleCategory.STOP_LOSS,
            modules_spec.get('stop_loss', {}),
            symbol_config.symbol,
        )
        take_profit = self._create_module(
            ModuleCategory.TAKE_PROFIT,
            modules_spec.get('take_profit', {}),
            symbol_config.symbol,
        )
        exit_det = self._create_module(
            ModuleCategory.EXIT,
            modules_spec.get('exit', {}),
            symbol_config.symbol,
        )

        # 호환성 경고
        warnings = self._registry.validate_combination(
            entry=modules_spec.get('entry', {}).get('type', _DEFAULT_MODULES[ModuleCategory.ENTRY][0]),
            stop_loss=modules_spec.get('stop_loss', {}).get('type', _DEFAULT_MODULES[ModuleCategory.STOP_LOSS][0]),
            take_profit=modules_spec.get('take_profit', {}).get('type', _DEFAULT_MODULES[ModuleCategory.TAKE_PROFIT][0]),
            exit_module=modules_spec.get('exit', {}).get('type', _DEFAULT_MODULES[ModuleCategory.EXIT][0]),
        )
        for w in warnings:
            logger.warning("[%s] Module compatibility: %s", symbol_config.symbol, w)

        module_config = StrategyModuleConfig(
            entry_determiner=entry,
            stop_loss_determiner=stop_loss,
            take_profit_determiner=take_profit,
            exit_determiner=exit_det,
        )

        # intervals는 aggregated_requirements에서 자동 도출
        from src.strategies.module_config_builder import _interval_to_minutes
        reqs = module_config.aggregated_requirements
        intervals = sorted(reqs.timeframes, key=_interval_to_minutes) if reqs.timeframes else None

        # min_rr_ratio: take_profit 파라미터에서 추출 또는 기본값
        tp_params = modules_spec.get('take_profit', {}).get('params', {})
        min_rr_ratio = tp_params.get('risk_reward_ratio', 1.5)

        logger.info(
            "[%s] Dynamic assembly complete: entry=%s, sl=%s, tp=%s, exit=%s, intervals=%s",
            symbol_config.symbol,
            modules_spec.get('entry', {}).get('type', 'default'),
            modules_spec.get('stop_loss', {}).get('type', 'default'),
            modules_spec.get('take_profit', {}).get('type', 'default'),
            modules_spec.get('exit', {}).get('type', 'default'),
            intervals,
        )

        return module_config, intervals, min_rr_ratio

    def _create_module(self, category: str, spec: dict, symbol: str):
        """단일 모듈 생성. spec이 없으면 기본 모듈 사용."""
        module_type = spec.get('type')
        params = spec.get('params', {})

        if not module_type:
            default_type, default_params = _DEFAULT_MODULES[category]
            module_type = default_type
            params = default_params
            logger.debug("[%s] No %s module specified, using default: %s", symbol, category, module_type)

        return self._registry.create_module(category, module_type, params)
```

### 2.5. SymbolConfig 확장 — modules 필드 추가

**파일**: `src/config/symbol_config.py` (수정)

```python
# SymbolConfig 데이터클래스에 추가할 필드:

@dataclass
class ModuleSpec:
    """단일 모듈 명세 (YAML modules 블록의 한 항목)"""
    type: str           # 'ict_entry', 'zone_based_sl' 등
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SymbolConfig:
    # ... 기존 필드 유지 ...

    # 신규: 모듈 단위 조립 명세 (Phase 2)
    modules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # 구조: {"entry": {"type": "ict_entry", "params": {...}},
    #         "stop_loss": {"type": "zone_based_sl", "params": {...}}, ...}
```

**하위 호환성**: `modules`가 빈 dict이면 기존 `strategy` + `strategy_params` 경로로 폴백.

### 2.6. ConfigUpdateEvent & StrategyHotReloader

**파일**: `src/events/config_events.py`

```python
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ConfigUpdateEvent:
    """
    UI에서 발생하는 설정 변경 이벤트.

    EventDispatcher 기존 이벤트 시스템과 분리된 Config 전용 이벤트.
    Event 모델(src/models/event.py)의 EventType에 CONFIG_UPDATE 추가하지 않음
    — Config 이벤트는 Trading 이벤트(Candle/Signal/Order)와 다른 생명주기를 가짐.
    """
    symbol: str
    category: str                        # 'entry' | 'stop_loss' | 'take_profit' | 'exit'
    module_type: Optional[str] = None    # None이면 파라미터만 변경
    params: Dict[str, Any] = field(default_factory=dict)
    requires_strategy_rebuild: bool = False  # True이면 전략 인스턴스 교체 필요


@dataclass(frozen=True)
class ConfigReloadCompleteEvent:
    """전략 교체 완료 알림"""
    symbol: str
    old_strategy_name: str
    new_strategy_name: str
    positions_closed: int
```

**파일**: `src/core/strategy_hot_reloader.py`

```python
"""
전략 Hot Reload 관리자.

ConfigUpdateEvent 수신 → 포지션 안전 정리 → 전략 인스턴스 교체.

실시간 트레이딩 가이드라인 준수:
- asyncio Lock으로 Race Condition 방지
- 포지션 정리 완료 대기 후 전략 교체
- 감사 로그(AuditLogger) 기록
"""
import asyncio
import logging
from typing import TYPE_CHECKING, Dict, Optional

from src.events.config_events import ConfigUpdateEvent, ConfigReloadCompleteEvent

if TYPE_CHECKING:
    from src.core.audit_logger import AuditLogger
    from src.strategies.dynamic_assembler import DynamicAssembler
    from src.config.symbol_config import TradingConfigHierarchical


logger = logging.getLogger(__name__)


class StrategyHotReloader:
    """
    Config 변경 이벤트를 받아 전략을 안전하게 교체.

    Safety Protocol:
    1. 심볼별 asyncio.Lock으로 동시 교체 방지
    2. 열린 포지션 정리 (close) 완료 대기
    3. 새 전략 인스턴스 생성 및 교체
    4. 감사 로그 기록
    """

    def __init__(
        self,
        strategies: Dict[str, "BaseStrategy"],
        assembler: "DynamicAssembler",
        hierarchical_config: "TradingConfigHierarchical",
        position_closer,            # PositionCacheManager or TradeCoordinator
        audit_logger: "AuditLogger",
    ):
        self._strategies = strategies
        self._assembler = assembler
        self._config = hierarchical_config
        self._position_closer = position_closer
        self._audit_logger = audit_logger
        self._locks: Dict[str, asyncio.Lock] = {}   # 심볼별 Lock

    def _get_lock(self, symbol: str) -> asyncio.Lock:
        if symbol not in self._locks:
            self._locks[symbol] = asyncio.Lock()
        return self._locks[symbol]

    async def on_config_update(self, event: ConfigUpdateEvent) -> Optional[ConfigReloadCompleteEvent]:
        """
        ConfigUpdateEvent 처리.

        파라미터만 변경: 전략 인스턴스의 config dict 업데이트 (경량)
        전략 종류 변경: 포지션 정리 → 새 전략 인스턴스 생성 → 교체 (중량)
        """
        async with self._get_lock(event.symbol):
            if event.requires_strategy_rebuild:
                return await self._rebuild_strategy(event)
            else:
                self._update_params(event)
                return None

    async def _rebuild_strategy(self, event: ConfigUpdateEvent) -> ConfigReloadCompleteEvent:
        """전략 인스턴스 전체 교체 (포지션 정리 후)"""
        symbol = event.symbol
        old_strategy = self._strategies.get(symbol)
        old_name = old_strategy.module_config.entry_determiner.name if old_strategy else "none"

        logger.info("[%s] Strategy rebuild requested: %s → ...", symbol, old_name)

        # 1. 포지션 정리
        closed_count = await self._close_positions(symbol)

        # 2. YAML 설정 리로드 (이미 UIConfigHook에서 업데이트됨)
        symbol_config = self._config.get_symbol_config(symbol)

        # 3. 새 전략 조립
        from src.strategies import StrategyFactory
        module_config, intervals, min_rr_ratio = self._assembler.assemble_for_symbol(symbol_config)
        new_strategy = StrategyFactory.create_composed(
            symbol=symbol,
            config=symbol_config.strategy_params,
            module_config=module_config,
            intervals=intervals,
            min_rr_ratio=min_rr_ratio,
        )

        # 4. 교체
        self._strategies[symbol] = new_strategy
        new_name = module_config.entry_determiner.name

        # 5. 감사 로그
        self._audit_logger.log_event(
            "STRATEGY_HOT_RELOAD",
            operation="rebuild_strategy",
            symbol=symbol,
            old_strategy=old_name,
            new_strategy=new_name,
            positions_closed=closed_count,
        )

        logger.info("[%s] Strategy rebuilt: %s → %s (closed %d positions)",
                     symbol, old_name, new_name, closed_count)

        return ConfigReloadCompleteEvent(
            symbol=symbol,
            old_strategy_name=old_name,
            new_strategy_name=new_name,
            positions_closed=closed_count,
        )

    def _update_params(self, event: ConfigUpdateEvent) -> None:
        """파라미터만 변경 (전략 인스턴스 유지)"""
        strategy = self._strategies.get(event.symbol)
        if strategy:
            strategy.config.update(event.params)
            logger.info("[%s] Strategy params updated: %s", event.symbol, list(event.params.keys()))

    async def _close_positions(self, symbol: str) -> int:
        """심볼의 열린 포지션 정리. 반환: 정리된 포지션 수."""
        positions = self._position_closer.get_open_positions(symbol)
        count = 0
        for pos in positions:
            await self._position_closer.close_position(pos, reason="strategy_hot_reload")
            count += 1
        return count
```

### 2.7. UIConfigHook — UI ↔ Config 연동

**파일**: `src/config/ui_config_hook.py`

```python
"""
UI ↔ Config 연동 Hook.

UI에서 모듈 구성/파라미터 조회 및 변경 요청을 처리.
getDynamicParamsFromUI() / apply_config_update() 두 가지 메인 API 제공.

설계 원칙:
- Cold Path: Pydantic 검증은 UI 입력 시에만 (Hot Path 침범 금지)
- 이벤트 기반: 변경 사항은 ConfigUpdateEvent로 전파
- YAML 동기화: 변경 시 YAML 파일에도 즉시 반영
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.config.symbol_config import TradingConfigHierarchical
from src.events.config_events import ConfigUpdateEvent
from src.strategies.module_registry import ModuleCategory, ModuleRegistry


@dataclass(frozen=True)
class UIConfigUpdate:
    """UI에서 전달되는 설정 변경 요청"""
    symbol: str
    module_category: str
    module_type: Optional[str] = None   # None이면 파라미터만 변경
    params: Optional[Dict[str, Any]] = None


class UIConfigHook:
    """UI ↔ Config 연동 Hook"""

    def __init__(
        self,
        hierarchical_config: TradingConfigHierarchical,
        registry: Optional[ModuleRegistry] = None,
        config_event_callback=None,      # async callable(ConfigUpdateEvent)
        yaml_writer=None,                 # callable(config) — YAML 파일 동기화
    ):
        self._config = hierarchical_config
        self._registry = registry or ModuleRegistry.get_instance()
        self._on_config_event = config_event_callback
        self._yaml_writer = yaml_writer

    def get_dynamic_params_from_ui(self, symbol: str) -> Dict[str, Any]:
        """
        심볼의 현재 모듈 구성 + 파라미터 + 스키마를 UI용 dict로 반환.

        Returns:
            {
                "symbol": "BTCUSDT",
                "entry": {
                    "type": "ict_entry",
                    "params": {"active_profile": "aggressive", ...},
                    "schema": {JSON Schema},
                    "available_modules": [{"name": ..., "description": ...}, ...]
                },
                "stop_loss": { ... },
                "take_profit": { ... },
                "exit": { ... }
            }
        """
        symbol_config = self._config.get_symbol_config(symbol)
        modules_spec = getattr(symbol_config, 'modules', {})
        result = {"symbol": symbol}

        for category in ModuleCategory.ALL:
            mod_spec = modules_spec.get(category, {})
            mod_type = mod_spec.get('type', '')
            mod_params = mod_spec.get('params', {})

            schema = self._registry.get_param_schema(category, mod_type)
            available = self._registry.get_available_modules(category)

            result[category] = {
                "type": mod_type,
                "params": mod_params,
                "schema": schema.model_json_schema() if schema else None,
                "available_modules": [
                    {"name": m.name, "description": m.description}
                    for m in available
                ],
            }

        return result

    def get_all_symbols_config(self) -> List[Dict[str, Any]]:
        """모든 활성 심볼의 현재 설정 반환"""
        return [
            self.get_dynamic_params_from_ui(symbol)
            for symbol in self._config.get_enabled_symbols()
        ]

    async def apply_config_update(self, update: UIConfigUpdate) -> ConfigUpdateEvent:
        """
        UI에서 받은 설정 변경을 검증 후 적용.

        Flow:
        1. Pydantic 스키마로 파라미터 검증 (Cold Path)
        2. TradingConfigHierarchical 인메모리 업데이트
        3. YAML 파일 동기화 (선택적)
        4. ConfigUpdateEvent 발행 → StrategyHotReloader가 수신

        Returns:
            발행된 ConfigUpdateEvent
        """
        # 현재 모듈 타입 (변경 안 되면 기존 값)
        symbol_config = self._config.get_symbol_config(update.symbol)
        modules_spec = getattr(symbol_config, 'modules', {})
        current_type = modules_spec.get(update.module_category, {}).get('type', '')

        effective_type = update.module_type or current_type
        requires_rebuild = (update.module_type is not None and update.module_type != current_type)

        # 1. Pydantic 검증
        validated_params = {}
        if update.params:
            schema = self._registry.get_param_schema(update.module_category, effective_type)
            if schema:
                validated = schema(**(update.params))
                validated_params = validated.model_dump()
            else:
                validated_params = update.params

        # 2. 인메모리 업데이트
        if update.module_category not in modules_spec:
            modules_spec[update.module_category] = {}
        if update.module_type:
            modules_spec[update.module_category]['type'] = update.module_type
        if validated_params:
            modules_spec[update.module_category]['params'] = validated_params

        # 3. YAML 동기화
        if self._yaml_writer:
            self._yaml_writer(self._config)

        # 4. 이벤트 발행
        event = ConfigUpdateEvent(
            symbol=update.symbol,
            category=update.module_category,
            module_type=update.module_type,
            params=validated_params,
            requires_strategy_rebuild=requires_rebuild,
        )

        if self._on_config_event:
            await self._on_config_event(event)

        return event
```

---

## 3. 시퀀스 다이어그램

### 3.1. 시스템 시작 — 심볼별 전략 조립

```
TradingEngine                ConfigManager              DynamicAssembler            ModuleRegistry
     │                            │                           │                          │
     │  initialize_components()   │                           │                          │
     │──────────────────────────→│                           │                          │
     │                            │  load_hierarchical()     │                          │
     │                            │──────(YAML 로드)         │                          │
     │                            │                           │                          │
     │  hierarchical_config       │                           │                          │
     │←──────────────────────────│                           │                          │
     │                            │                           │                          │
     │  for symbol in enabled_symbols:                       │                          │
     │  │                         │                           │                          │
     │  │  symbol_config = hierarchical_config.get_symbol_config(symbol)                │
     │  │                         │                           │                          │
     │  │  assemble_for_symbol(symbol_config)                │                          │
     │  │────────────────────────────────────────────────→│                          │
     │  │                         │                           │  create('entry', ...)   │
     │  │                         │                           │────────────────────────→│
     │  │                         │                           │  ← EntryDeterminer      │
     │  │                         │                           │  create('stop_loss',...) │
     │  │                         │                           │────────────────────────→│
     │  │                         │                           │  ← StopLossDeterminer   │
     │  │                         │                           │  create('take_profit'..) │
     │  │                         │                           │────────────────────────→│
     │  │                         │                           │  ← TakeProfitDeterminer │
     │  │                         │                           │  create('exit', ...)    │
     │  │                         │                           │────────────────────────→│
     │  │                         │                           │  ← ExitDeterminer       │
     │  │                         │                           │                          │
     │  │  ← (StrategyModuleConfig, intervals, min_rr)      │                          │
     │  │←───────────────────────────────────────────────│                          │
     │  │                         │                           │                          │
     │  │  StrategyFactory.create_composed(symbol, ...)      │                          │
     │  │  strategies[symbol] = ComposableStrategy           │                          │
     │  │                         │                           │                          │
     │  end for                   │                           │                          │
```

### 3.2. Hot Reload — UI에서 전략 변경

```
UI                  UIConfigHook           StrategyHotReloader      PositionCloser    DynamicAssembler
│                        │                        │                      │                  │
│  apply_config_update() │                        │                      │                  │
│  (symbol=BTC,          │                        │                      │                  │
│   entry→sma_entry)     │                        │                      │                  │
│──────────────────────→│                        │                      │                  │
│                        │  Pydantic 검증         │                      │                  │
│                        │  인메모리 업데이트       │                      │                  │
│                        │  YAML 동기화           │                      │                  │
│                        │                        │                      │                  │
│                        │  ConfigUpdateEvent     │                      │                  │
│                        │  (requires_rebuild=T)  │                      │                  │
│                        │──────────────────────→│                      │                  │
│                        │                        │  Lock(BTC) 획득      │                  │
│                        │                        │                      │                  │
│                        │                        │  close_positions(BTC)│                  │
│                        │                        │─────────────────────→│                  │
│                        │                        │  ← positions_closed  │                  │
│                        │                        │                      │                  │
│                        │                        │  assemble_for_symbol(BTC)               │
│                        │                        │──────────────────────────────────────→│
│                        │                        │  ← new StrategyModuleConfig            │
│                        │                        │←─────────────────────────────────────│
│                        │                        │                      │                  │
│                        │                        │  strategies[BTC] = new ComposableStrategy
│                        │                        │  Lock 해제            │                  │
│                        │                        │                      │                  │
│                        │  ← ConfigReloadComplete│                      │                  │
│                        │←──────────────────────│                      │                  │
│  ← 교체 완료 응답       │                        │                      │                  │
│←──────────────────────│                        │                      │                  │
```

---

## 4. YAML 스키마 상세

### 4.1. 확장된 trading_config.yaml 전체 구조

```yaml
# configs/trading_config.yaml
# Canonical Source — INI 사용하지 않음

trading:
  defaults:
    strategy: ict_strategy            # 레거시 호환 (modules 없을 때 폴백)
    leverage: 1
    max_risk_per_trade: 0.01
    margin_type: ISOLATED
    backfill_limit: 200
    intervals: ["5m", "1h", "4h"]

    # 기본 모듈 구성 (심볼별 오버라이드 가능)
    modules:
      entry:
        type: ict_entry
        params:
          active_profile: balanced
          use_killzones: true
      stop_loss:
        type: zone_based_sl
        params:
          min_sl_percent: 0.5
          max_sl_percent: 2.0
      take_profit:
        type: displacement_tp
        params:
          risk_reward_ratio: 2.0
      exit:
        type: ict_exit
        params:
          trailing_distance: 0.3

  symbols:
    BTCUSDT:
      enabled: true
      leverage: 2
      modules:
        entry:
          type: ict_entry
          params:
            active_profile: aggressive
            htf_interval: "4h"
        stop_loss:
          type: zone_based_sl
          params:
            min_sl_percent: 0.3
            max_sl_percent: 1.5
        take_profit:
          type: displacement_tp
          params:
            risk_reward_ratio: 2.5
        exit:
          type: ict_exit
          params:
            trailing_distance: 0.2

    ETHUSDT:
      enabled: true
      leverage: 3
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

### 4.2. modules 상속 규칙

```
우선순위: symbol.modules > defaults.modules > _DEFAULT_MODULES (코드 하드코딩)

머지 전략: 카테고리 단위 교체 (부분 머지 아님)
  - symbol에 entry만 지정 → entry는 symbol 것, 나머지 3개는 defaults 것
  - symbol에 entry.params만 지정 → entry.type도 함께 명시 필수
```

---

## 5. 모듈 호환성 매트릭스

| Entry \ SL | zone_based_sl | percentage_sl |
|------------|---------------|---------------|
| **ict_entry** | **권장** (FVG/OB 존 활용) | 호환 (폴백) |
| **sma_entry** | 호환 (존 없으면 폴백) | **권장** |
| **always_signal** | 호환 | **권장** |

| Entry \ TP | displacement_tp | rr_take_profit |
|------------|-----------------|----------------|
| **ict_entry** | **권장** (displacement 활용) | 호환 |
| **sma_entry** | 호환 (displacement 없으면 RR 폴백) | **권장** |
| **always_signal** | 호환 | **권장** |

| Entry \ Exit | ict_exit | null_exit |
|-------------|----------|-----------|
| **ict_entry** | **권장** (MTF/HTF 공유) | 호환 (TP/SL만 의존) |
| **sma_entry** | 호환 (기능 과잉) | **권장** |
| **always_signal** | 호환 | **권장** |

**핵심 규칙**: `price_extras`를 통한 데이터 전달이 핵심.
- `ict_entry`가 `price_extras`에 `fvg_zone`, `ob_zone`, `displacement_size` 제공
- `zone_based_sl`은 `extras["fvg_zone"]` 읽음 → 없으면 `percentage_sl`로 폴백
- `displacement_tp`는 `extras["displacement_size"]` 읽음 → 없으면 RR 폴백
- 따라서 **모든 조합이 기술적으로 호환** — 차이는 최적성(권장 vs 폴백)

---

## 6. ConfigManager 변경 상세

### 6.1. 제거할 코드 (INI 관련)

```python
# 제거 대상 메서드/로직:
- _load_trading_config()         # INI [trading] 섹션 파싱
- _load_strategy_config()        # INI [ict_strategy] 등 파싱
- TradingConfig dataclass        # 평면적 구조 → TradingConfigHierarchical로 대체
- INI fallback 로직              # YAML 없을 때 INI 사용하는 분기
```

### 6.2. 추가할 코드

```python
class ConfigManager:
    def get_symbol_config(self, symbol: str) -> SymbolConfig:
        """특정 심볼의 설정 반환 (TradingConfigHierarchical 위임)"""
        return self.hierarchical_config.get_symbol_config(symbol)

    def update_symbol_module(
        self, symbol: str, category: str, module_type: Optional[str], params: dict
    ) -> None:
        """심볼의 모듈 설정 업데이트 (인메모리 + YAML 동기화)"""
        symbol_config = self.get_symbol_config(symbol)
        modules = getattr(symbol_config, 'modules', {})
        if category not in modules:
            modules[category] = {}
        if module_type:
            modules[category]['type'] = module_type
        modules[category]['params'] = params
        self._save_yaml()

    def _save_yaml(self) -> None:
        """현재 hierarchical_config를 YAML 파일에 저장"""
        import yaml
        with open(self._yaml_path, 'w') as f:
            yaml.dump(self.hierarchical_config.to_dict(), f, default_flow_style=False)
```

### 6.3. TradingEngine.initialize_components() 변경

```python
# 현재 (AS-IS):
for symbol in trading_config.symbols:
    module_config, intervals, min_rr = build_module_config(
        strategy_name=trading_config.strategy,      # 전역 1개
        strategy_config=strategy_config,              # 전역 1개
        exit_config=trading_config.exit_config,
    )

# 변경 (TO-BE):
assembler = DynamicAssembler()
hierarchical_config = config_manager.hierarchical_config

for symbol in hierarchical_config.get_enabled_symbols():
    symbol_config = hierarchical_config.get_symbol_config(symbol)
    module_config, intervals, min_rr = assembler.assemble_for_symbol(symbol_config)
    self.strategies[symbol] = StrategyFactory.create_composed(
        symbol=symbol,
        config=symbol_config.strategy_params,
        module_config=module_config,
        intervals=intervals,
        min_rr_ratio=min_rr,
    )

# Hot Reloader 등록
self._hot_reloader = StrategyHotReloader(
    strategies=self.strategies,
    assembler=assembler,
    hierarchical_config=hierarchical_config,
    position_closer=self.position_cache_manager,
    audit_logger=self.audit_logger,
)
```

---

## 7. 성능 분석

### 7.1. Hot Path 영향 없음 확인

| 컴포넌트 | Hot Path? | Pydantic 사용? | 근거 |
|----------|-----------|---------------|------|
| `ModuleRegistry.create_module()` | No (시작/Hot Reload 시만) | Yes | Cold Path: 전략 생성 시 1회 |
| `UIConfigHook.apply_config_update()` | No (UI 입력 시만) | Yes | Cold Path: 사용자 액션 |
| `UIConfigHook.get_dynamic_params_from_ui()` | No (UI 조회 시만) | No (스키마 반환만) | Cold Path |
| `ComposableStrategy.analyze()` | **Yes** | **No** | Hot Path 변경 없음 |
| `StrategyHotReloader.on_config_update()` | No (이벤트 시만) | No | 전략 교체는 드문 이벤트 |

### 7.2. 메모리 영향

| 항목 | 추가 메모리 | 비고 |
|------|------------|------|
| ModuleRegistry (싱글톤) | ~10KB | ModuleInfo × ~10개 모듈 |
| ParamSchema 클래스 | ~5KB per module | Pydantic model class objects |
| DynamicAssembler | ~1KB | 상태 없는 조립기 |
| StrategyHotReloader | ~2KB + Lock per symbol | asyncio.Lock은 경량 |
| **합계** | **< 1MB** | 목표 5MB 이내 충족 |

---

## 8. 테스트 전략

### 8.1. 단위 테스트

| 테스트 파일 | 검증 항목 |
|------------|----------|
| `test_module_registry.py` | register, get_available, create_module, validate_combination |
| `test_decorators.py` | @register_module 정상 등록, ParamSchema 누락 시 에러 |
| `test_dynamic_assembler.py` | 유효 조합, 기본값 폴백, 무효 모듈명 에러 |
| `test_param_schemas.py` | 각 모듈 ParamSchema 검증 (범위, 타입, 기본값) |

### 8.2. 통합 테스트

| 테스트 파일 | 검증 항목 |
|------------|----------|
| `test_ui_config_hook.py` | get_dynamic_params, apply_update → 이벤트 발행 |
| `test_strategy_hot_reloader.py` | 파라미터 변경, 전략 교체, 포지션 정리 확인 |
| `test_yaml_config_loading.py` | 신규 YAML 포맷 → 심볼별 독립 전략 부팅 |
| `test_end_to_end.py` | YAML → DynamicAssembler → ComposableStrategy → analyze() |

### 8.3. 회귀 테스트

- 기존 `test_composable_strategy.py` 모든 케이스 통과
- 기존 백테스트 결과와 수치 100% 일치 (동일 파라미터 기준)

---

## 9. 마이그레이션 계획

### 9.1. INI → YAML 마이그레이션 스크립트

```python
# scripts/migrate_ini_to_yaml.py
# 기존 trading_config.ini를 신규 YAML 포맷으로 변환
# 사용법: python scripts/migrate_ini_to_yaml.py configs/trading_config.ini configs/trading_config.yaml

def migrate(ini_path: str, yaml_path: str):
    """
    1. INI 파일 파싱
    2. TradingConfigHierarchical.from_ini_sections() 사용
    3. 각 심볼의 strategy_params를 modules 블록으로 변환
       - strategy='ict_strategy' → modules.entry.type='ict_entry' + 관련 모듈
       - strategy='mock_sma' → modules.entry.type='sma_entry' + 관련 모듈
    4. YAML로 출력
    """
```

### 9.2. 하위 호환성 보장

| 시나리오 | 동작 |
|---------|------|
| YAML에 `modules` 블록 있음 | DynamicAssembler로 동적 조립 |
| YAML에 `modules` 없고 `strategy` + `strategy_params` 있음 | 레거시 빌더(`build_module_config`)로 폴백 |
| YAML 파일 자체가 없음 | **에러** (INI 폴백 제거) |

---

## 10. 구현 순서 체크리스트

- [ ] Phase 1.1: `src/strategies/module_registry.py` — ModuleRegistry 싱글톤
- [ ] Phase 1.2: `src/strategies/decorators.py` — @register_module
- [ ] Phase 1.3: 기존 모듈에 ParamSchema + from_validated_params 추가
- [ ] Phase 1.4: 기존 모듈에 @register_module 데코레이터 적용
- [ ] Phase 1.5: 단위 테스트 — registry, decorator, schema
- [ ] Phase 2.1: `src/config/symbol_config.py` — modules 필드 추가 + YAML 파싱
- [ ] Phase 2.2: `src/strategies/dynamic_assembler.py` — DynamicAssembler
- [ ] Phase 2.3: `src/events/config_events.py` — ConfigUpdateEvent
- [ ] Phase 2.4: `src/core/strategy_hot_reloader.py` — StrategyHotReloader
- [ ] Phase 2.5: `src/config/ui_config_hook.py` — UIConfigHook
- [ ] Phase 2.6: `src/utils/config_manager.py` — INI 제거 + YAML 전용화
- [ ] Phase 2.7: `src/core/trading_engine.py` — DynamicAssembler 와이어링
- [ ] Phase 3.1: 통합 테스트 — Hot Reload E2E
- [ ] Phase 3.2: 회귀 테스트 — 기존 백테스트 결과 일치
- [ ] Phase 3.3: `scripts/migrate_ini_to_yaml.py` — 마이그레이션 스크립트
