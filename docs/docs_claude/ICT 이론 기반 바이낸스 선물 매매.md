# **바이낸스 무기한 선물 시장에서의 ICT 이론 기반 기관급 매매 전략 및 실행 체계**

현대의 금융 시장, 특히 변동성이 극심한 가상자산 파생상품 시장은 더 이상 단순한 매수와 매수의 심리전으로 설명되지 않는다. 바이낸스(Binance)의 USDT 무기한 선물 시장은 거대한 유동성이 교차하는 장소이며, 이곳의 가격 움직임은 고도로 설계된 알고리즘에 의해 인도된다는 것이 ICT(Inner Circle Trader) 이론의 핵심적인 전제이다.1 본 보고서는 마이클 J. 허들스턴(Michael J. Huddleston)이 정립한 ICT 개념을 바탕으로, 바이낸스 선물 시장에서 기관 투자자들이 어떻게 유동성을 확보하고 가격을 전달하는지 분석하며, 이를 실전 매매에 적용하기 위한 구체적인 방법론을 제시한다.

## **알고리즘 가격 전달 이론의 기초와 스마트 머니의 본질**

ICT 이론은 시장이 무작위적인 보행(Random Walk)을 한다는 효율적 시장 가설을 정면으로 부정한다. 대신, 중앙은행이나 거대 금융 기관의 알고리즘이 특정 가격 수준에 머물러 있는 유동성(Liquidity)을 찾아가고, 가격 불균형(Imbalance)을 해소하기 위해 가격을 재전달한다는 관점을 취한다.2 바이낸스 선물 시장에서 이러한 주체는 소위 '스마트 머니(Smart Money)'로 불리며, 이들은 일반 개인 투자자들이 설정한 손절매 물량을 흡수함으로써 자신들의 거대한 포지션을 체결시킨다.4

### **기관 포지션의 흔적: 오더 블록(Order Block)**

기관들은 한 번에 대량의 주문을 시장가로 체결시킬 수 없다. 그렇게 할 경우 엄청난 슬리피지가 발생하여 자신들의 평단가가 극도로 불리해지기 때문이다. 따라서 그들은 특정 가격대에서 주문을 분할하여 축적하는데, 이 과정에서 차트상에 '오더 블록'이라는 흔적이 남는다.3 오더 블록은 강력한 추세가 시작되기 직전의 마지막 반대 방향 캔들로 정의된다. 예를 들어, 강력한 상승이 나타나기 전의 마지막 음봉이 상승 오더 블록(Bullish Order Block)이 된다.3

단순한 캔들 패턴과 오더 블록을 구분 짓는 핵심 요소는 네 가지이다. 첫째, 이전 캔들의 유동성을 휩쓸어야 한다(Liquidity Sweep). 둘째, 가격이 해당 지점에서 강력하고 빠르게 이탈해야 한다(Displacement). 셋째, 이탈 과정에서 페어 밸류 갭(Fair Value Gap)을 남겨야 한다. 넷째, 최종적으로 시장 구조의 변화(Market Structure Shift)를 만들어내야 한다.3 바이낸스 비트코인(BTC) 선물 차트에서 이러한 조건이 충족된 오더 블록은 향후 가격이 회귀했을 때 강력한 지지나 저항 역할을 하게 된다.4

### **효율적 가격 형성의 지표: 페어 밸류 갭(Fair Value Gap)**

시장이 한 방향으로 급격하게 움직일 때, 알고리즘은 모든 가격 수준에서 매수와 매수 주문을 균형 있게 매칭시키지 못한다. 이로 인해 차트상에는 '가격 공백'이 발생하는데, 이것이 바로 페어 밸류 갭(FVG)이다.3 구체적으로는 연속된 세 개의 캔들 중 첫 번째 캔들의 고가와 세 번째 캔들의 저가가 겹치지 않는 구간을 의미한다.3

