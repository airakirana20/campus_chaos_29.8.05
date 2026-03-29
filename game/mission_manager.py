import copy
import random
from dataclasses import dataclass

import pygame

from game.ui_fonts import ui_font
from game.ui_primitives import draw_smooth_panel
from game.zone_data import ZONE_NAMES
from settings import HUD_RIGHT_WIDTH


MISSION_TYPES = ("SINGLE", "CHAIN", "RISK")
MISSION_DIFFICULTIES = ("LOW", "MEDIUM", "HIGH")
MISSION_CHOICE_IDS = ("safe", "risk")
ALLOWED_LOCATIONS = set(ZONE_NAMES)

_DIFFICULTY_INDEX = {difficulty: index for index, difficulty in enumerate(MISSION_DIFFICULTIES)}
_CHOICE_LABELS = {"safe": "Safe", "risk": "Risk"}
_TYPE_LABELS = {
    "SINGLE": "Single Stop",
    "CHAIN": "Chain Route",
    "RISK": "Risk Run",
}

DEFAULT_MISSION = {
    "type": "SINGLE",
    "steps": [{"action": "GO_TO", "target": "Library"}],
    "time_limit": 16,
    "reward": {"money": 12, "score": 18},
    "penalty": {"stress": 6},
    "difficulty": "LOW",
    "title": "Single Stop: Library",
}


@dataclass
class MissionStep:
    step_type: str
    target: str
    duration: float = 0.0
    progress: float = 0.0
    completed: bool = False


def build_fallback_mission_payload(
    randomizer: random.Random | None = None,
    profile: str | None = None,
) -> dict:
    rng = randomizer or random.Random()
    if profile == "safe":
        mission_type = rng.choice(("SINGLE", "CHAIN"))
        difficulty = rng.choice(("LOW", "MEDIUM"))
    elif profile == "risk":
        mission_type = "RISK"
        difficulty = "HIGH"
    else:
        mission_type = rng.choice(MISSION_TYPES)
        difficulty = rng.choice(MISSION_DIFFICULTIES)

    locations = list(ZONE_NAMES)
    rng.shuffle(locations)

    if mission_type == "SINGLE":
        raw_mission = {
            "type": "SINGLE",
            "steps": [{"action": "GO_TO", "target": locations[0]}],
            "time_limit": rng.randint(14, 22),
            "reward": {"money": 10 + _DIFFICULTY_INDEX[difficulty] * 5, "score": 16 + _DIFFICULTY_INDEX[difficulty] * 14},
            "penalty": {"stress": 5 + _DIFFICULTY_INDEX[difficulty] * 3},
            "difficulty": difficulty,
        }
    elif mission_type == "CHAIN":
        raw_mission = {
            "type": "CHAIN",
            "steps": [
                {"action": "GO_TO", "target": locations[0]},
                {"action": "GO_TO", "target": locations[1]},
                {"action": "STAY", "duration": rng.randint(2, 6), "target": locations[1]},
            ],
            "time_limit": rng.randint(20, 30),
            "reward": {"money": 16 + _DIFFICULTY_INDEX[difficulty] * 8, "score": 28 + _DIFFICULTY_INDEX[difficulty] * 18},
            "penalty": {"stress": 7 + _DIFFICULTY_INDEX[difficulty] * 4},
            "difficulty": difficulty,
        }
    else:
        raw_mission = {
            "type": "RISK",
            "steps": [
                {"action": "GO_TO", "target": locations[0]},
                {"action": "STAY", "duration": rng.randint(2, 4), "target": locations[0]},
                {"action": "GO_TO", "target": locations[1]},
            ],
            "time_limit": rng.randint(12, 18),
            "reward": {"money": 28 + _DIFFICULTY_INDEX[difficulty] * 9, "score": 44 + _DIFFICULTY_INDEX[difficulty] * 24},
            "penalty": {"stress": 12 + _DIFFICULTY_INDEX[difficulty] * 4},
            "difficulty": difficulty,
        }

    return normalize_mission_payload(raw_mission)


