"""
SMC Library Bridge
==================
Bridges the external 'smartmoneyconcepts' (smart-money-concepts-master) library
with the XAU-60 trading bot's internal SMCAnalyzer.

The external library (smc.py) provides vectorized, highly-accurate implementations of:
  - Fair Value Gaps (FVG)
  - Swing Highs & Lows
  - BOS / CHoCH (Break of Structure / Change of Character)
  - Order Blocks (OB)
  - Liquidity Zones
  - Previous High/Low
  - Sessions

This bridge replaces the manual indicator calculations with the battle-tested
library implementations while keeping the same interface expected by the strategies.
"""
import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

# ── Path resolution ───────────────────────────────────────────────────────────
# Allow the bridge to work regardless of cwd
_THIS_DIR = Path(__file__).resolve().parent          # indicators/
_PROJECT_ROOT = _THIS_DIR.parent                     # XAU-60-main/
_SMC_LIB_ROOT = (
    _PROJECT_ROOT.parent.parent                      # Downloads/
    / "XAU-60-main"
    / "smart-money-concepts-master"
    / "smart-money-concepts-master"
    / "smartmoneyconcepts"
)

# Insert the external library path so `from smc import smc` works
_SMC_PACKAGE = str(_SMC_LIB_ROOT.parent)
if _SMC_PACKAGE not in sys.path:
    sys.path.insert(0, _SMC_PACKAGE)

try:
    from smartmoneyconcepts.smc import smc as _smc
    _SMC_AVAILABLE = True
except ImportError:
    _SMC_AVAILABLE = False
    import logging
    logging.getLogger(__name__).warning(
        "smartmoneyconcepts library not found – falling back to built-in indicators."
    )

# ── Re-export internal types (keeps strategy imports unchanged) ──────────────
from .smc_utils import (
    StructureType,
    SwingPoint,
    FairValueGap,
    OrderBlock,
    LiquidityZone,
    SMCAnalyzer,
)


