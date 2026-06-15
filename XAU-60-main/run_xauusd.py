#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XAUUSD SMC Trading Bot - Main Runner
=====================================
Runs the full XAU-60 trading bot with:
  - MT5 live connection (XAUUSD)
  - SmartMoneyConcepts library integration (FVG, CHoCH, OB, BOS)
  - All 3 strategies: SMC Scalper, CRT TBS, Trend Break Trauma
  - Real-time signal generation and trade execution

Usage:
    python run_xauusd.py             # Live trading mode
    python run_xauusd.py --dry-run   # Test configuration only
    python run_xauusd.py --scan      # One-shot signal scan (no trades)
    python run_xauusd.py --ui        # Launch Streamlit dashboard
"""
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── Encoding fix for Windows console ─────────────────────────────────────────
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from loguru import logger
import MetaTrader5 as mt5
import pandas as pd

from core.mt5_connector import MT5Connector
from core.strategy_loader import StrategyLoader
from core.risk_manager import RiskManager, RiskLimits
from core.trade_executor import TradeExecutor
from indicators.smc_library_bridge import get_smc_analyzer, _SMC_AVAILABLE
from utils.config import config as env_config


SYMBOL = "XAUUSD"
BANNER = """
╔══════════════════════════════════════════════════════════════╗
║         XAU-60 SMC Trading Bot  |  XAUUSD Edition           ║
║         SmartMoneyConcepts Library: {smc_status:<26}║
║         MT5 Terminal: {mt5_status:<39}║
╚══════════════════════════════════════════════════════════════╝
"""


def print_banner():
    smc_status = "ACTIVE" if _SMC_AVAILABLE else "FALLBACK (built-in)"
    try:
        mt5.initialize()
        info = mt5.account_info()
        if info:
            mt5_status = f"#{info.login} | {info.server}"
        else:
            mt5_status = "Connected (no account)"
        mt5.shutdown()
    except Exception:
        mt5_status = "Not connected"

    print(BANNER.format(smc_status=smc_status, mt5_status=mt5_status))


def scan_signals(timeframes=("M15", "H1")):
    """
    Connect to MT5, fetch XAUUSD data, and print current signals for all strategies.
    Does NOT place any trades.
    """
    print_banner()
    print(f"\n[SCAN] XAUUSD Signal Scan - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # Connect
    connector = MT5Connector()
    cfg = env_config.to_dict()["mt5"]
    if not connector.connect(
        login=cfg.get("login"),
        password=cfg.get("password"),
        server=cfg.get("server"),
        path=cfg.get("path") or None
    ):
        print("[ERROR] Failed to connect to MT5. Ensure MT5 terminal is running.")
        return

    # Load strategies
    loader = StrategyLoader()
    strategies = loader.load_all_strategies()
    enabled = loader.get_enabled_strategies()
    print(f"  Loaded {len(enabled)} strategies: {list(enabled.keys())}\n")

    print(f"{'─'*60}")
    print(f"{'Strategy':<22} {'TF':<6} {'Signal':<10} {'Entry':>10} {'SL':>10} {'TP':>10}")
    print(f"{'─'*60}")

    any_signal = False
    for name, strategy in enabled.items():
        for symbol in strategy.symbols:
            if symbol != SYMBOL:
                continue
            data = connector.get_ohlcv(symbol, strategy.timeframe, 200)
            if data is None:
                print(f"  {name:<20}  No data")
                continue

            # Disable session filter for scan (if supported)
            orig_session = getattr(strategy, 'use_session_filter', None)
            if orig_session is not None:
                strategy.use_session_filter = False

            try:
                signal = strategy.analyze(symbol, data)
            except Exception as e:
                print(f"  {name:<20}  Error: {e}")
                continue
            finally:
                if orig_session is not None:
                    strategy.use_session_filter = orig_session

            if signal and signal.signal.value != 0:
                direction = "BUY " if signal.signal.value > 0 else "SELL"
                print(f"  {name:<22} {strategy.timeframe:<6} {direction:<10} {signal.entry_price:>10.2f} {signal.stop_loss:>10.2f} {signal.take_profit:>10.2f}")
                any_signal = True
            else:
                print(f"  {name:<22} {strategy.timeframe:<6} {'NONE':<10} {'—':>10} {'—':>10} {'—':>10}")

    print(f"{'─'*60}")
    if not any_signal:
        print("\n  No signals. Market conditions not currently met.\n")

    # Show live SMC analysis
    print("\n[SMC ANALYSIS] XAUUSD H1")
    data_h1 = connector.get_ohlcv(SYMBOL, "H1", 200)
    if data_h1 is not None:
        smc = get_smc_analyzer(point=0.1)
        struct = smc.get_market_structure(data_h1, 50)
        choch_b = smc.detect_bullish_choch(data_h1, 50)
        choch_s = smc.detect_bearish_choch(data_h1, 50)
        fvg_b   = smc.detect_bullish_fvg(data_h1, 30)
        fvg_s   = smc.detect_bearish_fvg(data_h1, 30)
        ob_b    = smc.detect_bullish_order_block(data_h1, 30)
        ob_s    = smc.detect_bearish_order_block(data_h1, 30)
        liq     = smc.get_liquidity_zones(data_h1, 100)

        tick = connector.get_tick(SYMBOL)
        current = tick["bid"] if tick else data_h1.iloc[-1]["close"]

        print(f"  Current Price  : {current:.3f}")
        print(f"  Market Structure: {struct.name}")
        print(f"  Bullish CHoCH  : {f'YES @ {choch_b[1]:.2f}' if choch_b else 'No'}")
        print(f"  Bearish CHoCH  : {f'YES @ {choch_s[1]:.2f}' if choch_s else 'No'}")

        if fvg_b:
            print(f"  Bullish FVG    : {fvg_b.lower_price:.2f} - {fvg_b.upper_price:.2f} (mid={fvg_b.mid_price:.2f}, filled={fvg_b.filled})")
        else:
            print("  Bullish FVG    : None")

        if fvg_s:
            print(f"  Bearish FVG    : {fvg_s.lower_price:.2f} - {fvg_s.upper_price:.2f} (mid={fvg_s.mid_price:.2f}, filled={fvg_s.filled})")
        else:
            print("  Bearish FVG    : None")

        if ob_b:
            print(f"  Bullish OB     : {ob_b.lower_price:.2f} - {ob_b.upper_price:.2f}")
        if ob_s:
            print(f"  Bearish OB     : {ob_s.lower_price:.2f} - {ob_s.upper_price:.2f}")

        if liq:
            print(f"  Liquidity Zones: {len(liq)} zones detected")

    connector.disconnect()
    print("\n[SCAN COMPLETE]")


def run_live():
    """Run the live trading bot."""
    from main import TradingBot
    bot = TradingBot()
    bot.run()


def run_dry():
    """Run the dry-run configuration test."""
    from main import TradingBot
    bot = TradingBot()
    bot.dry_run()


def run_ui():
    """Launch Streamlit dashboard."""
    import subprocess
    import os
    print("Launching Streamlit dashboard on http://localhost:8501 ...")
    env = os.environ.copy()
    env["STREAMLIT_EMAIL"] = ""
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    subprocess.run([sys.executable, "-m", "streamlit", "run", "ui/app.py"], env=env)


def main():
    parser = argparse.ArgumentParser(
        description="XAU-60 XAUUSD SMC Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Test configuration without trading")
    parser.add_argument("--scan", action="store_true",
                        help="One-shot signal scan (no trades placed)")
    parser.add_argument("--ui", action="store_true",
                        help="Launch Streamlit dashboard")
    args = parser.parse_args()

    if args.scan:
        scan_signals()
    elif args.dry_run:
        run_dry()
    elif args.ui:
        run_ui()
    else:
        print_banner()
        print("\nStarting LIVE trading mode. Press Ctrl+C to stop.\n")
        run_live()


if __name__ == "__main__":
    main()
