"""
gen_graph_png.py — render LangGraph state diagram → docs/langgraph_state.png

ใช้ mermaid (styled) แล้ว render ผ่าน mermaid.ink (ออนไลน์) ครั้งเดียว → commit PNG
รัน:  python scripts/gen_graph_png.py

โครงสร้างตรงกับ agents/trading_graph.py:build_trading_graph()
อัปเดตไดอะแกรมเมื่อแก้ graph → รันสคริปต์นี้ใหม่
"""
import base64
import urllib.request
from pathlib import Path

# ── Mermaid (3 เส้นทาง: skip=ส้ม / full=เขียว / net_degraded=แดง) ──────────────
MERMAID = """graph TD
    S(( )) --> E[_entry]
    E -->|skip_ai| P[position_mgmt]
    E -->|full| C["chart<br/>ChartWatcher"]
    C --> A["advisor<br/>MarketAdvisor"]
    A -->|net_degraded| AC[accounting]
    A -->|ok| N[news]
    N --> AN["analyst<br/>sentiment"]
    AN --> D["decision<br/>DecisionMaker"]
    D --> P
    P -->|skip_ai| Z([END])
    P -->|full| R[reporter]
    R --> AC
    AC --> Z

    classDef entry fill:#e8eaf6,stroke:#3f51b5,stroke-width:2px,color:#1a237e
    classDef ai    fill:#e8f5e9,stroke:#43a047,stroke-width:2px,color:#1b5e20
    classDef mgmt  fill:#fff3e0,stroke:#fb8c00,stroke-width:2px,color:#e65100
    classDef term  fill:#eceff1,stroke:#607d8b,stroke-width:2px,color:#263238
    class E entry
    class C,A,N,AN,D ai
    class P,R,AC mgmt
    class S,Z term

    linkStyle 1,9 stroke:#fb8c00,stroke-width:2.5px
    linkStyle 2,10 stroke:#43a047,stroke-width:2.5px
    linkStyle 4 stroke:#e53935,stroke-width:2.5px
"""

OUT = Path(__file__).resolve().parent.parent / "docs" / "langgraph_state.png"


def render(mermaid: str) -> bytes:
    b64 = base64.urlsafe_b64encode(mermaid.encode("utf-8")).decode()
    url = f"https://mermaid.ink/img/{b64}?type=png&bgColor=FFFFFF"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = render(MERMAID)
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        # fallback: mermaid.ink อาจคืน JPEG — แปลงเป็น PNG ด้วย Pillow
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(data)).convert("RGB")
        img.save(OUT, "PNG")
        print(f"[gen] saved (via Pillow convert) -> {OUT}  ({OUT.stat().st_size} bytes)")
    else:
        OUT.write_bytes(data)
        print(f"[gen] saved PNG -> {OUT}  ({len(data)} bytes)")

    try:
        from PIL import Image
        w, h = Image.open(OUT).size
        print(f"[gen] dimensions: {w}x{h}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
