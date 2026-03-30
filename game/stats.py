import math

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
        self.meta_font = ui_font(18)
        self.caption_font = ui_font(14, bold=True)
        self.value_font = ui_font(24, bold=True)
        self.money_font = ui_font(22, bold=True)
        self.score_font = ui_font(20, bold=True)

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
            self.apply_change(
                "energy", -self.energy_drain_rate * energy_decay_multiplier * dt
            )
        elif not is_inside_zone:
            self.apply_change(
                "stress", -self.stress_recovery_rate * stress_recovery_multiplier * dt
            )

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
            remaining_magnitude = get_total_effect_magnitude(
                self.zone_effect_remaining[zone_name]
            )
            ratios[zone_name] = (
                0.0
                if total_magnitude <= 0
                else max(0.0, min(1.0, remaining_magnitude / total_magnitude))
            )
        return ratios

    def draw(self, surface: pygame.Surface) -> None:
        tick = pygame.time.get_ticks() / 1000.0

        start_x = scaled_ui(18)
        start_y = scaled_ui(22)
        stat_w = scaled_ui(300)
        row_h = scaled_ui(66)

        row_gap = scaled_ui(8)
        # Energy
        self._draw_stat_row(
            surface=surface,
            rect=pygame.Rect(start_x, start_y, stat_w, row_h),
            label="Energy",
            value=self.energy,
            maximum=self.max_energy,
            color=(102, 236, 169),
            icon_type="energy",
            tick=tick,
            subtitle="drive",
            danger_low=True,
        )

        # Stress
        self._draw_stat_row(
            surface=surface,
            rect=pygame.Rect(start_x, start_y + (row_h + row_gap), stat_w, row_h),
            label="Stress",
            value=self.stress,
            maximum=self.max_stress,
            color=(255, 100, 172),
            icon_type="stress",
            tick=tick,
            subtitle="pressure",
            danger_high=True,
        )

        # Focus
        self._draw_stat_row(
            surface=surface,
            rect=pygame.Rect(start_x, start_y + (row_h + row_gap) * 2, stat_w, row_h),
            label="Focus",
            value=self.focus,
            maximum=self.max_focus,
            color=(111, 180, 255),
            icon_type="focus",
            tick=tick,
            subtitle="clarity",
            danger_low=True,
        )

        # Money + Score Cards
        cards_y = start_y + row_h * 3 + scaled_ui(22)
        card_gap = scaled_ui(10)
        card_w = (stat_w - card_gap) // 2
        card_h = scaled_ui(104)

        self._draw_value_card(
            surface=surface,
            rect=pygame.Rect(start_x, cards_y, card_w, card_h),
            title="Money",
            value=f"${int(round(self.money))}",
            accent=(255, 210, 102),
            icon_type="money",
            tick=tick,
            subtitle="cash",
        )

        self._draw_value_card(
            surface=surface,
            rect=pygame.Rect(start_x + card_w + card_gap, cards_y, card_w, card_h),
            title="Score",
            value=f"{int(round(self.score))}",
            accent=(170, 134, 255),
            icon_type="score",
            tick=tick,
            subtitle="progress",
        )

    def _draw_outer_panel(
        self, surface: pygame.Surface, rect: pygame.Rect, tick: float
    ) -> None:
        glow_surface = pygame.Surface(
            (rect.width + 40, rect.height + 40), pygame.SRCALPHA
        )
        glow_rect = pygame.Rect(20, 20, rect.width, rect.height)

        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(tick * 1.7))
        pygame.draw.rect(
            glow_surface,
            (105, 123, 255, int(26 * pulse)),
            glow_rect.inflate(18, 18),
            border_radius=scaled_ui(26),
        )
        pygame.draw.rect(
            glow_surface,
            (255, 88, 188, int(18 * pulse)),
            glow_rect.inflate(8, 8),
            border_radius=scaled_ui(22),
        )
        surface.blit(glow_surface, (rect.x - 20, rect.y - 20))

        panel_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(
            panel_surface,
            (13, 17, 34, 228),
            panel_surface.get_rect(),
            border_radius=scaled_ui(22),
        )
        pygame.draw.rect(
            panel_surface,
            (76, 96, 162),
            panel_surface.get_rect(),
            width=2,
            border_radius=scaled_ui(22),
        )
        pygame.draw.rect(
            panel_surface,
            (255, 255, 255, 18),
            pygame.Rect(0, 0, rect.width, scaled_ui(54)),
            border_radius=scaled_ui(22),
        )
        surface.blit(panel_surface, rect.topleft)

    def _draw_stat_row(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        value: float,
        maximum: float,
        color: tuple[int, int, int],
        icon_type: str,
        tick: float,
        subtitle: str = "",
        danger_low: bool = False,
        danger_high: bool = False,
    ) -> None:
        ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
        row_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)

        pygame.draw.rect(
            row_surface,
            (10, 15, 30, 122),
            row_surface.get_rect(),
            border_radius=scaled_ui(16),
        )
        pygame.draw.rect(
            row_surface,
            (52, 67, 115),
            row_surface.get_rect(),
            width=1,
            border_radius=scaled_ui(16),
        )

        icon_rect = pygame.Rect(
            scaled_ui(8), scaled_ui(10), scaled_ui(38), scaled_ui(38)
        )
        self._draw_pixel_icon(row_surface, icon_rect, icon_type, color, tick, ratio)

        label_surface = self.font.render(label, True, (240, 244, 255))
        value_surface = self.value_font.render(
            f"{int(round(value))}/{int(round(maximum))}", True, (240, 244, 255)
        )
        row_surface.blit(label_surface, (scaled_ui(56), scaled_ui(4)))
        row_surface.blit(
            value_surface,
            (rect.width - scaled_ui(12) - value_surface.get_width(), scaled_ui(4)),
        )

        if subtitle:
            subtitle_surface = self.caption_font.render(
                subtitle.upper(), True, (154, 167, 210)
            )
            row_surface.blit(subtitle_surface, (scaled_ui(56), scaled_ui(28)))

        bar_rect = pygame.Rect(
            scaled_ui(56), scaled_ui(44), rect.width - scaled_ui(68), scaled_ui(14)
        )
        self._draw_animated_bar(
            row_surface,
            bar_rect,
            ratio,
            color,
            tick,
            danger_low=(danger_low and ratio <= 0.35),
            danger_high=(danger_high and ratio >= 0.72),
        )

        surface.blit(row_surface, rect.topleft)

    def _draw_value_card(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        title: str,
        value: str,
        accent: tuple[int, int, int],
        icon_type: str,
        tick: float,
        subtitle: str = "",
    ) -> None:
        glow_surface = pygame.Surface(
            (rect.width + 18, rect.height + 18), pygame.SRCALPHA
        )
        alpha = int(18 + 10 * (0.5 + 0.5 * math.sin(tick * 2.0)))
        pygame.draw.rect(
            glow_surface,
            (*accent, alpha),
            pygame.Rect(9, 9, rect.width, rect.height),
            border_radius=scaled_ui(18),
        )
        surface.blit(glow_surface, (rect.x - 9, rect.y - 9))

        card_surface = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(
            card_surface,
            (11, 16, 30, 226),
            card_surface.get_rect(),
            border_radius=scaled_ui(18),
        )
        pygame.draw.rect(
            card_surface,
            (*accent,),
            card_surface.get_rect(),
            width=2,
            border_radius=scaled_ui(18),
        )
        pygame.draw.rect(
            card_surface,
            (255, 255, 255, 14),
            pygame.Rect(0, 0, rect.width, scaled_ui(24)),
            border_radius=scaled_ui(18),
        )

        icon_rect = pygame.Rect(
            scaled_ui(10), scaled_ui(10), scaled_ui(24), scaled_ui(24)
        )
        self._draw_pixel_icon(card_surface, icon_rect, icon_type, accent, tick, 1.0)

        title_surface = self.caption_font.render(title.upper(), True, (202, 212, 240))
        value_surface = self.money_font.render(
            value, True, accent if title == "Money" else (231, 226, 255)
        )

        card_surface.blit(title_surface, (scaled_ui(42), scaled_ui(12)))
        card_surface.blit(value_surface, (scaled_ui(12), scaled_ui(44)))

        if subtitle:
            subtitle_surface = self.meta_font.render(subtitle, True, (152, 163, 197))
            card_surface.blit(
                subtitle_surface,
                (
                    scaled_ui(12),
                    rect.height - subtitle_surface.get_height() - scaled_ui(10),
                ),
            )

        surface.blit(card_surface, rect.topleft)

    def _draw_animated_bar(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        ratio: float,
        color: tuple[int, int, int],
        tick: float,
        danger_low: bool = False,
        danger_high: bool = False,
    ) -> None:
        pygame.draw.rect(surface, (8, 12, 25), rect, border_radius=scaled_ui(9))
        pygame.draw.rect(
            surface, (58, 73, 118), rect, width=1, border_radius=scaled_ui(9)
        )

        fill_width = max(0, min(rect.width, round(rect.width * ratio)))
        if fill_width <= 0:
            return

        fill_rect = pygame.Rect(rect.x, rect.y, fill_width, rect.height)

        fill_surface = pygame.Surface(
            (fill_rect.width, fill_rect.height), pygame.SRCALPHA
        )
        pygame.draw.rect(
            fill_surface,
            (*color, 210),
            fill_surface.get_rect(),
            border_radius=scaled_ui(9),
        )

        wave_x = int((tick * 90) % max(24, fill_surface.get_width() + 24))
        shine_rect = pygame.Rect(wave_x - 28, 0, 22, fill_surface.get_height())
        pygame.draw.rect(
            fill_surface, (255, 255, 255, 42), shine_rect, border_radius=scaled_ui(8)
        )
        pygame.draw.rect(
            fill_surface,
            (255, 255, 255, 20),
            shine_rect.inflate(18, 0),
            border_radius=scaled_ui(8),
        )

        surface.blit(fill_surface, fill_rect.topleft)

        if danger_low or danger_high:
            danger_surface = pygame.Surface(
                (rect.width + 16, rect.height + 16), pygame.SRCALPHA
            )
            danger_alpha = int(26 + 18 * (0.5 + 0.5 * math.sin(tick * 6.0)))
            danger_color = (
                (255, 106, 152, danger_alpha)
                if danger_high
                else (255, 197, 90, danger_alpha)
            )
            pygame.draw.rect(
                danger_surface,
                danger_color,
                pygame.Rect(8, 8, rect.width, rect.height),
                border_radius=scaled_ui(12),
            )
            surface.blit(danger_surface, (rect.x - 8, rect.y - 8))

    def _draw_pixel_icon(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        icon_type: str,
        accent: tuple[int, int, int],
        tick: float,
        ratio: float,
    ) -> None:
        pulse = 0.5 + 0.5 * math.sin(tick * 4.2)
        bob = int(round(math.sin(tick * 5.0) * 1.5))
        glow_alpha = int(24 + 18 * pulse)

        glow_surface = pygame.Surface(
            (rect.width + 10, rect.height + 10), pygame.SRCALPHA
        )
        pygame.draw.rect(
            glow_surface,
            (*accent, glow_alpha),
            pygame.Rect(5, 5, rect.width, rect.height),
            border_radius=scaled_ui(12),
        )
        surface.blit(glow_surface, (rect.x - 5, rect.y - 5 + bob))

        pygame.draw.rect(
            surface, (20, 28, 52), rect.move(0, bob), border_radius=scaled_ui(12)
        )
        pygame.draw.rect(
            surface,
            (56, 74, 130),
            rect.move(0, bob),
            width=1,
            border_radius=scaled_ui(12),
        )

        px = max(2, rect.width // 12)
        ox = rect.x + (rect.width - px * 8) // 2
        oy = rect.y + (rect.height - px * 8) // 2 + bob

        pattern = self._get_icon_pattern(
            icon_type, phase=int((tick * 6) % 2), ratio=ratio
        )
        for row_index, row in enumerate(pattern):
            for col_index, cell in enumerate(row):
                if not cell:
                    continue

                cell_rect = pygame.Rect(
                    ox + col_index * px, oy + row_index * px, px, px
                )
                cell_color = accent
                if cell == 2:
                    cell_color = (255, 255, 255)
                elif cell == 3:
                    cell_color = (255, 215, 102)
                elif cell == 4:
                    cell_color = (186, 152, 255)
                pygame.draw.rect(
                    surface, cell_color, cell_rect, border_radius=max(1, px // 2)
                )

    def _get_icon_pattern(
        self, icon_type: str, phase: int, ratio: float
    ) -> list[list[int]]:
        if icon_type == "energy":
            if phase == 0:
                return [
                    [0, 0, 1, 1, 0, 0, 0, 0],
                    [0, 1, 1, 1, 0, 0, 0, 0],
                    [0, 1, 1, 0, 0, 0, 0, 0],
                    [0, 0, 1, 0, 0, 1, 0, 0],
                    [0, 0, 1, 1, 1, 1, 0, 0],
                    [0, 0, 0, 0, 1, 1, 0, 0],
                    [0, 0, 0, 1, 1, 0, 0, 0],
                    [0, 0, 0, 1, 0, 0, 0, 0],
                ]
            return [
                [0, 0, 1, 1, 0, 0, 0, 0],
                [0, 1, 1, 1, 0, 0, 0, 0],
                [0, 1, 1, 0, 0, 0, 0, 0],
                [0, 0, 1, 0, 0, 1, 1, 0],
                [0, 0, 1, 1, 1, 1, 0, 0],
                [0, 0, 0, 0, 1, 1, 0, 0],
                [0, 0, 0, 1, 1, 0, 0, 0],
                [0, 0, 0, 1, 0, 0, 0, 0],
            ]

        if icon_type == "stress":
            blink = 2 if phase == 0 else 1
            return [
                [0, 0, 1, 1, 0, 0, 1, 1],
                [0, 1, blink, 1, 0, 1, blink, 1],
                [1, 1, 1, 1, 1, 1, 1, 1],
                [1, 0, 1, 1, 1, 1, 0, 1],
                [0, 1, 1, 1, 1, 1, 1, 0],
                [0, 0, 1, 1, 1, 1, 0, 0],
                [0, 1, 0, 1, 1, 0, 1, 0],
                [1, 0, 0, 1, 1, 0, 0, 1],
            ]

        if icon_type == "focus":
            center = 2 if phase == 0 else 1
            return [
                [0, 0, 1, 1, 1, 1, 0, 0],
                [0, 1, 1, 0, 0, 1, 1, 0],
                [1, 1, 0, center, center, 0, 1, 1],
                [1, 0, center, 2, 2, center, 0, 1],
                [1, 0, center, 2, 2, center, 0, 1],
                [1, 1, 0, center, center, 0, 1, 1],
                [0, 1, 1, 0, 0, 1, 1, 0],
                [0, 0, 1, 1, 1, 1, 0, 0],
            ]

        if icon_type == "money":
            return [
                [0, 0, 3, 3, 3, 3, 0, 0],
                [0, 3, 3, 0, 0, 3, 3, 0],
                [0, 0, 3, 0, 3, 0, 0, 0],
                [0, 3, 3, 3, 3, 3, 3, 0],
                [0, 0, 0, 3, 3, 0, 0, 0],
                [0, 3, 3, 0, 0, 3, 3, 0],
                [0, 0, 3, 3, 3, 3, 0, 0],
                [0, 0, 0, 3, 3, 0, 0, 0],
            ]

        if icon_type == "score":
            sparkle = 2 if phase == 0 else 4
            return [
                [0, 0, 0, sparkle, sparkle, 0, 0, 0],
                [0, 0, 4, 4, 4, 4, 0, 0],
                [0, 4, 4, 4, 4, 4, 4, 0],
                [4, 4, 4, 4, 4, 4, 4, 4],
                [0, 0, 4, 4, 4, 4, 0, 0],
                [0, 0, 4, 4, 4, 4, 0, 0],
                [0, 4, 0, 0, 0, 0, 4, 0],
                [4, 0, 0, 0, 0, 0, 0, 4],
            ]

        return [
            [0, 0, 1, 1, 1, 1, 0, 0],
            [0, 1, 1, 1, 1, 1, 1, 0],
            [1, 1, 0, 1, 1, 0, 1, 1],
            [1, 1, 1, 1, 1, 1, 1, 1],
            [1, 1, 0, 1, 1, 0, 1, 1],
            [0, 1, 1, 1, 1, 1, 1, 0],
            [0, 0, 1, 1, 1, 1, 0, 0],
            [0, 0, 0, 1, 1, 0, 0, 0],
        ]

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
