#!/usr/bin/env python
# coding: utf-8

__author__ = "Alireza Sadabadi"
__copyright__ = "Copyright (c) 2026 Alireza Sadabadi. All rights reserved."
__credits__ = ["Alireza Sadabadi"]
__license__ = "Apache"
__version__ = "3.0"
__maintainer__ = "Alireza Sadabadi"
__email__ = "alirezasadabady@gmail.com"
__status__ = "Test"
__doc__ = "you can see the tutorials in https://youtube.com/@alirezasadabadi?si=d8o7LK_Ai1Hf68is"

import MetaTrader5 as mt5
from datetime import datetime, timezone, time, timedelta
import time as time_module
from Meta import *
from colorama import init as colorama_init
from colorama import Fore
from colorama import Style
import socket
import sys
import json
import urllib.request
import pandas as pd
import numpy as np

colorama_init()

# ============================================================
# MT5 INITIALIZE
# ============================================================

if not mt5.initialize():
    print("initialize() failed, error code =", mt5.last_error())
    mt5.shutdown()
    quit()

# ============================================================
# INTERNET CHECK
# ============================================================

def internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        ).connect((host, port))
        return True

    except socket.error:
        print("@", end="")
        sys.stdout.flush()
        return False

# ------------------------------------------------------------
# Trading
# ------------------------------------------------------------

MAGIC = 8
LOT = 0.01

# ------------------------------------------------------------
# Balance-based lot factor
#
# Same logic as the backtest: lot size steps up +0.01 for
# every extra $100 of current account balance
# ($100-$200 -> 0.01, $200-$300 -> 0.02, ...). Recalculated
# fresh from the live account balance right before every
# order is placed.
# ------------------------------------------------------------

BALANCE_STEP_SIZE = 100.0

BASE_LOT = 0.01

def get_lot_size(current_balance):

    steps = int(
        current_balance
        //
        BALANCE_STEP_SIZE
    )

    steps = max(steps, 1)

    return round(
        steps * BASE_LOT,
        2
    )

LOOP_SECONDS = 3

# ============================================================
# SYMBOLS
# ============================================================

symbols_list = {
    "XAUUSD_o": ["XAUUSD_o", LOT],
}

# ============================================================
# SETTINGS
# ============================================================

SYMBOL = "XAUUSD_o"
TIMEFRAME = mt5.TIMEFRAME_M1
NUMBER_OF_DATA = 500

SPIKE_CANDLE_SIZE = 0.9

PGAP_POINTS = 100
MAX_SL_DISTANCE_POINTS = 500
MAX_SPREAD_POINTS = 30

TP_R = 1.0

# ============================================================
# ACCOUNT INFORMATION
# ============================================================

accountInfo = mt5.account_info()

print("-" * 75)

if accountInfo is not None:

    print(
        f"Login: {accountInfo.login}"
        f"\tserver: {accountInfo.server}"
        f"\tleverage: {accountInfo.leverage}"
    )

    print(
        f"Balance: {accountInfo.balance}"
        f"\tEquity: {accountInfo.equity}"
        f"\tProfit: {accountInfo.profit}"
    )

    tick = mt5.symbol_info_tick(SYMBOL)

    broker_time_str = (
        datetime.fromtimestamp(tick.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if tick is not None
        else "N/A"
    )

    print(
        "Running from(Broker time)      :",
        broker_time_str
    )

print("-" * 75)

# ============================================================
# SYMBOL INFORMATION
# ============================================================

symbol_info = mt5.symbol_info(SYMBOL)

if symbol_info is None:
    mt5.shutdown()
    raise RuntimeError(
        f"Could not get symbol information for {SYMBOL}"
    )

BROKER_POINT = float(symbol_info.point)
DIGITS = int(symbol_info.digits)

if BROKER_POINT <= 0:
    mt5.shutdown()
    raise RuntimeError("Invalid broker point.")

P_GAP_PRICE = PGAP_POINTS * BROKER_POINT

MAX_SL_DISTANCE_PRICE = MAX_SL_DISTANCE_POINTS * BROKER_POINT

def get_spread_points(symbol):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return (tick.ask - tick.bid) / BROKER_POINT

# ------------------------------------------------------------
# Second entry
# ------------------------------------------------------------

USE_SECOND_ENTRY = False

SECOND_ENTRY_VOLUME_MULTIPLIER = 2.0

# ------------------------------------------------------------
# EMA filter
# ------------------------------------------------------------

USE_EMA_FILTER = False

EMA_PERIOD = 60

# ------------------------------------------------------------
# Trend structure filter
# ------------------------------------------------------------

USE_TREND_FILTER = False

MAX_OPPOSITE_MOVES = 1

# ------------------------------------------------------------
# Range / ADX filter
# ------------------------------------------------------------

USE_RANGE_FILTER = False

ADX_PERIOD = 14
MIN_ADX = 20.0

# ------------------------------------------------------------
# Session filter (broker time)
#
# SESSION_START_HOUR / SESSION_END_HOUR are on the broker
# clock (same as candle timestamps), not New York time.
# End hour is exclusive: 01:00 <= t < 05:00 broker time.
# ------------------------------------------------------------

USE_SESSION_FILTER = False

SESSION_START_HOUR = 2
SESSION_END_HOUR = 23

# ------------------------------------------------------------
# News filter
#
# Imports this week's high-impact events from the Forex
# Factory calendar feed. Times are converted into broker
# time (BROKER_TIMEZONE) so they match candle timestamps.
#
# Around each imported event:
#   - new entries are blocked
#   - an already-open position is force-closed in the
#     minutes BEFORE the release
# ------------------------------------------------------------

USE_NEWS_FILTER = True

NEWS_BUFFER_MINUTES = 5

NEWS_CALENDAR_URL = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
)