알고리즘은 본능적으로 이러한 불균형을 메우려는 성질이 있다. 따라서 가격이 FVG 구간으로 다시 돌아오는 현상을 '재균형(Rebalancing)'이라고 부르며, ICT 트레이더들은 이 구간을 최적의 진입 시점으로 활용한다.3 바이낸스 선물 시장처럼 레버리지가 높은 환경에서는 이러한 갭이 더 빈번하게 발생하며, 특히 중요 경제 지표 발표 시나 뉴욕 세션 개장 직후에 형성된 FVG는 매우 높은 신뢰도를 가진다.7

## **시장 구조와 유동성 순환의 메커니즘**

매매의 방향성을 결정하는 가장 중요한 요소는 현재 시장의 구조가 어떠한가이다. 시장 구조는 단순히 고점과 저점의 연결이 아니라, 스마트 머니가 현재 매집 중인지, 혹은 물량을 넘기고 있는지(분배)를 보여주는 지도와 같다.2

### **추세의 지속과 전환: BOS와 MSS**

가격이 이전의 고점을 높이거나 저점을 낮추며 추세를 이어가는 현상을 구조의 돌파(Break of Structure, BOS)라고 한다.6 반면, 기존의 추세가 꺾이면서 이전의 유의미한 저점을 하향 돌파하거나 고점을 상향 돌파하는 현상을 시장 구조의 변화(Market Structure Shift, MSS)라고 정의한다.2 바이낸스 선물 매매에서 MSS는 특히 중요한데, 이는 단순히 가격이 꺾이는 것이 아니라 기관의 의도가 매수에서 매도로, 혹은 그 반대로 바뀌었음을 시사하기 때문이다.2

### **유동성 풀(Liquidity Pools)과 손절 사냥**

기관들이 포지션을 구축하기 위해서는 반드시 반대 방향의 유동성이 필요하다. 즉, 대량의 매수 포지션을 잡으려면 대량의 매도 물량이 시장에 나와야 한다.2 이를 위해 알고리즘은 가격을 의도적으로 개인 투자자들의 손절매 물량이 모여 있는 구간으로 밀어붙인다. 이러한 구간을 유동성 풀이라고 하며, 크게 두 가지로 나뉜다.2

| 유동성 유형 | 위치 | 심리적 배경 |
| :---- | :---- | :---- |
| 매수측 유동성 (BSL) | 이전 고점 위 | 공매도 포지션의 손절매(Buy Stop) 및 돌파 매수세의 진입 주문. |
| 매도측 유동성 (SSL) | 이전 저점 아래 | 매수 포지션의 손절매(Sell Stop) 및 하방 돌파 매도세의 진입 주문. |

바이낸스 선물 시장에서는 이러한 유동성 휩쓸기(Liquidity Sweep)가 '청산 맵(Liquidation Heatmap)' 상에서 밝은 색상으로 표시되는 지점에서 주로 발생한다.5 가격이 특정 저점을 살짝 이탈한 뒤 곧바로 강력하게 반등한다면, 이는 스마트 머니가 SSL을 성공적으로 흡수했음을 의미한다.10

## **시간과 가격의 결합: ICT 매매 모델**

ICT 이론의 정수는 가격뿐만 아니라 '시간'을 매매의 핵심 변수로 사용한다는 점이다. 알고리즘은 하루 중 특정 시간대에 가장 활발하게 작동하며, 이때의 움직임이 그날의 고점이나 저점을 형성할 확률이 매우 높다.13

### **파워 오브 쓰리(Power of Three: AMD)**

하루의 가격 형성을 세 단계로 나누는 모델이다. 이는 축적(Accumulation), 조작(Manipulation), 분배(Distribution)의 앞글자를 따서 AMD 모델이라고도 불린다.15

1. **축적(Accumulation):** 아시아 세션 동안 가격이 좁은 범위에서 횡보하며 유동성을 쌓는 단계이다.15  
2. **조작(Manipulation):** 런던 세션 개장 전후로 가격이 본래 가고자 하는 방향의 반대로 급격하게 움직여 개미들을 유인하고 손절을 유도하는 단계이다.15 이를 '유다 스윙(Judas Swing)'이라고 부른다.12  
3. **분배(Distribution):** 뉴욕 세션에서 본래의 의도된 방향으로 가격이 강력하게 확장되는 단계이다.15

