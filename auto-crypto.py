import pyupbit
import pandas as pd
import time
import datetime

ACCESS = ""
SECRET = ""
upbit = pyupbit.Upbit(ACCESS, SECRET)

krw = upbit.get_balance("KRW")
print("KRW 잔고 조회 결과:", krw)

# ✅ 시가총액 상위 5개 코인만 대상으로 지정
all_tickers = [
    "KRW-BTC",    # 비트코인
    "KRW-ETH",    # 이더리움
    "KRW-XRP",    # 리플
    "KRW-SOL",   # 솔라나
    "KRW-DOGE",   # 도지코인
    "KRW-ADA",  # 에이다
    "KRW-ETC"     # 이더리움 클래식
]

# ✅ 코인별 포지션 상태 초기화
positions = {
    ticker: {
        "buy_price": None,
        "buy_time": None,
        "sold_half": False,
        "max_profit": 0.0,
        "drop_start_time": None,
        "profit_history": [],
        "stoploss_cooldown_bars": 0  # 봉 개수 카운터
    } for ticker in all_tickers
}

import json
import os

POSITIONS_FILE = "positions.json"

def update_stoploss_cooldown():
    for ticker in all_tickers:
        if positions[ticker]["stoploss_cooldown_bars"] > 0:
            positions[ticker]["stoploss_cooldown_bars"] -= 1
            if positions[ticker]["stoploss_cooldown_bars"] < 0:
                positions[ticker]["stoploss_cooldown_bars"] = 0

# ✅ 포지션 로드 함수
def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, "r") as f:
            data = json.load(f)
            for v in data.values():
                if v["buy_time"]:
                    v["buy_time"] = datetime.datetime.fromisoformat(v["buy_time"])
                if "stoploss_cooldown_bars" not in v:
                    v["stoploss_cooldown_bars"] = 0  # 기본값 추가
            return data
    return {
        ticker: {
            "buy_price": None,
            "buy_time": None,
            "sold_half": False,
            "max_profit": 0.0,
            "drop_start_time": None,
            "profit_history": [],
            "stoploss_cooldown_bars": 0
        } for ticker in all_tickers
    }

# ✅ 포지션 저장 함수
def save_positions():
    to_save = {}
    for k, v in positions.items():
        to_save[k] = v.copy()
        if to_save[k]["buy_time"]:
            to_save[k]["buy_time"] = to_save[k]["buy_time"].isoformat()
    with open(POSITIONS_FILE, "w") as f:
        json.dump(to_save, f, indent=2)

# ✅ 초기화 시 로드
positions = load_positions()

def get_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    
    
    return 100 - (100 / (1 + rs))


def check_signal(ticker):
    df = pyupbit.get_ohlcv(ticker, interval="minute30", count=100)
    if df is None or len(df) < 30:
        return "HOLD"

    # 쿨다운 봉 남아있으면 매수 금지
    if positions[ticker]["stoploss_cooldown_bars"] > 0:
        print(f"⛔ {ticker} 손절 후 {positions[ticker]['stoploss_cooldown_bars']}분봉 남아 진입 금지")
        return "HOLD"

    df['rsi'] = get_rsi(df)
    rsi = df['rsi'].iloc[-1]
    current_price = get_current_price(ticker)
    if current_price is None:
        return "HOLD"

    # 수익률 계산 (보유 중일 때만)
    rate = 0
    buy_price = positions[ticker].get("buy_price", 0)
    if buy_price:
        rate = ((current_price - buy_price) / buy_price) * 100

    # 매수 조건
    if rsi < 30:
        return "BUY"

    # 매도 조건: RSI > 70 + 수익률 >= 1%
    elif rsi >= 70 and rate >= 1.0:
        return "SELL"

    return "HOLD"


def get_current_price(ticker):
    return pyupbit.get_current_price(ticker)

