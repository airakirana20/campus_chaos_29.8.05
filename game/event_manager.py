import threading
import time

import pygame

from game.ui_fonts import ui_font
from llm.llm_client import generate_event


class EventManager:
    def __init__(self) -> None:
        self.event_interval = 10.0
        self.time_since_last_event = 0.0
        self.message_duration = 3.0
        self.message_timer = 0.0
        self.request_timeout = 3.0
        self.font = ui_font(20, bold=True)
        self.current_event_text = ""
        self.pending_event: dict | None = None

        self._lock = threading.Lock()
        self._active_request_id = 0
        self._active_request_started_at = 0.0
        self._request_in_flight = False

    def update(self, dt: float, game_state: dict) -> None:
        self.time_since_last_event += dt

        if self.message_timer > 0:
            self.message_timer = max(0.0, self.message_timer - dt)

        if self._request_in_flight:
            self._expire_slow_request()

        while self.time_since_last_event >= self.event_interval:
            self.time_since_last_event -= self.event_interval
            self._start_event_request(game_state)

    def pop_pending_event(self) -> dict | None:
        with self._lock:
            pending_event = self.pending_event
            self.pending_event = None
        return pending_event

    def show_event_message(self, event_data: dict, mission_applied: bool) -> None:
        modifier = event_data.get("modifier", "EXAM")
        enemies = ", ".join(event_data.get("enemies", [])) or "none"
        missions = event_data.get("missions", {})
        risk_mission = missions.get("risk", {}) if isinstance(missions, dict) else {}
        mission_title = risk_mission.get("title", "Fallback Mission")
        mission_prefix = "New mission" if mission_applied else "Saved next mission"
        self.current_event_text = f"{mission_prefix}: {mission_title} | {modifier} | {enemies}"
        self.message_timer = self.message_duration

    def draw(self, surface: pygame.Surface) -> None:
        if self.message_timer <= 0 or not self.current_event_text:
            return

        text_surface = self.font.render(self.current_event_text, True, (246, 247, 250))
        text_rect = text_surface.get_rect(center=(surface.get_width() // 2, surface.get_height() - 22))
        background_rect = text_rect.inflate(20, 12)

        pygame.draw.rect(surface, (36, 43, 57), background_rect, border_radius=12)
        pygame.draw.rect(surface, (233, 237, 241), background_rect, width=2, border_radius=12)
        surface.blit(text_surface, text_rect)

    def _start_event_request(self, game_state: dict) -> None:
        with self._lock:
            if self._request_in_flight:
                return

            self._active_request_id += 1
            request_id = self._active_request_id
            self._active_request_started_at = time.monotonic()
            self._request_in_flight = True

        worker = threading.Thread(
            target=self._request_event_in_background,
            args=(request_id, dict(game_state)),
            daemon=True,
        )
        worker.start()

    def _request_event_in_background(self, request_id: int, game_state: dict) -> None:
        event_data = generate_event(game_state)

        with self._lock:
            elapsed = time.monotonic() - self._active_request_started_at
            if request_id != self._active_request_id or elapsed > self.request_timeout:
                return

            self.pending_event = event_data
            self._request_in_flight = False

    def _expire_slow_request(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._active_request_started_at
            if elapsed <= self.request_timeout:
                return

            self._request_in_flight = False
            self._active_request_id += 1
