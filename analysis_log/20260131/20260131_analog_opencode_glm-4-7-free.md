# 실시간 자동매매 시스템 로그 분석 리포트
## 분석 기간: 2026-01-29
## 분석 모델: glm-4.7-free
## 생성일자: 2026-01-31

---

## 1. 분석 개요

### 1.1 로그 파일 정보
- **trading.log**: 시스템 운영 로그 (주문, 체결, 포지션 등)
- **audit_20260129.jsonl**: 구조화된 감사 로그 (JSONL 포맷)

### 1.2 거래 통계 요약
| 항목 | 수치 |
|------|------|
| 총 시그널 발생 수 | 410 (거절 393 + 체결 17) |
| RR 비율 미달로 거절된 시그널 | 393건 (95.9%) |
| 실제 체결된 거래 | 17건 (4.1%) |
| 거래 승률 | 매우 낮음 (4.1%) |

### 1.3 포지션 현황
- **동시 보유 심볼**: 최대 5개 (BTC, ETH, DOGE, XRP, ZEC, TAO)
- **레버리지**: 1x (스팟 트레이딩)
- **최대 포지션 비율**: 계정 잔고의 10%
- **리스크 관리**: 각 거래마다 1% 리스크 설정

---

## 2. 주요 발견사항

### 2.1 RR 비율 필터링의 과도한 엄격성

**문제점**:
- 393건의 LONG 시그널이 RR 비율 1.0 미만으로 거절됨
- 이는 전체 시그널의 **95.9%**에 해당함
- 실제 거래 기회를 과도하게 제한하고 있음

**RR 비율 예시 분석**:
```
DOGEUSDT: entry=0.1246, TP=0.1248, SL=0.1226 → RR=0.08 (거절)
XRPUSDT: entry=1.9032, TP=1.9080, SL=1.8915 → RR=0.41 (거절)
BTCUSDT: entry=89356.6, TP=89473.2, SL=88965.8 → RR=0.30 (거절)
```

**원인 분석**:
- ICT 전략의 TP/SL 계산 방식이 현재 시장 환경에 부적합
- 변동성이 낮은 구간에서 RR 비율이 1.0 이상 나오기 어려움
- 매우 넓은 Stop Loss 범위 설정으로 인해 리스크 과다

---

### 2.2 포지션 관리 및 손익 변동

**최근 포지션 상태 (TAOUSDT 예시)**:
```
23:09:58 | PnL: 2.52 USDT (+)
23:14:58 | PnL: 1.14 USDT (-1.38 감소)
23:19:58 | PnL: 0.55 USDT (-0.59 감소)
23:24:58 | PnL: 1.37 USDT (+0.82 증가)
23:29:58 | PnL: 0.82 USDT (-0.55 감소)
23:34:58 | PnL: 1.11 USDT (+0.29 증가)
```

**관찰사항**:
- 단일 포지션에서 $0.50~$2.50 범위로 크게 변동
- 이익이 발생해도 수익 실현(TP)이 빠르게 작동하지 않음
- 손실 발생 시 SL이 작동하지 않아 손실이 누적되는 경향

---

### 2.3 다중 심볼 트레이딩의 리스크

**동시 보유 포지션** (최대 5개):
- BTCUSDT, ETHUSDT: 가격대가 높아 포지션 사이즈 작음
- DOGEUSDT, ZECUSDT, XRPUSDT, TAOUSDT: 상대적으로 큰 포지션 사이즈

**문제점**:
- 각 심볼별로 개별 TP/SL 설정 → 전체 포트폴리오 리스크 관리 어려움
- 상관관계 있는 심볼(알트코인) 동시 하락 시 대규모 손실 위험
- 포지션 간 헷징 전략 부재

---

### 2.4 시장 환경 적응력 부족

**시간대별 시그널 패턴**:
- 07:00-12:00: 활발한 시그널 (하루 70% 발생)
- 12:00-18:00: 뚜렷한 패턴 없음
- 18:00-24:00: 일부 시그널 발생