# Gold reacts most to USD releases. Add "EUR", "GBP", ...
# if you also want those high-impact events to pause trading.
NEWS_COUNTRIES = {"USD"}

NEWS_IMPACTS = {"High"}

NEWS_REFRESH_SECONDS = 60 * 60

# Naive MT5 candle timestamps on this broker are GMT+3.
BROKER_TIMEZONE = "Etc/GMT-3"


def to_broker_naive(timestamp):

    ts = pd.Timestamp(timestamp)

    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")

    return (
        ts.tz_convert(BROKER_TIMEZONE)
        .tz_localize(None)
        .to_pydatetime()
        .replace(second=0, microsecond=0)
    )


def fetch_high_impact_news():

    request = urllib.request.Request(
        NEWS_CALENDAR_URL,
        headers={
            "User-Agent": "SP2L-Advanced-Bot/3.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=10
    ) as response:

        payload = json.loads(
            response.read().decode("utf-8")
        )

    events = []
    news_times = []
    seen_times = set()

    for item in payload:

        impact = str(
            item.get("impact", "")
        ).strip()

        country = str(
            item.get("country", "")
        ).strip().upper()

        if impact not in NEWS_IMPACTS:
            continue

        if country not in NEWS_COUNTRIES:
            continue

        date_str = item.get("date")

        if not date_str:
            continue

        try:
            broker_time = to_broker_naive(date_str)
        except (TypeError, ValueError):
            continue

        title = str(
            item.get("title", "")
        ).strip()

        events.append(
            {
                "time": broker_time,
                "country": country,
                "impact": impact,
                "title": title
            }
        )

        if broker_time not in seen_times:
            seen_times.add(broker_time)
            news_times.append(broker_time)

    events.sort(key=lambda e: e["time"])
    news_times.sort()

    return events, news_times


def load_news_from_calendar():

    try:

        events, news_times = fetch_high_impact_news()

        print(
            f"{Fore.CYAN}"
            f"Loaded {len(events)} high-impact news event(s) "
            f"from the calendar."
            f"{Style.RESET_ALL}"
        )

        for event in events:

            print(
                "  ",
                event["time"].strftime("%Y-%m-%d %H:%M"),
                event["country"],
                event["title"]
            )

        return events, news_times

    except Exception as e:

        print(
            f"{Fore.YELLOW}"
            f"Could not import news calendar: {str(e)}"
            f"{Style.RESET_ALL}"
        )

        return [], []


NEWS_EVENTS, NEWS_TIMES = load_news_from_calendar()
last_news_refresh = time_module.time()


def refresh_news_if_needed():

    global NEWS_EVENTS, NEWS_TIMES, last_news_refresh

    if (
        time_module.time() - last_news_refresh
        <
        NEWS_REFRESH_SECONDS
    ):
        return

    events, news_times = load_news_from_calendar()

    if events or news_times:

        NEWS_EVENTS = events
        NEWS_TIMES = news_times

    last_news_refresh = time_module.time()

def is_near_news_time(
    current_time,
    buffer_minutes=NEWS_BUFFER_MINUTES
):

    if not USE_NEWS_FILTER:
        return False

    if not NEWS_TIMES:
        return False

    current_time = pd.Timestamp(current_time)

    buffer = timedelta(minutes=buffer_minutes)

    for news_time in NEWS_TIMES:

        news_time = pd.Timestamp(news_time)

        if (news_time - buffer) <= current_time <= (news_time + buffer):
            return True

    return False

def is_within_pre_news_window(
    current_time,
    buffer_minutes=NEWS_BUFFER_MINUTES
):
    """
    True only during the BEFORE side of the news window - used
    to force-close an already-open position ahead of the news,
    as opposed to is_near_news_time() which covers both sides
    and is used to block new entries.
    """

    if not USE_NEWS_FILTER:
        return False

    if not NEWS_TIMES:
        return False

    current_time = pd.Timestamp(current_time)

    buffer = timedelta(minutes=buffer_minutes)

    for news_time in NEWS_TIMES:

        news_time = pd.Timestamp(news_time)

        if (news_time - buffer) <= current_time < news_time:
            return True

    return False

def get_current_broker_time(symbol):
    """
    Naive datetime matching the same wall-clock convention used
    everywhere else in this script (candle timestamps,
    NEWS_TIMES) - broker server time, not local PC time or
    true UTC.
    """

    tick = mt5.symbol_info_tick(symbol)

    if tick is None:
        return None

    return datetime.fromtimestamp(
        tick.time,
        tz=timezone.utc
    ).replace(tzinfo=None)

# ============================================================
# PRINT SETTINGS
# ============================================================

print("-" * 75)
print("ADVANCED SP2L TRADER")
print("-" * 75)
print("Symbol              :", SYMBOL)
print("Point               :", BROKER_POINT)
print("Digits              :", DIGITS)
print("Current spread      :", round(get_spread_points(SYMBOL)))
print("Spike multiplier    :", SPIKE_CANDLE_SIZE)
print("Gap points          :", PGAP_POINTS)
print("Max SL points       :", MAX_SL_DISTANCE_POINTS)
print("Max spread points   :", MAX_SPREAD_POINTS)
print("TP                  :", f"{TP_R}R")
print("Second entry        :", USE_SECOND_ENTRY)
print("Second entry volume :", SECOND_ENTRY_VOLUME_MULTIPLIER)
print("EMA filter          :", USE_EMA_FILTER)
print("EMA period          :", EMA_PERIOD)
print("Trend filter        :", USE_TREND_FILTER)
print("Max opposite moves  :", MAX_OPPOSITE_MOVES)
print("Range filter        :", USE_RANGE_FILTER)
print("ADX period          :", ADX_PERIOD)
print("Minimum ADX         :", MIN_ADX)
print("Session filter      :", USE_SESSION_FILTER)
print("Session clock       :", "broker time")
print(
    "Session             :",
    f"{SESSION_START_HOUR:02d}:00 - {SESSION_END_HOUR:02d}:00"
)
print("News filter         :", USE_NEWS_FILTER)
print("News source         :", "Forex Factory calendar")
print("News countries      :", ", ".join(sorted(NEWS_COUNTRIES)))
print("News impact         :", ", ".join(sorted(NEWS_IMPACTS)))
print("News buffer         :", f"{NEWS_BUFFER_MINUTES} min")
print("News events loaded  :", len(NEWS_TIMES))
print("Magic               :", MAGIC)
print("Balance step size   :", BALANCE_STEP_SIZE)
print(
    "Starting lot        :",
    get_lot_size(accountInfo.balance)
    if accountInfo is not None
    else BASE_LOT,
    f"(at ${accountInfo.balance:.2f} balance)"
    if accountInfo is not None
    else ""
)
print("-" * 75)

# ============================================================
# EMA
# ============================================================

def calculate_ema(data):
    return (
        data["close"]
        .ewm(
            span=EMA_PERIOD,
            adjust=False
        )
        .mean()
    )

# ============================================================
# ADX
# ============================================================

def calculate_adx(data, period):

    high = data["high"]
    low = data["low"]
    close = data["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where(
            (up_move > down_move) & (up_move > 0),
            up_move,
            0.0
        ),
        index=data.index
    )

    minus_dm = pd.Series(
        np.where(
            (down_move > up_move) & (down_move > 0),
            down_move,
            0.0
        ),
        index=data.index
    )

    previous_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs()
        ],
        axis=1
    ).max(axis=1)

    atr = tr.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    plus_di = (
        100
        *
        plus_dm.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()
        /
        atr
    )

    minus_di = (
        100
        *
        minus_dm.ewm(
            alpha=1 / period,
            adjust=False
        ).mean()
        /
        atr
    )

    denominator = plus_di + minus_di

    dx = (
        100
        *
        (plus_di - minus_di).abs()
        /
        denominator.replace(0, np.nan)
    )

    adx = dx.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    return adx