바이낸스 트레이더는 아시아 세션의 범위를 설정하고, 런던 세션에서 그 범위의 고점이나 저점을 휩쓰는 조작이 나오는지를 관찰한 뒤, 뉴욕 세션에서 추세에 올라타는 전략을 구사한다.16

### **실전 필살기: 실버 불렛(Silver Bullet) 전략**

실버 불렛은 하루 중 딱 한 시간 동안 발생하는 알고리즘의 특정 패턴을 공략하는 전략이다. 이 시간대에는 유동성이 풍부하고 가격 전달이 매우 명확하게 일어난다.18

* **시간대(뉴욕 시간 EST 기준):**  
  * 런던 오픈: 오전 3:00 \~ 4:00 7  
  * 뉴욕 AM: 오전 10:00 \~ 11:00 7  
  * 뉴욕 PM: 오후 2:00 \~ 3:00 7

이 전략의 실행 지침은 간단하면서도 강력하다. 먼저 해당 시간대에 들어서면 인접한 유동성 목표(Liquidity Draw)를 확인한다. 이후 가격이 급격하게 움직이며 FVG를 형성하면, 그 FVG로 가격이 되돌아올 때 진입한다.18 바이낸스 비트코인 선물처럼 유동성이 풍부한 종목은 이 한 시간 동안만으로도 하루의 목표 수익을 충분히 달성할 수 있다.10

## **가상자산 특화 분석: SMT 다이버전스와 상관관계**

가상자산 시장에서 ICT 이론을 적용할 때 가장 강력한 확증 도구 중 하나는 스마트 머니 기법(Smart Money Technique, SMT) 다이버전스이다.21 이는 상관관계가 높은 두 자산(예: BTC와 ETH)의 가격 움직임이 일시적으로 어긋나는 현상을 포착하는 것이다.21

### **SMT 다이버전스의 메커니즘**

정상적인 시장 상황에서 비트코인과 이더리움은 같은 방향으로 움직인다. 그러나 반전 지점에서는 한 자산이 새로운 고점을 만들 때 다른 자산은 고점을 높이지 못하는 현상이 발생한다.21

* **하락 SMT(Bearish SMT):** 비트코인은 고점을 경신(Higher High)했지만, 이더리움은 고점을 경신하지 못하고 낮아지는(Lower High) 경우이다. 이는 시장 전체의 매수세가 약해졌음을 의미하며, 비트코인의 고점 돌파가 단순한 유동성 사냥(Liquidity Grab)이었을 가능성이 큼을 시사한다.23  
* **상승 SMT(Bullish SMT):** 비트코인은 저점을 경신(Lower Low)했지만, 이더리움은 저점을 높이는(Higher Low) 경우이다. 이는 이더리움에 강력한 기관 매집이 들어오고 있음을 나타내며, 곧 시장 전체가 반등할 것임을 암시한다.23

바이낸스 선물 트레이더는 두 차트를 동시에 띄워두고 중요 지지/저항선에서의 SMT 발생 여부를 확인하여 진입의 신뢰도를 높인다.23

## **바이낸스 선물 시장을 위한 고급 매매 체계**

바이낸스 무기한 선물(Perpetual Futures)은 24시간 거래되며 레버리지가 높다는 특수성이 있다. 따라서 전통적인 ICT 개념을 가상자산 시장에 맞게 최적화해야 한다.26

### **레버리지 및 증거금 관리의 수학적 접근**

레버리지는 수익을 극대화하지만, 동시에 작은 반대 움직임에도 청산될 위험을 내포한다. ICT 트레이더는 '청산 가격'을 단순히 피해야 할 지점이 아니라, 가격이 끌려가는 자석으로 이해한다.5

| 레버리지 | 필요 증거금 | 청산까지 필요한 가격 변동 | 위험 등급 |
| :---- | :---- | :---- | :---- |
| 5x | 20% | \-20% | 낮음 |
| 10x | 10% | \-10% | 보통 |
| 20x | 5% | \-5% | 높음 |
| 50x | 2% | \-2% | 매우 높음 |
| 100x | 1% | \-1% | 투기적 |

