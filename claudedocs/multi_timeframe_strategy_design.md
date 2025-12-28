# Multi-Timeframe (MTF) 전략 설계

## 📋 Overview

**목적**: ICT 전략에 멀티 인터벌(Multi-Timeframe) 분석을 적용하여 트레이딩 정확도 향상

**현재 상태**: BaseStrategy는 단일 인터벌 버퍼만 지원
**목표**: HTF(High), MTF(Medium), LTF(Low) 타임프레임 동시 분석

---

## 🎯 ICT에서의 MTF 활용

### Timeframe Hierarchy

```
HTF (Higher Timeframe) - 트렌드 방향 결정
├─ 4h, 1d, 1w
├─ 용도: 전체 시장 구조 파악
└─ 판단: Bullish/Bearish/Sideways

MTF (Medium Timeframe) - 구조 분석
├─ 15m, 1h
├─ 용도: FVG, Order Block, Liquidity 탐지
└─ 판단: Entry zone 식별

LTF (Lower Timeframe) - 진입 타이밍
├─ 1m, 5m
├─ 용도: Displacement, Entry confirmation
└─ 판단: 정확한 진입 가격
```

### ICT MTF Trading Flow

```
1. HTF (4h) → Trend: Bullish
   - Market structure shows HH, HL
   - BOS confirmed

2. MTF (1h) → Setup: Bullish FVG @ 50,000
   - Fair Value Gap identified
   - Discount zone (< 50% of range)

3. LTF (5m) → Entry: Displacement @ 50,200
   - Price enters FVG zone
   - Displacement candle confirms
   - Entry: 50,200 | SL: 49,800 | TP: 51,400
```

---

## 🏗️ 설계 옵션 비교

### Option 1: Multi-Buffer BaseStrategy (✅ 권장)

**구조**:
```python
class MultiTimeframeStrategy(BaseStrategy):
    def __init__(self, symbol: str, intervals: List[str], config: dict):
        self.symbol = symbol
        self.intervals = intervals
        self.buffers = {
            '1m': [],
            '5m': [],
            '1h': [],
            '4h': []
        }
```

**장점**:
- ✅ 단일 전략 인스턴스로 모든 인터벌 관리
- ✅ 인터벌 간 상호 참조 용이
- ✅ 메모리 효율적
- ✅ 코드 관리 간편

**단점**:
- BaseStrategy 인터페이스 변경 필요
- 기존 단일 인터벌 전략 호환성 고려

### Option 2: Separate Strategy Instances

**구조**:
```python
# TradingEngine
strategies = {
    '1m': ICTStrategy('BTCUSDT', '1m', config),
    '5m': ICTStrategy('BTCUSDT', '5m', config),
    '1h': ICTStrategy('BTCUSDT', '1h', config)
}
```

**장점**:
- BaseStrategy 인터페이스 변경 불필요
- 각 인터벌 독립 실행

**단점**:
- ❌ 인터벌 간 데이터 공유 복잡
- ❌ 메모리 낭비 (중복 객체)
- ❌ 신호 중복 가능성
- ❌ 관리 복잡도 증가

### Option 3: MTF Wrapper Class

**구조**:
```python
class MTFWrapper:
    def __init__(self, strategies: Dict[str, BaseStrategy]):
        self.strategies = strategies

    async def analyze(self, candles: Dict[str, Candle]):
        # Aggregate analysis from all timeframes
```

**장점**:
- BaseStrategy 재사용
- 유연한 조합

**단점**:
- ❌ 추가 레이어 복잡도
- ❌ analyze() 시그니처 변경 필요
- ❌ TradingEngine 통합 복잡

---

## ✅ 권장 설계: Multi-Buffer BaseStrategy

### 1. MultiTimeframeStrategy Base Class

