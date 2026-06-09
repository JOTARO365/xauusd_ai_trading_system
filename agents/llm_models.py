"""Single source of truth: agent -> model id.

ทุก agent + accounting อ่าน model จากที่นี่ที่เดียว → สลับ model/provider ของ agent
ทำได้ด้วยการตั้ง env ตัวเดียว (เช่น MODEL_ANALYST=grok-...) แล้ว accounting จะตามให้เอง.

⚠️ การสลับ "ข้าม provider" (เช่น analyst → Grok) ต้องทำ 3 อย่างพร้อมกัน ไม่ใช่แค่ตั้ง env:
   1) ตั้ง MODEL_<AGENT> เป็น model id ของ provider ใหม่
   2) wire client ของ provider นั้นใน agent (ChatAnthropic → ChatXAI/ChatGoogleGenerativeAI ฯลฯ)
   3) เพิ่มราคา model ใหม่ใน agents/accountant.py::_PRICING (ไม่งั้น cost คำนวณด้วย fallback = ผิด)
   ตั้ง env อย่างเดียวโดยไม่ทำ (2) → agent ยังเรียก provider เดิม แต่ accounting นึกว่าเป็นตัวใหม่ (เพี้ยน).
"""
import os

AGENT_MODELS: dict[str, str] = {
    "chart_watcher":  os.getenv("MODEL_CHART_WATCHER")  or "claude-sonnet-4-6",
    "market_advisor": os.getenv("MODEL_MARKET_ADVISOR") or "claude-sonnet-4-6",
    "analyst":        os.getenv("MODEL_ANALYST")        or "claude-sonnet-4-6",
    "decision_maker": os.getenv("MODEL_DECISION_MAKER") or "claude-sonnet-4-6",
    "reporter":       os.getenv("MODEL_REPORTER")       or "claude-haiku-4-5-20251001",
}


def model_for(agent: str) -> str:
    """คืน model id ที่ตั้งไว้สำหรับ agent (default = Sonnet)."""
    return AGENT_MODELS.get(agent, "claude-sonnet-4-6")