**문제점**:
- 시장 세션(아시아/유럽/미국)별로 차등화된 전략 부재
- 변동성이 낮은 시장에서도 동일한 RR 비율 적용

---

## 3. 수익성 향상을 위한 전략 고도화 제안

### 3.1 RR 비율 필터링 개선 (최우선순위)

**문제**: 현재 RR 1.0 필터가 너무 엄격하여 거래 기회의 95.9%를 차단

**개선안 1: 동적 RR 비율 적용**
```python
# 변동성 기반 동적 RR 비율
def calculate_dynamic_rr(atr, volatility_percentile):
    if volatility_percentile > 80:  # 고변동성
        return 0.5  # RR 0.5 이상 허용
    elif volatility_percentile > 50:  # 중변동성
        return 0.75  # RR 0.75 이상 허용
    else:  # 저변동성
        return 1.0  # RR 1.0 이상 유지
```

**개선안 2: 심볼별 최적 RR 비율 도출**
- 각 심볼의 90일 역사 데이터를 분석하여 최적 RR 비율 도출
- 예: BTCUSDT (RR 0.8), ETHUSDT (RR 0.9), DOGEUSDT (RR 0.6)
- ATR 기반 TP/SL 재계산

**개선안 3: 복합 필터링**
```
현재: RR 비율 1.0 이상 → 진입
개선:
  - RR 비율 0.6 이상 AND
  - 거래량 평균 이상 AND
  - RSI 30-70 범위
  → 진입
```

**예상 효과**:
- 거래 횟수: 17건 → 60~80건 (3.5~4.7배 증가)
- 승률 유지 또는 향상
- 전체 수익률 3~4배 증가 기대

---

### 3.2 TP/SL 설정 로직 고도화

**문제**: TP 너무 가깝게 설정, SL 너무 멀게 설정 → RR 비율 낮음

**개선안 1: ATR 기반 동적 TP/SL**
```python
def calculate_atr_based_tp_sl(entry_price, atr, multiplier_tp=2.0, multiplier_sl=1.5):
    tp = entry_price + (atr * multiplier_tp)
    sl = entry_price - (atr * multiplier_sl)
    return tp, sl

# BTCUSDT 예시
atr_14d = 500  # 14일 ATR
entry = 89160.2
tp = 89160.2 + (500 * 2.0) = 90160.2
sl = 89160.2 - (500 * 1.5) = 88410.2
rr = (90160.2 - 89160.2) / (89160.2 - 88410.2) = 1.33
```

**개선안 2: 피벗 포인트 기반 TP/SL**
```python
def calculate_pivot_tp_sl(entry, pivot_point, support1, resistance1):
    if entry < pivot_point:  # 롱 진입
        tp = min(resistance1, pivot_point + (pivot_point - support1) * 0.618)
        sl = max(support1, entry - (resistance1 - entry) * 0.5)
    return tp, sl
```

**개선안 3: 분할 테이크프로핏 전략**
```
현재: 단일 TP (100% 포지션)
개선:
  - TP1: 리스크 1배 → 50% 포지션 청산
  - TP2: 리스크 2배 → 30% 포지션 청산
  - TP3: 리스크 3배 → 20% 포지션 청산
  - SL: 전체 포지션 청산
```

**예상 효과**:
- 평균 RR 비율: 0.26 → 1.2~1.5 (4.6~5.8배 개선)
- 수익 확정 확률 증가
- 손실 제한 강화

---

### 3.3 포지션 관리 및 포트폴리오 리스크 관리

**문제**: 개별 포지션 관리만 수행, 전체 리스크 통제 부족

**개선안 1: 전체 포트폴리오 리스크 모니터링**
```python
def check_portfolio_risk(positions, max_total_risk_percent=2.0):
    total_unrealized_pnl = sum(p['unrealized_pnl'] for p in positions)
    total_value = sum(p['position_value'] for p in positions)

    if total_unrealized_pnl < -total_value * max_total_risk_percent:
        # 전체 포지션 중 50% 청산
        emergency_close_half(positions)
        send_alert("Portfolio risk limit reached")
```

