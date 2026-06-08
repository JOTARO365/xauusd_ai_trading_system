"""
Pydantic output schemas for all Claude agents.
Used with ChatAnthropic.with_structured_output() to eliminate manual parsers.
"""
from pydantic import BaseModel, Field
from typing import Literal, List


class ChartWatcherOutput(BaseModel):
    signal: Literal["BUY", "SELL", "NO_TRADE"]
    confidence: int = Field(ge=0, le=100)
    trend: str
    sr_zone: Literal["RESISTANCE", "SUPPORT", "NONE"]
    sr_strength: Literal["STRONG", "NORMAL", "WEAK"]
    entry_type: Literal[
        "SR_ZONE", "EMA_PULLBACK", "BREAKOUT_RETEST", "ENGULFING",
        "DOJI_AT_ZONE", "MOMENTUM_BREAKOUT", "STRUCTURE_PULLBACK", "NONE"
    ]
    momentum: Literal["UP_STRONG", "UP_MODERATE", "DOWN_STRONG", "DOWN_MODERATE", "FLAT"]
    fib_level: str = Field(default="NONE")
    sl_pips: int = Field(ge=100, le=3500)
    tp_pips: int = Field(ge=100)
    entry_reason: List[str] = Field(default_factory=list)
    risk_note: str = Field(default="none")


class IntradayStructure(BaseModel):
    h4: Literal["BULLISH", "BEARISH", "SIDEWAYS"]
    h1: Literal["TREND", "PULLBACK", "RANGE"]
    m15: Literal["MOMENTUM_UP", "MOMENTUM_DOWN", "WEAK"]


class MarketAdvisorOutput(BaseModel):
    regime: Literal["BULLISH_TREND", "BEARISH_TREND", "SIDEWAYS", "TRANSITION"]
    regime_confidence: int = Field(ge=0, le=95)
    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    volatility: Literal["LOW", "NORMAL", "HIGH"]
    tp_style: Literal["WIDE", "NORMAL", "TIGHT"]
    top_setup: str = Field(default="NO_DATA")
    best_indicators: List[str] = Field(default_factory=list)
    intraday_structure: IntradayStructure
    advisor_note: str = Field(default="")


class AnalystOutput(BaseModel):
    # decision drivers (ใช้จริง downstream) — ห้ามแตะ
    sentiment: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    confidence: int = Field(ge=0, le=90)
    bias: Literal["BUY", "SELL", "NEUTRAL"]
    # rationale — ใช้แค่ 60 ตัวแรก (decision_maker log) → จำกัดสั้นเพื่อลด output token
    summary: str = Field(default="", description="เหตุผลสั้นมาก 1 วลี ไม่เกิน 60 ตัวอักษร")
    # หมายเหตุ: ตัด key_factors + alignment ออก (generate แล้วทิ้ง ไม่ถูกใช้ downstream — ลด output token)


class DecisionMakerOutput(BaseModel):
    decision: Literal["EXECUTE", "SKIP"]
    direction: Literal["BUY", "SELL", "NONE"] = "NONE"
    trade_quality: Literal["A+", "B", "C", "SKIP"] = "SKIP"
    confidence_score: int = Field(ge=0, le=100, default=0)
    reason: str = Field(default="")
