import random

import pygame

from game.ui_fonts import ui_font
from game.ui_primitives import draw_smooth_panel
from settings import HUD_RIGHT_WIDTH


MODIFIER_RULES = {
    "NONE": {
        "description": "No active modifier right now.",
        "energy_decay_multiplier": 1.0,
        "stress_gain_multiplier": 1.0,
        "stress_recovery_multiplier": 1.0,
        "focus_loss_multiplier": 1.0,
        "cost_multiplier": 1.0,
        "enemy_bias": "None",
        "spawn_interval_multiplier": 1.2,
    },
    "PROCRASTINATION": {
        "description": "More distractions keep showing up.",
        "energy_decay_multiplier": 1.0,
        "stress_gain_multiplier": 1.0,
        "stress_recovery_multiplier": 1.0,
        "focus_loss_multiplier": 1.35,
        "cost_multiplier": 1.0,
        "enemy_bias": "Social Media Swarm",
        "spawn_interval_multiplier": 1.15,
    },
    "BURNOUT": {
        "description": "Everything feels heavier and drains faster.",
        "energy_decay_multiplier": 1.45,
        "stress_gain_multiplier": 1.2,
        "stress_recovery_multiplier": 0.65,
        "focus_loss_multiplier": 1.0,
        "cost_multiplier": 1.0,
        "enemy_bias": "Sleep Debt Slime",
        "spawn_interval_multiplier": 1.0,
    },
    "BROKE": {
        "description": "Campus costs hit harder than usual.",
        "energy_decay_multiplier": 1.0,
        "stress_gain_multiplier": 1.0,
        "stress_recovery_multiplier": 1.0,
        "focus_loss_multiplier": 1.0,
        "cost_multiplier": 1.5,
        "enemy_bias": "Freeloader Phantom",
        "spawn_interval_multiplier": 1.0,
    },
    "EXAM": {
        "description": "Pressure spikes across every task.",
        "energy_decay_multiplier": 1.1,
        "stress_gain_multiplier": 1.55,
        "stress_recovery_multiplier": 0.9,
        "focus_loss_multiplier": 1.1,
        "cost_multiplier": 1.0,
        "enemy_bias": "Deadline Blob",
        "spawn_interval_multiplier": 0.95,
    },
}


class ModifierSystem:
    def __init__(self) -> None:
        self.font = ui_font(24, bold=True)
        self.small_font = ui_font(19, bold=True)
        self.detail_font = ui_font(17)
        self.random = random.Random()
        self.active_modifier = "EXAM"
        self.modifier_order = [name for name in MODIFIER_RULES.keys() if name != "NONE"]
        self.remaining_time = 0.0
        self.set_active_modifier("EXAM")

    def set_active_modifier(self, modifier_name: str) -> None:
        if modifier_name not in MODIFIER_RULES:
            return

        if modifier_name == "NONE":
            self.active_modifier = "NONE"
            self.remaining_time = 0.0
            return

        if modifier_name == self.active_modifier:
            current_index = self.modifier_order.index(self.active_modifier)
            modifier_name = self.modifier_order[(current_index + 1) % len(self.modifier_order)]

        self.active_modifier = modifier_name
        self.remaining_time = float(self.random.randint(10, 30))

    def update(self, dt: float) -> None:
        if self.active_modifier == "NONE":
            return

        self.remaining_time = max(0.0, self.remaining_time - dt)
        if self.remaining_time == 0.0:
            self.set_active_modifier("NONE")

    def get_energy_decay_multiplier(self) -> float:
        return MODIFIER_RULES[self.active_modifier]["energy_decay_multiplier"]

    def get_stress_gain_multiplier(self) -> float:
        return MODIFIER_RULES[self.active_modifier]["stress_gain_multiplier"]

    def get_stress_recovery_multiplier(self) -> float:
        return MODIFIER_RULES[self.active_modifier]["stress_recovery_multiplier"]

    def get_focus_loss_multiplier(self) -> float:
        return MODIFIER_RULES[self.active_modifier]["focus_loss_multiplier"]

    def get_cost_multiplier(self) -> float:
        return MODIFIER_RULES[self.active_modifier]["cost_multiplier"]

    def get_modifier_enemy_type(self) -> str:
        return MODIFIER_RULES[self.active_modifier]["enemy_bias"]

    def get_spawn_interval_multiplier(self) -> float:
        return MODIFIER_RULES[self.active_modifier]["spawn_interval_multiplier"]

    def draw(self, surface: pygame.Surface) -> None:
        panel_width = HUD_RIGHT_WIDTH - 28
        panel_rect = pygame.Rect(surface.get_width() - panel_width - 16, 18, panel_width, 168)
        draw_smooth_panel(surface, panel_rect, (36, 43, 57), (230, 235, 240), border_radius=12)

        title_surface = self.font.render(self._fit_text(f"Modifier: {self.active_modifier}", self.font, panel_rect.width - 28), True, (244, 246, 249))
        surface.blit(title_surface, (panel_rect.x + 14, panel_rect.y + 12))

        y = panel_rect.y + 36
        for description_line in self._wrap_text(
            MODIFIER_RULES[self.active_modifier]["description"],
            self.small_font,
            panel_rect.width - 28,
        ):
            description_surface = self.small_font.render(description_line, True, (214, 220, 228))
            surface.blit(description_surface, (panel_rect.x + 14, y))
            y += 18

        y += 2
        for detail_line in self.get_modifier_detail_lines():
            detail_surface = self.detail_font.render(self._fit_text(detail_line, self.detail_font, panel_rect.width - 28), True, (196, 206, 219))
            surface.blit(detail_surface, (panel_rect.x + 14, y))
            y += 16

        timer_surface = self.detail_font.render(
            f"Time left: {self.remaining_time:.1f}s" if self.active_modifier != "NONE" else "Time left: --",
            True,
            (124, 217, 145),
        )
        surface.blit(timer_surface, (panel_rect.x + 14, panel_rect.bottom - 26))

    def get_modifier_detail_lines(self) -> list[str]:
        rules = MODIFIER_RULES[self.active_modifier]
        return [
            (
                f"Energy x{rules['energy_decay_multiplier']:.2f} | "
                f"Stress x{rules['stress_gain_multiplier']:.2f}"
            ),
            (
                f"Recover x{rules['stress_recovery_multiplier']:.2f} | "
                f"Focus x{rules['focus_loss_multiplier']:.2f}"
            ),
            f"Costs x{rules['cost_multiplier']:.2f} | Enemy: {rules['enemy_bias']}",
        ]

    def _wrap_text(self, text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current_line = ""

        for word in words:
            candidate = word if not current_line else f"{current_line} {word}"
            if font.size(candidate)[0] <= max_width:
                current_line = candidate
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return lines

    def _fit_text(self, text: str, font: pygame.font.Font, max_width: int) -> str:
        if font.size(text)[0] <= max_width:
            return text
        trimmed = text
        while trimmed and font.size(trimmed + "...")[0] > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + "...") if trimmed else text
