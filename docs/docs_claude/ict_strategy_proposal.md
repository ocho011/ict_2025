# ICT 전략 고도화 제안서

## 📋 Executive Summary

**현재 상태**: 시스템 파이프라인 완성 및 안정화 완료 ✅
**다음 단계**: 실전 ICT (Inner Circle Trader) 전략 구현

**기반 문서**:
- `claudedocs/journal/2025-12-26_diagnostic_report.md` - 시스템 안정성 확인
- `claudedocs/journal/2025-12-26_refactoring_log.md` - 전략 고도화 우선순위

**예상 작업 기간**: 2-3일 (중급 복잡도)

---

## 🎯 현재 상태 분석

### 완료된 인프라 (✅ 프로덕션 준비 완료)

#### 1. 데이터 수집 & 처리
- ✅ WebSocket 실시간 데이터 스트리밍 (Binance Futures)
- ✅ Historical candle backfilling (startup시 사전 로드)
- ✅ 멀티 인터벌 지원 (1m, 5m, 15m, 1h, 4h, 1d)
- ✅ Candle buffer 관리 (FIFO, configurable size)

#### 2. 거래 실행
- ✅ OrderExecutionManager (entry, TP, SL orders)
- ✅ Position management
- ✅ Account balance tracking
- ✅ Leverage configuration

#### 3. 리스크 관리
- ✅ RiskManager (position sizing, validation)
- ✅ TP/SL 검증
- ✅ Position size capping
- ✅ Risk-reward ratio enforcement

#### 4. 이벤트 & 로깅
- ✅ EventBus (data, signal, order queues)
- ✅ Comprehensive audit logging (JSON Lines)
- ✅ Standard logging (trading.log, trades.log)
- ✅ Graceful shutdown

#### 5. 전략 인터페이스
- ✅ BaseStrategy abstract class
- ✅ Signal generation interface
- ✅ TP/SL calculation interface
- ✅ Candle buffer access

### 현재 전략 (테스트용)

#### MockSMACrossoverStrategy
```python
# Fast/Slow SMA crossover (Golden Cross / Death Cross)
- Fast Period: 10
- Slow Period: 20
- Signal: Crossover detection
- Purpose: Testing only
```

**한계점**:
- 단순 테크니컬 지표 (ICT 개념 미포함)
- 시장 구조 분석 부재
- 스마트 머니 개념 미반영
- 실전 트레이딩에 부적합

---

## 🧠 ICT 전략 고도화 로드맵

### Phase 1: 기초 ICT 개념 구현 (1일)

#### 1.1 Market Structure 분석
**목적**: 시장의 구조적 트렌드 파악

**구현 항목**:
```python
class MarketStructure:
    """
    Higher High (HH), Higher Low (HL) 기반 상승 추세
    Lower High (LH), Lower Low (LL) 기반 하락 추세
    """
    - identify_swing_highs()
    - identify_swing_lows()
    - detect_bos()  # Break of Structure
    - detect_choch()  # Change of Character
```

**핵심 로직**:
- Swing points 탐지 (n-bar lookback)
- BOS: 이전 swing high/low 돌파
- CHoCH: 트렌드 전환 신호

#### 1.2 Fair Value Gap (FVG) 탐지
**목적**: 가격 불균형 영역(mispricing) 식별

**구현 항목**:
```python
class FairValueGap:
    """
    3-candle 패턴에서 gap 탐지
    Candle 1 high < Candle 3 low → Bullish FVG
    Candle 1 low > Candle 3 high → Bearish FVG
    """
    - detect_bullish_fvg()
    - detect_bearish_fvg()
    - is_fvg_filled()  # FVG retracement 확인
    - get_fvg_levels()  # Entry zone 계산
```

**핵심 로직**:
- 3-candle gap 패턴 스캔
- Gap zone 경계 계산 (high/low)
- Fill 여부 모니터링

#### 1.3 Order Block (OB) 식별
**목적**: 스마트 머니 진입 영역 파악

**구현 항목**:
```python
class OrderBlock:
    """
    Strong move 직전 마지막 opposite candle
    Bullish OB: Strong up move 전 마지막 bearish candle
    Bearish OB: Strong down move 전 마지막 bullish candle
    """
    - identify_bullish_ob()
    - identify_bearish_ob()
    - validate_ob_strength()  # Move 강도 검증
    - get_ob_zone()  # Mitigation zone
```

**핵심 로직**:
- Strong move 탐지 (% threshold)
- 직전 opposite candle 찾기
- OB zone: candle의 high-low 범위

---

### Phase 2: 고급 ICT 개념 통합 (1일)

#### 2.1 Liquidity Pools
**목적**: Stop hunt 영역 식별