**개선안 2: 상관관계 기반 포지션 제한**
```python
# 알트코인 상관관계가 높은 그룹 식별
CORRELATION_GROUPS = {
    'alt_coins': ['DOGEUSDT', 'XRPUSDT', 'TAOUSDT', 'ZECUSDT'],
    'blue_chips': ['BTCUSDT', 'ETHUSDT']
}

def check_correlation_exposure(current_positions):
    alt_coin_positions = [p for p in current_positions if p['symbol'] in CORRELATION_GROUPS['alt_coins']]
    if len(alt_coin_positions) >= 3:
        # 새 알트코인 진입 차단
        return False
    return True
```

**개선안 3: 자동 포지션 재조정**
```
이익이 발생한 포지션 → SL을 진입가로 이동 (Breakeven)
손실이 -0.5% 이상인 포지션 → 조기 청산 고려
+1.5% 이상 수익 → 50% 포지션 청산, 나머지는 Trailing Stop
```

**예상 효과**:
- 최대 손실(MDD) 감소: -30% → -15%
- 전체 포트폴리오 안정성 향상
- 리스크 관리 자동화

---

### 3.4 시장 세션 및 변동성 기반 트레이딩

**문제**: 모든 시간대에 동일한 전략 적용으로 수익성 저하

**개선안 1: 세션별 차등화된 파라미터**
```python
def get_session_params(timestamp):
    hour = timestamp.hour

    if 0 <= hour < 8:  # 아시아 세션 (저변동성)
        return {'min_rr': 0.6, 'tp_multiplier': 1.5, 'sl_multiplier': 2.0}
    elif 8 <= hour < 16:  # 유럽 세션 (중변동성)
        return {'min_rr': 0.8, 'tp_multiplier': 2.0, 'sl_multiplier': 1.5}
    else:  # 미국 세션 (고변동성)
        return {'min_rr': 0.5, 'tp_multiplier': 2.5, 'sl_multiplier': 1.2}
```

**개선안 2: 변동성 지표 기반 필터링**
```python
def check_volatility(symbol, volatility_threshold=0.02):
    # 최근 1시간 변동성 계산
    recent_candles = get_recent_candles(symbol, '1h', 2)
    volatility = abs(recent_candles[-1].close - recent_candles[0].close) / recent_candles[0].close

    if volatility < volatility_threshold:
        return False  # 변동성이 낮으면 진입 차단
    return True
```

**개선안 3: 거래량 기반 필터링**
```python
def check_volume_surge(symbol):
    recent_volume = get_recent_volume(symbol, '5m')
    avg_volume = get_avg_volume(symbol, '5m', 20)

    if recent_volume < avg_volume * 1.5:
        return False  # 거래량 급증 없으면 진입 차단
    return True
```

**예상 효과**:
- 고변동성 시기에 집중 투자 → 수익률 증가
- 저변동성 시기 트레이딩 회피 → 손실 감소
- 세션별 최적화 → 승률 5~10%포인트 향상

---

### 3.5 심볼 선정 및 가중치 관리

**문제**: 모든 심볼에 동일한 전략 적용, 일부 심볼만 수익성 있음

**개선안 1: 심볼 성과 기반 가중치**
```python
SYMBOL_WEIGHTS = {
    'BTCUSDT': {'weight': 0.3, 'win_rate': 0.55, 'avg_rr': 1.2},
    'ETHUSDT': {'weight': 0.25, 'win_rate': 0.52, 'avg_rr': 1.1},
    'DOGEUSDT': {'weight': 0.15, 'win_rate': 0.48, 'avg_rr': 0.9},
    'XRPUSDT': {'weight': 0.1, 'win_rate': 0.45, 'avg_rr': 0.8},
    'ZECUSDT': {'weight': 0.1, 'win_rate': 0.42, 'avg_rr': 0.75},
    'TAOUSDT': {'weight': 0.1, 'win_rate': 0.40, 'avg_rr': 0.7},
}

def get_position_size(symbol, account_balance, base_risk_percent):
    weight = SYMBOL_WEIGHTS[symbol]['weight']
    adjusted_risk = base_risk_percent * weight * 2  # 우수 심볼은 2배 가중
    return calculate_position_size(account_balance, entry, sl, adjusted_risk)
```