def normalize_mission_payload(mission_data: dict | None) -> dict:
    if not isinstance(mission_data, dict):
        return copy.deepcopy(DEFAULT_MISSION)

    mission_type = mission_data.get("type")
    difficulty = mission_data.get("difficulty")
    if not isinstance(mission_type, str) or mission_type.upper() not in MISSION_TYPES:
        return copy.deepcopy(DEFAULT_MISSION)
    if not isinstance(difficulty, str) or difficulty.upper() not in MISSION_DIFFICULTIES:
        return copy.deepcopy(DEFAULT_MISSION)

    mission_type = mission_type.upper()
    difficulty = difficulty.upper()
    raw_steps = mission_data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return copy.deepcopy(DEFAULT_MISSION)

    normalized_steps = []
    last_target: str | None = None
    go_to_targets: list[str] = []
    for raw_step in raw_steps[:3]:
        if not isinstance(raw_step, dict):
            return copy.deepcopy(DEFAULT_MISSION)

        action = raw_step.get("action", raw_step.get("type"))
        if not isinstance(action, str):
            return copy.deepcopy(DEFAULT_MISSION)
        action = action.upper()

        if action == "GO_TO":
            target = raw_step.get("target", raw_step.get("location"))
            if not isinstance(target, str) or target not in ALLOWED_LOCATIONS:
                return copy.deepcopy(DEFAULT_MISSION)
            normalized_steps.append({"action": "GO_TO", "target": target})
            go_to_targets.append(target)
            last_target = target
        elif action == "STAY":
            duration = raw_step.get("duration")
            target = raw_step.get("target", raw_step.get("location", last_target))
            if not isinstance(target, str) or target not in ALLOWED_LOCATIONS or not isinstance(duration, (int, float)):
                return copy.deepcopy(DEFAULT_MISSION)
            clamped_duration = int(max(2, min(6, round(float(duration)))))
            normalized_steps.append({"action": "STAY", "target": target, "duration": clamped_duration})
            last_target = target
        else:
            return copy.deepcopy(DEFAULT_MISSION)

    if mission_type == "SINGLE" and len(normalized_steps) != 1:
        return copy.deepcopy(DEFAULT_MISSION)
    if mission_type == "CHAIN":
        if not 2 <= len(normalized_steps) <= 3:
            return copy.deepcopy(DEFAULT_MISSION)
        if len(set(go_to_targets)) < 2:
            return copy.deepcopy(DEFAULT_MISSION)
    if mission_type == "RISK" and len(normalized_steps) > 3:
        return copy.deepcopy(DEFAULT_MISSION)

    time_limit = _normalize_time_limit(mission_type, difficulty, normalized_steps, mission_data.get("time_limit"))
    reward = _normalize_reward(mission_type, difficulty, normalized_steps, mission_data.get("reward"))
    penalty = _normalize_penalty(mission_type, difficulty, mission_data.get("penalty"))
    title = _derive_title(mission_type, difficulty, normalized_steps, mission_data.get("title"))

    return {
        "type": mission_type,
        "steps": normalized_steps,
        "time_limit": time_limit,
        "reward": reward,
        "penalty": penalty,
        "difficulty": difficulty,
        "title": title,
    }


def _normalize_time_limit(
    mission_type: str,
    difficulty: str,
    steps: list[dict],
    raw_time_limit: object,
) -> int:
    step_count = len(steps)
    stay_time = sum(int(step.get("duration", 0)) for step in steps if step["action"] == "STAY")
    difficulty_shift = {"LOW": 2, "MEDIUM": 0, "HIGH": -2}[difficulty]
    base_min = {"SINGLE": 12, "CHAIN": 18, "RISK": 10}[mission_type] + (step_count - 1) * 3 + stay_time // 2 + difficulty_shift
    base_max = {"SINGLE": 20, "CHAIN": 30, "RISK": 18}[mission_type] + (step_count - 1) * 4 + stay_time + difficulty_shift
    min_time = max(8, base_min)
    max_time = max(min_time, base_max)

    if not isinstance(raw_time_limit, (int, float)):
        return (min_time + max_time) // 2
    return int(max(min_time, min(max_time, round(float(raw_time_limit)))))