# ============================================================
# SESSION (BROKER TIME)
# ============================================================

def is_in_session(timestamp):

    if pd.isna(timestamp):
        return False

    ts = pd.Timestamp(timestamp)

    candle_time = ts.time()

    start_time = time(
        SESSION_START_HOUR,
        0
    )

    end_time = time(
        SESSION_END_HOUR,
        0
    )

    return (
        start_time
        <=
        candle_time
        <
        end_time
    )

# ============================================================
# GET MARKET DATA
# ============================================================

def get_data(symbol):

    try:

        data = Meta.GetRates(
            symbol,
            NUMBER_OF_DATA,
            timeFrame=TIMEFRAME
        ).copy()

        if data.empty:
            print("No data received")
            return None

        data.columns = [
            str(c).lower()
            for c in data.columns
        ]

        required = [
            "open",
            "high",
            "low",
            "close"
        ]

        for col in required:

            if col not in data.columns:

                print(
                    f"Missing required column: {col}"
                )

                return None

        for col in required:

            data[col] = pd.to_numeric(
                data[col],
                errors="coerce"
            )

        data.dropna(
            subset=required,
            inplace=True
        )

        if not isinstance(
            data.index,
            pd.DatetimeIndex
        ):

            possible_time_columns = [
                "time",
                "datetime",
                "date",
                "local time"
            ]

            found_time = None

            for c in possible_time_columns:

                if c in data.columns:
                    found_time = c
                    break

            if found_time is not None:

                data[found_time] = pd.to_datetime(
                    data[found_time]
                )

                data.set_index(
                    found_time,
                    inplace=True
                )

        data.sort_index(
            inplace=True
        )

        data["EMA"] = calculate_ema(data)

        if USE_RANGE_FILTER:

            data["ADX"] = calculate_adx(
                data,
                ADX_PERIOD
            )

        else:

            data["ADX"] = np.nan

        return data

    except BaseException as e:

        print(
            "An exception has occurred in "
            f"AdvancedSP2LTrader.GetRates: {str(e)}"
        )

        return None

# ============================================================
# ENTRY FILTERS
# ============================================================

