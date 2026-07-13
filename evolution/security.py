from __future__ import annotations

from typing import Optional

_SOL_CHAINS = {"sol", "solana"}
_EVM_CHAINS = {"eth", "ethereum", "bsc", "bnb", "base"}


def check_security(chain: str, snap: dict) -> tuple[bool, Optional[str]]:
    """Return (passes, detail). passes=False → skip writing to evolution_cases."""
    c = (chain or "").lower()
    reasons: list[str] = []

    if c in _SOL_CHAINS:
        # renounced_mint/freeze deliberately excluded — meme coins rarely renounce
        if snap.get("can_not_sell") == 1:
            reasons.append("can_not_sell=1")
        rug = snap.get("rug_ratio")
        if rug is not None and rug > 0.3:
            reasons.append(f"rug_ratio={rug:.2f}")

    elif c in _EVM_CHAINS:
        if snap.get("is_honeypot") == "yes":
            reasons.append("is_honeypot=true")
        if snap.get("can_not_sell") == 1:
            reasons.append("can_not_sell=1")
        if snap.get("is_blacklist") == "yes":
            reasons.append("is_blacklist=true")
        rug = snap.get("rug_ratio")
        if rug is not None and rug > 0.3:
            reasons.append(f"rug_ratio={rug:.2f}")

    if reasons:
        return False, "; ".join(reasons)
    return True, None