**구현 항목**:
```python
class LiquidityAnalysis:
    """
    Equal Highs/Lows 탐지 → Stop loss clustering
    Premium/Discount zones 계산
    """
    - find_equal_highs()
    - find_equal_lows()
    - calculate_premium_discount()  # 50% 기준
    - detect_liquidity_sweep()  # Stop hunt 확인
```

**핵심 로직**:
- Equal highs/lows: ±0.1% tolerance
- Premium: > 50% of range
- Discount: < 50% of range
- Sweep: wick beyond equal level

#### 2.2 Smart Money Concepts (SMC)
**목적**: Institutional order flow 추적

**구현 항목**:
```python
class SmartMoneyConcepts:
    """
    Inducement, Displacement, Mitigation 패턴
    """
    - detect_inducement()  # Fake breakout
    - detect_displacement()  # Strong directional move
    - find_mitigation_zone()  # OB/FVG retest
```

**핵심 로직**:
- Inducement: Liquidity sweep → reversal
- Displacement: Large candle (> 2x ATR)
- Mitigation: Return to OB/FVG zone

#### 2.3 Kill Zones
**목적**: 최적 거래 시간대 필터링

**구현 항목**:
```python
class KillZones:
    """
    London Open: 08:00-11:00 UTC
    New York Open: 13:00-16:00 UTC
    Asia Session: 00:00-03:00 UTC
    """
    - is_london_killzone()
    - is_newyork_killzone()
    - get_active_killzone()
```

**핵심 로직**:
- Datetime-based filtering
- Timezone conversion (UTC)
- Session overlap detection

---

### Phase 3: 통합 ICT 전략 구현 (1일)

#### 3.1 ICTStrategy 클래스 설계

```python
class ICTStrategy(BaseStrategy):
    """
    Comprehensive ICT trading strategy.

    Entry Logic:
    1. Market Structure: BOS/CHoCH 확인
    2. Liquidity Sweep: Equal highs/lows 탐지
    3. Mitigation: FVG/OB retest 대기
    4. Kill Zone: 적절한 시간대 확인
    5. Confirmation: Displacement candle 발생

    Exit Logic:
    - TP: Next FVG/OB level or risk-reward ratio
    - SL: Recent swing high/low beyond OB
    """

    def __init__(self, symbol: str, config: dict):
        super().__init__(symbol, config)

        # ICT 컴포넌트 초기화
        self.market_structure = MarketStructure(config)
        self.fvg_detector = FairValueGap(config)
        self.ob_detector = OrderBlock(config)
        self.liquidity = LiquidityAnalysis(config)
        self.smc = SmartMoneyConcepts(config)
        self.killzones = KillZones()

        # 전략 파라미터
        self.swing_lookback = config.get('swing_lookback', 20)
        self.fvg_threshold = config.get('fvg_threshold', 0.001)  # 0.1%
        self.ob_strength = config.get('ob_strength', 0.015)  # 1.5%
        self.risk_reward = config.get('risk_reward_ratio', 2.0)

    async def analyze(self, candle: Candle) -> Optional[Signal]:
        """
        Multi-step ICT analysis for signal generation.
        """
        # Step 0: Only analyze closed candles
        if not candle.is_closed:
            return None

        # Step 1: Update buffer
        self.update_buffer(candle)

        # Step 2: Minimum data requirement
        if len(self.candle_buffer) < self.swing_lookback * 2:
            return None

        # Step 3: Kill Zone filtering
        if not self.killzones.is_active_killzone(candle.timestamp):
            return None

        # Step 4: Market Structure analysis
        structure = self.market_structure.analyze(self.candle_buffer)
        if structure.trend == 'sideways':
            return None

        # Step 5: Liquidity analysis
        liquidity = self.liquidity.find_sweep(self.candle_buffer)
        if not liquidity.sweep_detected:
            return None

        # Step 6: FVG/OB detection
        fvgs = self.fvg_detector.find_unfilled_gaps(self.candle_buffer)
        obs = self.ob_detector.find_valid_blocks(self.candle_buffer)

        mitigation_zones = fvgs + obs
        if not mitigation_zones:
            return None

        # Step 7: Mitigation check (price in zone)
        current_price = candle.close
        active_zone = None
        for zone in mitigation_zones:
            if zone.contains_price(current_price):
                active_zone = zone
                break

        if not active_zone:
            return None

        # Step 8: Displacement confirmation
        displacement = self.smc.detect_displacement(self.candle_buffer[-3:])
        if not displacement:
            return None

        # Step 9: Signal generation
        if structure.trend == 'bullish' and active_zone.type == 'bullish':
            signal_type = SignalType.LONG_ENTRY
            entry_price = current_price
            stop_loss = self.calculate_stop_loss(entry_price, 'LONG', active_zone)
            take_profit = self.calculate_take_profit(entry_price, 'LONG', structure)

        elif structure.trend == 'bearish' and active_zone.type == 'bearish':
            signal_type = SignalType.SHORT_ENTRY
            entry_price = current_price
            stop_loss = self.calculate_stop_loss(entry_price, 'SHORT', active_zone)
            take_profit = self.calculate_take_profit(entry_price, 'SHORT', structure)

        else:
            return None

        # Step 10: Create signal
        return Signal(
            signal_type=signal_type,
            symbol=self.symbol,
            entry_price=entry_price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            strategy_name="ICTStrategy",
            timestamp=datetime.now(timezone.utc),
            metadata={
                'trend': structure.trend,
                'zone_type': active_zone.type,
                'zone_level': active_zone.level,
                'liquidity_sweep': liquidity.level,
                'killzone': self.killzones.get_active_killzone(candle.timestamp)
            }
        )

    def calculate_take_profit(
        self,
        entry_price: float,
        side: str,
        structure: MarketStructure
    ) -> float:
        """
        TP = Next significant FVG/OB level or risk-reward target
        """
        if side == 'LONG':
            # Find next resistance (bearish FVG/OB)
            next_level = structure.find_next_resistance(entry_price)
            rr_target = entry_price + (entry_price - self.last_sl) * self.risk_reward
            return min(next_level, rr_target) if next_level else rr_target
        else:
            # Find next support (bullish FVG/OB)
            next_level = structure.find_next_support(entry_price)
            rr_target = entry_price - (self.last_sl - entry_price) * self.risk_reward
            return max(next_level, rr_target) if next_level else rr_target

    def calculate_stop_loss(
        self,
        entry_price: float,
        side: str,
        zone: MitigationZone
    ) -> float:
        """
        SL = Beyond the mitigation zone (recent swing)
        """
        if side == 'LONG':
            # SL below OB/FVG low
            sl = zone.low * 0.998  # 0.2% buffer
        else:
            # SL above OB/FVG high
            sl = zone.high * 1.002  # 0.2% buffer

        self.last_sl = sl  # Store for TP calculation
        return sl
```