def entry_filters_are_valid(
    data,
    entry_pos,
    direction
):

    entry_idx = data.index[entry_pos]

    # --------------------------------------------------------
    # EMA FILTER
    # --------------------------------------------------------

    if USE_EMA_FILTER:

        entry_close = float(
            data.iloc[entry_pos]["close"]
        )

        entry_ema = float(
            data.iloc[entry_pos]["EMA"]
        )

        if not np.isfinite(entry_ema):
            return False

        if direction == "BUY":

            if entry_close <= entry_ema:
                return False

        else:

            if entry_close >= entry_ema:
                return False

    # --------------------------------------------------------
    # RANGE / ADX FILTER
    # --------------------------------------------------------

    if USE_RANGE_FILTER:

        entry_adx = float(
            data.iloc[entry_pos]["ADX"]
        )

        if not np.isfinite(entry_adx):
            return False

        if entry_adx < MIN_ADX:
            return False

    # --------------------------------------------------------
    # SESSION FILTER
    # --------------------------------------------------------

    if USE_SESSION_FILTER:

        if not is_in_new_york_session(
            entry_idx
        ):
            return False

    # --------------------------------------------------------
    # NEWS FILTER
    # --------------------------------------------------------

    if USE_NEWS_FILTER:

        if is_near_news_time(entry_idx):
            return False

    return True

# ============================================================
# TREND FILTER
# ============================================================

def buy_trend_is_valid(
    data,
    start_pos,
    entry_pos
):

    if not USE_TREND_FILTER:
        return True

    consecutive_opposite = 0

    for pos in range(
        start_pos + 1,
        entry_pos + 1
    ):

        current_high = float(
            data.iloc[pos]["high"]
        )

        previous_high = float(
            data.iloc[pos - 1]["high"]
        )

        if current_high > previous_high:

            consecutive_opposite = 0

        else:

            consecutive_opposite += 1

            if (
                consecutive_opposite
                >
                MAX_OPPOSITE_MOVES
            ):

                return False

    return True

def sell_trend_is_valid(
    data,
    start_pos,
    entry_pos
):

    if not USE_TREND_FILTER:
        return True

    consecutive_opposite = 0

    for pos in range(
        start_pos + 1,
        entry_pos + 1
    ):

        current_low = float(
            data.iloc[pos]["low"]
        )

        previous_low = float(
            data.iloc[pos - 1]["low"]
        )

        if current_low < previous_low:

            consecutive_opposite = 0

        else:

            consecutive_opposite += 1

            if (
                consecutive_opposite
                >
                MAX_OPPOSITE_MOVES
            ):

                return False

    return True

# ============================================================
# SETUP DETECTION
#
# Live-trader indexing follows the same index shift used when
# converting "Simple Backtest" into "Simple Trader":
#
#   -1 = latest candle
#   -2 = candle after spike
#   -3 = spike candle
#   -4 = candle before spike
#
# The current candle is used exactly as in the live trader style.
# ============================================================

def detect_buy_setup(data):

    if len(data) < 5:
        return False

    buy0 = (
        data["low"].iloc[-1]
        <
        data["low"].iloc[-2]
    )

    buy1 = (
        data["close"].iloc[-2]
        >
        data["close"].iloc[-3]
    )

    buy2 = (
        data["open"].iloc[-2]
        >
        data["open"].iloc[-3]
    )

    buy3 = (
        data["close"].iloc[-3]
        >
        data["close"].iloc[-4]
    )

    buy4 = (
        data["open"].iloc[-3]
        >
        data["open"].iloc[-4]
    )

    buy5 = (
        data["close"].iloc[-2]
        >
        data["open"].iloc[-2]
    )

    buy6 = (
        data["close"].iloc[-3]
        >
        data["open"].iloc[-3]
    )

    buy7 = (
        data["close"].iloc[-4]
        >
        data["open"].iloc[-4]
    )

    p_gap_buy = (
        data["low"].iloc[-2]
        >
        data["high"].iloc[-4]
        +
        P_GAP_PRICE
    )

    spike_buy = (

        (
            data["close"].iloc[-3]
            -
            data["open"].iloc[-3]
        )
        >
        SPIKE_CANDLE_SIZE
        *
        (
            data["close"].iloc[-2]
            -
            data["open"].iloc[-2]
        )

    ) & (

        (
            data["close"].iloc[-3]
            -
            data["open"].iloc[-3]
        )
        >
        SPIKE_CANDLE_SIZE
        *
        (
            data["close"].iloc[-4]
            -
            data["open"].iloc[-4]
        )

    ) & (

        (
            data["close"].iloc[-3]
            -
            data["open"].iloc[-3]
        )
        >
        SPIKE_CANDLE_SIZE
        *
        (
            data["close"].iloc[-1]
            -
            data["open"].iloc[-1]
        )
    )

    return (
        buy0
        & buy1
        & buy2
        & buy3
        & buy4
        & buy5
        & buy6
        & buy7
        & p_gap_buy
        & spike_buy
    )

def detect_sell_setup(data):

    if len(data) < 5:
        return False

    sell0 = (
        data["high"].iloc[-1]
        >
        data["high"].iloc[-2]
    )

    sell1 = (
        data["close"].iloc[-2]
        <
        data["close"].iloc[-3]
    )

    sell2 = (
        data["open"].iloc[-2]
        <
        data["open"].iloc[-3]
    )

    sell3 = (
        data["close"].iloc[-3]
        <
        data["close"].iloc[-4]
    )

    sell4 = (
        data["open"].iloc[-3]
        <
        data["open"].iloc[-4]
    )

    sell5 = (
        data["close"].iloc[-2]
        <
        data["open"].iloc[-2]
    )

    sell6 = (
        data["close"].iloc[-3]
        <
        data["open"].iloc[-3]
    )

    sell7 = (
        data["close"].iloc[-4]
        <
        data["open"].iloc[-4]
    )

    p_gap_sell = (
        data["high"].iloc[-2]
        <
        data["low"].iloc[-4]
        -
        P_GAP_PRICE
    )

    spike_sell = (

        (
            data["open"].iloc[-3]
            -
            data["close"].iloc[-3]
        )
        >
        SPIKE_CANDLE_SIZE
        *
        (
            data["open"].iloc[-2]
            -
            data["close"].iloc[-2]
        )

    ) & (

        (
            data["open"].iloc[-3]
            -
            data["close"].iloc[-3]
        )
        >
        SPIKE_CANDLE_SIZE
        *
        (
            data["open"].iloc[-4]
            -
            data["close"].iloc[-4]
        )

    ) & (

        (
            data["open"].iloc[-3]
            -
            data["close"].iloc[-3]
        )
        >
        SPIKE_CANDLE_SIZE
        *
        (
            data["open"].iloc[-1]
            -
            data["close"].iloc[-1]
        )
    )

    return (
        sell0
        & sell1
        & sell2
        & sell3
        & sell4
        & sell5
        & sell6
        & sell7
        & p_gap_sell
        & spike_sell
    )

