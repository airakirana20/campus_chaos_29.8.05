from dataclasses import dataclass, field

import pygame

from game.ui_fonts import ui_font
from game.ui_primitives import draw_smooth_panel
from settings import HUD_RIGHT_WIDTH, SCREEN_HEIGHT, SCREEN_WIDTH


@dataclass
class PowerupDefinition:
    name: str
    hotkey: int
    hotkey_label: str
    cost: int
    effect: dict[str, float]
    side_effect: dict[str, float] = field(default_factory=dict)
    duration: float = 12.0
    bonuses: dict[str, float] = field(default_factory=dict)


@dataclass
class ActivePowerup:
    definition: PowerupDefinition
    remaining: float


POWERUP_DEFINITIONS = [
    PowerupDefinition(
        name="Coffee Boost",
        hotkey=pygame.K_1,
        hotkey_label="1",
        cost=12,
        effect={"energy": 18, "focus": 8},
        side_effect={"stress": 4},
        duration=12,
        bonuses={"speed_multiplier": 1.15},
    ),
    PowerupDefinition(
        name="Cheap Meal",
        hotkey=pygame.K_2,
        hotkey_label="2",
        cost=8,
        effect={"energy": 14},
        side_effect={"focus": -4},
        duration=14,
        bonuses={"energy_decay_multiplier": 0.85},
    ),
    PowerupDefinition(
        name="Extension Letter",
        hotkey=pygame.K_3,
        hotkey_label="3",
        cost=18,
        effect={"stress": -10},
        duration=18,
        bonuses={"mission_stay_multiplier": 0.7},
    ),
    PowerupDefinition(
        name="Time-Block Totem",
        hotkey=pygame.K_4,
        hotkey_label="4",
        cost=14,
        effect={"focus": 10},
        duration=15,
        bonuses={"focus_damage_multiplier": 0.65},
    ),
    PowerupDefinition(
        name="Headphones",
        hotkey=pygame.K_5,
        hotkey_label="5",
        cost=11,
        effect={"stress": -5},
        duration=15,
        bonuses={"focus_damage_multiplier": 0.5},
    ),
    PowerupDefinition(
        name="Lecture Recording",
        hotkey=pygame.K_6,
        hotkey_label="6",
        cost=9,
        effect={"focus": 6},
        side_effect={"energy": -3},
        duration=18,
        bonuses={"condition_focus_bonus": 10.0},
    ),
    PowerupDefinition(
        name="Supportive Friend",
        hotkey=pygame.K_7,
        hotkey_label="7",
        cost=13,
        effect={"stress": -14},
        duration=14,
        bonuses={"stress_gain_multiplier": 0.7, "stress_recovery_multiplier": 1.2},
    ),
    PowerupDefinition(
        name="All-Nighter Mode",
        hotkey=pygame.K_8,
        hotkey_label="8",
        cost=6,
        effect={"focus": 16},
        side_effect={"stress": 12, "energy": -8},
        duration=12,
        bonuses={"speed_multiplier": 1.2, "energy_decay_multiplier": 1.35},
    ),
]


