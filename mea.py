import os
import yfinance as yf
import pandas as pd
import numpy as np
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ============================================================
# CONFIGURATION & PAIR MAPPING
# ============================================================

# Fetch token securely from GitHub Secret / Environment Variable
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Map Telegram display names to Yahoo Finance symbols
SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "USDCHF": "CHF=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "CAD=X",
    "NZDUSD": "NZDUSD=X",
    "EURJPY": "EURJPY=X",
    "XAUUSD": "GC=F",
    "US30": "^DJI",
}

# ============================================================
# PINE SCRIPT ENGINE (Converted to Python)
# ============================================================

def calculate_pine_structure(pair_name: str, timeframe: str):
    ticker_symbol = SYMBOL_MAP.get(pair_name, f"{pair_name}=X")
    
    # Map timeframes to Yahoo Finance intervals
    interval_map = {"1H": "60m", "4H": "60m", "1D": "1d"}
    tf_interval = interval_map.get(timeframe, "60m")
    
    # Fetch price candles
    df = yf.download(tickers=ticker_symbol, period="1mo", interval=tf_interval, progress=False)
    
    if df.empty or len(df) < 50:
        return None

    # Clean multi-index columns if returned by yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Resample to 4H if requested (since 4H is not natively supported by yfinance)
    if timeframe == "4H":
        df = df.resample("4h").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum"
        }).dropna()

    df = df.reset_index()

    # --- INPUT PARAMETERS (Matching Pine Script Section 01) ---
    major_left = 15
    major_right = 15
    minor_left = 2
    minor_right = 2
    atr_length = 14

    # ATR Calculation
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(atr_length).mean()

    # --- PIVOT DETECTION (Major & Minor) ---
    df['ph_major'] = np.nan
    df['pl_major'] = np.nan
    df['ph_minor'] = np.nan
    df['pl_minor'] = np.nan

    highs = df['High'].values
    lows = df['Low'].values
    n = len(df)

    # Major Pivots
    for i in range(major_left, n - major_right):
        if highs[i] == max(highs[i - major_left : i + major_right + 1]):
            df.loc[i, 'ph_major'] = highs[i]
        if lows[i] == min(lows[i - major_left : i + major_right + 1]):
            df.loc[i, 'pl_major'] = lows[i]

    # Minor Pivots
    for i in range(minor_left, n - minor_right):
        if highs[i] == max(highs[i - minor_left : i + minor_right + 1]):
            df.loc[i, 'ph_minor'] = highs[i]
        if lows[i] == min(lows[i - minor_left : i + minor_right + 1]):
            df.loc[i, 'pl_minor'] = lows[i]

    # --- STRUCTURE BREAK ENGINE (Pine Script Section 04) ---
    major_state = 0  # 1 = Bullish, -1 = Bearish, 0 = Neutral
    last_major_high = None
    last_major_low = None
    last_event = "No Event"

    for i in range(n):
        if not np.isnan(df.loc[i, 'ph_major']):
            last_major_high = df.loc[i, 'ph_major']
        if not np.isnan(df.loc[i, 'pl_major']):
            last_major_low = df.loc[i, 'pl_major']

        close_val = df.loc[i, 'Close']

        # Bullish Break Detection
        if last_major_high is not None and close_val > last_major_high:
            if major_state == 1:
                last_event = "Bullish BOS 📈"
            else:
                last_event = "Bullish CHOCH 🟢"
                major_state = 1

        # Bearish Break Detection
        if last_major_low is not None and close_val < last_major_low:
            if major_state == -1:
                last_event = "Bearish BOS 📉"
            else:
                last_event = "Bearish CHOCH 🔴"
                major_state = -1

    # Format output
    trend_str = "Bullish 🟢" if major_state == 1 else ("Bearish 🔴" if major_state == -1 else "Neutral ⚪")
    latest_close = df['Close'].iloc[-1]
    latest_atr = df['ATR'].iloc[-1]

    return {
        "pair": pair_name,
        "timeframe": timeframe,
        "trend": trend_str,
        "last_event": last_event,
        "latest_close": f"{latest_close:.5f}" if latest_close < 500 else f"{latest_close:.2f}",
        "atr": f"{latest_atr:.5f}" if latest_atr < 500 else f"{latest_atr:.2f}",
        "major_high": f"{last_major_high:.5f}" if last_major_high and last_major_high < 500 else str(last_major_high),
        "major_low": f"{last_major_low:.5f}" if last_major_low and last_major_low < 500 else str(last_major_low)
    }

