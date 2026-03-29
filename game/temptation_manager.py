import random
from dataclasses import dataclass

import pygame

from game.ui_fonts import ui_font
from game.ui_primitives import draw_smooth_panel

@dataclass(frozen=True)
class Temptation:
    temptation_type: str
    title: str
    description: str


TEMPTATIONS = (
    Temptation(
        temptation_type="WATCH_VIDEO",
        title="Watch video",
        description="+Energy now, but it wrecks focus.",
    ),
    Temptation(
        temptation_type="SCROLL_PHONE",
        title="Scroll phone",
        description="Slow focus drain while you doomscroll.",
    ),
)


class TemptationManager:
    def __init__(self) -> None:
        self.font = ui_font(22, bold=True)
        self.small_font = ui_font(17)
        self.random = random.Random()
        self.time_since_last_spawn = 0.0
        self.next_spawn_interval = self.random.uniform(9.0, 15.0)
        self.active_temptation: Temptation | None = None
        self.active_timer = 0.0
        self.active_message = ""
        self.message_timer = 0.0
        self.scroll_effect_timer = 0.0
        self.scroll_focus_loss_rate = 6.5

    def update(self, dt: float, stats) -> None:
        self.time_since_last_spawn += dt

        if self.message_timer > 0:
            self.message_timer = max(0.0, self.message_timer - dt)

        if self.active_temptation is None and self.time_since_last_spawn >= self.next_spawn_interval:
            self.active_temptation = self.random.choice(TEMPTATIONS)
            self.active_timer = 7.0
            self.time_since_last_spawn = 0.0
            self.next_spawn_interval = self.random.uniform(10.0, 16.0)

        if self.active_temptation is not None:
            self.active_timer = max(0.0, self.active_timer - dt)
            if self.active_timer <= 0:
                self.ignore()

        if self.scroll_effect_timer > 0:
            self.scroll_effect_timer = max(0.0, self.scroll_effect_timer - dt)
            stats.apply_change("focus", -self.scroll_focus_loss_rate * dt)

    def has_choice(self) -> bool:
        return self.active_temptation is not None

    def engage(self, stats) -> bool:
        if self.active_temptation is None:
            return False

        temptation_type = self.active_temptation.temptation_type
        if temptation_type == "WATCH_VIDEO":
            stats.apply_change("energy", 12.0)
            stats.apply_change("focus", -10.0)
            self.active_message = "Temptation: watched a video. +12 energy, -10 focus"
        elif temptation_type == "SCROLL_PHONE":
            self.scroll_effect_timer = 6.0
            self.active_message = "Temptation: doomscrolling. Focus is draining"
        else:
            return False

        self.message_timer = 3.0
        self.active_temptation = None
        self.active_timer = 0.0
        return True

    def ignore(self) -> bool:
        if self.active_temptation is None:
            return False
        self.active_message = f"Ignored temptation: {self.active_temptation.title}"
        self.message_timer = 2.5
        self.active_temptation = None
        self.active_timer = 0.0
        return True

    def draw(self, surface: pygame.Surface) -> None:
        panel_rect = pygame.Rect(surface.get_width() // 2 - 180, 18, 360, 66)
        if self.active_temptation is not None:
            draw_smooth_panel(surface, panel_rect, (54, 42, 58), (231, 164, 255), border_radius=12)

            title_surface = self.font.render(f"Temptation: {self.active_temptation.title}", True, (245, 247, 250))
            body_surface = self.small_font.render(self.active_temptation.description, True, (227, 232, 239))
            hint_surface = self.small_font.render("[T] engage  |  [G] ignore", True, (244, 194, 255))

            surface.blit(title_surface, (panel_rect.x + 12, panel_rect.y + 8))
            surface.blit(body_surface, (panel_rect.x + 12, panel_rect.y + 30))
            surface.blit(hint_surface, (panel_rect.x + 12, panel_rect.y + 46))
            return

        if self.message_timer <= 0 and self.scroll_effect_timer <= 0:
            return

        draw_smooth_panel(surface, panel_rect, (42, 45, 57), (219, 225, 234), border_radius=12)

        if self.message_timer > 0 and self.active_message:
            message_surface = self.small_font.render(self.active_message, True, (237, 240, 245))
            surface.blit(message_surface, (panel_rect.x + 12, panel_rect.y + 24))
        elif self.scroll_effect_timer > 0:
            scroll_surface = self.small_font.render(
                f"Scrolling phone... focus drain for {self.scroll_effect_timer:0.1f}s",
                True,
                (237, 240, 245),
            )
            surface.blit(scroll_surface, (panel_rect.x + 12, panel_rect.y + 24))