```python
# src/strategies/multi_timeframe.py
"""
Multi-Timeframe strategy base class for ICT strategies.

Extends BaseStrategy to support multiple interval buffers simultaneously,
enabling HTF trend analysis, MTF structure detection, and LTF entry timing.
"""

from abc import abstractmethod
from typing import Dict, List, Optional
from src.models.candle import Candle
from src.models.signal import Signal
from src.strategies.base import BaseStrategy


class MultiTimeframeStrategy(BaseStrategy):
    """
    Base class for multi-timeframe trading strategies.

    Manages separate candle buffers for each timeframe, allowing strategies
    to analyze HTF trends, MTF structures, and LTF entries simultaneously.

    Example:
        ```python
        class ICTStrategy(MultiTimeframeStrategy):
            def __init__(self, symbol: str, config: dict):
                intervals = ['1m', '5m', '1h', '4h']
                super().__init__(symbol, intervals, config)

            async def analyze_mtf(
                self,
                candle: Candle,
                buffers: Dict[str, List[Candle]]
            ) -> Optional[Signal]:
                # HTF: Trend direction
                htf_trend = self.analyze_htf(buffers['4h'])

                # MTF: Structure and zones
                mtf_zones = self.analyze_mtf_structure(buffers['1h'])

                # LTF: Entry timing
                ltf_entry = self.analyze_ltf_entry(buffers['5m'])

                # Combine analysis
                if htf_trend == 'bullish' and mtf_zones and ltf_entry:
                    return self.create_signal(...)
        ```

    Attributes:
        symbol: Trading pair (e.g., 'BTCUSDT')
        intervals: List of timeframes to analyze (e.g., ['1m', '5m', '1h'])
        buffers: Dict mapping interval → candle buffer
        buffer_size: Max candles per buffer
    """

    def __init__(
        self,
        symbol: str,
        intervals: List[str],
        config: dict
    ) -> None:
        """
        Initialize multi-timeframe strategy.

        Args:
            symbol: Trading pair
            intervals: List of intervals to track (e.g., ['1m', '5m', '1h', '4h'])
            config: Strategy configuration with buffer_size, etc.

        Notes:
            - Each interval gets its own buffer
            - Buffer size applies to ALL intervals
            - Intervals should be ordered low → high for clarity
        """
        # Don't call super().__init__() to avoid single buffer creation
        self.symbol = symbol
        self.intervals = sorted(intervals)  # Ensure consistent ordering
        self.config = config
        self.buffer_size = config.get('buffer_size', 100)

        # Create separate buffer for each interval
        self.buffers: Dict[str, List[Candle]] = {
            interval: [] for interval in intervals
        }

        self._initialized: Dict[str, bool] = {
            interval: False for interval in intervals
        }

        import logging
        self.logger = logging.getLogger(self.__class__.__name__)

        self.logger.info(
            f"[{self.__class__.__name__}] Initialized MTF strategy for {symbol} "
            f"with {len(intervals)} intervals: {intervals}"
        )

    def initialize_with_historical_data(
        self,
        interval: str,
        candles: List[Candle]
    ) -> None:
        """
        Initialize buffer for specific interval with historical data.

        Called once per interval during startup after backfilling.

        Args:
            interval: Timeframe (e.g., '1m', '5m')
            candles: Historical candles for this interval

        Example:
            >>> # After backfill, called for each interval
            >>> strategy.initialize_with_historical_data('1m', candles_1m)
            >>> strategy.initialize_with_historical_data('5m', candles_5m)
            >>> strategy.initialize_with_historical_data('1h', candles_1h)
        """
        if interval not in self.buffers:
            self.logger.warning(
                f"[{self.__class__.__name__}] Interval {interval} not configured. "
                f"Expected: {self.intervals}"
            )
            return

        if not candles:
            self.logger.warning(
                f"[{self.__class__.__name__}] No historical candles for {interval}"
            )
            self._initialized[interval] = True
            return

        self.logger.info(
            f"[{self.__class__.__name__}] Initializing {interval} buffer "
            f"with {len(candles)} historical candles"
        )

        # Clear existing buffer
        self.buffers[interval].clear()

        # Add all candles
        for candle in candles:
            self.buffers[interval].append(candle)

        # Trim to buffer_size
        if len(self.buffers[interval]) > self.buffer_size:
            excess = len(self.buffers[interval]) - self.buffer_size
            self.buffers[interval] = self.buffers[interval][excess:]
            self.logger.debug(
                f"[{self.__class__.__name__}] Trimmed {excess} oldest candles "
                f"from {interval} buffer"
            )

        self._initialized[interval] = True

        self.logger.info(
            f"[{self.__class__.__name__}] {interval} initialization complete: "
            f"{len(self.buffers[interval])} candles"
        )

    def update_buffer(self, interval: str, candle: Candle) -> None:
        """
        Update buffer for specific interval with new candle.

        Args:
            interval: Timeframe (e.g., '1m')
            candle: New candle to add

        FIFO Behavior:
            - Append candle to end
            - Remove oldest if buffer exceeds buffer_size
        """
        if interval not in self.buffers:
            self.logger.warning(
                f"[{self.__class__.__name__}] Cannot update buffer for "
                f"unconfigured interval: {interval}"
            )
            return

        self.buffers[interval].append(candle)

        if len(self.buffers[interval]) > self.buffer_size:
            self.buffers[interval].pop(0)  # Remove oldest

        self.logger.debug(
            f"[{self.__class__.__name__}] Updated {interval} buffer: "
            f"{len(self.buffers[interval])} candles"
        )

    def is_ready(self) -> bool:
        """
        Check if ALL interval buffers are initialized.

        Returns:
            True if all intervals have historical data loaded
        """
        return all(self._initialized.values())

    def get_buffer(self, interval: str) -> List[Candle]:
        """
        Get candle buffer for specific interval.

        Args:
            interval: Timeframe (e.g., '5m')

        Returns:
            List of candles for this interval (empty if not initialized)
        """
        return self.buffers.get(interval, [])

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Single-candle analyze() for backward compatibility.

        Routes to analyze_mtf() with current buffer state.

        Args:
            candle: New candle (any interval)

        Returns:
            Trading signal if conditions met

        Notes:
            - Updates buffer for candle's interval
            - Only analyzes on LTF candle close (e.g., 1m, 5m)
            - Subclasses should override analyze_mtf() instead
        """
        if not candle.is_closed:
            return None

        # Update buffer for this interval
        self.update_buffer(candle.interval, candle)

        # Only analyze on LTF (lowest timeframe) to avoid duplicate signals
        ltf = self.intervals[0]  # Lowest interval
        if candle.interval != ltf:
            return None

        # Check if all intervals ready
        if not self.is_ready():
            self.logger.debug(
                f"[{self.__class__.__name__}] Waiting for all intervals to initialize"
            )
            return None

        # Delegate to multi-timeframe analysis
        return await self.analyze_mtf(candle, self.buffers)

    @abstractmethod
    async def analyze_mtf(
        self,
        candle: Candle,
        buffers: Dict[str, List[Candle]]
    ) -> Optional[Signal]:
        """
        Multi-timeframe analysis method.

        Subclasses MUST implement this instead of analyze().

        Args:
            candle: Latest candle (from LTF)
            buffers: Dict mapping interval → candle list
                     Example: {'1m': [...], '5m': [...], '1h': [...]}

        Returns:
            Signal if all MTF conditions met, None otherwise

        Example Implementation:
            ```python
            async def analyze_mtf(self, candle, buffers):
                # HTF: Trend
                htf_candles = buffers['4h']
                trend = self.get_trend(htf_candles)
                if trend != 'bullish':
                    return None

                # MTF: Structure
                mtf_candles = buffers['1h']
                fvg = self.find_fvg(mtf_candles)
                if not fvg:
                    return None

                # LTF: Entry
                ltf_candles = buffers['5m']
                if not self.check_displacement(ltf_candles):
                    return None

                # Generate signal
                return Signal(...)
            ```
        """
        pass

    # Optional: Backward compatibility with BaseStrategy interface
    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """Default TP calculation - subclasses should override."""
        rr_ratio = self.config.get('risk_reward_ratio', 2.0)
        sl_percent = self.config.get('stop_loss_percent', 0.02)

        if side == 'LONG':
            return entry_price * (1 + rr_ratio * sl_percent)
        else:
            return entry_price * (1 - rr_ratio * sl_percent)

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """Default SL calculation - subclasses should override."""
        sl_percent = self.config.get('stop_loss_percent', 0.02)

        if side == 'LONG':
            return entry_price * (1 - sl_percent)
        else:
            return entry_price * (1 + sl_percent)
```

