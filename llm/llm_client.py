import json
import os
import random
from pathlib import Path
import time

from game.mission_manager import MISSION_DIFFICULTIES, MISSION_TYPES, build_fallback_mission_payload, normalize_mission_payload
from game.zone_data import ZONE_NAMES


GROQ_MODEL = "openai/gpt-oss-120b"
ALLOWED_MODIFIERS = {"NONE", "PROCRASTINATION", "BURNOUT", "BROKE", "EXAM"}
ALLOWED_ENEMIES = {
    "Deadline Blob",
    "Social Media Swarm",
    "Freeloader Phantom",
    "Sleep Debt Slime",
}
ALLOWED_LOCATIONS = set(ZONE_NAMES)
ALLOWED_FRIEND_MOODS = {"supportive", "playful", "concerned"}
ALLOWED_FRIEND_CHOICE_IDS = ("quick_break", "go_to_class", "ask_for_help", "hang_out")
DEFAULT_FRIEND_LABELS = {
    "quick_break": "Take a quick break",
    "go_to_class": "Go to class now",
    "ask_for_help": "Ask for help later",
    "hang_out": "Hang out a bit",
}
LAST_LLM_STATUS = {
    "mode": "offline",
    "label": "OFFLINE",
    "detail": "No LLM call yet",
    "reason": "startup",
    "call_id": 0,
}
LLM_BACKOFF_UNTIL = 0.0


def get_llm_status() -> dict:
    return dict(LAST_LLM_STATUS)


def generate_director_update(game_state: dict, reason: str = "new_mission") -> dict:
    try:
        _guard_llm_backoff()
        client = _get_groq_client()
        messages = _build_messages(game_state, reason)
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=_get_groq_model(),
            temperature=0.55,
            max_tokens=500,
        )
        content = chat_completion.choices[0].message.content or "{}"
        parsed_event = _extract_json(content)
        _record_llm_status("live", "LIVE", f"Director via {_get_groq_model()}", reason)
        return _normalize_payload(parsed_event, game_state)
    except Exception as exc:
        _record_llm_status("offline", "OFFLINE", _describe_llm_error(exc), reason)
        return _build_fallback_payload(game_state, reason)


def generate_event(game_state: dict, reason: str = "new_mission") -> dict:
    return generate_director_update(game_state, reason)


def generate_dream_mission(game_state: dict, allowed_locations: tuple[str, ...] | list[str]) -> dict:
    normalized_locations = tuple(location for location in allowed_locations if location in ALLOWED_LOCATIONS)
    if not normalized_locations:
        normalized_locations = ZONE_NAMES

    try:
        _guard_llm_backoff()
        client = _get_groq_client()
        messages = _build_dream_messages(game_state, normalized_locations)
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=_get_groq_model(),
            temperature=0.55,
            max_tokens=220,
        )
        content = chat_completion.choices[0].message.content or "{}"
        parsed_mission = _extract_json(content)
        _record_llm_status("live", "LIVE", f"Dream via {_get_groq_model()}", "dream")
        return _normalize_dream_payload(parsed_mission, normalized_locations, game_state)
    except Exception as exc:
        _record_llm_status("offline", "OFFLINE", _describe_llm_error(exc), "dream")
        return _build_fallback_dream_payload(normalized_locations, game_state)


def generate_friend_encounter(friend_context: dict) -> dict:
    try:
        _guard_llm_backoff()
        client = _get_groq_client()
        messages = _build_friend_messages(friend_context)
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=_get_groq_model(),
            temperature=0.6,
            max_tokens=160,
        )
        content = chat_completion.choices[0].message.content or "{}"
        parsed_encounter = _extract_json(content)
        _record_llm_status("live", "LIVE", f"Mika via {_get_groq_model()}", "friend")
        return _normalize_friend_payload(parsed_encounter)
    except Exception as exc:
        _record_llm_status("offline", "OFFLINE", _describe_llm_error(exc), "friend")
        return _build_fallback_friend_encounter(friend_context)


class LLMClient:
    def generate_event(self, game_state: dict, reason: str = "new_mission") -> dict:
        return generate_director_update(game_state, reason)

    def generate_director_update(self, game_state: dict, reason: str = "new_mission") -> dict:
        return generate_director_update(game_state, reason)

    def generate_dream_mission(self, game_state: dict, allowed_locations: tuple[str, ...] | list[str]) -> dict:
        return generate_dream_mission(game_state, allowed_locations)

    def generate_friend_encounter(self, friend_context: dict) -> dict:
        return generate_friend_encounter(friend_context)


