"""
TrendScore V6 Engine — "How Much Will It Rise?"
=================================================

THE ONE QUESTION: What % will this stock go HIGHER in the next 1-2 years?

This is NOT a "company quality" score. It is a PERCENTAGE UPSIDE score.
NVIDIA can be the best company on earth and score LOWER than a $20 stock
nobody's watching — because the market already priced NVIDIA's greatness
into a $2.8T valuation. The $20 stock with real catalysts can 5x-10x.

THE CORE FORMULA:
  Score = (Future Potential - What Market Already Priced In) × Confidence

  A score of 800 means: "This stock has massive % upside that the market
  hasn't recognized yet, and we're confident about it."

  A score of 400 means: "Good company, but the market already knows it.
  Limited % upside from here."

Philosophy:
- The algorithm does NOT reward being a great company
- It rewards being a great company THAT THE MARKET UNDERVALUES
- A $20 stock going to $200 (10x) ALWAYS beats a $500 stock going to $700 (1.4x)
- Big companies CAN still score high IF the market hasn't priced in a major catalyst
- Small companies DON'T get free points for being small — they must have real catalysts
- EVERYTHING is measured by: "How much % upside is NOT yet in the price?"

The V6 Stocking Score (1-1000):
================================

PILLAR 1: UPSIDE GAP (30%) — "How much growth is NOT priced in yet?"
  The most important pillar. Measures the difference between:
  - What the company WILL be worth (based on all other pillars)
  - What the market CURRENTLY prices it at
  Sub-factors:
  - Forward P/E vs Growth Rate (PEG ratio) — low PEG = undervalued growth
  - Price vs Intrinsic Value — DCF, EV/EBITDA relative to peers
  - Market Expectations Gap — analyst consensus vs what's actually happening
  - Catalyst Timeline — upcoming events that will force re-pricing
  - Sector Re-rating Potential — is the whole sector about to get repriced?
  - Institutional Discovery — are big funds just starting to notice?
  - Revenue Inflection Point — is revenue about to accelerate?
  Example: NVIDIA already trades at 50x earnings, market KNOWS it's great = LOW gap
  Example: A $15B infrastructure company about to win $5B in AI data center contracts
           that analysts haven't modeled = HUGE gap = HIGH score

PILLAR 2: DIG / MOAT (20%) — "What makes you irreplaceable?"
  Still matters, but now in service of: "Will this moat GROW the stock %?"
  A moat only helps the score if it's either:
  (a) Not yet priced in by the market, OR
  (b) Getting STRONGER (expanding moat = future repricing)
  Sub-factors: Infrastructure, supply chain bottleneck, switching costs,
  network effects, tech moat, scale, ecosystem, regulatory, data, vertical integration

PILLAR 3: MONEY FLOW TRAJECTORY (15%) — "Where is big money going NEXT?"
  Forward-looking: where is money SHIFTING to, not where it already is.
  Sub-factors:
  - Sector rotation signals (money leaving one sector, entering another)
  - Institutional accumulation (smart money BUILDING positions, not holding)
  - Capex pipeline ($690B AI infra spend — who captures the NEXT wave?)
  - Customer pipeline (backlog, LOIs, pending contracts)
  - Product catalysts (launches that will drive re-pricing)
  - Geographic expansion (new markets opening)

PILLAR 4: DEBT INTELLIGENCE (10%) — "Does debt limit the % upside?"
  Debt matters because it caps how much a stock can rise.
  A company with massive debt has a ceiling on its multiple expansion.
  Sub-factors:
  - Debt-to-FCF years (can they pay it off FAST enough?)
  - Interest burden vs growth investment
  - Debt trajectory (improving = upside, worsening = ceiling)
  - Strategic debt (borrowing to grow = OK if growth materializes)
  - Peer comparison (is debt normal for the sector?)

PILLAR 5: GROWTH ENGINE (15%) — "Is growth ACCELERATING?"
  Not just "is it growing?" but "is growth SPEEDING UP?"
  Accelerating growth = market will reprice higher.
  Decelerating growth = market will reprice lower (even if still growing).
  Sub-factors:
  - Revenue acceleration (QoQ growth rate INCREASING?)
  - Margin expansion trajectory
  - Customer acquisition velocity (speeding up?)
  - TAM expansion rate
  - R&D pipeline about to monetize
  - Forward guidance vs current trajectory

PILLAR 6: TREND & DISCOVERY (10%) — "Is the market ABOUT TO notice?"
  Being trending is bad if everyone already knows (priced in).
  Being ABOUT TO trend is gold (not yet priced in).
  Sub-factors:
  - Early institutional discovery (first big fund buying in)
  - Analyst initiation (coverage just starting)
  - Retail discovery curve (early stage = good, late stage = priced in)
  - News catalyst pipeline (upcoming events that will drive attention)
  - CEO visibility trajectory (rising profile = upcoming repricing)

THE PRICED-IN PENALTY:
  Everything gets REDUCED by how much the market has ALREADY priced in.
  This is the key innovation:
  - $2.8T market cap with 50x P/E? Market already knows = heavy penalty
  - $15B market cap with 15x P/E and accelerating growth? Under-radar = bonus
  - This is NOT a "small cap bonus" — a $15B company with no catalysts still scores low
  - This IS a "the market hasn't figured it out yet" bonus

  Priced-In Factor = f(P/E relative to growth, market cap vs revenue trajectory,
                       analyst coverage density, institutional ownership %)
  Range: 0.5 (fully priced in) to 1.5 (massively undervalued)

RISK PENALTY (x0.5 to x1.0):
  - Debt crisis risk, concentration risk, regulatory risk
  - Competition acceleration (someone catching up FAST)
  - Management risk, sector headwind
  - Disruption risk (about to be made obsolete)
"""