전문적인 매매를 위해서는 총 자산의 1\~2%만을 한 번의 거래에 리스크로 노출시키는 원칙을 엄격히 준수해야 한다.20 또한, 바이낸스의 격리(Isolated) 증거금 모드를 사용하여 특정 포지션의 실패가 전체 잔고로 전이되는 것을 방지하는 것이 권장된다.29

### **청산 맵(Liquidation Heatmap)의 활용**

바이낸스 스퀘어(Binance Square)와 같은 플랫폼에서 제공되는 청산 맵은 ICT의 유동성 개념을 시각화한 것이다.5 밝은 노란색이나 주황색으로 표시되는 구간은 고레버리지 포지션의 청산 물량이 대거 몰려 있는 곳이다. 가격이 이러한 '유동성 거품(Liquidity Bubbles)'에 도달하면 일시적인 청산 가스케이드(Cascade)가 발생하며 급격한 변동성이 나타난다.11 ICT 트레이더는 가격이 이 구간을 휩쓴 직후의 반전 패턴을 노려 정밀한 진입(Sniper Entry)을 시도한다.11

## **프리미엄 및 디스카운트(PD) 어레이 체계**

알고리즘이 가격을 효율적으로 전달하기 위해 사용하는 도구 세트를 PD 어레이라고 한다. 가격이 현재 범위의 상단 50%(Premium)에 있는지, 하단 50%(Discount)에 있는지에 따라 매매 전략이 완전히 달라진다.1

### **PD 어레이의 계층 구조**

트레이더는 특정 레인지를 설정한 후 피보나치 0.5 레벨을 기준으로 시장을 이분한다.1

* **프리미엄 구간:** 가격이 상대적으로 비싼 상태이다. 여기서는 매수 진입을 지양하고, 오더 블록이나 FVG를 활용한 매도 포지션을 탐색한다.1  
* **디스카운트 구간:** 가격이 싼 상태이다. 기관들은 여기서 매집을 시작하며, 트레이더는 하단부의 FVG나 오더 블록에서 매수 기회를 찾는다.1

피보나치 수열 중 0.618, 0.705, 0.79 구간은 최적 진입 구간(Optimal Trade Entry, OTE)으로 불리며, 이는 가격이 충분히 디스카운트되거나 프리미엄이 붙었음을 나타내는 지표로 활용된다.2

## **시장 조성자 모델(Market Maker Models: MMXM)**

MMXM은 가격이 한 유동성 지점에서 다른 유동성 지점으로 이동하는 전체적인 경로를 설명하는 가장 상위 단계의 모델이다.33 이는 크게 매수 모델(MMBM)과 매도 모델(MMSM)로 나뉜다.

### **시장 조성자 매수 모델(MMBM)의 단계**

1. **원천 축적(Original Consolidation):** 가격이 박스권에 머물며 초기 물량을 확보하는 단계이다.33  
2. **유동성 설계(Engineering Liquidity):** 의도적으로 저점을 낮추며 하락 추세를 형성하여 개인들의 매도를 유도한다.33  
3. **스마트 머니 반전(Smart Money Reversal):** 상위 프레임의 디스카운트 구간에 도달하여 MSS와 SMT 다이버전스가 발생하며 추세가 반전된다.33  
4. **재축적 및 확장:** 반등 과정에서 형성된 FVG와 오더 블록을 지지 삼아 원천 축적 단계의 고점을 향해 나아간다.33

바이낸스 선물 차트에서 이 모델을 이해하면 현재 가격이 단순한 조정인지, 아니면 전체적인 추세의 반전인지를 파악할 수 있는 거시적인 시각을 갖게 된다.33

## **실전 매매를 위한 필수 체크리스트 및 루틴**

성공적인 ICT 트레이딩은 매일 반복되는 체계적인 루틴에서 나온다.37

### **상위 프레임에서 하위 프레임으로의 분석 (HTF to LTF)**

1. **주봉 및 일봉 분석:** 전체적인 시장의 방향성(Daily Bias)을 설정한다. 이번 주 캔들이 양봉이 될지 음봉이 될지 예측하는 과정이다.36  
2. **4시간봉 및 1시간봉 분석:** 주요 지지/저항선과 미체결된 FVG, 오더 블록을 표시한다.37  
3. **15분봉 및 5분봉 분석:** 세션별 유동성 구간(Asia High/Low 등)을 설정하고 알고리즘의 움직임을 관찰한다.37  
4. **1분봉 진입:** 킬존(Killzone) 시간대에 맞춰 MSS가 발생하는지 확인하고 정밀하게 진입한다.7

