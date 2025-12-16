
import asyncio
import logging
import sys
import os
from pathlib import Path

# 프로젝트 루트 디렉토리를 파이썬 경로에 추가 (scripts 폴더에서 실행 시 src 모듈 인식을 위해)
# 현재 파일(scripts/simple_btc_stream.py)의 부모(scripts)의 부모(project_root)
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from src.core.data_collector import BinanceDataCollector
from src.models.candle import Candle

# 로깅 설정: 보기 편한 시간 포맷 사용
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)

# 불필요한 라이브러리 로그 줄이기
logging.getLogger("binance.websocket").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

def print_candle_info(candle: Candle) -> None:
    """캔들 데이터가 도착할 때마다 호출되는 함수"""
    status = "🔴 확정(Closed)" if candle.is_closed else "🟢 진행중"
    
    # 가독성 좋은 출력 포맷
    print(
        f"[{candle.close_time.strftime('%H:%M:%S')}] "
        f"{candle.symbol} {candle.interval} | "
        f"종가: {candle.close:10.2f} | "
        f"거래량: {candle.volume:10.3f} | {status}"
    )

async def main():
    print("=" * 60)
    print("🚀 ZECUSDT 1분봉 실시간 수신 테스트 (Binance Mainnet)")
    print("종료하려면 터미널에서 Ctrl+C를 누르세요.")
    print("=" * 60)

    # 1. 수집기 초기화
    # 단순 실시간 시세 수신(Public Stream)은 실제 API Key가 없어도 작동하는 경우가 많지만,
    # 라이브러리 요구사항을 맞추기 위해 더미 값을 넣습니다.
    # 만약 에러가 난다면 api_keys.ini의 실제 Testnet 키를 사용하세요.
    collector = BinanceDataCollector(
        api_key="DUMMY_KEY",
        api_secret="DUMMY_SECRET",
        symbols=["ZECUSDT"],
        intervals=["1m"],
        is_testnet=False,
        on_candle_callback=print_candle_info
    )

    try:
        # 2. 스트리밍 시작
        await collector.start_streaming()
        print("📡 웹소켓 연결 성공! 데이터 수신 대기중...\n")

        # 3. 무한 대기 (프로그램 종료 방지)
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n👋 사용자 요청으로 종료합니다.")
    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
    finally:
        # 4. 안전한 종료 처리
        print("시스템 종료 중...")
        await collector.stop()
        print("시스템이 안전하게 종료되었습니다.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # 윈도우 등에서 발생할 수 있는 이벤트 루프 강제 종료 에러 방지
        pass