import math
import json
from datetime import datetime
from typing import Dict, List, Optional


# ============================================================
# V6 SCORING CONSTANTS — % UPSIDE FOCUSED
# ============================================================

V6_WEIGHTS = {
    "upside_gap":  0.30,   # 30% — How much growth is NOT priced in?
    "dig":         0.20,   # 20% — Moat (only if not yet priced in)
    "money_flow":  0.15,   # 15% — Where is big money going NEXT?
    "debt_iq":     0.10,   # 10% — Does debt limit the % upside?
    "growth":      0.15,   # 15% — Is growth ACCELERATING?
    "discovery":   0.10,   # 10% — Is the market ABOUT TO notice?
}

MAX_SCORE = 1000


# ============================================================
# SUB-FACTOR DEFINITIONS
# ============================================================

UPSIDE_GAP_SUBFACTORS = [
    "peg_ratio",              # Forward P/E vs Growth Rate — low = undervalued
    "price_vs_intrinsic",     # DCF gap, EV/EBITDA relative to peers
    "expectations_gap",       # What analysts expect vs what's actually happening
    "catalyst_timeline",      # Upcoming events forcing re-pricing
    "sector_rerate",          # Whole sector about to get repriced?
    "institutional_discovery",# Big funds just starting to notice?
    "revenue_inflection",     # Revenue about to accelerate?
]

DIG_SUBFACTORS = [
    "infrastructure_ownership",
    "supply_chain_position",
    "switching_costs",
    "network_effects",
    "technology_moat",
    "scale_advantage",
    "ecosystem_lockin",
    "regulatory_moat",
    "data_moat",
    "vertical_integration",
]

MONEY_FLOW_SUBFACTORS = [
    "sector_rotation",        # Money leaving one sector, entering another
    "institutional_accumulation",
    "capex_pipeline_capture",
    "customer_pipeline",
    "product_catalyst",
    "geographic_expansion",
    "contract_momentum",
]

DEBT_SUBFACTORS = [
    "debt_to_fcf_years",
    "interest_vs_growth",
    "debt_trajectory",
    "strategic_debt_quality",
    "peer_comparison",
]

GROWTH_SUBFACTORS = [
    "revenue_acceleration",   # QoQ growth rate INCREASING?
    "margin_expansion",
    "customer_velocity",      # Customer acquisition speeding up?
    "tam_expansion",
    "rd_monetization",        # R&D pipeline about to pay off?
    "guidance_vs_trajectory", # Forward guidance above current trend?
]

DISCOVERY_SUBFACTORS = [
    "institutional_early",    # First big fund buying in
    "analyst_initiation",     # Coverage just starting
    "retail_discovery_stage", # Early = good, late = priced in
    "news_catalyst_pipeline", # Upcoming events driving attention
    "ceo_visibility_rising",  # Rising profile = upcoming repricing
]


