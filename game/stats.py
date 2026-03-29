import pygame

from game.ui_fonts import scaled_ui, ui_font
from game.zone_data import ZONE_EFFECTS, ZONE_NAMES, get_total_effect_magnitude


class Stats:
    def __init__(self) -> None:
        self.energy = 100.0
        self.stress = 55.0
        self.money = 80.0
        self.focus = 70.0
        self.score = 0.0

        self.max_energy = 100.0
        self.max_stress = 100.0
        self.max_money = 250.0
        self.max_focus = 100.0
        self.max_score = 9999.0

        self.energy_drain_rate = 6.0
        self.stress_recovery_rate = 8.0
        self.zone_effect_apply_duration = 2.4
        self.pending_money_spent = 0.0
        self.zone_effect_remaining = {
            zone_name: dict(ZONE_EFFECTS[zone_name]) for zone_name in ZONE_NAMES
        }

        self.font = ui_font(22, bold=True)
        self.meta_font = ui_font(20)

    def apply_change(self, stat_name: str, delta: float) -> float:
        if not hasattr(self, stat_name) or not hasattr(self, f"max_{stat_name}"):
            return 0.0

        current_value = getattr(self, stat_name)
        maximum = getattr(self, f"max_{stat_name}")
        updated_value = max(0.0, min(maximum, current_value + delta))
        setattr(self, stat_name, updated_value)
        applied_delta = updated_value - current_value
        if stat_name == "money" and applied_delta < 0:
            self.pending_money_spent += -applied_delta
        return applied_delta

    def apply_event(self, effects: dict[str, float]) -> None:
        for stat_name, delta in effects.items():
            self.apply_change(stat_name, delta)

    def update(
        self,
        dt: float,
        is_moving: bool,
        active_zone_names: set[str],
        modifier_system,
        powerup_manager,
    ) -> None:
        energy_decay_multiplier = (
            modifier_system.get_energy_decay_multiplier()
            * powerup_manager.get_energy_decay_multiplier()
        )
        stress_recovery_multiplier = (
            modifier_system.get_stress_recovery_multiplier()
            * powerup_manager.get_stress_recovery_multiplier()
        )

        is_inside_zone = bool(active_zone_names)

        if is_moving and not is_inside_zone:
            self.apply_change("energy", -self.energy_drain_rate * energy_decay_multiplier * dt)
        elif not is_inside_zone:
            self.apply_change("stress", -self.stress_recovery_rate * stress_recovery_multiplier * dt)

        for zone_name in active_zone_names:
            self._apply_zone_visit(zone_name, dt)

    def is_out_of_energy(self) -> bool:
        return self.energy <= 0.0

    def is_game_over(self) -> bool:
        return self.energy <= 0.0 and self.money <= 0.0

    def pop_money_spent_display(self) -> int:
        if self.pending_money_spent < 1.0:
            return 0

        spent_amount = max(1, int(round(self.pending_money_spent)))
        self.pending_money_spent = 0.0
        return spent_amount

    def get_zone_charge_ratios(self) -> dict[str, float]:
        ratios: dict[str, float] = {}
        for zone_name in ZONE_NAMES:
            total_magnitude = get_total_effect_magnitude(ZONE_EFFECTS[zone_name])
            remaining_magnitude = get_total_effect_magnitude(self.zone_effect_remaining[zone_name])
            ratios[zone_name] = 0.0 if total_magnitude <= 0 else max(0.0, min(1.0, remaining_magnitude / total_magnitude))
        return ratios

    def draw(self, surface: pygame.Surface) -> None:
        bar_specs = [
            ("Energy", self.energy, self.max_energy, (88, 214, 141)),
            ("Stress", self.stress, self.max_stress, (227, 93, 106)),
            ("Focus", self.focus, self.max_focus, (92, 167, 255)),
        ]

        start_x = scaled_ui(18)
        start_y = scaled_ui(24)
        bar_width = scaled_ui(172)
        bar_height = scaled_ui(12)
        row_height = scaled_ui(64)

        for index, (label, value, maximum, color) in enumerate(bar_specs):
            y = start_y + index * row_height

            label_surface = self.font.render(f"{label}: {int(round(value))}", True, (235, 239, 245))
            surface.blit(label_surface, (start_x, y))

            bar_rect = pygame.Rect(start_x, y + scaled_ui(28), bar_width, bar_height)
            fill_ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
            fill_rect = pygame.Rect(bar_rect.x, bar_rect.y, round(bar_rect.width * fill_ratio), bar_rect.height)

            pygame.draw.rect(surface, (45, 52, 66), bar_rect, border_radius=6)
            pygame.draw.rect(surface, color, fill_rect, border_radius=6)
            pygame.draw.rect(surface, (230, 235, 240), bar_rect, width=2, border_radius=6)

        money_y = start_y + len(bar_specs) * row_height + scaled_ui(16)
        money_surface = self.font.render(f"Money: ${int(round(self.money))}", True, (235, 239, 245))
        surface.blit(money_surface, (start_x, money_y))

        score_y = money_y + scaled_ui(34)
        score_surface = self.font.render(f"Score: {int(round(self.score))}", True, (235, 239, 245))
        surface.blit(score_surface, (start_x, score_y))

    def _apply_zone_visit(self, zone_name: str, dt: float) -> None:
        remaining_effects = self.zone_effect_remaining.get(zone_name)
        template_effects = ZONE_EFFECTS.get(zone_name)
        if remaining_effects is None or template_effects is None:
            return

        for stat_name, total_delta in template_effects.items():
            remaining_delta = remaining_effects.get(stat_name, 0.0)
            if abs(remaining_delta) <= 0.01:
                remaining_effects[stat_name] = 0.0
                continue

            max_step = abs(total_delta) / self.zone_effect_apply_duration * dt
            requested_delta = min(abs(remaining_delta), max_step)
            if remaining_delta < 0:
                requested_delta *= -1

            applied_delta = self.apply_change(stat_name, requested_delta)
            updated_remaining = remaining_delta - applied_delta
            if remaining_delta > 0:
                remaining_effects[stat_name] = max(0.0, updated_remaining)
            else:
                remaining_effects[stat_name] = min(0.0, updated_remaining)
