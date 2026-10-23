"""
JSON shapes the client reads.

Shared by the API and by the offline bundle, so a hand served by Flask and a
hand dealt on the phone describe the spot with the same fields.
"""
from __future__ import annotations


def serialize_chart(chart):
    if not chart: return {}
    json_chart = {}
    for hand, data in chart.items():
        acceptable = [a.value for a in data.get("acceptable", [data["action"]])]
        json_chart[hand] = {
            "action": data["action"].value,
            "explanation": data["explanation"],
        }
        # Only sent when it adds something, to keep the per-hand payload small.
        if len(acceptable) > 1:
            json_chart[hand]["mix"] = acceptable
    return json_chart


def serialize_node(sc):
    """Everything about the spot except hero's cards."""
    return {
        "hero_pos": sc.hero_position.value,
        "stack": sc.effective_stack_bb,
        "pot": sc.pot_bb,
        "situation": sc.situation,
        "actions": [{"pos": a.position.value, "act": a.action.value, "amt": a.size_bb} for a in sc.actions_before_hero],
        "to_call": sc.to_call_bb,
        # Labels come from the node definition so the UI does not keep its own
        # copy of what each situation means.
        "raise_label": sc.raise_label,
        "action_text": sc.action_text,
    }


def serialize_scenario(sc):
    if not sc: return None
    return {
        **serialize_node(sc),
        "card1": {"rank": sc.hero_hand.card1.rank, "suit": sc.hero_hand.card1.suit},
        "card2": {"rank": sc.hero_hand.card2.rank, "suit": sc.hero_hand.card2.suit},
    }