class StockingScoreV6:
    """
    V6 Stocking Score Engine — Predicts % UPSIDE, not company quality.

    The score answers: "How much will this stock rise in percentage?"
    NOT: "How good is this company?"

    NVIDIA = great company, but if market already priced it in = lower score.
    Unknown $20 stock with real catalysts = higher score IF upside is real.
    """

    def __init__(self):
        self.scores = {}

    def score_stock(self, ticker: str, data: Dict) -> Dict:
        """
        Score a single stock for % UPSIDE potential (1-1000).

        The score predicts how much the stock will rise in percentage,
        NOT how good the company is.
        """
        # PILLAR 1: UPSIDE GAP — how much is NOT priced in (0-100)
        upside_raw = self._calc_upside_gap(data.get("upside_scores", {}))

        # PILLAR 2: DIG/MOAT — only counts if not priced in (0-100)
        dig_raw = self._calc_dig(data.get("dig_scores", {}))

        # PILLAR 3: MONEY FLOW — where is money going NEXT (0-100)
        flow_raw = self._calc_money_flow(data.get("money_flow_scores", {}))

        # PILLAR 4: DEBT IQ — does debt cap the upside? (0-100)
        debt_raw = self._calc_debt_iq(data.get("debt_scores", {}))

        # PILLAR 5: GROWTH — is growth ACCELERATING? (0-100)
        growth_raw = self._calc_growth(data.get("growth_scores", {}))

        # PILLAR 6: DISCOVERY — is market ABOUT TO notice? (0-100)
        discovery_raw = self._calc_discovery(data.get("discovery_scores", {}))

        # WEIGHTED COMBINATION (0-100)
        weighted = (
            upside_raw * V6_WEIGHTS["upside_gap"] +
            dig_raw * V6_WEIGHTS["dig"] +
            flow_raw * V6_WEIGHTS["money_flow"] +
            debt_raw * V6_WEIGHTS["debt_iq"] +
            growth_raw * V6_WEIGHTS["growth"] +
            discovery_raw * V6_WEIGHTS["discovery"]
        )

        # PRICED-IN PENALTY — the market already knows? reduce score
        priced_in = self._calc_priced_in_factor(data)

        # RISK PENALTY (x0.5 to x1.0)
        risk_mult = self._calc_risk_penalty(data.get("risk_factors", {}))

        # FINAL SCORE (1-1000)
        # weighted (0-100) × priced_in (0.5-1.5) × risk (0.5-1.0) × 10
        final = weighted * priced_in * risk_mult * 10
        final = max(1, min(MAX_SCORE, round(final)))

        result = {
            "ticker": ticker,
            "score": final,
            "grade": self._get_grade(final),
            "pillars": {
                "upside_gap": round(upside_raw, 1),
                "dig": round(dig_raw, 1),
                "money_flow": round(flow_raw, 1),
                "debt_iq": round(debt_raw, 1),
                "growth": round(growth_raw, 1),
                "discovery": round(discovery_raw, 1),
            },
            "priced_in_factor": round(priced_in, 3),
            "risk_multiplier": round(risk_mult, 3),
            "weighted_raw": round(weighted, 1),
            "market_cap": data.get("market_cap", 0),
            "price": data.get("price", 0),
            "sector": data.get("sector", ""),
            "company": data.get("company", ""),
        }

        self.scores[ticker] = result
        return result

    def _calc_upside_gap(self, scores: Dict) -> float:
        """
        THE KEY PILLAR: How much potential growth is NOT yet in the price?

        This is the difference between what the company WILL be worth
        and what the market CURRENTLY prices it at.
        """
        if not scores:
            return 30

        weights = {
            "peg_ratio": 1.4,              # Low PEG = undervalued growth
            "price_vs_intrinsic": 1.3,     # Below intrinsic value = opportunity
            "expectations_gap": 1.2,       # Reality > expectations = upside
            "catalyst_timeline": 1.3,      # Near-term catalysts force repricing
            "sector_rerate": 1.0,          # Sector-wide repricing coming?
            "institutional_discovery": 1.1,# Smart money just finding it
            "revenue_inflection": 1.2,     # Revenue about to jump
        }

        weighted_sum = sum(
            scores.get(f, 30) * weights.get(f, 1.0)
            for f in UPSIDE_GAP_SUBFACTORS
        )
        total_weight = sum(weights.get(f, 1.0) for f in UPSIDE_GAP_SUBFACTORS)
        return min(100, weighted_sum / total_weight)

    def _calc_dig(self, scores: Dict) -> float:
        """Moat — but only valuable if it drives FUTURE % gains."""
        if not scores:
            return 30
        weights = {
            "infrastructure_ownership": 1.1,
            "supply_chain_position": 1.2,
            "switching_costs": 1.0,
            "network_effects": 1.0,
            "technology_moat": 1.1,
            "scale_advantage": 0.9,
            "ecosystem_lockin": 1.0,
            "regulatory_moat": 0.9,
            "data_moat": 1.0,
            "vertical_integration": 0.9,
        }
        weighted_sum = sum(
            scores.get(f, 30) * weights.get(f, 1.0)
            for f in DIG_SUBFACTORS
        )
        total_weight = sum(weights.get(f, 1.0) for f in DIG_SUBFACTORS)
        return min(100, weighted_sum / total_weight)

    def _calc_money_flow(self, scores: Dict) -> float:
        """Where is money SHIFTING to next?"""
        if not scores:
            return 25
        weights = {
            "sector_rotation": 1.2,
            "institutional_accumulation": 1.3,
            "capex_pipeline_capture": 1.1,
            "customer_pipeline": 1.2,
            "product_catalyst": 1.1,
            "geographic_expansion": 0.9,
            "contract_momentum": 1.2,
        }
        weighted_sum = sum(
            scores.get(f, 25) * weights.get(f, 1.0)
            for f in MONEY_FLOW_SUBFACTORS
        )
        total_weight = sum(weights.get(f, 1.0) for f in MONEY_FLOW_SUBFACTORS)
        return min(100, weighted_sum / total_weight)

    def _calc_debt_iq(self, scores: Dict) -> float:
        """Does debt create a ceiling on % upside?"""
        if not scores:
            return 50
        weights = {
            "debt_to_fcf_years": 1.4,
            "interest_vs_growth": 1.2,
            "debt_trajectory": 1.1,
            "strategic_debt_quality": 1.0,
            "peer_comparison": 0.8,
        }
        weighted_sum = sum(
            scores.get(f, 50) * weights.get(f, 1.0)
            for f in DEBT_SUBFACTORS
        )
        total_weight = sum(weights.get(f, 1.0) for f in DEBT_SUBFACTORS)
        return min(100, weighted_sum / total_weight)

    def _calc_growth(self, scores: Dict) -> float:
        """Is growth ACCELERATING? Not just "is it growing."
        Accelerating growth = market will reprice higher."""
        if not scores:
            return 30
        weights = {
            "revenue_acceleration": 1.4,   # Acceleration > absolute growth
            "margin_expansion": 1.1,
            "customer_velocity": 1.2,
            "tam_expansion": 1.0,
            "rd_monetization": 1.1,
            "guidance_vs_trajectory": 1.2,
        }
        weighted_sum = sum(
            scores.get(f, 30) * weights.get(f, 1.0)
            for f in GROWTH_SUBFACTORS
        )
        total_weight = sum(weights.get(f, 1.0) for f in GROWTH_SUBFACTORS)
        return min(100, weighted_sum / total_weight)

    def _calc_discovery(self, scores: Dict) -> float:
        """Is the market ABOUT TO notice? Early discovery = massive upside."""
        if not scores:
            return 30
        weights = {
            "institutional_early": 1.3,
            "analyst_initiation": 1.2,
            "retail_discovery_stage": 1.0,
            "news_catalyst_pipeline": 1.1,
            "ceo_visibility_rising": 0.9,
        }
        weighted_sum = sum(
            scores.get(f, 30) * weights.get(f, 1.0)
            for f in DISCOVERY_SUBFACTORS
        )
        total_weight = sum(weights.get(f, 1.0) for f in DISCOVERY_SUBFACTORS)
        return min(100, weighted_sum / total_weight)

    def _calc_priced_in_factor(self, data: Dict) -> float:
        """
        THE PRICED-IN PENALTY — How much does the market ALREADY know?

        This is NOT a market cap bonus/penalty. It's a KNOWLEDGE bonus/penalty.
        A $500B company where the market has NO IDEA about an upcoming catalyst
        gets the same boost as a $5B company in the same situation.

        But in practice, larger companies get more analyst coverage, more
        institutional ownership, and more efficient pricing — so their
        upside gap tends to be smaller. This is natural, not artificial.

        Range: 0.5 (fully priced in, no upside) to 1.5 (massively undervalued)
        """
        priced_in_score = data.get("priced_in_score", 50)  # 0-100

        # 0 = fully priced in → factor = 0.5
        # 50 = neutral → factor = 1.0
        # 100 = massively undervalued → factor = 1.5
        return 0.5 + (priced_in_score / 100)

    def _calc_risk_penalty(self, risks: Dict) -> float:
        """Risk multiplier (0.5 to 1.0)."""
        penalty = 0
        penalty += (risks.get("debt_crisis", 0) / 100) * 0.15
        penalty += (risks.get("concentration", 0) / 100) * 0.10
        penalty += (risks.get("regulatory", 0) / 100) * 0.08
        penalty += (risks.get("competition_threat", 0) / 100) * 0.10
        penalty += (risks.get("management", 0) / 100) * 0.05
        penalty += (risks.get("sector_headwind", 0) / 100) * 0.04
        penalty += (risks.get("disruption", 0) / 100) * 0.08
        return max(0.5, 1.0 - penalty)

    def _get_grade(self, score: int) -> str:
        if score >= 800: return "S"
        if score >= 680: return "A"
        if score >= 550: return "B"
        if score >= 400: return "C"
        if score >= 280: return "D"
        if score >= 150: return "E"
        return "F"

    def rank_all(self) -> List[Dict]:
        ranked = sorted(self.scores.values(), key=lambda x: x["score"], reverse=True)
        for i, stock in enumerate(ranked):
            stock["rank"] = i + 1
        return ranked

    def export_json(self, filepath: str):
        output = {
            "algorithm": "TrendScore V6 — How Much Will It Rise?",
            "timestamp": datetime.now().isoformat(),
            "weights": V6_WEIGHTS,
            "total_stocks": len(self.scores),
            "rankings": self.rank_all(),
        }
        with open(filepath, "w") as f:
            json.dump(output, f, indent=2, default=str)
        return filepath


