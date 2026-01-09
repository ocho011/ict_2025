# ICT 지표 구현 계획 (옵션 B)

## 전략적 결정

**선택한 옵션**: B - ICT 지표 먼저 구현 → Phase 3 진행

**근거**:
- MTF 프레임워크 이미 완성 ✅
- Placeholder 로직은 실전 가치 없음
- ICT 지표가 핵심 기능
- 한 번에 제대로 구현 = 재작업 방지

## ICT 개념 정리

### 1. Fair Value Gap (FVG)
- **정의**: 3개 연속 캔들에서 갭 발생 (candle1.high < candle3.low)
- **Bullish FVG**: 상승장에서 갭 발생, 가격이 갭을 채우러 돌아올 확률
- **Bearish FVG**: 하락장에서 갭 발생
- **용도**: Entry zone, Mitigation zone

### 2. Order Block (OB)
- **정의**: 큰 움직임 직전의 마지막 반대 방향 캔들
- **Bullish OB**: 큰 상승 전 마지막 bearish 캔들
- **Bearish OB**: 큰 하락 전 마지막 bullish 캔들
- **용도**: Support/Resistance, Entry zone

### 3. Displacement
- **정의**: 평균 range 대비 큰 방향성 움직임
- **기준**: 일반적으로 평균의 1.5x ~ 2.0x
- **용도**: Trend confirmation, Entry timing

### 4. Market Structure
- **BOS (Break of Structure)**: 추세 지속 신호
- **CHoCH (Change of Character)**: 추세 전환 신호
- **Swing High/Low**: 구조 파악

## 구현 순서

### Phase 1: 기본 지표 구현 (1-1.5 days)

#### Task 1.1: FVG 감지기
```python
# src/indicators/ict_fvg.py

class FVGDetector:
    def detect_fvg(
        self,
        candles: List[Candle],
        min_gap_percent: float = 0.001  # 0.1%
    ) -> List[FVG]:
        """
        3-candle 패턴에서 FVG 감지
        
        Bullish FVG:
        - candle[0].high < candle[2].low
        - gap = candle[2].low - candle[0].high
        
        Bearish FVG:
        - candle[0].low > candle[2].high
        - gap = candle[0].low - candle[2].high
        """
```

#### Task 1.2: Order Block 식별
```python
# src/indicators/ict_order_block.py

class OrderBlockDetector:
    def detect_order_block(
        self,
        candles: List[Candle],
        displacement_threshold: float = 1.5
    ) -> List[OrderBlock]:
        """
        Displacement 직전 마지막 반대 캔들 찾기
        
        Bullish OB:
        - 큰 상승 전 마지막 bearish 캔들
        - zone = (ob_candle.low, ob_candle.high)
        
        Bearish OB:
        - 큰 하락 전 마지막 bullish 캔들
        """
```

#### Task 1.3: Displacement 계산
```python
# src/indicators/ict_displacement.py

class DisplacementDetector:
    def detect_displacement(
        self,
        candles: List[Candle],
        lookback: int = 20,
        threshold: float = 1.5
    ) -> List[Displacement]:
        """
        평균 range 대비 큰 움직임 감지
        
        avg_range = mean([c.high - c.low for c in last 20])
        displacement = abs(c.close - c.open) > avg_range * 1.5
        direction = 'bullish' if c.close > c.open else 'bearish'
        """
```

### Phase 2: Market Structure (0.5-1 day)

#### Task 2.1: Swing High/Low 추적
```python
# src/indicators/ict_structure.py

class MarketStructure:
    def find_swing_highs(
        self,
        candles: List[Candle],
        left_bars: int = 5,
        right_bars: int = 5
    ) -> List[SwingPoint]:
        """
        Swing High: 좌우 N개 캔들보다 high가 높은 경우
        Swing Low: 좌우 N개 캔들보다 low가 낮은 경우
        """
```

#### Task 2.2: BOS/CHoCH 감지
```python
def detect_structure_breaks(
    self,
    candles: List[Candle],
    swing_points: List[SwingPoint]
) -> List[StructureBreak]:
    """
    BOS (Break of Structure): 이전 swing high/low 돌파
    CHoCH (Change of Character): 추세 반대 방향 structure break
    """
```

### Phase 3: ICT MTF Strategy 통합 (0.5 day)

#### Task 3.1: ICTMultiTimeframeStrategy 구현
```python
# src/strategies/ict_mtf_strategy.py

class ICTMultiTimeframeStrategy(MultiTimeframeStrategy):
    async def analyze_mtf(
        self,
        candle: Candle,
        buffers: Dict[str, deque]
    ) -> Optional[Signal]:
        # HTF (4h): Market Structure 분석
        htf_trend = self.structure.analyze_trend(buffers[self.htf_interval])
        
        # MTF (1h): FVG/OB 감지
        fvgs = self.fvg_detector.detect_fvg(buffers[self.mtf_interval])
        obs = self.ob_detector.detect_order_block(buffers[self.mtf_interval])
        
        # LTF (5m): Displacement 확인
        displacement = self.displacement.detect(buffers[self.ltf_interval])
        
        # Signal 생성
        if htf_trend and fvgs and displacement:
            return self._create_signal(...)
```

### Phase 4: 테스트 & 검증 (0.5 day)

#### Task 4.1: 단위 테스트
- `tests/indicators/test_ict_fvg.py`
- `tests/indicators/test_ict_order_block.py`
- `tests/indicators/test_ict_displacement.py`
- `tests/indicators/test_ict_structure.py`

#### Task 4.2: 통합 테스트
- `tests/strategies/test_ict_mtf_strategy.py`

## 데이터 모델

```python
# src/models/ict_signals.py

@dataclass
class FVG:
    start_index: int
    end_index: int
    gap_high: float
    gap_low: float
    direction: str  # 'bullish' or 'bearish'
    is_mitigated: bool = False

@dataclass
class OrderBlock:
    index: int
    zone_high: float
    zone_low: float
    direction: str  # 'bullish' or 'bearish'
    is_mitigated: bool = False

@dataclass
class Displacement:
    index: int
    size: float  # multiplier of avg range
    direction: str  # 'bullish' or 'bearish'

@dataclass
class StructureBreak:
    index: int
    type: str  # 'BOS' or 'CHoCH'
    direction: str  # 'bullish' or 'bearish'
    swing_point: SwingPoint
```

## 참고 자료

- ICT YouTube: https://www.youtube.com/@TheInnerCircleTrader
- FVG 개념: 3-candle imbalance pattern
- Order Block: Last opposing candle before displacement
- Market Structure: Higher highs/lows for trend identification

## 예상 소요 시간

- Phase 1 (기본 지표): 1-1.5 days
- Phase 2 (Market Structure): 0.5-1 day
- Phase 3 (ICT MTF Strategy): 0.5 day
- Phase 4 (테스트): 0.5 day
- **총합**: 2.5-3.5 days

## 다음 세션 시작 스텝

1. 메모리 로드:
   ```python
   read_memory("ict_implementation_plan")
   read_memory("mtf_implementation_status")
   ```

2. Task 1.1부터 시작:
   - `src/indicators/ict_fvg.py` 생성
   - FVGDetector 클래스 구현
   - 단위 테스트 작성

3. TodoWrite로 태스크 트래킹:
   ```python
   TodoWrite([
       {"content": "Implement FVG detector", "status": "in_progress"},
       {"content": "Implement Order Block detector", "status": "pending"},
       {"content": "Implement Displacement detector", "status": "pending"},
       ...
   ])
   ```