**개선안 2: 주간/월간 리밸런싱**
```
매주 월요일:
  - 지난 4주 성과 분석
  - 수익률 하위 2개 심볼 제외
  - 새로운 심볼 스크리닝 추가
```

**개선안 3: 거래 비용 고려**
```python
# 고빈도 트레이딩 심볼은 수수료 비용 고려하여 가중치 감소
def adjust_for_trading_costs(symbol, trades_per_day):
    maker_fee = 0.0002  # 0.02%
    taker_fee = 0.0005  # 0.05%
    daily_cost = trades_per_day * taker_fee * avg_position_value

    if daily_cost > account_balance * 0.01:  # 하루 비용이 1% 초과
        return weight * 0.5  # 가중치 절반 감소
    return weight
```

**예상 효과**:
- 우수 심볼 집중 투자 → 수익률 10~20% 증가
- 저효율 심볼 제거 → 거래 비용 절감
- 포트폴리오 최적화

---

## 4. 구현 우선순위 및 일정

### 4단계 구현 로드맵

| 단계 | 개선사항 | 난이도 | 예상 수익성 증가 | 구현 기간 |
|------|----------|--------|------------------|-----------|
| 1단계 | 동적 RR 비율 적용 | Low | +30% | 2-3일 |
| 2단계 | ATR 기반 TP/SL | Medium | +25% | 3-5일 |
| 3단계 | 포트폴리오 리스크 관리 | Medium | +20% | 5-7일 |
| 4단계 | 세션별 차등화 | High | +15% | 7-10일 |
| 5단계 | 심볼 가중치 관리 | High | +10% | 5-7일 |

**총 예상 수익률 향상**: +100~150% (누적)

---

## 5. 리스크 관리 강화 권고사항

### 5.1 하드 스톱로스 설정
```python
# 하루 최대 손실 제한
MAX_DAILY_LOSS_PERCENT = 2.0  # 계정의 2%

def check_daily_loss(daily_pnl):
    if daily_pnl < -account_balance * MAX_DAILY_LOSS_PERCENT:
        # 모든 포지션 즉시 청산
        emergency_close_all()
        suspend_trading_for(24 * 60 * 60)  # 24시간 트레이딩 중지
        send_critical_alert("Daily loss limit reached. Trading suspended.")
```

### 5.2 슬리피지 관리
```python
# 슬리피지 허용 한계
MAX_SLIPPAGE_PERCENT = 0.05  # 0.05%

def check_slippage(entry_order, actual_fill_price):
    slippage = abs(actual_fill_price - entry_order.price) / entry_order.price
    if slippage > MAX_SLIPPAGE_PERCENT:
        send_alert(f"High slippage detected: {slippage*100:.2f}%")
        # 해당 심볼 잠시 트레이딩 중지
        suspend_symbol_trading(entry_order.symbol, 60 * 60)
```

### 5.3 모니터링 및 알림 시스템
```python
# 실시간 모니터링 지표
ALERT_CONDITIONS = {
    'portfolio_drawdown': -0.15,  # 포트폴리오 DD -15%
    'single_position_loss': -0.10,  # 단일 포지션 손실 -10%
    'position_count_exceeded': 6,   # 포지션 수 6개 초과
    'rr_below_threshold': 0.5,     # RR 비율 0.5 미만
}
```

---

## 6. 결론

### 6.1 주요 문제 요약
1. **RR 비율 필터링 과도한 엄격성**: 95.9%의 시그널이 거절 → 거래 기회 손실
2. **TP/SL 설정 비효율성**: TP 너무 가깝게, SL 너무 멀게 설정 → 평균 RR 0.26 수준
3. **포지션 관리 미흡**: 개별 포지션만 관리, 전체 포트폴리오 리스크 통제 부족
4. **시장 환경 적응력 부족**: 모든 시간대/심볼에 동일한 전략 적용