# ── Enhanced Analyzer using the external library ──────────────────────────────
class SMCLibraryAnalyzer(SMCAnalyzer):
    """
    Drop-in replacement for SMCAnalyzer that uses the 'smartmoneyconcepts'
    library for its core computations.

    Falls back to the parent class implementation when the library is not
    available (non-Windows dev environments).
    """

    def __init__(
        self,
        swing_lookback: int = 5,
        fvg_min_pips: float = 5.0,
        ob_displacement_factor: float = 2.0,
        point: float = 0.1,
    ):
        super().__init__(
            swing_lookback=swing_lookback,
            fvg_min_pips=fvg_min_pips,
            ob_displacement_factor=ob_displacement_factor,
            point=point,
        )
        self._use_library = _SMC_AVAILABLE

    # ── FVG ──────────────────────────────────────────────────────────────────
    def detect_bullish_fvg(
        self, data: pd.DataFrame, lookback: int = 20
    ) -> Optional[FairValueGap]:
        """Find the most recent unfilled bullish FVG using the external library."""
        if not self._use_library:
            return super().detect_bullish_fvg(data, lookback)

        subset = data.tail(lookback + 5).reset_index(drop=True)
        try:
            fvg_df = _smc.fvg(subset)
            # Filter for bullish FVGs (FVG == 1)
            bull_mask = fvg_df["FVG"] == 1
            if not bull_mask.any():
                return None

            last_idx = fvg_df[bull_mask].index[-1]
            top = float(fvg_df.loc[last_idx, "Top"])
            bottom = float(fvg_df.loc[last_idx, "Bottom"])

            # Check if still active (MitigatedIndex == 0 → not yet filled)
            mitigated = fvg_df.loc[last_idx, "MitigatedIndex"]
            filled = bool(mitigated and mitigated > 0)

            return FairValueGap(
                upper_price=top,
                lower_price=bottom,
                mid_price=(top + bottom) / 2,
                is_bullish=True,
                start_index=last_idx,
                time=subset.iloc[last_idx]["time"] if "time" in subset.columns else pd.Timestamp.now(),
                filled=filled,
            )
        except Exception:
            return super().detect_bullish_fvg(data, lookback)

    def detect_bearish_fvg(
        self, data: pd.DataFrame, lookback: int = 20
    ) -> Optional[FairValueGap]:
        """Find the most recent unfilled bearish FVG using the external library."""
        if not self._use_library:
            return super().detect_bearish_fvg(data, lookback)

        subset = data.tail(lookback + 5).reset_index(drop=True)
        try:
            fvg_df = _smc.fvg(subset)
            bear_mask = fvg_df["FVG"] == -1
            if not bear_mask.any():
                return None

            last_idx = fvg_df[bear_mask].index[-1]
            top = float(fvg_df.loc[last_idx, "Top"])
            bottom = float(fvg_df.loc[last_idx, "Bottom"])

            mitigated = fvg_df.loc[last_idx, "MitigatedIndex"]
            filled = bool(mitigated and mitigated > 0)

            return FairValueGap(
                upper_price=top,
                lower_price=bottom,
                mid_price=(top + bottom) / 2,
                is_bullish=False,
                start_index=last_idx,
                time=subset.iloc[last_idx]["time"] if "time" in subset.columns else pd.Timestamp.now(),
                filled=filled,
            )
        except Exception:
            return super().detect_bearish_fvg(data, lookback)

    # ── CHoCH ─────────────────────────────────────────────────────────────────
    def detect_bullish_choch(
        self, data: pd.DataFrame, lookback: int = 50
    ) -> Optional[Tuple[int, float]]:
        """Detect bullish CHoCH using the library's bos_choch function."""
        if not self._use_library:
            return super().detect_bullish_choch(data, lookback)

        subset = data.tail(lookback + 10).reset_index(drop=True)
        try:
            swing_df = _smc.swing_highs_lows(subset, swing_length=self.swing_lookback)
            bos_choch_df = _smc.bos_choch(subset, swing_df)

            # CHOCH == 1 → bullish change of character
            bull_choch = bos_choch_df[bos_choch_df["CHOCH"] == 1]
            if bull_choch.empty:
                return None

            last = bull_choch.index[-1]
            level = float(bos_choch_df.loc[last, "Level"])
            return (last, level)
        except Exception:
            return super().detect_bullish_choch(data, lookback)

    def detect_bearish_choch(
        self, data: pd.DataFrame, lookback: int = 50
    ) -> Optional[Tuple[int, float]]:
        """Detect bearish CHoCH using the library's bos_choch function."""
        if not self._use_library:
            return super().detect_bearish_choch(data, lookback)

        subset = data.tail(lookback + 10).reset_index(drop=True)
        try:
            swing_df = _smc.swing_highs_lows(subset, swing_length=self.swing_lookback)
            bos_choch_df = _smc.bos_choch(subset, swing_df)

            # CHOCH == -1 → bearish change of character
            bear_choch = bos_choch_df[bos_choch_df["CHOCH"] == -1]
            if bear_choch.empty:
                return None

            last = bear_choch.index[-1]
            level = float(bos_choch_df.loc[last, "Level"])
            return (last, level)
        except Exception:
            return super().detect_bearish_choch(data, lookback)

    # ── Order Blocks ──────────────────────────────────────────────────────────
    def detect_bullish_order_block(
        self, data: pd.DataFrame, lookback: int = 20
    ) -> Optional[OrderBlock]:
        """Find the most recent untested bullish OB using the external library."""
        if not self._use_library:
            return super().detect_bullish_order_block(data, lookback)

        subset = data.tail(lookback + 5).reset_index(drop=True)
        try:
            swing_df = _smc.swing_highs_lows(subset, swing_length=self.swing_lookback)
            ob_df = _smc.ob(subset, swing_df)

            # OB == 1 → bullish order block
            bull_ob = ob_df[ob_df["OB"] == 1]
            if bull_ob.empty:
                return None

            # Filter un-mitigated OBs
            active = bull_ob[bull_ob["MitigatedIndex"].isna() | (bull_ob["MitigatedIndex"] == 0)]
            if active.empty:
                active = bull_ob  # fall back to last known

            last_idx = active.index[-1]
            top = float(ob_df.loc[last_idx, "Top"])
            bottom = float(ob_df.loc[last_idx, "Bottom"])

            return OrderBlock(
                upper_price=top,
                lower_price=bottom,
                trigger_price=float(subset.iloc[-1]["close"]),
                is_bullish=True,
                strength=3,
                start_index=last_idx,
                time=subset.iloc[last_idx]["time"] if "time" in subset.columns else pd.Timestamp.now(),
                tested=False,
            )
        except Exception:
            return super().detect_bullish_order_block(data, lookback)

    def detect_bearish_order_block(
        self, data: pd.DataFrame, lookback: int = 20
    ) -> Optional[OrderBlock]:
        """Find the most recent untested bearish OB using the external library."""
        if not self._use_library:
            return super().detect_bearish_order_block(data, lookback)

        subset = data.tail(lookback + 5).reset_index(drop=True)
        try:
            swing_df = _smc.swing_highs_lows(subset, swing_length=self.swing_lookback)
            ob_df = _smc.ob(subset, swing_df)

            # OB == -1 → bearish order block
            bear_ob = ob_df[ob_df["OB"] == -1]
            if bear_ob.empty:
                return None

            active = bear_ob[bear_ob["MitigatedIndex"].isna() | (bear_ob["MitigatedIndex"] == 0)]
            if active.empty:
                active = bear_ob

            last_idx = active.index[-1]
            top = float(ob_df.loc[last_idx, "Top"])
            bottom = float(ob_df.loc[last_idx, "Bottom"])

            return OrderBlock(
                upper_price=top,
                lower_price=bottom,
                trigger_price=float(subset.iloc[-1]["close"]),
                is_bullish=False,
                strength=3,
                start_index=last_idx,
                time=subset.iloc[last_idx]["time"] if "time" in subset.columns else pd.Timestamp.now(),
                tested=False,
            )
        except Exception:
            return super().detect_bearish_order_block(data, lookback)

    # ── Market Structure ──────────────────────────────────────────────────────
    def get_market_structure(self, data: pd.DataFrame, lookback: int = 50) -> StructureType:
        """Determine market structure using library swing highs/lows + BOS."""
        if not self._use_library:
            return super().get_market_structure(data, lookback)

        subset = data.tail(lookback + 10).reset_index(drop=True)
        try:
            swing_df = _smc.swing_highs_lows(subset, swing_length=self.swing_lookback)
            bos_choch_df = _smc.bos_choch(subset, swing_df)

            # Get recent BOS signals
            recent_bos = bos_choch_df[bos_choch_df["BOS"].notna()].tail(3)
            if recent_bos.empty:
                return StructureType.NEUTRAL

            last_bos = float(recent_bos.iloc[-1]["BOS"])
            if last_bos == 1:
                return StructureType.BULLISH
            elif last_bos == -1:
                return StructureType.BEARISH
            return StructureType.NEUTRAL
        except Exception:
            return super().get_market_structure(data, lookback)

    # ── Liquidity ─────────────────────────────────────────────────────────────
    def get_liquidity_zones(
        self, data: pd.DataFrame, lookback: int = 100
    ) -> List[LiquidityZone]:
        """Get liquidity zones using the external library."""
        if not self._use_library:
            return []

        subset = data.tail(lookback).reset_index(drop=True)
        zones: List[LiquidityZone] = []
        try:
            swing_df = _smc.swing_highs_lows(subset, swing_length=self.swing_lookback)
            liq_df = _smc.liquidity(subset, swing_df)

            for idx, row in liq_df[liq_df["Liquidity"].notna()].iterrows():
                liq_type = float(row["Liquidity"])
                zones.append(LiquidityZone(
                    level=float(row["Level"]),
                    touch_count=2,  # library confirms only multi-touch groups
                    is_resistance=(liq_type == 1),
                    swept=bool(row.get("Swept", 0) and row["Swept"] > 0),
                ))
        except Exception:
            pass
        return zones


def get_smc_analyzer(
    swing_lookback: int = 5,
    fvg_min_pips: float = 5.0,
    ob_displacement_factor: float = 2.0,
    point: float = 0.1,
) -> SMCAnalyzer:
    """
    Factory: returns SMCLibraryAnalyzer when the external library is available,
    otherwise returns the built-in SMCAnalyzer.
    """
    return SMCLibraryAnalyzer(
        swing_lookback=swing_lookback,
        fvg_min_pips=fvg_min_pips,
        ob_displacement_factor=ob_displacement_factor,
        point=point,
    )