### **매매 실행 체크리스트**

* 현재 시간이 실버 불렛 혹은 킬존 시간대인가? 18  
* 가격이 상위 프레임의 PD 어레이(FVG, OB)에 도달했는가? 1  
* 유동성 휩쓸기(Liquidity Sweep)가 발생했는가? 12  
* 하위 프레임에서 MSS와 Displacement가 확인되었는가? 9  
* 진입 지점이 프리미엄/디스카운트 관점에서 유리한가? 1  
* 손절가는 구조적 고점/저점 너머에 설정되었는가? 3

## **리스크 관리와 트레이더의 심리학**

ICT 매매는 기술적인 정교함만큼이나 철저한 자기 통제를 요구한다. 가상자산 시장의 높은 변동성은 트레이더의 감정을 자극하여 계획되지 않은 매매를 유도하기 때문이다.40

### **흔한 실패 원인과 극복 방법**

* **과도한 레버리지 사용:** 단기간에 큰 수익을 내려는 욕심은 필연적으로 청산으로 이어진다. 레버리지는 도구가 아니라 리스크 관리의 변수로 사용해야 한다.30  
* **뇌동매매(FOMO):** 가격이 급등할 때 뒤늦게 추격 매수하는 행위는 기관들의 분배(Distribution) 단계에서 물량을 받아주는 꼴이 된다. 반드시 가격이 FVG나 오더 블록으로 '되돌아올 때'까지 기다려야 한다.32  
* **손절매 부재:** 알고리즘은 가끔 예상치 못한 변수(뉴욕 시간 외 뉴스 등)에 의해 구조를 완전히 무시할 수 있다. 이때 손절매가 없다면 한 번의 거래로 계좌가 파괴될 수 있다.32

### **트레이딩 저널의 중요성**

모든 매매는 기록되어야 한다. 왜 해당 진입을 선택했는지, 그때의 감정 상태는 어떠했는지, 결과적으로 가격이 유동성 목표에 도달했는지를 복기해야 한다.32 ICT 이론을 마스터하는 데는 최소 2년 이상의 시간이 걸린다고 알려져 있으며, 이 기간을 버티게 해주는 것은 수익이 아니라 데이터에 기반한 시스템적 매매 경험이다.44

## **결론 및 제언**

바이낸스 무기한 선물 시장에서의 ICT 매매 기법은 단순한 지표 매매를 넘어 시장의 작동 원리를 이해하는 철학적인 접근이다.4 가격은 우연히 움직이는 것이 아니라, 유동성을 확보하고 불균형을 해소하기 위한 명확한 목적을 가지고 움직인다.2

본 보고서에서 제시한 AMD 모델, 실버 불렛 전략, SMT 다이버전스, 그리고 PD 어레이 체계를 바이낸스의 실시간 데이터와 결합한다면, 개인 투자자도 기관의 움직임에 동참할 수 있는 강력한 무기를 갖게 될 것이다.8 그러나 가장 중요한 것은 기술이 아니라 규율이다. 킬존 시간에만 차트를 보고, 정해진 셋업이 나왔을 때만 진입하며, 리스크 원칙을 칼같이 지키는 트레이더만이 이 거대한 유동성의 바다에서 생존하고 승리할 수 있다.14 가상자산 시장의 미래는 더욱 알고리즘화될 것이며, ICT 이론은 그 미래를 항해하는 가장 정교한 나침반이 될 것이다.1

#### **참고 자료**