def _normalize_reward(
    mission_type: str,
    difficulty: str,
    steps: list[dict],
    raw_reward: object,
) -> dict[str, int]:
    step_count = len(steps)
    base_money = {"LOW": 10, "MEDIUM": 16, "HIGH": 24}[difficulty] + (step_count - 1) * 4
    base_score = {"LOW": 16, "MEDIUM": 30, "HIGH": 48}[difficulty] + (step_count - 1) * 10
    multiplier = {"SINGLE": 0.9, "CHAIN": 1.15, "RISK": 1.55}[mission_type]
    min_money = int(round(base_money * multiplier))
    min_score = int(round(base_score * multiplier))

    if not isinstance(raw_reward, dict):
        return {"money": min_money, "score": min_score}

    money = raw_reward.get("money")
    score = raw_reward.get("score")
    if not isinstance(money, (int, float)):
        money = min_money
    if not isinstance(score, (int, float)):
        score = min_score

    return {
        "money": int(max(min_money, min(70, round(float(money))))),
        "score": int(max(min_score, min(160, round(float(score))))),
    }


def _normalize_penalty(mission_type: str, difficulty: str, raw_penalty: object) -> dict[str, int]:
    base_stress = {"LOW": 5, "MEDIUM": 9, "HIGH": 13}[difficulty]
    multiplier = {"SINGLE": 0.85, "CHAIN": 1.0, "RISK": 1.6}[mission_type]
    min_stress = int(round(base_stress * multiplier))

    if not isinstance(raw_penalty, dict):
        return {"stress": min_stress}

    stress = raw_penalty.get("stress")
    if not isinstance(stress, (int, float)):
        stress = min_stress
    return {"stress": int(max(min_stress, min(30, round(float(stress)))))}


def _derive_title(mission_type: str, difficulty: str, steps: list[dict], raw_title: object) -> str:
    if isinstance(raw_title, str) and raw_title.strip():
        return raw_title.strip()[:48]

    primary_target = steps[0]["target"]
    if mission_type == "SINGLE":
        return f"{difficulty.title()} {_TYPE_LABELS[mission_type]}: {primary_target}"[:48]
    if mission_type == "CHAIN":
        last_target = steps[-1]["target"]
        return f"{difficulty.title()} Route: {primary_target} to {last_target}"[:48]
    return f"{difficulty.title()} Risk Run: {primary_target}"[:48]