def buy(ticker):
    krw = upbit.get_balance("KRW")
    if krw is None:
        print("⚠️ 잔고 정보를 불러오지 못했습니다.")
        return

    # 현재 포지션이 비어 있는 코인 수 기준으로 분배
    empty_positions = [t for t in all_tickers if positions[t]["buy_price"] is None]
    if len(empty_positions) == 0:
        print("⚠️ 매수 가능한 코인이 없습니다.")
        return

    if krw > 5000:
        amount = krw * 0.9995 / len(empty_positions)
        upbit.buy_market_order(ticker, amount)
        price = get_current_price(ticker)
        positions[ticker]["buy_price"] = price
        positions[ticker]["buy_time"] = datetime.datetime.now()
        positions[ticker]["sold_half"] = False
        print(f"🟢 매수: {ticker} @ {price:.0f}")
        save_positions()  # ✅ 저장

def sell(ticker, ratio=1.0):
    coin_balance = upbit.get_balance(ticker)
    if coin_balance and coin_balance > 0.0001:
        upbit.sell_market_order(ticker, coin_balance * ratio * 0.9995)
        if ratio == 1.0:
            # 손절 판단을 위해 가격 비교 후 쿨다운 초기화
            price = get_current_price(ticker)
            buy_price = positions[ticker]["buy_price"]
            loss_rate = (price - buy_price) / buy_price * 100 if buy_price else 0

            if loss_rate <= -10:
                positions[ticker]["stoploss_cooldown_bars"] = 1440  # 24시간 = 1440분봉

            positions[ticker]["buy_price"] = None
            positions[ticker]["buy_time"] = None
            positions[ticker]["sold_half"] = False
            positions[ticker]["max_profit"] = 0.0
            positions[ticker]["drop_start_time"] = None
            positions[ticker]["profit_history"].clear()
            print(f"🔴 전량 매도: {ticker}")
            save_positions()
        else:
            positions[ticker]["sold_half"] = True
            print(f"🟠 절반 매도: {ticker}")
            save_positions()
            

def check_profit_or_loss(ticker):
    p = positions[ticker]
    if p["buy_price"] is None:
        return
    current_price = get_current_price(ticker)
    rate = (current_price - p["buy_price"]) / p["buy_price"] * 100

    if rate <= -10:
        sell(ticker, 1.0)
    elif rate <= -5 and not p["sold_half"]:
        sell(ticker, 0.5)
    
def check_volatility_drop(ticker):
    p = positions[ticker]
    if p["buy_price"] is None:
        return

    current_price = get_current_price(ticker)
    current_profit = (current_price - p["buy_price"]) / p["buy_price"] * 100

    # 🔹 수익률 기록 (최대 10개 유지 = 10초 추정)
    p["profit_history"].append(current_profit)
    if len(p["profit_history"]) > 10:
        p["profit_history"].pop(0)

    # 🔹 변동률 체크
    if len(p["profit_history"]) >= 10:
        max_profit = max(p["profit_history"])
        min_profit = min(p["profit_history"])
        if max_profit - min_profit >= 5:
            sell(ticker, 1.0)
            print(f"⚠️ 10초 내 수익률 변동 5% 이상 감지 → 전량 매도: {ticker}")
            p["profit_history"].clear()  # 초기화
            
def log(msg):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}")

# 🔁 메인 루프
import time
import datetime

last_signal_check = time.time()

while True:
    try:
        now = time.time()

        for ticker in all_tickers:
            # 🔹 실시간 대응용 로직 (1초마다 실행)
            check_volatility_drop(ticker)
            check_profit_or_loss(ticker)

        # 🔹 매수/매도 로직은 60초마다 실행
        if now - last_signal_check >= 60:
            update_stoploss_cooldown()
            for ticker in all_tickers:
                signal = check_signal(ticker)

                if signal == "BUY" and positions[ticker]["buy_price"] is None:
                    buy(ticker)

                elif signal == "SELL" and positions[ticker]["buy_price"] is not None:
                    sell(ticker, 1.0)

            last_signal_check = now

        # 🔹 전체 루프 딜레이 (1초)
        time.sleep(1)

    except Exception as e:
        print("⚠️ 오류:", e)
        time.sleep(5)
        