class PowerupManager:
    def __init__(self) -> None:
        self.font = ui_font(24, bold=True)
        self.small_font = ui_font(17)
        self.detail_font = ui_font(18, bold=True)
        self.definitions = {powerup.name: powerup for powerup in POWERUP_DEFINITIONS}
        self.hotkey_map = {powerup.hotkey: powerup.name for powerup in POWERUP_DEFINITIONS}
        self.active_powerups: dict[str, ActivePowerup] = {}
        self.message = "Press 1-8 to buy powerups"
        self.message_timer = 0.0
        self.selected_powerup_name: str | None = None
        self.info_button_rects = self._build_info_button_rects()

    def handle_event(self, event: pygame.event.Event, stats, modifier_system) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for powerup_name, button_rect in self.info_button_rects.items():
                if button_rect.collidepoint(event.pos):
                    if self.selected_powerup_name == powerup_name:
                        self.selected_powerup_name = None
                    else:
                        self.selected_powerup_name = powerup_name
                    return False

        if event.type != pygame.KEYDOWN:
            return False

        powerup_name = self.hotkey_map.get(event.key)
        if powerup_name is None:
            return False

        return self.activate(powerup_name, stats, modifier_system)

    def activate(self, powerup_name: str, stats, modifier_system) -> bool:
        definition = self.definitions[powerup_name]
        adjusted_cost = int(round(definition.cost * modifier_system.get_cost_multiplier()))
        if stats.money < adjusted_cost:
            self._set_message(f"Need ${adjusted_cost} for {definition.name}")
            return False

        stats.apply_change("money", -adjusted_cost)
        stats.apply_event(definition.effect)
        if definition.side_effect:
            stats.apply_event(definition.side_effect)

        self.active_powerups[powerup_name] = ActivePowerup(definition=definition, remaining=definition.duration)
        self._set_message(f"{definition.name} active for {int(definition.duration)}s")
        return True

    def update(self, dt: float) -> None:
        expired_names = []
        for active_powerup in self.active_powerups.values():
            active_powerup.remaining -= dt
            if active_powerup.remaining <= 0:
                expired_names.append(active_powerup.definition.name)

        for powerup_name in expired_names:
            self.active_powerups.pop(powerup_name, None)

        if self.message_timer > 0:
            self.message_timer = max(0.0, self.message_timer - dt)

    def get_player_speed_multiplier(self) -> float:
        multiplier = 1.0
        for active_powerup in self.active_powerups.values():
            multiplier *= active_powerup.definition.bonuses.get("speed_multiplier", 1.0)
        return multiplier

    def get_energy_decay_multiplier(self) -> float:
        multiplier = 1.0
        for active_powerup in self.active_powerups.values():
            multiplier *= active_powerup.definition.bonuses.get("energy_decay_multiplier", 1.0)
        return multiplier

    def get_stress_gain_multiplier(self) -> float:
        multiplier = 1.0
        for active_powerup in self.active_powerups.values():
            multiplier *= active_powerup.definition.bonuses.get("stress_gain_multiplier", 1.0)
        return multiplier

    def get_stress_recovery_multiplier(self) -> float:
        multiplier = 1.0
        for active_powerup in self.active_powerups.values():
            multiplier *= active_powerup.definition.bonuses.get("stress_recovery_multiplier", 1.0)
        return multiplier

    def get_focus_damage_multiplier(self) -> float:
        multiplier = 1.0
        for active_powerup in self.active_powerups.values():
            multiplier *= active_powerup.definition.bonuses.get("focus_damage_multiplier", 1.0)
        return multiplier

    def get_mission_stay_multiplier(self) -> float:
        multiplier = 1.0
        for active_powerup in self.active_powerups.values():
            multiplier *= active_powerup.definition.bonuses.get("mission_stay_multiplier", 1.0)
        return multiplier

    def get_condition_bonus(self, stat_name: str) -> float:
        if stat_name != "focus":
            return 0.0

        bonus = 0.0
        for active_powerup in self.active_powerups.values():
            bonus += active_powerup.definition.bonuses.get("condition_focus_bonus", 0.0)
        return bonus

    def get_active_names(self) -> list[str]:
        return list(self.active_powerups.keys())

    def draw(self, surface: pygame.Surface) -> None:
        panel_width = HUD_RIGHT_WIDTH - 28
        panel_rect = pygame.Rect(surface.get_width() - panel_width - 16, surface.get_height() - 206, panel_width, 182)
        draw_smooth_panel(surface, panel_rect, (36, 43, 57), (230, 235, 240), border_radius=12)

        title_surface = self.font.render("Powerups", True, (244, 246, 249))
        surface.blit(title_surface, (panel_rect.x + 14, panel_rect.y + 12))

        left_x = panel_rect.x + 14
        right_x = panel_rect.x + panel_rect.width // 2 + 4
        y = panel_rect.y + 42
        for index, definition in enumerate(POWERUP_DEFINITIONS):
            column_x = left_x if index % 2 == 0 else right_x
            row_y = y + (index // 2) * 24
            active_powerup = self.active_powerups.get(definition.name)
            active_marker = "*" if active_powerup is not None else ""
            line = f"[{definition.hotkey_label}] ${definition.cost} {definition.name[:7]}{active_marker}"
            line_surface = self.small_font.render(line, True, (235, 239, 245))
            surface.blit(line_surface, (column_x, row_y))

            button_rect = self.info_button_rects[definition.name]
            pygame.draw.rect(surface, (68, 86, 116), button_rect, border_radius=6)
            pygame.draw.rect(surface, (230, 235, 240), button_rect, width=1, border_radius=6)
            info_surface = self.small_font.render("i", True, (244, 246, 249))
            info_rect = info_surface.get_rect(center=button_rect.center)
            surface.blit(info_surface, info_rect)

        active_names = self.get_active_names()
        if active_names:
            active_text = ", ".join(
                f"{name} {self.active_powerups[name].remaining:.0f}s" for name in active_names[:2]
            )
        else:
            active_text = "No active powerups"
        active_surface = self.small_font.render(self._fit_text(active_text, self.small_font, panel_rect.width - 28), True, (214, 220, 228))
        surface.blit(active_surface, (panel_rect.x + 14, panel_rect.bottom - 52))

        if self.message_timer > 0:
            message_surface = self.small_font.render(self.message, True, (124, 217, 145))
            surface.blit(message_surface, (panel_rect.x + 14, panel_rect.bottom - 28))
        else:
            hint_surface = self.small_font.render("Buy with keys 1-8", True, (124, 217, 145))
            surface.blit(hint_surface, (panel_rect.x + 14, panel_rect.bottom - 28))

        if self.selected_powerup_name is not None:
            self._draw_powerup_details(surface, panel_rect)

    def _set_message(self, message: str) -> None:
        self.message = message
        self.message_timer = 2.5

    def _build_info_button_rects(self) -> dict[str, pygame.Rect]:
        panel_width = HUD_RIGHT_WIDTH - 28
        panel_rect = pygame.Rect(SCREEN_WIDTH - panel_width - 16, SCREEN_HEIGHT - 206, panel_width, 182)
        left_x = panel_rect.x + 14
        right_x = panel_rect.x + panel_rect.width // 2 + 4
        base_y = panel_rect.y + 42
        button_rects = {}
        for index, definition in enumerate(POWERUP_DEFINITIONS):
            column_x = left_x if index % 2 == 0 else right_x
            row_y = base_y + (index // 2) * 24
            button_rects[definition.name] = pygame.Rect(column_x + 94, row_y - 1, 16, 16)
        return button_rects

    def _draw_powerup_details(self, surface: pygame.Surface, panel_rect: pygame.Rect) -> None:
        definition = self.definitions[self.selected_powerup_name]
        detail_rect = pygame.Rect(panel_rect.x - 240, panel_rect.bottom - 124, 220, 124)
        draw_smooth_panel(surface, detail_rect, (30, 36, 48), (230, 235, 240), border_radius=12)

        title_surface = self.detail_font.render(definition.name, True, (244, 246, 249))
        info_lines = [
            f"Cost: ${definition.cost}  Duration: {int(definition.duration)}s",
            f"Effect: {self._format_effects(definition.effect)}",
            f"Side effect: {self._format_effects(definition.side_effect) if definition.side_effect else 'None'}",
            f"Bonus: {self._format_bonuses(definition.bonuses)}",
        ]
        surface.blit(title_surface, (detail_rect.x + 12, detail_rect.y + 10))
        y = detail_rect.y + 38
        for line in info_lines:
            line_surface = self.detail_font.render(self._fit_text(line, self.detail_font, detail_rect.width - 24), True, (220, 226, 233))
            surface.blit(line_surface, (detail_rect.x + 12, y))
            y += 18

    def _format_effects(self, effects: dict[str, float]) -> str:
        if not effects:
            return "None"
        parts = []
        for stat_name, value in effects.items():
            sign = "+" if value > 0 else ""
            parts.append(f"{stat_name} {sign}{int(value)}")
        return ", ".join(parts)

    def _format_bonuses(self, bonuses: dict[str, float]) -> str:
        if not bonuses:
            return "None"
        readable_names = {
            "speed_multiplier": "speed",
            "energy_decay_multiplier": "energy drain",
            "mission_stay_multiplier": "stay timer",
            "focus_damage_multiplier": "focus loss",
            "condition_focus_bonus": "focus check",
            "stress_gain_multiplier": "stress gain",
            "stress_recovery_multiplier": "stress recovery",
        }
        parts = []
        for key, value in bonuses.items():
            label = readable_names.get(key, key)
            if "multiplier" in key:
                parts.append(f"{label} x{value:.2f}")
            else:
                parts.append(f"{label} +{value}")
        return ", ".join(parts)

    def _fit_text(self, text: str, font: pygame.font.Font, max_width: int) -> str:
        if font.size(text)[0] <= max_width:
            return text
        trimmed = text
        while trimmed and font.size(trimmed + "...")[0] > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + "...") if trimmed else text