#### 3.2 Configuration

```ini
# configs/trading_config.ini
[trading]
strategy = ict_strategy

[ict_strategy]
# Market Structure
swing_lookback = 20           # Bars for swing detection
bos_threshold = 0.001         # 0.1% break threshold

# Fair Value Gap
fvg_threshold = 0.001         # 0.1% minimum gap
fvg_lookback = 50             # Bars to search

# Order Block
ob_strength = 0.015           # 1.5% minimum move
ob_lookback = 30              # Bars to search

# Liquidity
equal_threshold = 0.001       # 0.1% tolerance for equal highs/lows
liquidity_lookback = 50       # Bars to search

# Risk Management
risk_reward_ratio = 2.0       # TP:SL ratio
max_risk_per_trade = 0.01     # 1% account risk

# Kill Zones (UTC times)
london_start = 08:00
london_end = 11:00
newyork_start = 13:00
newyork_end = 16:00
enable_killzone_filter = true
```

---

## 📊 구현 우선순위

### Priority 1: 필수 (MVP)
1. ✅ Market Structure (BOS, CHoCH)
2. ✅ Fair Value Gap detection
3. ✅ Order Block identification
4. ✅ Basic ICTStrategy integration

### Priority 2: 중요
1. ⏳ Liquidity analysis
2. ⏳ Kill Zone filtering
3. ⏳ Smart Money Concepts (inducement, displacement)

### Priority 3: 고급
1. ⏳ Multi-timeframe analysis (MTF)
2. ⏳ Session-based analysis
3. ⏳ Advanced confirmation filters

---

## 🧪 테스트 전략

### Phase 1: Unit Testing
```python
# tests/strategies/test_ict_components.py
def test_market_structure_bos():
    """Test Break of Structure detection"""

def test_fvg_detection():
    """Test Fair Value Gap identification"""

def test_order_block_validation():
    """Test Order Block strength calculation"""
```

### Phase 2: Integration Testing
```python
# tests/strategies/test_ict_strategy.py
def test_ict_signal_generation():
    """Test full ICT strategy signal generation"""

def test_tp_sl_calculation():
    """Test TP/SL levels with ICT logic"""
```

### Phase 3: Backtesting
```python
# tests/backtest/test_ict_backtest.py
def test_historical_performance():
    """
    Historical data: 2024-01-01 ~ 2024-12-31
    Metrics: Win rate, Risk-reward, Sharpe ratio
    """
```

---

## 📈 성과 측정 지표

### Trading Metrics
```python
# Performance tracking
- Win Rate: Winning trades / Total trades
- Risk-Reward Ratio: Average win / Average loss
- Profit Factor: Gross profit / Gross loss
- Max Drawdown: Peak-to-trough decline
- Sharpe Ratio: Risk-adjusted returns
```