def _build_messages(game_state: dict, reason: str) -> list[dict[str, str]]:
    location_options = " | ".join(ZONE_NAMES)
    mission_types = " | ".join(MISSION_TYPES)
    mission_difficulties = " | ".join(MISSION_DIFFICULTIES)
    director_snapshot = _build_director_snapshot(game_state)
    required_output = {
        "missions": {
            "safe": {
                "type": mission_types,
                "steps": [
                    {"action": "GO_TO", "target": location_options},
                    {"action": "STAY", "duration": "int"},
                ],
                "time_limit": "int",
                "reward": {"money": "int", "score": "int"},
                "penalty": {"stress": "int"},
                "difficulty": mission_difficulties,
            },
            "risk": {
                "type": mission_types,
                "steps": [
                    {"action": "GO_TO", "target": location_options},
                    {"action": "STAY", "duration": "int"},
                ],
                "time_limit": "int",
                "reward": {"money": "int", "score": "int"},
                "penalty": {"stress": "int"},
                "difficulty": mission_difficulties,
            },
        },
        "modifier": "NONE | PROCRASTINATION | BURNOUT | BROKE | EXAM",
        "enemies": [
            "Deadline Blob | Social Media Swarm | Freeloader Phantom | Sleep Debt Slime"
        ],
    }
    user_content = (
        f"reason:\n{reason}\n\n"
        f"game_state:\n{json.dumps(director_snapshot, indent=2)}\n\n"
        f"required output format:\n{json.dumps(required_output, indent=2)}\n\n"
        "Rules:\n"
        "- return only JSON\n"
        "- return both missions.safe and missions.risk\n"
        "- each mission type must be SINGLE, CHAIN, or RISK\n"
        "- SINGLE must contain exactly 1 step\n"
        "- CHAIN must contain 2 to 3 steps and move across different locations\n"
        "- RISK must have higher reward, shorter time limit, and harsher penalty\n"
        "- every mission must use at most 3 steps total\n"
        "- every STAY duration must be between 2 and 6 seconds\n"
        "- missions.safe is the safer low-pressure job\n"
        "- missions.risk is the riskier high-reward job\n"
        "- missions.safe should usually be SINGLE or an easier CHAIN, with gentler penalty and more forgiving timer\n"
        "- missions.risk should be RISK or a demanding CHAIN, with higher reward and tighter pressure\n"
        "- game_state includes player_location plus route_time_to_zones, which estimates real travel time from the player's current position to every room through the current pathways\n"
        "- use the player's current location and route_time_to_zones to size both timers fairly for the first target, then add enough time for follow-up steps and STAY durations\n"
        "- if the player is already near the first target, a shorter timer is acceptable; if the path is long or the mission chains across campus, add more time\n"
        "- if the steps are longer or involve multiple locations, give more time instead of forcing an unfair rush\n"
        "- missions.safe and missions.risk should start at different first targets when possible\n"
        "- vary locations and vary difficulty\n"
        "- avoid repeating the current mission pattern, mission difficulty, and recent locations from game_state\n"
        "- if player_state is STRONG: generate harder missions with 2 to 3 steps more often, stronger modifiers, and more enemies\n"
        "- if player_state is WEAK: generate simpler missions, allow more forgiving time/reward balance, and use gentler pressure\n"
        "- if player_state is STABLE: keep variety without extreme punishment\n"
        "- when reason is new_mission, focus on producing the next adaptive pair of missions\n"
        "- when reason is pressure_shift, adjust modifier and enemies to respond to the player's current momentum\n"
        "- combo is the current mission combo multiplier pressure, not raw score\n"
        "- only use the allowed locations, modifiers, and enemies\n"
        "- enemy list length between 0 and 3"
    )
    return [
        {
            "role": "system",
            "content": "You are a dynamic difficulty controller and mission generator for a campus survival game. Return ONLY valid JSON.",
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def _build_director_snapshot(game_state: dict) -> dict:
    energy = int(round(game_state.get("energy", 0)))
    stress = int(round(game_state.get("stress", 0)))
    money = int(round(game_state.get("money", 0)))
    focus = int(round(game_state.get("focus", 0)))
    day = int(round(game_state.get("day", 1)))
    time_left = int(round(game_state.get("time_left", game_state.get("day_time_remaining", 0))))
    mission_score = int(round(game_state.get("mission_score", 0)))
    combo = int(round(game_state.get("combo", game_state.get("combo_multiplier", 1))))
    snapshot = {
        "energy": energy,
        "stress": stress,
        "money": money,
        "focus": focus,
        "day": day,
        "time_left": time_left,
        "mission_score": mission_score,
        "combo": combo,
        "player_location": game_state.get("player_location", "Unknown"),
        "route_time_to_zones": game_state.get("route_time_to_zones", {}),
        "player_state": _classify_player_state(
            {
                "energy": energy,
                "stress": stress,
                "money": money,
                "focus": focus,
                "day": day,
                "time_left": time_left,
                "mission_score": mission_score,
                "combo": combo,
            }
        ).upper(),
    }
    return snapshot


def _extract_json(content: str) -> dict:
    start_index = content.find("{")
    end_index = content.rfind("}")
    if start_index == -1 or end_index == -1 or end_index < start_index:
        raise ValueError("No JSON object found in response content")
    return json.loads(content[start_index : end_index + 1])


def _build_dream_messages(game_state: dict, allowed_locations: tuple[str, ...]) -> list[dict[str, str]]:
    location_options = " | ".join(allowed_locations)
    director_snapshot = _build_director_snapshot(game_state)
    required_output = {
        "type": "DREAM",
        "steps": [
            {"action": "GO_TO", "target": location_options},
            {"action": "STAY", "duration": "int", "target": location_options},
        ],
        "time_limit": "int",
    }
    user_content = (
        f"game_state:\n{json.dumps(director_snapshot, indent=2)}\n\n"
        f"required output format:\n{json.dumps(required_output, indent=2)}\n\n"
        "Rules:\n"
        "- return only JSON\n"
        "- type must be DREAM\n"
        "- make the objective simple and readable in one glance\n"
        "- use 1 or 2 steps only\n"
        "- steps may only use GO_TO or STAY\n"
        "- STAY duration must be between 2 and 4 seconds\n"
        "- total time_limit must be between 8 and 14 seconds\n"
        "- game_state includes player_location plus route_time_to_zones, so use the actual campus path distance from the player when setting the dream timer\n"
        "- if the player starts far from the target or the dream includes a STAY step, give the dream more time\n"
        "- only use allowed locations\n"
        "- if player_state is STRONG, slightly increase challenge but keep it short\n"
        "- if player_state is WEAK, keep the dream objective gentler and clearer\n"
        "- if the dream uses a STAY step or a longer route, give it more time\n"
        "- avoid repeating the current daytime mission target if possible"
    )
    return [
        {
            "role": "system",
            "content": "You are a surreal game director for dream intermissions. Return ONLY valid JSON.",
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def _build_friend_messages(friend_context: dict) -> list[dict[str, str]]:
    required_output = {
        "mood": "supportive or playful or concerned",
        "line": "one short sentence under 18 words",
        "choices": [
            {"id": "quick_break", "label": "Take a quick break"},
            {"id": "go_to_class", "label": "Go to class now"},
            {"id": "ask_for_help", "label": "Ask for help later"},
        ],
    }
    user_content = (
        f"friend_context:\n{json.dumps(friend_context, indent=2)}\n\n"
        f"required output format:\n{json.dumps(required_output, indent=2)}\n\n"
        "Rules:\n"
        "- return only JSON\n"
        "- Mika is supportive, social, and sometimes distracting\n"
        "- line must be one short sentence with fewer than 18 words\n"
        "- choices must contain 2 or 3 entries only\n"
        "- valid choice ids only: quick_break, go_to_class, ask_for_help, hang_out\n"
        "- do not include any stat numbers\n"
        "- do not write paragraphs or extra explanation\n"
        "- use current_location, class_live_now, and recent_actions to make the moment feel adaptive\n"
    )
    return [
        {
            "role": "system",
            "content": "You write tiny JSON-only friend encounters for Mika in a campus game. Return ONLY valid JSON.",
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def _normalize_payload(payload: dict, game_state: dict) -> dict:
    if not isinstance(payload, dict):
        return _build_fallback_payload(game_state, "new_mission")

    safe_mission, risk_mission = _normalize_offer_pair(payload, game_state)
    modifier = _normalize_modifier(payload.get("modifier"))
    enemies = _normalize_enemies(payload.get("enemies"))
    if modifier is None or enemies is None:
        return _build_fallback_payload(game_state, "new_mission")

    return {
        "missions": {
            "safe": safe_mission,
            "risk": risk_mission,
        },
        "modifier": modifier,
        "enemies": enemies,
    }


def _normalize_dream_payload(payload: dict, allowed_locations: tuple[str, ...], game_state: dict) -> dict:
    if not isinstance(payload, dict):
        return _build_fallback_dream_payload(allowed_locations, game_state)

    if payload.get("type") != "DREAM":
        return _build_fallback_dream_payload(allowed_locations, game_state)

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return _build_fallback_dream_payload(allowed_locations, game_state)

    normalized_steps: list[dict[str, object]] = []
    last_target: str | None = None
    allowed_location_set = set(allowed_locations)

    for raw_step in raw_steps[:2]:
        if not isinstance(raw_step, dict):
            return _build_fallback_dream_payload(allowed_locations, game_state)

        action = raw_step.get("action", raw_step.get("type"))
        if not isinstance(action, str):
            return _build_fallback_dream_payload(allowed_locations, game_state)
        action = action.upper()

        if action == "GO_TO":
            target = raw_step.get("target", raw_step.get("location"))
            if not isinstance(target, str) or target not in allowed_location_set:
                return _build_fallback_dream_payload(allowed_locations, game_state)
            normalized_steps.append({"action": "GO_TO", "target": target})
            last_target = target
        elif action == "STAY":
            duration = raw_step.get("duration")
            target = raw_step.get("target", raw_step.get("location", last_target))
            if not isinstance(duration, (int, float)) or not isinstance(target, str) or target not in allowed_location_set:
                return _build_fallback_dream_payload(allowed_locations, game_state)
            normalized_steps.append(
                {
                    "action": "STAY",
                    "target": target,
                    "duration": int(max(2, min(4, round(float(duration))))),
                }
            )
            last_target = target
        else:
            return _build_fallback_dream_payload(allowed_locations, game_state)

    raw_time_limit = payload.get("time_limit")
    if not isinstance(raw_time_limit, (int, float)):
        raw_time_limit = 7
    requested_time_limit = int(max(8, min(14, round(float(raw_time_limit)))))

    if not normalized_steps:
        return _build_fallback_dream_payload(allowed_locations, game_state)

    primary_target = normalized_steps[0]["target"]
    time_limit = _estimate_route_based_time_limit(normalized_steps, game_state, minimum=8, maximum=14, buffer_seconds=2.0)
    time_limit = max(requested_time_limit, time_limit)
    return {
        "type": "DREAM",
        "title": f"Dream Drift: {primary_target}",
        "steps": normalized_steps,
        "time_limit": time_limit,
    }


def _normalize_friend_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return _build_fallback_friend_encounter({})

    mood = str(payload.get("mood", "")).strip().lower()
    if mood not in ALLOWED_FRIEND_MOODS:
        return _build_fallback_friend_encounter({})

    raw_line = payload.get("line")
    if not isinstance(raw_line, str) or not raw_line.strip():
        return _build_fallback_friend_encounter({})
    line_words = raw_line.strip().split()
    line = " ".join(line_words[:17])

    raw_choices = payload.get("choices")
    if not isinstance(raw_choices, list):
        return _build_fallback_friend_encounter({})

    normalized_choices: list[dict[str, str]] = []
    for raw_choice in raw_choices[:3]:
        if not isinstance(raw_choice, dict):
            continue
        choice_id = str(raw_choice.get("id", "")).strip()
        if choice_id not in ALLOWED_FRIEND_CHOICE_IDS:
            continue
        label = raw_choice.get("label")
        if not isinstance(label, str) or not label.strip():
            label = DEFAULT_FRIEND_LABELS[choice_id]
        normalized_choices.append({"id": choice_id, "label": label.strip()[:28]})

    deduped_choices: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for choice in normalized_choices:
        if choice["id"] in seen_ids:
            continue
        deduped_choices.append(choice)
        seen_ids.add(choice["id"])

    if not 2 <= len(deduped_choices) <= 3:
        return _build_fallback_friend_encounter({})

    return {
        "mood": mood,
        "line": line,
        "choices": deduped_choices,
    }


def _normalize_modifier(modifier: object) -> str | None:
    if not isinstance(modifier, str) or modifier not in ALLOWED_MODIFIERS:
        return None
    return modifier


def _normalize_enemies(enemies: object) -> list[str] | None:
    if not isinstance(enemies, list):
        return None

    normalized_enemies = []
    for enemy_name in enemies[:3]:
        if not isinstance(enemy_name, str) or enemy_name not in ALLOWED_ENEMIES:
            return None
        if enemy_name not in normalized_enemies:
            normalized_enemies.append(enemy_name)
    return normalized_enemies


def _normalize_offer_pair(payload: dict, game_state: dict) -> tuple[dict, dict]:
    missions = payload.get("missions")
    if isinstance(missions, dict):
        raw_safe = missions.get("safe")
        raw_risk = missions.get("risk")
    else:
        raw_safe = payload.get("safe_mission")
        raw_risk = payload.get("risk_mission")

    if raw_safe is None and payload.get("mission") is not None:
        raw_risk = payload.get("mission")
    safe_mission = _coerce_offer_profile(raw_safe, "safe", game_state)
    risk_mission = _coerce_offer_profile(raw_risk, "risk", game_state)

    if safe_mission["steps"][0]["target"] == risk_mission["steps"][0]["target"]:
        fallback_safe = _coerce_offer_profile(build_fallback_mission_payload(profile="safe"), "safe", game_state)
        if fallback_safe["steps"][0]["target"] != risk_mission["steps"][0]["target"]:
            safe_mission = fallback_safe

    return safe_mission, risk_mission


def _build_fallback_payload(game_state: dict, reason: str) -> dict:
    profile = _classify_player_state(_build_director_snapshot(game_state))
    enemy_pool = list(ALLOWED_ENEMIES)
    random.shuffle(enemy_pool)

    safe_mission = _coerce_offer_profile(build_fallback_mission_payload(profile="safe"), "safe", game_state)
    if profile == "strong":
        risk_mission = _coerce_offer_profile(build_fallback_mission_payload(profile="risk"), "risk", game_state)
        modifier = random.choice(["EXAM", "BURNOUT"])
        enemy_count = 2
    elif profile == "weak":
        risk_mission = _coerce_offer_profile(build_fallback_mission_payload(profile="risk"), "risk", game_state)
        safe_mission["reward"]["money"] = min(80, safe_mission["reward"]["money"] + 4)
        safe_mission["reward"]["score"] = min(180, safe_mission["reward"]["score"] + 8)
        safe_mission["time_limit"] = min(30, safe_mission["time_limit"] + 3)
        safe_mission = normalize_mission_payload(safe_mission)
        modifier = random.choice(["NONE", "PROCRASTINATION", "BROKE"])
        enemy_count = 0 if reason == "pressure_shift" else 1
    else:
        risk_mission = _coerce_offer_profile(build_fallback_mission_payload(profile="risk"), "risk", game_state)
        modifier = random.choice(list(ALLOWED_MODIFIERS))
        enemy_count = 1 if reason == "pressure_shift" else random.randint(1, 2)

    if safe_mission["steps"][0]["target"] == risk_mission["steps"][0]["target"]:
        for _ in range(6):
            candidate = _coerce_offer_profile(build_fallback_mission_payload(profile="safe"), "safe", game_state)
            if candidate["steps"][0]["target"] != risk_mission["steps"][0]["target"]:
                safe_mission = candidate
                break

    return {
        "missions": {
            "safe": safe_mission,
            "risk": risk_mission,
        },
        "modifier": modifier,
        "enemies": enemy_pool[:enemy_count],
    }


def _build_fallback_dream_payload(allowed_locations: tuple[str, ...], game_state: dict) -> dict:
    locations = list(allowed_locations)
    random.shuffle(locations)
    primary_target = locations[0]
    profile = _classify_player_state(_build_director_snapshot(game_state)) if game_state else "stable"

    if profile == "weak":
        steps = [{"action": "GO_TO", "target": primary_target}]
        time_limit = random.randint(10, 14)
    elif profile == "strong":
        steps = [
            {"action": "GO_TO", "target": primary_target},
            {"action": "STAY", "target": primary_target, "duration": random.randint(3, 4)},
        ]
        time_limit = random.randint(10, 13)
    elif random.random() < 0.55:
        steps = [{"action": "GO_TO", "target": primary_target}]
        time_limit = random.randint(9, 12)
    else:
        steps = [
            {"action": "GO_TO", "target": primary_target},
            {"action": "STAY", "target": primary_target, "duration": random.randint(2, 4)},
        ]
        time_limit = random.randint(10, 14)

    time_limit = max(
        time_limit,
        _estimate_route_based_time_limit(steps, game_state, minimum=8, maximum=14, buffer_seconds=2.0),
    )

    return {
        "type": "DREAM",
        "title": f"Dream Drift: {primary_target}",
        "steps": steps,
        "time_limit": time_limit,
    }


def _build_fallback_friend_encounter(friend_context: dict) -> dict:
    energy = int(round(friend_context.get("energy", 50)))
    stress = int(round(friend_context.get("stress", 50)))
    current_location = str(friend_context.get("current_location", "Hallway"))
    class_live_now = bool(friend_context.get("class_live_now", False))

    if energy <= 28:
        return {
            "mood": "concerned",
            "line": "You look wiped. Want a reset before you crash?",
            "choices": [
                {"id": "quick_break", "label": "Take a quick break"},
                {"id": "ask_for_help", "label": "Ask for help later"},
            ],
        }
    if stress >= 76:
        return {
            "mood": "supportive",
            "line": "You are spiraling a little. Let me help steady this.",
            "choices": [
                {"id": "ask_for_help", "label": "Ask for help later"},
                {"id": "quick_break", "label": "Take a quick break"},
                {"id": "go_to_class", "label": "Go to class now"},
            ],
        }
    if current_location in {"Cafe", "Club Room"} and not class_live_now:
        return {
            "mood": "playful",
            "line": "I was about to wander. Want to make this detour count?",
            "choices": [
                {"id": "hang_out", "label": "Hang out a bit"},
                {"id": "go_to_class", "label": "Go to class now"},
            ],
        }
    return {
        "mood": "supportive",
        "line": "Want a small win before the day gets louder?",
        "choices": [
            {"id": "go_to_class", "label": "Go to class now"},
            {"id": "ask_for_help", "label": "Ask for help later"},
            {"id": "quick_break", "label": "Take a quick break"},
        ],
    }


def _classify_player_state(game_state: dict) -> str:
    energy = int(round(game_state.get("energy", 0)))
    stress = int(round(game_state.get("stress", 0)))
    money = int(round(game_state.get("money", 0)))
    focus = int(round(game_state.get("focus", 0)))
    time_left = int(round(game_state.get("time_left", 0)))
    mission_score = int(round(game_state.get("mission_score", 0)))
    combo = int(round(game_state.get("combo", 1)))

    strong_signals = 0
    weak_signals = 0

    if energy >= 72:
        strong_signals += 1
    elif energy <= 34:
        weak_signals += 1

    if focus >= 70:
        strong_signals += 1
    elif focus <= 34:
        weak_signals += 1

    if stress <= 28:
        strong_signals += 1
    elif stress >= 76:
        weak_signals += 1

    if combo >= 2:
        strong_signals += 1
    if money <= 18 and time_left < 25:
        weak_signals += 1
    if mission_score >= max(2, game_state.get("day", 1)):
        strong_signals += 1

    if strong_signals >= 3 and weak_signals == 0:
        return "strong"
    if weak_signals >= 2:
        return "weak"
    return "stable"


def _coerce_offer_profile(mission_data: dict | None, profile: str, game_state: dict) -> dict:
    adjusted = normalize_mission_payload(mission_data)
    if profile == "safe":
        if adjusted["type"] == "RISK":
            adjusted["type"] = "CHAIN" if len(adjusted["steps"]) > 1 else "SINGLE"
        adjusted["difficulty"] = "LOW" if adjusted["difficulty"] == "HIGH" else adjusted["difficulty"]
        adjusted["reward"]["money"] = max(8, int(round(adjusted["reward"]["money"] * 0.75)))
        adjusted["reward"]["score"] = max(12, int(round(adjusted["reward"]["score"] * 0.7)))
        adjusted["penalty"]["stress"] = max(4, int(round(adjusted["penalty"]["stress"] * 0.8)))
        adjusted["time_limit"] = max(int(adjusted["time_limit"]), 18)
    else:
        adjusted["type"] = "RISK"
        adjusted["difficulty"] = "HIGH"
        adjusted["reward"]["money"] = min(80, max(22, int(round(adjusted["reward"]["money"] * 1.35))))
        adjusted["reward"]["score"] = min(180, max(40, int(round(adjusted["reward"]["score"] * 1.4))))
        adjusted["penalty"]["stress"] = min(30, max(12, int(round(adjusted["penalty"]["stress"] * 1.4))))
        adjusted["time_limit"] = max(12, min(int(adjusted["time_limit"]), 18))

    adjusted["time_limit"] = _apply_route_time_floor(adjusted, game_state)
    return normalize_mission_payload(adjusted)


def _apply_route_time_floor(mission: dict, game_state: dict) -> int:
    return _estimate_route_based_time_limit(
        mission.get("steps", []),
        game_state,
        minimum=10 if mission.get("type") == "RISK" else 12,
        maximum=18 if mission.get("type") == "RISK" else 30,
        buffer_seconds=3.0 if mission.get("type") == "RISK" else 4.0,
        requested_time_limit=mission.get("time_limit"),
    )


def _estimate_route_based_time_limit(
    steps: list[dict],
    game_state: dict,
    minimum: int,
    maximum: int,
    buffer_seconds: float,
    requested_time_limit: object | None = None,
) -> int:
    route_estimates = game_state.get("route_time_to_zones", {}) if isinstance(game_state, dict) else {}
    total_seconds = 0.0

    first_target_counted = False
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action", step.get("type", ""))).upper()
        target = step.get("target")
        if action == "GO_TO" and isinstance(target, str):
            if not first_target_counted:
                total_seconds += _lookup_route_time(route_estimates, target)
                first_target_counted = True
            else:
                total_seconds += 4.0
        elif action == "STAY":
            duration = step.get("duration", 0)
            if isinstance(duration, (int, float)):
                total_seconds += max(2.0, float(duration))

    if total_seconds <= 0:
        total_seconds = float(minimum)
    total_seconds += buffer_seconds

    if isinstance(requested_time_limit, (int, float)):
        total_seconds = max(total_seconds, float(requested_time_limit))

    return int(max(minimum, min(maximum, round(total_seconds))))


def _lookup_route_time(route_estimates: object, target: str) -> float:
    if isinstance(route_estimates, dict):
        raw_value = route_estimates.get(target)
        if isinstance(raw_value, (int, float)):
            return max(2.0, float(raw_value))
    return 5.0


def _record_llm_status(mode: str, label: str, detail: str, reason: str) -> None:
    LAST_LLM_STATUS["mode"] = mode
    LAST_LLM_STATUS["label"] = label
    LAST_LLM_STATUS["detail"] = detail
    LAST_LLM_STATUS["reason"] = reason
    LAST_LLM_STATUS["call_id"] = int(LAST_LLM_STATUS.get("call_id", 0)) + 1


def _describe_llm_error(exc: Exception) -> str:
    global LLM_BACKOFF_UNTIL
    if isinstance(exc, KeyError):
        return "Set GROQ_API_KEY to enable live AI"
    if isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", "") == "groq":
        return "groq package missing, using built-in AI"
    message = str(exc).strip()
    if not message:
        return "Using built-in AI"
    lowered = message.lower()
    if "429" in lowered or "rate li" in lowered:
        LLM_BACKOFF_UNTIL = time.monotonic() + 18.0
        return "Groq rate limit hit, retrying soon"
    if "connection" in lowered or "timeout" in lowered or "network" in lowered:
        return "AI offline, using built-in AI"
    return message[:48]


def _guard_llm_backoff() -> None:
    if time.monotonic() < LLM_BACKOFF_UNTIL:
        raise RuntimeError("Groq rate limit hit, retrying soon")


def _get_groq_api_key() -> str:
    _load_local_env()
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if api_key:
        return api_key
    raise KeyError("GROQ_API_KEY")


def _get_groq_model() -> str:
    _load_local_env()
    return os.environ.get("GROQ_MODEL", GROQ_MODEL).strip() or GROQ_MODEL


def _get_groq_client():
    from groq import Groq

    return Groq(api_key=_get_groq_api_key())


def _load_local_env() -> None:
    if os.environ.get("_CAMPUS_CHAOS_ENV_LOADED") == "1":
        return

    from dotenv import load_dotenv

    candidate_paths = (
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
        Path.cwd() / ".env.local",
        Path(__file__).resolve().parents[1] / ".env.local",
        Path.home() / ".campus_chaos.env",
        Path.home() / "Library" / "Application Support" / "Campus Chaos" / ".env",
    )

    for env_path in candidate_paths:
        if env_path.is_file():
            load_dotenv(env_path, override=False)

    os.environ["_CAMPUS_CHAOS_ENV_LOADED"] = "1"
