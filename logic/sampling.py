"""
Dealing hero a hand they could actually be holding.

Hands used to be drawn uniformly from the deck regardless of the node. But hero
only reaches a `vs_3Bet` node by opening and a `vs_4Bet` node by 3-betting, so
most of those deals were hands hero could not have: around 75% on average across
the 17 such charts, and 95% at `BTN_vs_MP_4Bet`.

Those reps are worse than wasted. The spot cannot occur, and because the chart
folds everything outside the reachable range, the answer is always FOLD - so the
drill rewards reflexive folding at exactly the nodes that are hardest to play.

The reachable range comes from `chart_schema.prior_range_key`, the same
definition the validator uses, so the trainer and the validator cannot disagree
about what hero can be holding.
"""
from __future__ import annotations

import logging
import random

from .chart_schema import combo_count, index_prior_ranges, prior_range_keys, resolve_prior_range
from .scenario import Hand, get_random_hand, random_hand_of

logger = logging.getLogger(__name__)


class ReachabilitySampler:
    """Deals hero a hand from the range that can actually arrive at each node."""

    def __init__(self, charts: dict[str, dict]):
        prior_ranges = index_prior_ranges(charts)
        self._pools: dict[str, tuple[list[str], list[int]]] = {}

        for key, data in charts.items():
            meta = data.get("metadata", {})
            if not prior_range_keys(meta):
                continue  # hero has not acted; the whole deck is reachable

            prior = resolve_prior_range(meta, prior_ranges)
            if prior is None:
                logger.warning(
                    "No prior range for %s; dealing from the full deck, so most "
                    "of these scenarios will be spots hero cannot reach",
                    key,
                )
                continue

            hands = sorted(prior[2])
            self._pools[key] = (hands, [combo_count(hand) for hand in hands])

    def pool(self, chart_key: str) -> list[str] | None:
        """The hand classes hero can hold here, or None if hero can hold anything."""
        entry = self._pools.get(chart_key)
        return list(entry[0]) if entry else None

    def weighted_pool(self, chart_key: str) -> tuple[list[str], list[int]] | None:
        """The hand classes hero can hold here with their combo weights, or None for the full deck."""
        entry = self._pools.get(chart_key)
        return (list(entry[0]), list(entry[1])) if entry else None

    def deal(self, chart_key: str) -> Hand:
        """
        Deal hero a hand for this node.

        Weighted by combinations, so the mix of pairs, suited and offsuit hands
        matches what a real deal from that range would look like.
        """
        entry = self._pools.get(chart_key)
        if entry is None:
            return get_random_hand()
        hands, weights = entry
        return random_hand_of(random.choices(hands, weights=weights, k=1)[0])
