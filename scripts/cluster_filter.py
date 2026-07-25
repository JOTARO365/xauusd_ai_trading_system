"""scripts/cluster_filter.py — OFFLINE breakout-quality filter via unsupervised clustering (KMeans/GMM).

สมมติฐาน: momentum breakout ที่ **ทะลุออกจาก price-cluster (S/R หนาแน่น) เข้าที่โล่ง** = คุณภาพสูงกว่า
breakout ในที่โล่งอยู่แล้ว/ชนกำแพงข้างหน้า. ใช้ unsupervised clustering (sklearn KMeans/GMM) หา S/R zone
จาก price ล่าสุด → คำนวณ feature คุณภาพต่อ breakout. **ยังไม่แตะ live** — validate ก่อน (validate_cluster_filter.py).

CORE INVARIANT: clustering เลือก "เมื่อไหร่ momentum eligible" (SELECTION) ไม่ตั้งราคา entry (EXECUTION ยัง deterministic).
READ-ONLY (คำนวณล้วน, ไม่แตะ MT5/order).
"""
import warnings

import numpy as np

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from sklearn.cluster import KMeans
    from sklearn.mixture import GaussianMixture


def _price_sample(high, low, close, i, window):
    """levels ที่ราคาแตะในหน้าต่าง [i-window, i] (high+low+close = จุดที่ราคาใช้เวลา/กลับตัว)."""
    a = max(0, i - window)
    return np.concatenate([high[a:i + 1], low[a:i + 1], close[a:i + 1]]).astype(float)


def _pick_k(sample, atr, k_min=3, k_max=8):
    """heuristic K จากช่วงราคา/ATR (คู่กว้าง=cluster เยอะ) clamp [k_min,k_max]."""
    if atr <= 0:
        return k_min
    span = float(sample.max() - sample.min())
    return int(np.clip(round(span / (2.0 * atr)), k_min, k_max))


def fit_clusters(sample, atr, method="kmeans", k=None):
    """fit → คืน (centers[sorted], weights[align centers]) โดย weight = สัดส่วนตัวอย่างในกลุ่ม.
    GMM ใช้ BIC เลือก K; KMeans ใช้ heuristic. fail-soft → (None, None)."""
    x = np.asarray(sample, float).reshape(-1, 1)
    n = len(x)
    if n < 12:
        return None, None
    kk = k or _pick_k(sample, atr)
    kk = int(min(kk, n))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if method == "gmm":
                best, best_bic = None, np.inf
                for cand in range(3, min(9, n) + 1):
                    g = GaussianMixture(cand, covariance_type="spherical", random_state=0, n_init=1).fit(x)
                    b = g.bic(x)
                    if b < best_bic:
                        best_bic, best = b, g
                centers = best.means_.ravel()
                weights = best.weights_.ravel()
            else:
                km = KMeans(n_clusters=kk, n_init=10, random_state=0).fit(x)
                centers = km.cluster_centers_.ravel()
                counts = np.bincount(km.labels_, minlength=kk).astype(float)
                weights = counts / counts.sum()
    except Exception:
        return None, None
    order = np.argsort(centers)
    return centers[order], weights[order]


def breakout_quality(high, low, close, i, level, direction, atr,
                     *, window=150, method="kmeans", k=None, clearance_cap=3.0):
    """feature คุณภาพของ breakout ที่บาร์ i ทะลุ `level` ทิศ `direction`.
    คืน dict: wall_strength (0-1 = ทะลุ cluster หนักแค่ไหน), clearance_atr (ที่โล่งข้างหน้า, capped),
    entry_density (0-1 = ความแออัด cluster ที่ราคาปัจจุบัน), n_clusters, quality (0-1 = คะแนนรวม default).
    ATR/price-relative ทั้งหมด → symbol-agnostic. คืน None ถ้า fit ไม่ได้."""
    if atr is None or atr <= 0:
        return None
    sample = _price_sample(high, low, close, i, window)
    centers, weights = fit_clusters(sample, atr, method=method, k=k)
    if centers is None or len(centers) == 0:
        return None
    is_buy = direction == "BUY"

    # cluster ที่ถูกทะลุ = ใกล้ level สุด → weight = wall_strength
    d_level = np.abs(centers - level)
    j_wall = int(np.argmin(d_level))
    wall_strength = float(weights[j_wall])

    # ที่โล่งข้างหน้า = ระยะถึง cluster ถัดไปในทิศ breakout (ATR units)
    if is_buy:
        ahead = centers[centers > level + 1e-9]
    else:
        ahead = centers[centers < level - 1e-9]
    if len(ahead) == 0:
        clearance_atr = clearance_cap                        # ไม่มี cluster ขวาง = โล่งสุด
    else:
        nxt = ahead.min() if is_buy else ahead.max()
        clearance_atr = float(min(abs(nxt - level) / atr, clearance_cap))

    # ความแออัดที่ราคาปัจจุบัน (close[i]) = weight cluster ใกล้สุด
    px = float(close[i])
    entry_density = float(weights[int(np.argmin(np.abs(centers - px)))])

    # quality default: ทะลุกำแพงหนัก (wall) + มีที่วิ่ง (clearance) = ดี. interpretable, ให้ validate ปรับ.
    quality = float(wall_strength * (clearance_atr / clearance_cap))

    return {"wall_strength": round(wall_strength, 4),
            "clearance_atr": round(clearance_atr, 3),
            "entry_density": round(entry_density, 4),
            "n_clusters": int(len(centers)),
            "quality": round(quality, 4)}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    # smoke test: synthetic price ที่มี cluster ชัด แล้ว breakout ทะลุออก
    rng = np.arange(200)
    base = 70.0 + 0.5 * np.sin(rng / 8.0)                    # แกว่งใน band = cluster หนาแน่น
    base[-5:] = base[-6] + np.array([0.3, 0.6, 1.0, 1.4, 1.8])  # breakout ขึ้น
    high = base + 0.15; low = base - 0.15; close = base
    atr = 0.25
    lvl = float(high[-8:-2].max())                           # Donchian-ish level
    q = breakout_quality(high, low, close, len(close) - 2, lvl, "BUY", atr)
    print("smoke breakout_quality:", q)