---

## 🔧 TradingEngine 통합

### 수정 필요 사항

```python
# src/core/trading_engine.py

class TradingEngine:
    def initialize_strategy_with_historical_data(
        self,
        historical_candles: Dict[str, List[Candle]]
    ) -> None:
        """
        Initialize strategy with historical data.

        Args:
            historical_candles: Dict mapping 'SYMBOL_INTERVAL' → candle list
                               Example: {
                                   'BTCUSDT_1m': [...],
                                   'BTCUSDT_5m': [...],
                                   'BTCUSDT_1h': [...]
                               }
        """
        if self.strategy is None:
            self.logger.warning("No strategy set, skipping historical data initialization")
            return

        # Check if strategy is multi-timeframe
        if isinstance(self.strategy, MultiTimeframeStrategy):
            # MTF strategy: initialize each interval separately
            for key, candles in historical_candles.items():
                # Parse key: 'BTCUSDT_1m' → symbol='BTCUSDT', interval='1m'
                parts = key.rsplit('_', 1)
                if len(parts) != 2:
                    continue

                symbol, interval = parts
                if symbol == self.strategy.symbol:
                    self.strategy.initialize_with_historical_data(interval, candles)

        else:
            # Single-interval strategy (backward compatibility)
            # Use first matching interval for this symbol
            for key, candles in historical_candles.items():
                if key.startswith(self.strategy.symbol):
                    self.strategy.initialize_with_historical_data(candles)
                    break
```