1. PD Arrays in ICT: What They Are and How They Work | Market Pulse \- FXOpen UK, 12월 29, 2025에 액세스, [https://fxopen.com/blog/en/what-is-a-pd-array-in-ict-and-how-can-you-use-it-in-trading/](https://fxopen.com/blog/en/what-is-a-pd-array-in-ict-and-how-can-you-use-it-in-trading/)  
2. ICT TRADING STRATEGY \[PDF\] \- HowToTrade, 12월 29, 2025에 액세스, [https://howtotrade.com/wp-content/uploads/2023/11/ICT-Trading-Strategy-1.pdf](https://howtotrade.com/wp-content/uploads/2023/11/ICT-Trading-Strategy-1.pdf)  
3. Key ICT Concepts \- TradeZella, 12월 29, 2025에 액세스, [https://www.tradezella.com/learning-items/key-ict-concepts](https://www.tradezella.com/learning-items/key-ict-concepts)  
4. ICT Trading Concepts Overview \- Coconote, 12월 29, 2025에 액세스, [https://coconote.app/notes/8dd31b5b-90cc-4bf1-b108-af82d1784fbc](https://coconote.app/notes/8dd31b5b-90cc-4bf1-b108-af82d1784fbc)  
5. How to use Coinglass to view the liquidation heatmap? | 无秋 on ..., 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/29660463048473](https://www.binance.com/en/square/post/29660463048473)  
6. Ict | PDF | Market Trend | Market Liquidity \- Scribd, 12월 29, 2025에 액세스, [https://www.scribd.com/document/890183464/Ict](https://www.scribd.com/document/890183464/Ict)  
7. The ICT Silver Bullet Trading Strategy: Mechanics and Application | Market Pulse, 12월 29, 2025에 액세스, [https://fxopen.com/blog/en/what-is-the-ict-silver-bullet-strategy-and-how-does-it-work/](https://fxopen.com/blog/en/what-is-the-ict-silver-bullet-strategy-and-how-does-it-work/)  
8. Mastering ICT Concepts: The Ultimate Trading Strategy Guide for ..., 12월 29, 2025에 액세스, [https://www.tradingview.com/chart/BTCUSDT.P/XrrOfC4G-Mastering-ICT-Concepts-The-Ultimate-Trading-Strategy-Guide/](https://www.tradingview.com/chart/BTCUSDT.P/XrrOfC4G-Mastering-ICT-Concepts-The-Ultimate-Trading-Strategy-Guide/)  
9. ICT Silver Bullet Setup & Trading Methods \- LuxAlgo, 12월 29, 2025에 액세스, [https://www.luxalgo.com/blog/ict-silver-bullet-setup-trading-methods/](https://www.luxalgo.com/blog/ict-silver-bullet-setup-trading-methods/)  
10. ICT Silver Bullet Strategy Explained: How to Identify and Trade It \- Flux Charts, 12월 29, 2025에 액세스, [https://www.fluxcharts.com/articles/trading-strategies/ict-strategies/ict-silver-bullet](https://www.fluxcharts.com/articles/trading-strategies/ict-strategies/ict-silver-bullet)  
11. “How to trade Liquidity” | Tracer on Binance Square, 12월 29, 2025에 액세스, [https://www.binance.com/en-AE/square/post/12952389375497](https://www.binance.com/en-AE/square/post/12952389375497)  
12. Top 5 ICT Trading Strategies for New and Pros \- B2PRIME, 12월 29, 2025에 액세스, [https://b2prime.com/news/top-5-ict-trading-strategies-for-new-and-pros](https://b2prime.com/news/top-5-ict-trading-strategies-for-new-and-pros)  
13. ICT SILVER BULLET TRADING STRATEGY \[PDF\] | HowToTrade, 12월 29, 2025에 액세스, [https://howtotrade.com/wp-content/uploads/2024/04/ICT-Silver-Bullet-Trading-Strategy.pdf](https://howtotrade.com/wp-content/uploads/2024/04/ICT-Silver-Bullet-Trading-Strategy.pdf)  
14. What Are ICT Killzone Times? Simple Trading Hours Guide \- EBC Financial Group, 12월 29, 2025에 액세스, [https://www.ebc.com/forex/what-are-ict-killzone-times-simple-trading-hours-guide](https://www.ebc.com/forex/what-are-ict-killzone-times-simple-trading-hours-guide)  
15. ICT Power of Three Strategy Explained: How to Identify and Trade It \- Flux Charts, 12월 29, 2025에 액세스, [https://www.fluxcharts.com/articles/trading-strategies/ict-strategies/ict-power-of-three](https://www.fluxcharts.com/articles/trading-strategies/ict-strategies/ict-power-of-three)  
16. ICT Power of 3 (PO3): What It Is and How to Trade It \- XS, 12월 29, 2025에 액세스, [https://www.xs.com/en/blog/ict-power-of-3-po3/](https://www.xs.com/en/blog/ict-power-of-3-po3/)  
17. Intraday Kill Zones and Silver Bullet | Coconote, 12월 29, 2025에 액세스, [https://coconote.app/notes/64e7f551-19dc-40e5-aa96-a681a88570f7](https://coconote.app/notes/64e7f551-19dc-40e5-aa96-a681a88570f7)  
18. Master ICT Silver Bullet Strategy – Step by Step Guide for 2025 \- ICT Trading, 12월 29, 2025에 액세스, [https://innercircletrader.net/tutorials/ict-silver-bullet-strategy/](https://innercircletrader.net/tutorials/ict-silver-bullet-strategy/)  
19. What Is the ICT Silver Bullet? Meaning, Rules, and Examples | EBC Financial Group, 12월 29, 2025에 액세스, [https://www.ebc.com/forex/what-is-the-ict-silver-bullet-meaning-rules-and-examples](https://www.ebc.com/forex/what-is-the-ict-silver-bullet-meaning-rules-and-examples)  
20. ICT Silver Bullet | PDF | Day Trading | Financial Markets \- Scribd, 12월 29, 2025에 액세스, [https://www.scribd.com/document/899910422/ICT-Silver-Bullet-4](https://www.scribd.com/document/899910422/ICT-Silver-Bullet-4)  
21. How to Identify and Use SMT Divergence in Trading \- FundYourFX, 12월 29, 2025에 액세스, [https://fundyourfx.com/mastering-smt-divergence-in-trading/](https://fundyourfx.com/mastering-smt-divergence-in-trading/)  
22. SMT Divergence Simply Explained (ICT), Powerful Results \- YouTube, 12월 29, 2025에 액세스, [https://www.youtube.com/watch?v=TuydTHPr120](https://www.youtube.com/watch?v=TuydTHPr120)  
23. SMT (Smart Money Technique) Guide for Futures Trading 2025 \- Phemex, 12월 29, 2025에 액세스, [https://phemex.com/academy/what-is-smt-smart-money-technique-guide-futures-trading](https://phemex.com/academy/what-is-smt-smart-money-technique-guide-futures-trading)  
24. Bitcoin \- Ethereum SMT Divergence: What Is It & How to Use It | Bitsgap blog, 12월 29, 2025에 액세스, [https://bitsgap.com/blog/bitcoin-ethereum-smt-divergence-what-is-it-how-to-use-it](https://bitsgap.com/blog/bitcoin-ethereum-smt-divergence-what-is-it-how-to-use-it)  
25. What Is SMT Divergence, and How Can Traders Use It? | Market Pulse \- FXOpen UK, 12월 29, 2025에 액세스, [https://fxopen.com/blog/en/what-is-smt-divergence-and-how-can-you-use-it-in-trading/](https://fxopen.com/blog/en/what-is-smt-divergence-and-how-can-you-use-it-in-trading/)  
26. How to Use Killzones in Your Crypto Trading Strategy | Callistemon on Binance Square, 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/14521834223058](https://www.binance.com/en/square/post/14521834223058)  
27. Advanced Guide to Margin Trading with Crypto Derivatives: Risks and Rewards | Coinbase, 12월 29, 2025에 액세스, [https://www.coinbase.com/learn/futures/advanced-guide-to-margin-trading-with-crypto-derivatives](https://www.coinbase.com/learn/futures/advanced-guide-to-margin-trading-with-crypto-derivatives)  
28. Crypto Futures Risk Management Guide – The Secret to Protecting Capital | Dyan Le BNB on Binance Square, 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/17736618433209](https://www.binance.com/en/square/post/17736618433209)  
29. Crypto Leverage Trading for Beginners: How It Works and What to Watch Out For \- Changelly, 12월 29, 2025에 액세스, [https://changelly.com/blog/what-is-crypto-leverage-trading/](https://changelly.com/blog/what-is-crypto-leverage-trading/)  
30. The Dangers of High-Leverage Trading: Lessons from My Binance Liquidation Experience, 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/20966019978193](https://www.binance.com/en/square/post/20966019978193)  
31. What is Liquidation Heatmap & Chart? A Must-Know for Traders | CoinRank on Binance Square, 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/27595064191602](https://www.binance.com/en/square/post/27595064191602)  
32. 7 Common Trading Strategy Mistakes (And How to Avoid | frajes trading on Binance Square, 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/26832460983977](https://www.binance.com/en/square/post/26832460983977)  
33. Mastering ICT Market Maker Buy Model | PDF \- Scribd, 12월 29, 2025에 액세스, [https://www.scribd.com/document/789983292/ICT-Market-Maker-Buy-Model-PDF-Download](https://www.scribd.com/document/789983292/ICT-Market-Maker-Buy-Model-PDF-Download)  
34. Master the Market with the ICT Strategy Trade like insti | thecryptoguy\_0199 on Binance Square, 12월 29, 2025에 액세스, [https://www.binance.com/en-IN/square/post/24737359650585](https://www.binance.com/en-IN/square/post/24737359650585)  
35. NoteGPT \- ICT Mentorship 2023 \- Market Maker Models | PDF \- Scribd, 12월 29, 2025에 액세스, [https://www.scribd.com/document/896137179/NoteGPT-ICT-Mentorship-2023-Market-Maker-Models](https://www.scribd.com/document/896137179/NoteGPT-ICT-Mentorship-2023-Market-Maker-Models)  
36. ICT Trading Simplified: A Step-by-Step Guide to a Clear Strategy Highly Profit Strategy | Trading Heights on Binance Square, 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/12292418467337](https://www.binance.com/en/square/post/12292418467337)  
37. ICT Execution Checklist | PDF \- Scribd, 12월 29, 2025에 액세스, [https://www.scribd.com/document/868030345/ICT-Execution-Checklist](https://www.scribd.com/document/868030345/ICT-Execution-Checklist)  
38. Timeframe Alignment Tips for New Traders Starting your | Cryptoalrts on Binance Square, 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/15994830471689](https://www.binance.com/en/square/post/15994830471689)  
39. What is Accumulation Manipulation Distribution – ICT Power of 3 ..., 12월 29, 2025에 액세스, [https://innercircletrader.net/tutorials/ict-power-of-3/](https://innercircletrader.net/tutorials/ict-power-of-3/)  
40. Why 90% of ICT Traders Fail (And the Mindset Shift to Win in Crypto) \- Altrady, 12월 29, 2025에 액세스, [https://www.altrady.com/blog/crypto-trading-strategies/ict-trading-strategy-why-most-ict-traders-fail](https://www.altrady.com/blog/crypto-trading-strategies/ict-trading-strategy-why-most-ict-traders-fail)  
41. Common Mistakes Made When Trading Crypto Futures and How to Overcome Them, 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/20300673140689](https://www.binance.com/en/square/post/20300673140689)  
42. Top Mistakes Crypto Traders Make in Funded Challenges, 12월 29, 2025에 액세스, [https://www.fortraders.com/blog/top-mistakes-crypto-traders-make-in-funded-challenges](https://www.fortraders.com/blog/top-mistakes-crypto-traders-make-in-funded-challenges)  
43. \#TradeLessons \*5 Common Mistakes in Futures Trading\*\* 1\. | AYECHANAUNG1992 on Binance Square, 12월 29, 2025에 액세스, [https://www.binance.com/en/square/post/24223662656226](https://www.binance.com/en/square/post/24223662656226)  
44. How to determine draw on liquidity? ICT Silverbullet strategy : r/FuturesTrading \- Reddit, 12월 29, 2025에 액세스, [https://www.reddit.com/r/FuturesTrading/comments/14wygx2/how\_to\_determine\_draw\_on\_liquidity\_ict/](https://www.reddit.com/r/FuturesTrading/comments/14wygx2/how_to_determine_draw_on_liquidity_ict/)