### ICT-Specific Metrics
```python
# Strategy validation
- FVG Fill Rate: FVG entries filled / Total FVG entries
- OB Respect Rate: OB mitigation success / Total OB signals
- BOS Accuracy: Valid BOS / Total BOS signals
- Liquidity Sweep Success: Sweep → reversal / Total sweeps
```

---

## 🛠️ 구현 계획

### Day 1: 기초 구현
**오전 (4h)**:
- MarketStructure 클래스 구현
- FairValueGap 클래스 구현
- Unit tests 작성

**오후 (4h)**:
- OrderBlock 클래스 구현
- 통합 테스트
- 문서화

### Day 2: 고급 기능
**오전 (4h)**:
- LiquidityAnalysis 구현
- SmartMoneyConcepts 구현
- KillZones 구현

**오후 (4h)**:
- ICTStrategy 통합
- 설정 파일 작성
- End-to-end 테스트

### Day 3: 검증 & 최적화
**오전 (4h)**:
- 백테스팅 시스템 구축
- Historical data 테스트
- 성능 분석

**오후 (4h)**:
- 파라미터 튜닝
- 문서화 완성
- 프로덕션 배포 준비

---

## 📚 참고 자료

### ICT 개념 학습
- [The Inner Circle Trader YouTube](https://www.youtube.com/@TheInnerCircleTrader)
- ICT Mentorship 2022 (Free content)
- Market Maker Models

### 기술 구현
- `src/strategies/base.py` - Strategy interface
- `src/strategies/mock_strategy.py` - Reference implementation
- `claudedocs/backfill_implementation.md` - Data pipeline

### 외부 라이브러리
```python
# 추가 고려 사항
- pandas_ta: Technical indicators
- numpy: Numerical calculations
- scipy: Statistical analysis (optional)
```

---

## 🎯 성공 기준

### Minimum Viable Product (MVP)
- ✅ Market Structure 분석 작동
- ✅ FVG 탐지 정확도 > 90%
- ✅ Order Block 식별 정상 작동
- ✅ Signal 생성 및 주문 실행 성공
- ✅ TP/SL 레벨 로직 검증

### Production Ready
- ✅ Unit test coverage > 80%
- ✅ Integration tests 통과
- ✅ Backtesting 결과 양호 (Sharpe > 1.0)
- ✅ Real-time 테스트 (testnet) 안정적
- ✅ Documentation 완성

---

## 🚧 리스크 & 대응

### Technical Risks
| Risk | Impact | Mitigation |
|------|--------|------------|
| FVG 오탐지 | 중 | Multi-candle 검증, threshold 튜닝 |
| OB 강도 판단 오류 | 중 | ATR 기반 동적 threshold |
| Market structure 오독 | 높음 | Multiple timeframe 확인 |
| Liquidity sweep 오판 | 중 | Tolerance 조정, 재확인 로직 |

### Operational Risks
| Risk | Impact | Mitigation |
|------|--------|------------|
| 과도한 신호 생성 | 높음 | Kill zone filtering, 추가 필터 |
| 신호 부족 | 중 | Threshold 완화, 다중 전략 |
| Testnet/Mainnet 차이 | 높음 | Testnet 충분 검증 후 단계 배포 |

---

## 📋 체크리스트

### 개발 전
- [ ] Journal 문서 리뷰 완료
- [ ] BaseStrategy 인터페이스 이해
- [ ] ICT 개념 학습 완료
- [ ] 구현 계획 승인

### 개발 중
- [ ] MarketStructure 구현 & 테스트
- [ ] FairValueGap 구현 & 테스트
- [ ] OrderBlock 구현 & 테스트
- [ ] ICTStrategy 통합
- [ ] Configuration 설정
- [ ] Unit tests 작성 (> 80% coverage)

### 개발 후
- [ ] Integration tests 통과
- [ ] Backtesting 실행 및 분석
- [ ] Testnet 실시간 테스트 (24h+)
- [ ] Performance metrics 수집
- [ ] Documentation 업데이트
- [ ] Code review 완료

---

## 🎓 학습 목표

### ICT 개념 마스터
- Market Structure (BOS, CHoCH) 완벽 이해
- Fair Value Gap 형성 원리 및 활용
- Order Block의 스마트 머니 개념
- Liquidity manipulation 패턴

### 코딩 스킬
- Python async/await 패턴
- OOP design patterns (Strategy, Factory)
- Unit testing best practices
- Performance optimization

### Trading 스킬
- Risk management principles
- Position sizing strategies
- Backtesting methodology
- Performance analysis

---

**제안서 작성일**: 2025-12-27
**예상 착수일**: TBD (사용자 승인 후)
**예상 완료일**: 착수 후 3일

**문의 및 피드백**: 이 제안서에 대한 질문이나 수정 요청은 언제든 환영합니다.