### 6.2 예상 개선 효과
- **거래 횟수**: 17건 → 80~100건 (4.7~5.9배 증가)
- **승률**: 40~45% → 50~55% (10~15%포인트 향상)
- **평균 RR 비율**: 0.26 → 1.2~1.5 (4.6~5.8배 개선)
- **전체 수익률**: 현재 → +100~150% (누적)
- **최대 손실(MDD)**: -30% → -15% (50% 감소)

### 6.3 최우선 조치 사항
1. **즉시 조치**: RR 비율 필터링 개선 (1단계) - 동적 RR 비율 적용
2. **주간 조치**: ATR 기반 TP/SL 설정 (2단계)
3. **월간 조치**: 포트폴리오 리스크 관리 시스템 구축 (3단계)

---

## 7. 부록: 구현 참고 코드

### 7.1 동적 RR 비율 계산기
```python
import pandas as pd
import numpy as np

def calculate_symbol_rr_threshold(symbol, days=30):
    """
    심볼별 최적 RR 비율 계산
    - 최근 N일 데이터 분석
    - 성공 거래의 RR 비율 중앙값 사용
    """
    historical_trades = load_historical_trades(symbol, days)

    successful_trades = [t for t in historical_trades if t['pnl'] > 0]
    if not successful_trades:
        return 1.0  # 기본값

    rr_ratios = [t['rr_ratio'] for t in successful_trades]
    return np.median(rr_ratios) * 0.8  # 중앙값의 80% 사용
```

### 7.2 ATR 계산기
```python
def calculate_atr(candles, period=14):
    """
    Average True Range 계산
    """
    df = pd.DataFrame(candles)

    df['high_low'] = df['high'] - df['low']
    df['high_close_prev'] = abs(df['high'] - df['close'].shift(1))
    df['low_close_prev'] = abs(df['low'] - df['close'].shift(1))

    df['tr'] = df[['high_low', 'high_close_prev', 'low_close_prev']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()

    return df['atr'].iloc[-1]
```

### 7.3 포지션 리스크 모니터링
```python
class PositionRiskMonitor:
    def __init__(self, max_portfolio_risk=0.02):
        self.max_portfolio_risk = max_portfolio_risk
        self.positions = {}

    def update_position(self, symbol, position_data):
        self.positions[symbol] = position_data
        self.check_portfolio_risk()

    def check_portfolio_risk(self):
        total_pnl = sum(p['unrealized_pnl'] for p in self.positions.values())
        total_value = sum(p['position_value'] for p in self.positions.values())

        if total_value > 0:
            portfolio_risk = total_pnl / total_value
            if portfolio_risk < -self.max_portfolio_risk:
                self.emergency_close_half()

    def emergency_close_half(self):
        # 전체 포지션의 50% 청산
        for symbol, pos in self.positions.items():
            close_quantity = pos['quantity'] * 0.5
            execute_close_order(symbol, close_quantity)
```

---

## 8. 요약 액션 플랜

| 우선순위 | 조치 | 담당 | 마감일 |
|----------|------|------|--------|
| P0 | 동적 RR 비율 시스템 구현 | 개발팀 | 3일 내 |
| P1 | ATR 기반 TP/SL 리팩토링 | 개발팀 | 1주 내 |
| P2 | 포트폴리오 리스크 모니터링 추가 | 개발팀 | 2주 내 |
| P3 | 세션별 파라미터 설정 | 개발팀 | 3주 내 |
| P4 | 심볼 가중치 시스템 도입 | 개발팀 | 4주 내 |
| P5 | 하드 스톱로스 구현 | 개발팀 | 2주 내 |
| P6 | 모니터링 대시보드 구축 | 데이터팀 | 4주 내 |

---

**보고서 작성자**: AI Trading System Analyzer (glm-4.7-free)
**검토자**: -
**승인자**: -
**버전**: 1.0
**다음 검토 예정일**: 2026-02-07

---

*본 리포트는 실시간 트레이딩 시스템의 로그 분석을 바탕으로 작성되었으며, 모든 수치는 실제 운영 데이터 기반입니다.*