# ============================================================
# PENDING SETUP
# ============================================================

def create_pending_buy(data):

    # The live setup corresponds to the backtest setup row.
    setup_time = data.index[-1]

    # In the advanced backtest the BUY SL is the low of the
    # candle before the spike.
    sl = float(
        data["low"].iloc[-4]
    )

    spike_body = abs(
        float(data["close"].iloc[-3])
        -
        float(data["open"].iloc[-3])
    )

    return {
        "direction": "BUY",
        "setup_time": setup_time,
        "setup_pos_time": setup_time,
        "sl": sl,
        "spike_body": spike_body,
        "second_entry_active": False
    }

def create_pending_sell(data):

    setup_time = data.index[-1]

    # In the advanced backtest the SELL SL is the high of the
    # candle before the spike.
    sl = float(
        data["high"].iloc[-4]
    )

    spike_body = abs(
        float(data["open"].iloc[-3])
        -
        float(data["close"].iloc[-3])
    )

    return {
        "direction": "SELL",
        "setup_time": setup_time,
        "setup_pos_time": setup_time,
        "sl": sl,
        "spike_body": spike_body,
        "second_entry_active": False
    }

# ============================================================
# FIND FIRST VALID BUY ENTRY
#
# This is the live equivalent of the advanced backtest's
# find_first_buy_entry(). It does NOT enter immediately when
# a setup is detected.
# ============================================================

def check_pending_buy(
    data,
    pending,
    symbol
):

    if len(data) < 2:
        return None

    sl = pending["sl"]

    current_low = float(
        data["low"].iloc[-1]
    )

    previous_low = float(
        data["low"].iloc[-2]
    )

    if current_low >= previous_low:
        return None

    # ------------------------------------------------------
    # SPREAD FILTER
    # ------------------------------------------------------
    spread_points = get_spread_points(symbol)

    if spread_points is None:
        return None

    if spread_points > MAX_SPREAD_POINTS:
        print(
            f"\n{Fore.YELLOW}"
            f"Spread too high ({spread_points:.1f} pts) "
            f"- BUY entry skipped"
            f"{Style.RESET_ALL}"
        )
        return None

    tick = mt5.symbol_info_tick(symbol)

    if tick is None:
        return None

    entry = tick.ask

    risk = entry - sl

    if risk <= 0:
        return None

    if risk > MAX_SL_DISTANCE_PRICE:
        return "INVALID"

    # Find the setup candle in the current data.
    try:
        start_pos = data.index.get_loc(
            pending["setup_pos_time"]
        )
    except KeyError:
        return None

    entry_pos = len(data) - 1

    if not buy_trend_is_valid(
        data,
        start_pos,
        entry_pos
    ):
        return None

    if not entry_filters_are_valid(
        data,
        entry_pos,
        "BUY"
    ):
        return None

    return {
        "direction": "BUY",
        "entry": entry,
        "sl": sl,
        "risk": risk,
        "setup_time": pending["setup_time"],
        "entry_time": data.index[-1],
        "spike_body": pending["spike_body"]
    }

# ============================================================
# FIND FIRST VALID SELL ENTRY
# ============================================================

def check_pending_sell(
    data,
    pending,
    symbol
):

    if len(data) < 2:
        return None

    sl = pending["sl"]

    current_high = float(
        data["high"].iloc[-1]
    )

    previous_high = float(
        data["high"].iloc[-2]
    )

    if current_high <= previous_high:
        return None

    # ------------------------------------------------------
    # SPREAD FILTER
    # ------------------------------------------------------
    spread_points = get_spread_points(symbol)

    if spread_points is None:
        return None

    if spread_points > MAX_SPREAD_POINTS:
        print(
            f"\n{Fore.YELLOW}"
            f"Spread too high ({spread_points:.1f} pts) "
            f"- SELL entry skipped"
            f"{Style.RESET_ALL}"
        )
        return None
    tick = mt5.symbol_info_tick(symbol)

    if tick is None:
        return None

    entry = tick.bid
    risk = sl - entry

    if risk <= 0:
        return None

    if risk > MAX_SL_DISTANCE_PRICE:
        return "INVALID"

    try:
        start_pos = data.index.get_loc(
            pending["setup_pos_time"]
        )
    except KeyError:
        return None

    entry_pos = len(data) - 1

    if not sell_trend_is_valid(
        data,
        start_pos,
        entry_pos
    ):
        return None

    if not entry_filters_are_valid(
        data,
        entry_pos,
        "SELL"
    ):
        return None

    return {
        "direction": "SELL",
        "entry": entry,
        "sl": sl,
        "risk": risk,
        "setup_time": pending["setup_time"],
        "entry_time": data.index[-1],
        "spike_body": pending["spike_body"]
    }