class MissionManager:
    def __init__(self) -> None:
        self.font = ui_font(24, bold=True)
        self.small_font = ui_font(18, bold=True)
        self.meta_font = ui_font(16)
        self.choice_font = ui_font(15)
        self.random = random.Random()
        self.title = ""
        self.mission_type = "SINGLE"
        self.difficulty = "LOW"
        self.steps: list[MissionStep] = []
        self.time_limit = 12
        self.time_remaining = 12.0
        self.reward = {"money": 12, "score": 18}
        self.penalty = {"stress": 6}
        self.completed = False
        self.failed = False
        self.pending_completion_reward = {"money": 0, "score": 0}
        self.pending_failure_penalty = {"stress": 0}
        self.pending_refresh = False
        self.choice_offers: dict[str, dict] = {}
        self.last_signature: tuple | None = None
        self.refresh_choices()

    def can_replace_mission(self) -> bool:
        return self.pending_refresh or self.has_choice_pending()

    def ready_for_next_mission(self) -> bool:
        return self.pending_refresh

    def needs_refresh(self) -> bool:
        return self.pending_refresh

    def has_choice_pending(self) -> bool:
        return bool(self.choice_offers)

    def get_break_time_remaining(self) -> float:
        return 0.0

    def refresh_choices(
        self,
        safe_mission: dict | None = None,
        risk_mission: dict | None = None,
        route_time_to_zones: dict[str, float] | None = None,
    ) -> None:
        safe_offer = self._apply_route_time_floor(self._generate_offer("safe", safe_mission), route_time_to_zones)
        risk_offer = self._apply_route_time_floor(self._generate_offer("risk", risk_mission), route_time_to_zones)

        for _ in range(8):
            safe_target = safe_offer["steps"][0]["target"]
            risk_target = risk_offer["steps"][0]["target"]
            if safe_target != risk_target:
                break
            safe_offer = self._apply_route_time_floor(self._generate_offer("safe"), route_time_to_zones)

        self.choice_offers = {"safe": safe_offer, "risk": risk_offer}
        self.title = "Choose a mission"
        self.steps = []
        self.completed = False
        self.failed = False
        self.pending_refresh = False
        self.pending_completion_reward = {"money": 0, "score": 0}
        self.pending_failure_penalty = {"stress": 0}

    def choose_mission(self, choice_id: str) -> bool:
        if choice_id not in self.choice_offers:
            return False
        self.set_mission(self.choice_offers[choice_id])
        self.choice_offers = {}
        return True

    def auto_choose_for_zones(self, active_zone_names: set[str]) -> str | None:
        if not self.choice_offers:
            return None

        for choice_id in MISSION_CHOICE_IDS:
            offer = self.choice_offers.get(choice_id)
            if offer is None:
                continue
            first_target = offer["steps"][0]["target"]
            if first_target in active_zone_names:
                self.choose_mission(choice_id)
                return choice_id
        return None

    def set_mission(self, mission_data: dict | None) -> None:
        normalized_mission = normalize_mission_payload(mission_data)
        normalized_signature = self._mission_signature(normalized_mission)
        if normalized_signature == self.last_signature:
            normalized_mission = self._generate_offer("safe")
            normalized_signature = self._mission_signature(normalized_mission)

        self.title = normalized_mission["title"]
        self.mission_type = normalized_mission["type"]
        self.difficulty = normalized_mission["difficulty"]
        self.steps = [
            MissionStep(
                step_type=step["action"],
                target=step["target"],
                duration=float(step.get("duration", 0.0)),
            )
            for step in normalized_mission["steps"]
        ]
        self.time_limit = int(normalized_mission["time_limit"])
        self.time_remaining = float(self.time_limit)
        self.reward = dict(normalized_mission["reward"])
        self.penalty = dict(normalized_mission["penalty"])
        self.completed = False
        self.failed = False
        self.choice_offers = {}
        self.pending_completion_reward = {"money": 0, "score": 0}
        self.pending_failure_penalty = {"stress": 0}
        self.pending_refresh = False
        self.last_signature = normalized_signature

    def set_random_mission(self) -> None:
        self.set_mission(self._generate_offer("safe"))

    def generate_random_mission(self) -> dict:
        return self._generate_offer("safe")

    def get_current_step(self) -> MissionStep | None:
        for step in self.steps:
            if not step.completed:
                return step
        return None

    def get_current_step_text(self) -> str:
        if self.choice_offers:
            return "Choose safe or risk mission"
        step = self.get_current_step()
        if step is None:
            return "Mission complete"
        return self._format_step(step)

    def get_choice_summary(self, choice_id: str) -> dict | None:
        return self.choice_offers.get(choice_id)

    def update(self, dt: float, active_zone_names: set[str], stats, powerup_manager) -> None:
        if self.choice_offers or self.pending_refresh:
            return

        self.time_remaining = max(0.0, self.time_remaining - dt)
        if self.time_remaining <= 0:
            self.failed = True
            self.completed = False
            self.pending_failure_penalty = dict(self.penalty)
            self.pending_refresh = True
            return

        step = self.get_current_step()
        if step is None:
            self._complete_mission()
            return

        if step.step_type == "GO_TO":
            if step.target in active_zone_names:
                step.completed = True
        elif step.step_type == "STAY":
            required_duration = step.duration * powerup_manager.get_mission_stay_multiplier()
            if step.target in active_zone_names:
                step.progress = min(required_duration, step.progress + dt)
            else:
                step.progress = max(0.0, step.progress - dt * 0.75)
            if step.progress >= required_duration:
                step.completed = True

        if all(current_step.completed for current_step in self.steps):
            self._complete_mission()

    def apply_progress_penalty(self, amount: float) -> None:
        if self.pending_refresh or self.choice_offers:
            return

        step = self.get_current_step()
        if step is None:
            return

        if step.step_type == "STAY":
            step.progress = max(0.0, step.progress - amount)
        else:
            self.time_remaining = max(1.0, self.time_remaining - amount * 0.75)

    def draw(self, surface: pygame.Surface) -> None:
        panel_width = HUD_RIGHT_WIDTH - 28
        panel_rect = pygame.Rect(surface.get_width() - panel_width - 16, 198, panel_width, 214)
        draw_smooth_panel(surface, panel_rect, (36, 43, 57), (230, 235, 240), border_radius=12)

        if self.choice_offers:
            title_surface = self.font.render("Mission Choice", True, (244, 246, 249))
            hint_surface = self.meta_font.render("Press F1/F2 or walk into target.", True, (204, 212, 224))
            surface.blit(title_surface, (panel_rect.x + 14, panel_rect.y + 12))
            surface.blit(hint_surface, (panel_rect.x + 14, panel_rect.y + 36))

            self._draw_choice_card(surface, panel_rect.x + 14, panel_rect.y + 62, panel_rect.width - 28, 60, "safe")
            self._draw_choice_card(surface, panel_rect.x + 14, panel_rect.y + 132, panel_rect.width - 28, 60, "risk")
            return

        title_surface = self.font.render(self._fit_text(f"Mission: {self.title}", self.font, panel_rect.width - 28), True, (244, 246, 249))
        meta_surface = self.meta_font.render(
            f"{self.mission_type} | {self.difficulty} | {self.time_remaining:0.1f}s",
            True,
            (175, 226, 144) if self.mission_type == "RISK" else (205, 214, 228),
        )
        reward_surface = self.meta_font.render(
            f"Reward +${self.reward['money']} | +{self.reward['score']} score",
            True,
            (129, 221, 151),
        )
        penalty_surface = self.meta_font.render(
            f"Fail +{self.penalty['stress']} stress",
            True,
            (227, 129, 143),
        )

        surface.blit(title_surface, (panel_rect.x + 14, panel_rect.y + 12))
        surface.blit(meta_surface, (panel_rect.x + 14, panel_rect.y + 36))
        surface.blit(reward_surface, (panel_rect.x + 14, panel_rect.y + 56))
        surface.blit(penalty_surface, (panel_rect.x + 14, panel_rect.y + 74))

        y = panel_rect.y + 104
        for index, step in enumerate(self.steps[:3], start=1):
            color = (121, 216, 145) if step.completed else (235, 239, 245)
            prefix = "[x]" if step.completed else "[ ]"
            line_surface = self.small_font.render(
                self._fit_text(f"{prefix} {index}. {self._format_step(step)}", self.small_font, panel_rect.width - 28),
                True,
                color,
            )
            surface.blit(line_surface, (panel_rect.x + 14, y))
            y += 24

    def pop_completion_reward(self) -> dict[str, int]:
        reward = dict(self.pending_completion_reward)
        self.pending_completion_reward = {"money": 0, "score": 0}
        return reward

    def pop_failure_penalty(self) -> dict[str, int]:
        penalty = dict(self.pending_failure_penalty)
        self.pending_failure_penalty = {"stress": 0}
        return penalty

    def _complete_mission(self) -> None:
        if self.pending_refresh:
            return
        self.completed = True
        self.failed = False
        self.pending_completion_reward = dict(self.reward)
        self.pending_refresh = True

    def _draw_choice_card(self, surface: pygame.Surface, x: int, y: int, width: int, height: int, choice_id: str) -> None:
        offer = self.choice_offers[choice_id]
        card_rect = pygame.Rect(x, y, width, height)
        card_color = (44, 73, 60) if choice_id == "safe" else (92, 50, 62)
        accent_color = (132, 224, 159) if choice_id == "safe" else (241, 128, 144)
        draw_smooth_panel(surface, card_rect, card_color, accent_color, border_radius=10)

        label_surface = self.small_font.render(f"[{'F1' if choice_id == 'safe' else 'F2'}] {_CHOICE_LABELS[choice_id]}", True, (245, 247, 250))
        target_surface = self.choice_font.render(
            f"{offer['type']} {offer['difficulty']} -> {offer['steps'][0]['target']}",
            True,
            (233, 238, 245),
        )
        reward_surface = self.choice_font.render(
            self._fit_text(
                f"+${offer['reward']['money']} | +{offer['reward']['score']} score | +{offer['penalty']['stress']} stress fail",
                self.choice_font,
                width - 20,
            ),
            True,
            accent_color,
        )
        surface.blit(label_surface, (card_rect.x + 10, card_rect.y + 8))
        surface.blit(target_surface, (card_rect.x + 10, card_rect.y + 26))
        surface.blit(reward_surface, (card_rect.x + 10, card_rect.y + 42))

    def _format_step(self, step: MissionStep) -> str:
        if step.step_type == "GO_TO":
            return f"Go to {step.target}"
        if step.step_type == "STAY":
            duration_text = f"{step.progress:.1f}/{step.duration:.1f}s"
            return f"Stay in {step.target} ({duration_text})"
        return "Unknown step"

    def _generate_offer(self, profile: str, mission_data: dict | None = None) -> dict:
        if mission_data is not None:
            mission = self._coerce_profile(normalize_mission_payload(mission_data), profile)
            if self._mission_signature(mission) != self.last_signature:
                return mission

        for _ in range(12):
            mission = self._coerce_profile(build_fallback_mission_payload(self.random, profile), profile)
            if self._mission_signature(mission) != self.last_signature:
                return mission
        return self._coerce_profile(build_fallback_mission_payload(self.random, profile), profile)

    def _coerce_profile(self, mission: dict, profile: str) -> dict:
        adjusted = copy.deepcopy(mission)
        if profile == "safe":
            if adjusted["type"] == "RISK":
                adjusted["type"] = "CHAIN" if len(adjusted["steps"]) > 1 else "SINGLE"
            adjusted["difficulty"] = "LOW" if adjusted["difficulty"] == "HIGH" else adjusted["difficulty"]
            adjusted["reward"]["money"] = max(8, int(round(adjusted["reward"]["money"] * 0.75)))
            adjusted["reward"]["score"] = max(12, int(round(adjusted["reward"]["score"] * 0.7)))
            adjusted["penalty"]["stress"] = max(4, int(round(adjusted["penalty"]["stress"] * 0.8)))
            adjusted["time_limit"] = max(adjusted["time_limit"], 18)
        else:
            adjusted["type"] = "RISK"
            adjusted["difficulty"] = "HIGH"
            adjusted["reward"]["money"] = min(80, max(22, int(round(adjusted["reward"]["money"] * 1.35))))
            adjusted["reward"]["score"] = min(180, max(40, int(round(adjusted["reward"]["score"] * 1.4))))
            adjusted["penalty"]["stress"] = min(30, max(12, int(round(adjusted["penalty"]["stress"] * 1.4))))
            adjusted["time_limit"] = max(12, min(adjusted["time_limit"], 18))
        adjusted["title"] = _derive_title(adjusted["type"], adjusted["difficulty"], adjusted["steps"], None)
        return normalize_mission_payload(adjusted)

    def _mission_signature(self, mission_data: dict) -> tuple:
        return (
            mission_data.get("type"),
            mission_data.get("difficulty"),
            tuple(
                (
                    step.get("action"),
                    step.get("target"),
                    step.get("duration"),
                )
                for step in mission_data.get("steps", [])
            ),
        )

    def _apply_route_time_floor(self, mission: dict, route_time_to_zones: dict[str, float] | None) -> dict:
        if not route_time_to_zones:
            return mission

        adjusted = copy.deepcopy(mission)
        total_seconds = 0.0
        first_target_counted = False
        for step in adjusted["steps"]:
            if step["action"] == "GO_TO":
                if not first_target_counted:
                    total_seconds += max(2.0, float(route_time_to_zones.get(step["target"], 5.0)))
                    first_target_counted = True
                else:
                    total_seconds += 4.0
            elif step["action"] == "STAY":
                total_seconds += max(2.0, float(step.get("duration", 0)))

        buffer_seconds = 3.0 if adjusted["type"] == "RISK" else 4.0
        min_limit = 10 if adjusted["type"] == "RISK" else 12
        max_limit = 18 if adjusted["type"] == "RISK" else 30
        recommended_limit = int(max(min_limit, min(max_limit, round(total_seconds + buffer_seconds))))
        adjusted["time_limit"] = max(int(adjusted["time_limit"]), recommended_limit)
        return normalize_mission_payload(adjusted)

    def _fit_text(self, text: str, font: pygame.font.Font, max_width: int) -> str:
        if font.size(text)[0] <= max_width:
            return text
        trimmed = text
        while trimmed and font.size(trimmed + "...")[0] > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + "...") if trimmed else text
