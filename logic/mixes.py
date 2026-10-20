"""
Which hands a chart plays more than one way.

A chart assigns each of the 169 hands exactly one action, which states a hard
line where real preflop strategy has a gradient. Around 12% of drilled hands
sit on one of those lines - 30% in the Big Blind defending spots - and at those
nodes a solver mixes. Marking them pure means the trainer calls a legitimate
action wrong and docks the user for it, which over a long enough session
teaches them out of the mixed action and into an exploitable pure strategy.

Real mixing frequencies need a solver. What does not need one is *which* hands
are close, because that is structural: a hand is a close decision when the hand
immediately next to it in the range matrix is played differently. 76s is a
marginal call precisely when 75s folds and 87s calls.

So this derives the boundary, not the frequency. A hand on a boundary is
accepted either way and reported as close, rather than scored as wrong. When
solver output is available the same field can carry real frequencies without
any change to how the rest of the app reads it.
"""
from __future__ import annotations

RANKS = "AKQJT98765432"

#: Below this many reachable hands, an action group is too small for adjacency
#: to mean anything - every member touches an edge.
MIN_GROUP_FOR_MIXING = 3


def neighbours(hand: str) -> list[str]:
    """
    The hands one step away in the range matrix.

    For a pair, the pair above and below. For a suited or offsuit hand, the
    same high card with the next kicker up and down. That adjacency is what
    "the next hand along" means when reading a chart.
    """
    if len(hand) == 2:
        index = RANKS.index(hand[0])
        return [RANKS[i] * 2 for i in (index - 1, index + 1) if 0 <= i < len(RANKS)]

    high, low, suffix = hand[0], hand[1], hand[2]
    index = RANKS.index(low)
    return [
        high + RANKS[i] + suffix
        for i in (index - 1, index + 1)
        if 0 <= i < len(RANKS) and RANKS[i] != high
    ]


def derive_mixes(
    actions_by_hand: dict[str, str], reachable: set[str] | None = None
) -> dict[str, list[str]]:
    """
    Map each boundary hand to the actions it should be allowed to take.

    The hand's own action comes first, so callers can still treat it as the
    primary recommendation. Only hands that sit on a boundary appear;
    everything else stays pure.

    Two deliberate limits:

    * **At most one alternative.** A hand next to both a raise and a fold would
      otherwise accept all three actions, which leaves no wrong answer and
      teaches nothing. The alternative held by more neighbours wins; a tie means
      the structure is genuinely ambiguous, so the chart's single answer stands
      rather than being weakened.
    * **Reachable hands only.** At a node hero arrives at by raising, most of
      the 169 cannot be dealt - marking JJ as a close decision facing a 5-bet
      is noise, since hero never 4-bet it.
    * **Not inside a tiny action group.** In a group of one or two hands every
      member is an edge by construction, and adjacency stops meaning
      "marginal". Facing a 5-bet with a raising range of {AA, KK}, KK sits next
      to a calling hand and would be marked callable - but calling KK there is
      a plain mistake, not a close decision. Groups smaller than
      MIN_GROUP_FOR_MIXING keep the chart's single answer.
    """
    pool = reachable if reachable is not None else set(actions_by_hand)
    group_size: dict[str, int] = {}
    for hand, action in actions_by_hand.items():
        if hand in pool:
            group_size[action] = group_size.get(action, 0) + 1

    mixes: dict[str, list[str]] = {}
    for hand, action in actions_by_hand.items():
        if hand not in pool:
            continue
        if group_size.get(action, 0) < MIN_GROUP_FOR_MIXING:
            continue

        votes: dict[str, int] = {}
        for other in neighbours(hand):
            other_action = actions_by_hand.get(other)
            if other_action and other_action != action:
                votes[other_action] = votes.get(other_action, 0) + 1
        if not votes:
            continue

        ranked = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            continue  # ambiguous: keep the chart's answer as the only one
        mixes[hand] = [action, ranked[0][0]]
    return mixes


def acceptable_actions(hand: str, primary: str, mixes: dict[str, list[str]]) -> list[str]:
    """Every action that should be treated as correct for this hand."""
    return list(mixes.get(hand) or [primary])


def is_acceptable(hand: str, primary: str, mixes: dict[str, list[str]], action: str) -> bool:
    return action in acceptable_actions(hand, primary, mixes)