# ============================================================
# SECOND ENTRY
# ============================================================

def get_second_entry(
    direction,
    entry,
    risk
):

    if direction == "BUY":

        return entry - risk / 2

    return entry + risk / 2

# ============================================================
# TRADE STATE
# ============================================================

def get_trade_state(symbol):

    resume = Meta.resume()

    if resume is None:
        return False, None

    if resume.shape[0] == 0:
        return False, None

    row = resume.loc[
        (resume["symbol"] == symbol)
        &
        (resume["magic"] == MAGIC)
    ]

    if row.empty:
        return False, None

    return True, row

# ============================================================
# LAST CLOSED TRADE (sequential IN -> OUT pairing)
#
# Processes this symbol+magic's deals in chronological order
# and pairs each opening (IN) deal with the very next closing
# (OUT) deal - the same approach used in the working MQL5
# reporting code. This is reliable here specifically because
# this bot only ever holds ONE position at a time (a new
# setup is blocked while one is active), so there is never a
# second, overlapping position to confuse the pairing.
# ============================================================

def get_position_trade(
    ticket,
    max_age_seconds=120
):
    """
    Fetches the exact deals belonging to ONE position, by its
    ticket - no date range involved at all, so there is no
    timezone/date-window mismatch to go wrong. This is the
    fix: history_deals_get(position=ticket) asks MT5 directly
    for this position's own deals, precisely, regardless of
    how many other trades exist or what timezone anything is
    displayed in.
    """

    if ticket is None:
        return None

    deals = mt5.history_deals_get(
        position=ticket
    )

    if deals is None or len(deals) == 0:
        return None

    open_deal = next(
        (
            d for d in deals
            if d.entry == mt5.DEAL_ENTRY_IN
        ),
        None
    )

    close_deal = next(
        (
            d for d in deals
            if d.entry == mt5.DEAL_ENTRY_OUT
        ),
        None
    )

    if close_deal is None:
        # Position not closed yet (or not found).
        return None

    net_profit = (
        close_deal.profit
        +
        close_deal.commission
        +
        close_deal.swap
        +
        (open_deal.commission if open_deal is not None else 0.0)
        +
        (open_deal.swap if open_deal is not None else 0.0)
    )

    trade = {
        "open_price": (
            open_deal.price if open_deal is not None else None
        ),
        "close_price": close_deal.price,
        "profit": net_profit,
        "raw_profit": close_deal.profit,
        "time": close_deal.time
    }

    # ------------------------------------------------------------
    # FRESHNESS CHECK - same purpose as before: flag (don't
    # discard) a result that looks unexpectedly old.
    # ------------------------------------------------------------

    deal_age_seconds = (
        datetime.now(timezone.utc)
        -
        datetime.fromtimestamp(
            close_deal.time,
            tz=timezone.utc
        )
    ).total_seconds()

    trade["is_stale"] = (
        deal_age_seconds > max_age_seconds
    )

    trade["age_seconds"] = deal_age_seconds

    return trade

def get_last_closed_trade(
    symbol,
    magic,
    lookback_hours=48,
    max_age_seconds=120
):
    """
    FALLBACK ONLY - used when no ticket is available (e.g. an
    abnormally detected position that this bot didn't open
    itself). Sequential IN -> OUT pairing by time; only safe
    when exactly one position for this symbol+magic is ever
    open at a time.
    """

    date_to = (
        datetime.now(timezone.utc)
        +
        timedelta(hours=1)
    )

    date_from = (
        date_to
        -
        timedelta(hours=lookback_hours)
    )

    deals = mt5.history_deals_get(
        date_from,
        date_to
    )

    if deals is None or len(deals) == 0:
        return None

    relevant = [
        d for d in deals
        if d.symbol == symbol
        and d.magic == magic
    ]

    # Order matters for this pairing logic - always process
    # oldest to newest.
    relevant.sort(
        key=lambda d: d.time
    )

    open_price = None
    last_trade = None

    for d in relevant:

        if d.entry == mt5.DEAL_ENTRY_IN:

            open_price = d.price

        elif d.entry == mt5.DEAL_ENTRY_OUT:

            last_trade = {
                "open_price": open_price,
                "close_price": d.price,
                "profit": d.profit,
                "raw_profit": d.profit,
                "time": d.time
            }

            open_price = None

    if last_trade is not None:

        deal_age_seconds = (
            datetime.now(timezone.utc)
            -
            datetime.fromtimestamp(
                last_trade["time"],
                tz=timezone.utc
            )
        ).total_seconds()

        last_trade["is_stale"] = (
            deal_age_seconds > max_age_seconds
        )

        last_trade["age_seconds"] = deal_age_seconds

    return last_trade

# ============================================================
# ADVANCED SP2L STRATEGY
#
# Returns:
#
#   preBuy
#   preSell
#   status
#   sl
#   tp
#   pending_setup
#   trade_setup
#
# pending_setup is deliberately kept separate from status.
# A pending setup is NOT an open position.
# ============================================================