---

## 📝 ICT MTF Strategy 예제

```python
# src/strategies/ict_mtf_strategy.py
"""
ICT Multi-Timeframe Strategy Implementation.

Combines HTF trend, MTF structure, and LTF entry analysis.
"""

from typing import Dict, List, Optional
from datetime import datetime, timezone

from src.strategies.multi_timeframe import MultiTimeframeStrategy
from src.models.candle import Candle
from src.models.signal import Signal, SignalType


class ICTMultiTimeframeStrategy(MultiTimeframeStrategy):
    """
    ICT trading strategy with multi-timeframe analysis.

    Timeframe Roles:
        - HTF (4h): Market structure, trend direction
        - MTF (1h): FVG, Order Blocks, liquidity zones
        - LTF (5m): Displacement, entry confirmation

    Configuration:
        ```ini
        [trading]
        symbol = BTCUSDT
        intervals = 5m,1h,4h
        strategy = ict_mtf

        [ict_mtf]
        htf_interval = 4h
        mtf_interval = 1h
        ltf_interval = 5m
        buffer_size = 200
        ```
    """

    def __init__(self, symbol: str, config: dict):
        # Define intervals for MTF analysis
        htf = config.get('htf_interval', '4h')
        mtf = config.get('mtf_interval', '1h')
        ltf = config.get('ltf_interval', '5m')

        intervals = [ltf, mtf, htf]  # Low to High

        super().__init__(symbol, intervals, config)

        # Store interval references
        self.htf_interval = htf
        self.mtf_interval = mtf
        self.ltf_interval = ltf

        # ICT configuration
        self.swing_lookback = config.get('swing_lookback', 20)
        self.risk_reward = config.get('risk_reward_ratio', 2.0)

    async def analyze_mtf(
        self,
        candle: Candle,
        buffers: Dict[str, List[Candle]]
    ) -> Optional[Signal]:
        """
        Multi-timeframe ICT analysis.

        Step 1: HTF - Determine trend direction
        Step 2: MTF - Find FVG/OB zones
        Step 3: LTF - Confirm displacement entry
        """
        # Get buffers
        htf_candles = buffers[self.htf_interval]
        mtf_candles = buffers[self.mtf_interval]
        ltf_candles = buffers[self.ltf_interval]

        # Minimum data check
        if len(htf_candles) < self.swing_lookback:
            return None
        if len(mtf_candles) < 50:
            return None
        if len(ltf_candles) < 10:
            return None

        # === STEP 1: HTF Trend Analysis ===
        htf_trend = self._analyze_htf_trend(htf_candles)
        if htf_trend == 'sideways':
            return None

        self.logger.debug(f"HTF ({self.htf_interval}) Trend: {htf_trend}")

        # === STEP 2: MTF Structure Analysis ===
        mtf_zone = self._find_mitigation_zone(mtf_candles, htf_trend)
        if not mtf_zone:
            return None

        self.logger.debug(
            f"MTF ({self.mtf_interval}) Zone: {mtf_zone['type']} "
            f"@ {mtf_zone['level']:.2f}"
        )

        # === STEP 3: LTF Entry Confirmation ===
        current_price = candle.close

        # Check if price in mitigation zone
        if not mtf_zone['low'] <= current_price <= mtf_zone['high']:
            return None

        # Check displacement
        displacement = self._check_displacement(ltf_candles[-3:], htf_trend)
        if not displacement:
            return None

        self.logger.info(
            f"✅ MTF Signal: {htf_trend.upper()} entry confirmed "
            f"@ {current_price:.2f}"
        )

        # === STEP 4: Generate Signal ===
        if htf_trend == 'bullish':
            signal_type = SignalType.LONG_ENTRY
            entry_price = current_price
            stop_loss = mtf_zone['low'] * 0.998  # Below zone
            take_profit = entry_price + (entry_price - stop_loss) * self.risk_reward

        else:  # bearish
            signal_type = SignalType.SHORT_ENTRY
            entry_price = current_price
            stop_loss = mtf_zone['high'] * 1.002  # Above zone
            take_profit = entry_price - (stop_loss - entry_price) * self.risk_reward

        return Signal(
            signal_type=signal_type,
            symbol=self.symbol,
            entry_price=entry_price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            strategy_name="ICTMultiTimeframeStrategy",
            timestamp=datetime.now(timezone.utc),
            metadata={
                'htf_trend': htf_trend,
                'mtf_zone_type': mtf_zone['type'],
                'mtf_zone_level': mtf_zone['level'],
                'ltf_displacement': True,
                'timeframes': {
                    'htf': self.htf_interval,
                    'mtf': self.mtf_interval,
                    'ltf': self.ltf_interval
                }
            }
        )

    def _analyze_htf_trend(self, candles: List[Candle]) -> str:
        """
        Determine HTF trend via market structure.

        Returns:
            'bullish', 'bearish', or 'sideways'
        """
        # Simple implementation: compare recent highs/lows
        # TODO: Implement proper BOS/CHoCH detection
        if len(candles) < self.swing_lookback:
            return 'sideways'

        recent = candles[-self.swing_lookback:]
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]

        # Higher highs and higher lows
        if highs[-1] > max(highs[:-1]) and lows[-1] > min(lows[:len(lows)//2]):
            return 'bullish'

        # Lower highs and lower lows
        if highs[-1] < min(highs[:len(highs)//2]) and lows[-1] < min(lows[:-1]):
            return 'bearish'

        return 'sideways'

    def _find_mitigation_zone(
        self,
        candles: List[Candle],
        trend: str
    ) -> Optional[dict]:
        """
        Find FVG or Order Block in MTF.

        Returns:
            Dict with zone info or None
        """
        # Simple FVG detection (3-candle pattern)
        for i in range(len(candles) - 3, max(len(candles) - 50, 0), -1):
            c1, c2, c3 = candles[i], candles[i+1], candles[i+2]

            # Bullish FVG
            if trend == 'bullish' and c1.high < c3.low:
                return {
                    'type': 'bullish_fvg',
                    'low': c1.high,
                    'high': c3.low,
                    'level': (c1.high + c3.low) / 2
                }

            # Bearish FVG
            if trend == 'bearish' and c1.low > c3.high:
                return {
                    'type': 'bearish_fvg',
                    'low': c3.high,
                    'high': c1.low,
                    'level': (c1.low + c3.high) / 2
                }

        return None

    def _check_displacement(
        self,
        candles: List[Candle],
        trend: str
    ) -> bool:
        """
        Check for displacement candle on LTF.

        Displacement = large directional move (> 1.5x average range)
        """
        if len(candles) < 3:
            return False

        # Calculate average range
        avg_range = sum(c.high - c.low for c in candles[:-1]) / (len(candles) - 1)

        # Check last candle
        last = candles[-1]
        last_range = last.high - last.low

        # Displacement threshold: 1.5x average
        if last_range < avg_range * 1.5:
            return False

        # Check direction matches trend
        if trend == 'bullish':
            return last.close > last.open  # Bullish candle
        else:
            return last.close < last.open  # Bearish candle
```

