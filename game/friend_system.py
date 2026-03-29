from collections import deque
from dataclasses import dataclass, field
import random
import threading

import pygame

from game.player import Player
from game.ui_fonts import ui_font
from game.ui_primitives import draw_smooth_panel
from llm.llm_client import generate_friend_encounter
from settings import FRIEND_SPRITE_PATH


ALLOWED_FRIEND_CHOICE_IDS = ("quick_break", "go_to_class", "ask_for_help", "hang_out")


@dataclass
class FriendState:
    friend_id: str = "mika"
    affinity: int = 0
    last_interaction_type: str = "none"


@dataclass
class MikaChoice:
    choice_id: str
    label: str


@dataclass
class MikaEncounter:
    mood: str
    line: str
    choices: list[MikaChoice]


@dataclass
class EscortState:
    destination: str
    player_route: list[pygame.Vector2]
    player_route_index: int = 0
    player_trail: deque[pygame.Vector2] = field(default_factory=lambda: deque(maxlen=28))
    hold_timer: float = 0.0
    choice_id: str = ""
    arrived: bool = False


class FriendSystem:
    def __init__(self, asset_loader, randomizer: random.Random | None = None) -> None:
        self.state = FriendState()
        self.npc = Player(
            width=30,
            height=30,
            asset_loader=asset_loader,
            sprite_path=FRIEND_SPRITE_PATH,
            color=(133, 198, 255),
        )
        self.random = randomizer or random.Random()
        self.current_encounter: MikaEncounter | None = None
        self.pending_encounter: MikaEncounter | None = None
        self.encounter_cooldown = 6.0
        self.pause_timer = 0.0
        self.idle_route: list[pygame.Vector2] = []
        self.idle_route_index = 0
        self.escort_state: EscortState | None = None
        self.recent_actions: list[str] = []
        self.encounter_timer = 0.0
        self.request_in_flight = False
        self._request_lock = threading.Lock()
        self._request_id = 0
        self._last_location = ""
        self._last_visible_hint = ""
        self._wander_target = "Cafe"
        self.completed_destination: str | None = None
        self.name_font = ui_font(14, bold=True)
        self.bubble_font = ui_font(14, bold=True)
        self.choice_font = ui_font(12, bold=True)
        self.hint_font = ui_font(11)

    def reset_for_day(self, game_map) -> None:
        self.clear_runtime(preserve_cooldown=False)
        spawn_zone = self.random.choice(("Cafe", "Club Room", "Park", "Library"))
        spawn_rect = game_map.get_zone_rect(spawn_zone)
        if spawn_rect is None:
            spawn_rect = pygame.Rect(0, 0, 32, 32)
            spawn_rect.center = game_map.get_spawn_position()
        self.npc.set_center(*spawn_rect.center)
        self.npc.set_speed_multiplier(0.9)
        self._wander_target = spawn_zone
        self._last_location = game_map.get_current_location_label(self.npc.rect)

    def clear_runtime(self, preserve_cooldown: bool = True) -> None:
        with self._request_lock:
            self._request_id += 1
        self.current_encounter = None
        self.pending_encounter = None
        self.request_in_flight = False
        self.idle_route = []
        self.idle_route_index = 0
        self.pause_timer = 0.0
        self.encounter_timer = 0.0
        self.escort_state = None
        self.completed_destination = None
        if not preserve_cooldown:
            self.encounter_cooldown = 4.0

    def update_runtime(self, dt: float) -> None:
        if self.encounter_cooldown > 0:
            self.encounter_cooldown = max(0.0, self.encounter_cooldown - dt)
        if self.pause_timer > 0:
            self.pause_timer = max(0.0, self.pause_timer - dt)
        if self.current_encounter is not None:
            self.encounter_timer = max(0.0, self.encounter_timer - dt)
            if self.encounter_timer <= 0:
                self.current_encounter = None
        with self._request_lock:
            if self.pending_encounter is not None:
                self.current_encounter = self.pending_encounter
                self.pending_encounter = None
                self.encounter_timer = 14.0

    def update_idle(self, dt: float, game_map, player_rect: pygame.Rect) -> None:
        if self.escort_state is not None:
            return

        player_distance = pygame.Vector2(self.npc.rect.center).distance_to(player_rect.center)
        if player_distance <= 104:
            self.pause_timer = max(self.pause_timer, 1.0)

        if self.pause_timer > 0:
            self.npc.move_with_direction(pygame.Vector2(), dt, game_map.world_rect.width, game_map.world_rect.height, can_move=False)
            return

        if self.idle_route_index >= len(self.idle_route):
            self._choose_idle_route(game_map)

        if self.idle_route_index < len(self.idle_route):
            target = self.idle_route[self.idle_route_index]
            self._move_entity_along_route(self.npc, target, dt, game_map)
            if pygame.Vector2(self.npc.rect.center).distance_to(target) <= 12:
                self.idle_route_index += 1
                if self.idle_route_index >= len(self.idle_route):
                    self.pause_timer = self.random.uniform(1.1, 2.1)

    def maybe_trigger_encounter(self, context: dict) -> None:
        if self.current_encounter is not None or self.pending_encounter is not None or self.request_in_flight:
            return
        if self.encounter_cooldown > 0 or self.escort_state is not None:
            return

        current_location = str(context.get("current_location", ""))
        trigger_reason: str | None = None
        if current_location in {"Cafe", "Club Room"} and current_location != self._last_location:
            trigger_reason = current_location.lower().replace(" ", "_")
        elif float(context.get("stress", 0)) >= 76:
            trigger_reason = "high_stress"
        elif float(context.get("energy", 100)) <= 28:
            trigger_reason = "low_energy"

        self._last_location = current_location
        if trigger_reason is None:
            return

        self.encounter_cooldown = 18.0
        self._request_encounter(dict(context))

    def is_player_close(self, player_rect: pygame.Rect) -> bool:
        return pygame.Vector2(self.npc.rect.center).distance_to(player_rect.center) <= 108

    def has_active_choices(self) -> bool:
        return self.current_encounter is not None and bool(self.current_encounter.choices)

    def choose_option(self, choice_number: int, current_location: str, class_live_now: bool, energy: float) -> dict | None:
        if self.current_encounter is None:
            return None
        if not 1 <= choice_number <= len(self.current_encounter.choices):
            return None

        choice = self.current_encounter.choices[choice_number - 1]
        choice_id = choice.choice_id
        affinity_delta = 0
        focus_delta = 0
        stress_delta = 0
        energy_delta = 0
        time_cost = 0.0
        destination: str | None = None

        if choice_id == "quick_break":
            energy_delta = 6
            stress_delta = -5
            focus_delta = -4 if class_live_now else -1
            time_cost = 1.0
            destination = "Dorm" if energy < 35 else "Park"
            affinity_delta = 1
        elif choice_id == "go_to_class":
            focus_delta = 6
            stress_delta = 2
            time_cost = 0.5
            destination = "Lecture Hall"
            affinity_delta = -1 if self.current_encounter.mood == "playful" else 0
        elif choice_id == "ask_for_help":
            focus_delta = 4
            stress_delta = -2
            time_cost = 1.0
            destination = "Library"
            affinity_delta = 2
        elif choice_id == "hang_out":
            energy_delta = 4
            stress_delta = -9
            focus_delta = -5
            time_cost = 2.0
            destination = "Club Room" if current_location == "Cafe" else "Cafe"
            affinity_delta = 1
        else:
            return None

        self.state.affinity = max(-10, min(10, self.state.affinity + affinity_delta))
        self.state.last_interaction_type = choice_id
        self.recent_actions.append(choice_id)
        self.recent_actions = self.recent_actions[-3:]
        self.current_encounter = None
        self.encounter_timer = 0.0
        self.encounter_cooldown = 22.0

        return {
            "choice_id": choice_id,
            "energy_delta": energy_delta,
            "stress_delta": stress_delta,
            "focus_delta": focus_delta,
            "time_cost": time_cost,
            "destination": destination,
            "affinity_delta": affinity_delta,
        }

    def start_escort(self, destination: str, game_map, player) -> bool:
        route_points = game_map.get_route_points(player.rect, destination, traversal="bfs")
        if len(route_points) < 2:
            return False
        self.completed_destination = None

        escort_state = EscortState(
            destination=destination,
            player_route=route_points[1:],
            choice_id=self.state.last_interaction_type,
        )
        escort_state.player_trail.append(pygame.Vector2(player.rect.center))
        self.escort_state = escort_state
        self.pause_timer = 0.0
        return True

    def update_escort(self, dt: float, game_map, player) -> bool:
        escort = self.escort_state
        if escort is None:
            return False

        player_moved = False
        player.set_speed_multiplier(1.0)
        if escort.player_route_index < len(escort.player_route):
            target = escort.player_route[escort.player_route_index]
            player_moved = self._move_entity_along_route(player, target, dt, game_map)
            escort.player_trail.append(pygame.Vector2(player.rect.center))
            if pygame.Vector2(player.rect.center).distance_to(target) <= 12:
                escort.player_route_index += 1
        else:
            if not escort.arrived:
                escort.arrived = True
                escort.hold_timer = 1.15
            else:
                escort.hold_timer = max(0.0, escort.hold_timer - dt)

        self._update_npc_trail_follow(dt, game_map, player, escort)
        if escort.arrived and escort.hold_timer <= 0:
            if pygame.Vector2(self.npc.rect.center).distance_to(player.rect.center) <= 46:
                self.completed_destination = escort.destination
                self.escort_state = None
                self.pause_timer = 0.8
        return player_moved

    def draw(self, surface: pygame.Surface, game_map, player_rect: pygame.Rect, show_hint: bool = True) -> None:
        npc_screen_rect = game_map.world_to_screen_rect(self.npc.rect)
        if npc_screen_rect.colliderect(game_map.playfield_rect):
            self.npc.draw(surface, npc_screen_rect)

        visible_ratio = self._visible_ratio(npc_screen_rect, game_map.playfield_rect)
        if visible_ratio < 0.5:
            return

        close_enough = self.is_player_close(player_rect)
        if self.current_encounter is not None and close_enough:
            self._draw_encounter_ui(surface, game_map.playfield_rect, npc_screen_rect)
        elif self.current_encounter is not None:
            self._draw_hint(surface, game_map.playfield_rect, npc_screen_rect, "Walk closer")
        elif self.request_in_flight and close_enough:
            self._draw_hint(surface, game_map.playfield_rect, npc_screen_rect, "Mika...")
        elif show_hint:
            self._draw_hint(surface, game_map.playfield_rect, npc_screen_rect, "Mika")

    def pop_completed_destination(self) -> str | None:
        destination = self.completed_destination
        self.completed_destination = None
        return destination

    def place_npc(self, center: tuple[int, int]) -> None:
        self.npc.set_center(*center)

    def _request_encounter(self, context: dict) -> None:
        with self._request_lock:
            self._request_id += 1
            request_id = self._request_id
            self.request_in_flight = True

        def _worker() -> None:
            try:
                encounter_data = generate_friend_encounter(context)
                encounter = MikaEncounter(
                    mood=str(encounter_data.get("mood", "supportive")),
                    line=str(encounter_data.get("line", "Want a quick reset?")),
                    choices=[
                        MikaChoice(choice_id=choice["id"], label=choice["label"])
                        for choice in encounter_data.get("choices", [])
                    ],
                )
                with self._request_lock:
                    if request_id != self._request_id:
                        return
                    self.pending_encounter = encounter
            finally:
                with self._request_lock:
                    if request_id != self._request_id:
                        return
                    self.request_in_flight = False

        threading.Thread(target=_worker, daemon=True).start()

    def _choose_idle_route(self, game_map) -> None:
        zone_names = [zone.name for zone in game_map.zones if zone.name != self._wander_target]
        if not zone_names:
            return
        self._wander_target = self.random.choice(zone_names)
        route_points = game_map.get_route_points(self.npc.rect, self._wander_target, traversal="bfs")
        self.idle_route = route_points[1:] if len(route_points) > 1 else route_points
        self.idle_route_index = 0

    def _update_npc_trail_follow(self, dt: float, game_map, player, escort: EscortState) -> None:
        if len(escort.player_trail) > 8:
            trail_target = escort.player_trail[0]
            self._move_entity_along_route(self.npc, trail_target, dt, game_map)
            if pygame.Vector2(self.npc.rect.center).distance_to(trail_target) <= 12:
                escort.player_trail.popleft()
        else:
            fallback_target = pygame.Vector2(player.rect.center)
            self._move_entity_along_route(self.npc, fallback_target, dt, game_map)

    def _move_entity_along_route(self, entity: Player, target: pygame.Vector2, dt: float, game_map) -> bool:
        current_center = pygame.Vector2(entity.rect.center)
        offset = pygame.Vector2(target) - current_center
        if abs(offset.x) <= 6 and abs(offset.y) <= 6:
            entity.move_with_direction(pygame.Vector2(), dt, game_map.world_rect.width, game_map.world_rect.height, can_move=False)
            return False

        axis_order = ("x", "y") if abs(offset.x) >= abs(offset.y) else ("y", "x")
        for axis in axis_order:
            component = offset.x if axis == "x" else offset.y
            if abs(component) <= 4:
                continue
            direction = pygame.Vector2(0, 0)
            if axis == "x":
                direction.x = 1 if component > 0 else -1
            else:
                direction.y = 1 if component > 0 else -1

            previous_center = pygame.Vector2(entity.rect.center)
            entity.move_with_direction(direction, dt, game_map.world_rect.width, game_map.world_rect.height)
            entity.clamp_to_rect(game_map.get_player_bounds())
            game_map.keep_player_on_paths(entity)
            entity.clamp_to_rect(game_map.get_player_bounds())
            if pygame.Vector2(entity.rect.center).distance_to(previous_center) >= 1.0:
                return True

        return self._try_pixel_adjustments(entity, game_map, offset)

    def _try_pixel_adjustments(self, entity: Player, game_map, offset: pygame.Vector2) -> bool:
        x_sign = 1 if offset.x > 0 else -1
        y_sign = 1 if offset.y > 0 else -1
        adjustments = [
            (x_sign, 0),
            (0, y_sign),
            (-x_sign, 0),
            (0, -y_sign),
            (x_sign * 2, 0),
            (0, y_sign * 2),
        ]

        for adjust_x, adjust_y in adjustments:
            original_position = entity.position.copy()
            original_rect = entity.rect.copy()
            entity.position.x += adjust_x
            entity.position.y += adjust_y
            entity.rect.topleft = (round(entity.position.x), round(entity.position.y))
            entity.clamp_to_rect(game_map.get_player_bounds())
            if game_map.is_rect_on_paths(entity.rect):
                return True
            entity.position.update(original_position)
            entity.rect = original_rect

        return False

    def _visible_ratio(self, target_rect: pygame.Rect, clip_rect: pygame.Rect) -> float:
        intersection = target_rect.clip(clip_rect)
        visible_area = intersection.width * intersection.height
        total_area = max(1, target_rect.width * target_rect.height)
        return visible_area / total_area

    def _draw_hint(self, surface: pygame.Surface, playfield_rect: pygame.Rect, npc_rect: pygame.Rect, text: str) -> None:
        hint_surface = self.hint_font.render(text, True, (241, 245, 249))
        hint_rect = hint_surface.get_rect(midbottom=(npc_rect.centerx, npc_rect.y - 6))
        hint_box = hint_rect.inflate(12, 8)
        hint_box.clamp_ip(playfield_rect.inflate(-8, -8))
        hint_rect.center = hint_box.center
        draw_smooth_panel(surface, hint_box, (33, 39, 52), (213, 219, 228), border_radius=10)
        surface.blit(hint_surface, hint_rect)

    def _draw_encounter_ui(self, surface: pygame.Surface, playfield_rect: pygame.Rect, npc_rect: pygame.Rect) -> None:
        if self.current_encounter is None:
            return

        bubble_width = 204
        bubble_height = 48 + len(self.current_encounter.choices) * 20
        bubble_rect = pygame.Rect(npc_rect.right + 10, npc_rect.y - 8, bubble_width, bubble_height)
        if bubble_rect.right > playfield_rect.right - 8:
            bubble_rect.x = npc_rect.x - bubble_width - 10
        if bubble_rect.y < playfield_rect.y + 8:
            bubble_rect.y = npc_rect.bottom + 8
        bubble_rect.clamp_ip(playfield_rect.inflate(-8, -8))

        border_color = {
            "supportive": (126, 225, 160),
            "playful": (249, 193, 108),
            "concerned": (178, 188, 255),
        }.get(self.current_encounter.mood, (213, 220, 229))
        draw_smooth_panel(surface, bubble_rect, (34, 39, 53), border_color, border_radius=12)

        line_surface = self.bubble_font.render(self.current_encounter.line, True, (245, 247, 250))
        surface.blit(line_surface, (bubble_rect.x + 10, bubble_rect.y + 10))

        y = bubble_rect.y + 28
        for index, choice in enumerate(self.current_encounter.choices, start=1):
            choice_surface = self.choice_font.render(f"[{index}] {choice.label}", True, (228, 234, 243))
            surface.blit(choice_surface, (bubble_rect.x + 10, y))
            y += 18