def Strategy(
    symbol,
    preBuy,
    preSell,
    status,
    pending_setup
):

    sl = 0
    tp = 0
    trade_setup = None

    data = get_data(symbol)

    if data is None:
        return (
            preBuy,
            preSell,
            status,
            sl,
            tp,
            pending_setup,
            trade_setup
        )

    # ========================================================
    # If a position is already open, do not search for another
    # setup.
    # ========================================================

    if status:

        return (
            preBuy,
            preSell,
            status,
            sl,
            tp,
            pending_setup,
            trade_setup
        )

    # ========================================================
    # PENDING SETUP
    #
    # This is the key difference from Simple Trader.
    # The setup waits for the first valid entry.
    # ========================================================

    if pending_setup is not None:

        direction = pending_setup["direction"]

        if direction == "BUY":

            result = check_pending_buy(
                data,
                pending_setup,
                symbol
            )

        else:

            result = check_pending_sell(
                data,
                pending_setup,
                symbol
            )

        if result == "INVALID":

            pending_setup = None

        elif result is not None:

            entry = result["entry"]
            sl = result["sl"]
            risk = result["risk"]

            if risk <= 0:
                pending_setup = None

            else:

                if direction == "BUY":

                    tp = (
                        entry
                        +
                        TP_R * risk
                    )

                else:

                    tp = (
                        entry
                        -
                        TP_R * risk
                    )

                second_entry = get_second_entry(
                    direction,
                    entry,
                    risk
                )

                trade_setup = {
                    "direction": direction,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "risk": risk,
                    "second_entry": second_entry,
                    "setup_time": result["setup_time"],
                    "entry_time": result["entry_time"],
                    "spike_body": result["spike_body"]
                }

                if direction == "BUY":
                    preBuy = True
                    preSell = False
                else:
                    preBuy = False
                    preSell = True

                status = True

                pending_setup = None

                return (
                    preBuy,
                    preSell,
                    status,
                    sl,
                    tp,
                    pending_setup,
                    trade_setup
                )

    # ========================================================
    # LOOK FOR A NEW SETUP
    #
    # A setup is only created here.
    # It is NOT an entry.
    # ========================================================

    buy = detect_buy_setup(data)
    sell = detect_sell_setup(data)

    if buy and not sell:

        pending_setup = create_pending_buy(
            data
        )

        print(
            f"\n{Fore.CYAN}"
            f"BUY pending setup detected"
            f"{Style.RESET_ALL}"
        )

    elif sell and not buy:

        pending_setup = create_pending_sell(
            data
        )

        print(
            f"\n{Fore.CYAN}"
            f"SELL pending setup detected"
            f"{Style.RESET_ALL}"
        )

    return (
        preBuy,
        preSell,
        status,
        sl,
        tp,
        pending_setup,
        trade_setup
    )

# ============================================================
# INITIAL STATE
# ============================================================

buy = False
sell = False
status = False

pending_setup = None

# Ticket of the currently open position, captured directly
# from the order result when it opens (no polling, no date-
# range guessing).
open_ticket = None

# ============================================================
# MAIN LOOP
# ============================================================