---

## 📊 Configuration 예제

```ini
# configs/trading_config.ini
[trading]
symbol = BTCUSDT
intervals = 5m,1h,4h
strategy = ict_mtf
leverage = 1
max_risk_per_trade = 0.01
backfill_limit = 200

[ict_mtf]
# Timeframe assignments
htf_interval = 4h          # Trend analysis
mtf_interval = 1h          # Structure analysis
ltf_interval = 5m          # Entry timing

# Buffer settings
buffer_size = 200          # Applies to all intervals

# Market structure
swing_lookback = 20        # Bars for swing detection

# Risk management
risk_reward_ratio = 2.0
stop_loss_percent = 0.02
```

---

## 🧪 테스트 전략

### Unit Tests

```python
# tests/strategies/test_mtf_strategy.py

def test_mtf_buffer_initialization():
    """Test multi-buffer initialization"""
    strategy = MultiTimeframeStrategy('BTCUSDT', ['1m', '5m', '1h'], {})

    # Initialize each interval
    strategy.initialize_with_historical_data('1m', candles_1m)
    strategy.initialize_with_historical_data('5m', candles_5m)
    strategy.initialize_with_historical_data('1h', candles_1h)

    # Verify buffers
    assert len(strategy.get_buffer('1m')) == len(candles_1m)
    assert len(strategy.get_buffer('5m')) == len(candles_5m)
    assert strategy.is_ready() == True

def test_mtf_buffer_update():
    """Test buffer update for each interval"""
    strategy = MultiTimeframeStrategy('BTCUSDT', ['1m', '5m'], {})

    # Update different intervals
    strategy.update_buffer('1m', candle_1m)
    strategy.update_buffer('5m', candle_5m)

    assert strategy.get_buffer('1m')[-1] == candle_1m
    assert strategy.get_buffer('5m')[-1] == candle_5m

def test_ict_mtf_analysis():
    """Test ICT MTF signal generation"""
    strategy = ICTMultiTimeframeStrategy('BTCUSDT', config)

    # Setup buffers with test data
    strategy.initialize_with_historical_data('5m', ltf_candles)
    strategy.initialize_with_historical_data('1h', mtf_candles)
    strategy.initialize_with_historical_data('4h', htf_candles)

    # Analyze with bullish setup
    signal = await strategy.analyze(ltf_candle_closed)

    assert signal is not None
    assert signal.signal_type == SignalType.LONG_ENTRY
    assert 'htf_trend' in signal.metadata
```