# ============================================================
# V6 ALGORITHM SUMMARY
# ============================================================

V6_ALGORITHM_DOC = """
STOCKING SCORE V6 — "HOW MUCH WILL IT RISE?"
==============================================

THE ONE QUESTION: What % will this stock go HIGHER?

NOT "how good is this company" — but "how much UPSIDE is left?"
NVIDIA at $2.8T with 50x P/E = market already knows = LIMITED % upside
A $15B company with incoming $5B in contracts analysts missed = MASSIVE % upside

THE 6 PILLARS:

1. UPSIDE GAP (30%)
   How much growth is NOT yet priced in?
   PEG ratio, DCF gap, expectations vs reality, catalyst timeline,
   sector re-rating, institutional discovery, revenue inflection.

2. DIG / MOAT (20%)
   What makes you irreplaceable? But only counts toward score
   IF the moat isn't already priced into the stock.

3. MONEY FLOW (15%)
   Where is big money going NEXT? Sector rotation, institutional
   accumulation, capex capture, customer pipeline, product catalysts.

4. DEBT IQ (10%)
   Does debt cap the % upside? Smart debt analysis.

5. GROWTH ENGINE (15%)
   Is growth ACCELERATING? Acceleration > absolute growth.
   QoQ growth rate increasing, margins expanding, TAM growing.

6. DISCOVERY (10%)
   Is the market ABOUT TO notice? Early discovery = highest upside.
   Late discovery = already priced in.

MODIFIERS:

PRICED-IN FACTOR (x0.5 to x1.5):
   How much does the market already know?
   NOT a size bonus — a KNOWLEDGE gap bonus.
   x0.5 = everyone knows, fully priced in
   x1.0 = neutral
   x1.5 = massively undervalued, market hasn't figured it out

RISK PENALTY (x0.5 to x1.0):
   Debt crisis, competition, disruption, regulatory, management.

GRADE SCALE:
   S: 800-1000 — massive % upside potential
   A: 680-799 — strong % upside
   B: 550-679 — moderate upside
   C: 400-549 — limited upside
   D: 280-399 — minimal upside or priced in
   E/F: below 280 — avoid
"""

if __name__ == "__main__":
    print(V6_ALGORITHM_DOC)