while True:

    if internet() is True:

        refresh_news_if_needed()

        for asset in symbols_list.keys():

            symbol = symbols_list[asset][0]

            # ------------------------------------------------
            # BALANCE-BASED LOT SIZE
            #
            # Recalculated every loop from the live account
            # balance, instead of using a fixed lot value.
            # ------------------------------------------------

            current_account_info = mt5.account_info()

            if current_account_info is not None:

                lot = get_lot_size(
                    current_account_info.balance
                )

            else:

                # Fallback if account info is briefly
                # unavailable - use the base lot rather than
                # skipping the trade entirely.
                lot = BASE_LOT

            selected = mt5.symbol_select(
                symbol
            )

            if not selected:

                print(
                    f"\nERROR - Failed to select "
                    f"'{symbol}' in MetaTrader 5 "
                    f"with error :",
                    mt5.last_error()
                )

                continue

            # =================================================
            # CHECK EXISTING POSITION
            # =================================================

            position_exists, row = get_trade_state(
                symbol
            )

            # -------------------------------------------------
            # Stop loss / position closed
            # -------------------------------------------------

            if not position_exists and status:

                status = False
                buy = False
                sell = False
                pending_setup = None

                # Preferred: exact position lookup, no date
                # range involved. Falls back to sequential
                # time-based pairing only if no ticket was
                # captured (e.g. an abnormally detected
                # position this bot didn't open itself).
                last_trade = get_position_trade(open_ticket)

                if last_trade is None:

                    last_trade = get_last_closed_trade(
                        symbol,
                        MAGIC
                    )

                open_ticket = None

                if last_trade is not None:

                    open_price_str = (
                        round(last_trade["open_price"], DIGITS)
                        if last_trade["open_price"] is not None
                        else "N/A"
                    )

                    print(
                        "Open price:",
                        open_price_str,
                        "\tClose price:",
                        round(last_trade["close_price"], DIGITS),
                        "\tProfit:",
                        round(last_trade["raw_profit"], 2)
                    )

                    if last_trade["is_stale"]:

                        print(
                            f"{Fore.YELLOW}"
                            f"Warning: this deal closed "
                            f"{last_trade['age_seconds']:.0f}s ago - "
                            f"it may not be the trade that just "
                            f"closed. Verify against MT5 history."
                            f"{Style.RESET_ALL}"
                        )

                else:

                    print(
                        f"{Fore.YELLOW}"
                        f"Could not retrieve closing deal "
                        f"details from history."
                        f"{Style.RESET_ALL}"
                    )

                print(
                    f"Strategy "
                    f"{Fore.YELLOW}"
                    f"Position closed / SL or TP hit!"
                    f"{Style.RESET_ALL}"
                )

                time_module.sleep(60-LOOP_SECONDS)

            # -------------------------------------------------
            # Abnormal open position
            # -------------------------------------------------

            elif position_exists and not status:

                print(
                    "Abnormally position: "
                    "you have an open position "
                    "with Advanced SP2L Trader "
                    "but the status key is False!!"
                )

            # -------------------------------------------------
            # Force-close ahead of scheduled news
            # -------------------------------------------------

            if status and USE_NEWS_FILTER:

                current_broker_time = get_current_broker_time(
                    symbol
                )

                if (
                    current_broker_time is not None
                    and
                    is_within_pre_news_window(
                        current_broker_time
                    )
                ):

                    print(
                        f"\n{Fore.MAGENTA}"
                        f"Closing position ahead of scheduled "
                        f"news (within "
                        f"{NEWS_BUFFER_MINUTES} min)."
                        f"{Style.RESET_ALL}"
                    )

                    Meta.run(
                        symbol,
                        False,
                        False,
                        lot,
                        tp,
                        sl,
                        MAGIC,
                        stopLossPure=True,
                        comment="SP2L_Spike_v1"
                    )

                    status = False
                    buy = False
                    sell = False
                    pending_setup = None

                    last_trade = get_position_trade(
                        open_ticket
                    )

                    if last_trade is None:

                        last_trade = get_last_closed_trade(
                            symbol,
                            MAGIC
                        )

                    open_ticket = None

                    if last_trade is not None:

                        open_price_str = (
                            round(
                                last_trade["open_price"],
                                DIGITS
                            )
                            if last_trade["open_price"]
                            is not None
                            else "N/A"
                        )

                        print(
                            "Open price:",
                            open_price_str,
                            "\tClose price:",
                            round(
                                last_trade["close_price"],
                                DIGITS
                            ),
                            "\tProfit:",
                            round(last_trade["raw_profit"], 2)
                        )

                    time_module.sleep(60 - LOOP_SECONDS)

            # =================================================
            # STRATEGY
            # =================================================

            (
                buy,
                sell,
                status,
                sl,
                tp,
                pending_setup,
                trade_setup
            ) = Strategy(
                symbol,
                buy,
                sell,
                status,
                pending_setup
            )

            # =================================================
            # EXECUTE ENTRY 1
            # =================================================

            if trade_setup is not None:

                direction = trade_setup["direction"]

                entry = trade_setup["entry"]
                sl = trade_setup["sl"]
                tp = trade_setup["tp"]

                print()
                print("-" * 75)
                print(
                    f"{Fore.GREEN if buy == True else Fore.RED}"
                    f"VALID {direction} ENTRY"
                    f"{Style.RESET_ALL}"
                )

                print(
                    "Setup time :",
                    trade_setup["setup_time"]
                )

                print(
                    "Entry time :",
                    trade_setup["entry_time"]
                )

                print(
                    "Entry      :",
                    round(entry, DIGITS)
                )

                print(
                    "SL         :",
                    round(sl, DIGITS)
                )

                print(
                    "TP         :",
                    round(tp, DIGITS)
                )

                print(
                    "Risk       :",
                    round(
                        trade_setup["risk"],
                        DIGITS
                    )
                )

                print(
                    "Second     :",
                    round(
                        trade_setup["second_entry"],
                        DIGITS
                    )
                )

                print("-" * 75)

                result = Meta.run(
                    symbol,
                    buy,
                    sell,
                    lot,
                    tp,
                    sl,
                    MAGIC,
                    stopLossPure=True,
                    comment="SP2L_Spike_V3"
                )

                # -----------------------------------------------
                # CAPTURE THE OPENED POSITION'S TICKET
                #
                # Taken directly from the order result - no
                # polling, no date-range history queries. This
                # ticket is what lets the close report look up
                # THIS exact position later via
                # history_deals_get(position=ticket), which has
                # no timezone/date-window to go wrong.
                # -----------------------------------------------

                if (
                    result is not None
                    and
                    getattr(result, "order", None)
                ):

                    open_ticket = int(result.order)

                else:

                    open_ticket = None

                    print(
                        f"{Fore.YELLOW}"
                        f"Warning: could not capture the "
                        f"opened position's ticket from the "
                        f"order result."
                        f"{Style.RESET_ALL}"
                    )

                # =================================================
                # SECOND ENTRY
                #
                # This is intentionally optional.
                # Default = False.
                #
                # If enabled, the actual second-entry order must
                # be handled by the same Meta execution layer
                # used by the user's existing trader environment.
                # And also use the different magic number.
                # For example MAGIC = 7.
                # Implement new status for it as above.
                # =================================================

                if USE_SECOND_ENTRY:

                    print(
                        f"{Fore.MAGENTA}"
                        f"Second entry is ENABLED."
                        f"{Style.RESET_ALL}"
                    )

                    print(
                        "Second entry price:",
                        round(
                            trade_setup["second_entry"],
                            DIGITS
                        )
                    )

                    print(
                        "Second entry volume:",
                        lot
                        *
                        SECOND_ENTRY_VOLUME_MULTIPLIER
                    )
                    # Meta.run(
                    #     symbol,
                    #     buy,
                    #     sell,
                    #     lot,
                    #     tp,
                    #     sl,
                    #     MAGIC=7,
                    #     stopLossPure=True
                    # )

                trade_setup = None

    time_module.sleep(
        LOOP_SECONDS
    )