---

## 📈 구현 우선순위

### Phase 1: 기반 구축 (1일)
- [x] MultiTimeframeStrategy base class 구현
- [ ] TradingEngine 통합 수정
- [ ] Unit tests 작성
- [ ] Documentation

### Phase 2: ICT MTF 구현 (1일)
- [ ] ICTMultiTimeframeStrategy 구현
- [ ] HTF trend analysis
- [ ] MTF structure detection (FVG)
- [ ] LTF displacement confirmation

### Phase 3: 테스트 & 최적화 (0.5일)
- [ ] Integration tests
- [ ] Backtesting
- [ ] Configuration tuning
- [ ] Performance validation

---

## 🎯 성공 기준

### MVP
- ✅ MultiTimeframeStrategy 정상 작동
- ✅ 3개 인터벌 동시 분석 가능
- ✅ HTF → MTF → LTF flow 구현
- ✅ Signal 생성 및 실행 성공

### Production
- ✅ Unit test coverage > 80%
- ✅ Backtesting 결과 양호
- ✅ Real-time 테스트 안정적
- ✅ Documentation 완성

---

## 📚 참고 자료

### ICT MTF 개념
- [ICT Mentorship: MTF Analysis](https://www.youtube.com/@TheInnerCircleTrader)
- Multi-timeframe confluence
- Top-down analysis methodology

### 코드베이스
- `src/strategies/base.py` - 현재 BaseStrategy
- `src/core/data_collector.py` - 인터벌별 버퍼 관리
- `src/core/trading_engine.py` - 전략 통합

---

**문서 작성일**: 2025-12-27
**Status**: Design Complete → Ready for Implementation
**Estimated Effort**: 2.5 days