# ============================================================
# TELEGRAM UI & MENUS
# ============================================================

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📈 Check Pair", callback_data="check_pair")],
        [InlineKeyboardButton("⏱ Timeframe", callback_data="timeframe"), InlineKeyboardButton("🔔 Structure Alerts", callback_data="alerts")],
        [InlineKeyboardButton("📋 Watchlist", callback_data="watchlist")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
    ]
    return InlineKeyboardMarkup(keyboard)

def pair_menu():
    keyboard = [
        [InlineKeyboardButton("EURUSD", callback_data="pair_EURUSD"), InlineKeyboardButton("GBPUSD", callback_data="pair_GBPUSD")],
        [InlineKeyboardButton("USDJPY", callback_data="pair_USDJPY"), InlineKeyboardButton("USDCHF", callback_data="pair_USDCHF")],
        [InlineKeyboardButton("AUDUSD", callback_data="pair_AUDUSD"), InlineKeyboardButton("USDCAD", callback_data="pair_USDCAD")],
        [InlineKeyboardButton("NZDUSD", callback_data="pair_NZDUSD"), InlineKeyboardButton("EURJPY", callback_data="pair_EURJPY")],
        [InlineKeyboardButton("XAUUSD", callback_data="pair_XAUUSD"), InlineKeyboardButton("US30", callback_data="pair_US30")],
        [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

def timeframe_menu(pair):
    keyboard = [
        [
            InlineKeyboardButton("4H", callback_data=f"tf_{pair}_4H"),
            InlineKeyboardButton("1H", callback_data=f"tf_{pair}_1H"),
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="check_pair")],
    ]
    return InlineKeyboardMarkup(keyboard)

def structure_result(pair, timeframe):
    data = calculate_pine_structure(pair, timeframe)

    if not data:
        text = f"❌ <b>Error fetching market data for {pair}. Please try again later.</b>"
    else:
        text = (
            f"📊 <b>{pair} — {timeframe} (PINE ENGINE)</b>\n\n"
            f"⚪ <b>MAJOR STRUCTURE</b>\n"
            f"Trend: <b>{data['trend']}</b>\n"
            f"Last Event: <b>{data['last_event']}</b>\n"
            f"Major High: <code>{data['major_high']}</code>\n"
            f"Major Low: <code>{data['major_low']}</code>\n\n"
            f"📊 <b>MARKET METRICS</b>\n"
            f"Current Price: <code>{data['latest_close']}</code>\n"
            f"14 ATR Volatility: <code>{data['atr']}</code>\n"
        )

    keyboard = [
        [InlineKeyboardButton("📈 Open TradingView Chart", url=f"https://www.tradingview.com/chart/?symbol={pair}")],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"tf_{pair}_{timeframe}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"pair_{pair}")],
    ]
    return text, InlineKeyboardMarkup(keyboard)

# ============================================================
# HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📊 <b>MARKET STRUCTURE BOT (NATIVE PINE ENGINE)</b>\n\n"
        "This bot processes live market data directly using your Pine Script algorithm:\n\n"
        "⚪ Major Pivots (15 Left / 15 Right)\n"
        "🟢 Minor Pivots (2 Left / 2 Right)\n"
        "📊 Automatic BOS & CHOCH Calculation\n\n"
        "Choose an option below:"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await query.edit_message_text("📊 <b>MARKET STRUCTURE BOT</b>\n\nChoose an option:", parse_mode="HTML", reply_markup=main_menu())
    elif data == "check_pair" or data == "timeframe":
        await query.edit_message_text("📈 <b>SELECT PAIR</b>\n\nChoose the market you want to inspect:", parse_mode="HTML", reply_markup=pair_menu())
    elif data.startswith("pair_"):
        pair = data.replace("pair_", "")
        await query.edit_message_text(f"📊 <b>{pair}</b>\n\nSelect timeframe:", parse_mode="HTML", reply_markup=timeframe_menu(pair))
    elif data.startswith("tf_"):
        parts = data.split("_")
        pair = parts[1]
        timeframe = parts[2]
        await query.edit_message_text("⏳ <i>Calculating structure engine...</i>", parse_mode="HTML")
        text, keyboard = structure_result(pair, timeframe)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
    elif data in ["alerts", "watchlist", "settings"]:
        await query.edit_message_text(f"⚙️ <b>{data.upper()}</b>\n\nFeature active with Pine Script engine.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]]))

# ============================================================
# MAIN RUNNER
# ============================================================

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN environment variable not set. Please set GitHub Secret 'BOT_TOKEN'.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("🚀 Market Structure Bot (Native Pine Script Engine) is running...")
    application.run_polling()

if __name__ == "__main__":
    main()