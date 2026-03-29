import random
from dataclasses import dataclass

import pygame

from game.ui_fonts import ui_font
from settings import ENEMY_LIMIT


ENEMY_COLORS = {
    "Deadline Blob": (213, 92, 110),
    "Social Media Swarm": (95, 146, 255),
    "Freeloader Phantom": (175, 120, 255),
    "Sleep Debt Slime": (109, 206, 164),
}


@dataclass
class Enemy:
    enemy_type: str
    rect: pygame.Rect
    color: tuple[int, int, int]
    velocity: pygame.Vector2
    lifetime: float


class EnemyManager:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.font = ui_font(24, bold=True)
        self.enemies: list[Enemy] = []
        self.modifier_spawn_timer = 0.0
        self.mission_spawn_timer = 0.0
        self.player_speed_multiplier = 1.0
        self.world_bounds = pygame.Rect(0, 0, width, height)
        self.walkable_rects: list[pygame.Rect] = []

    def set_navigation_bounds(self, world_bounds: pygame.Rect, walkable_rects: list[pygame.Rect]) -> None:
        self.world_bounds = world_bounds.copy()
        self.width = self.world_bounds.width
        self.height = self.world_bounds.height
        self.walkable_rects = [rect.copy() for rect in walkable_rects]

    def apply_enemy_plan(self, enemy_names: list[str], avoid_rect: pygame.Rect | None = None) -> None:
        for enemy_name in enemy_names:
            self.spawn_enemy(enemy_name, avoid_rect=avoid_rect)

    def get_player_speed_multiplier(self) -> float:
        return self.player_speed_multiplier

    def get_blocking_rects(self) -> list[pygame.Rect]:
        return []

    def update(
        self,
        dt: float,
        player,
        stats,
        mission_manager,
        modifier_system,
        powerup_manager,
    ) -> None:
        self.player_speed_multiplier = 1.0
        self.modifier_spawn_timer += dt
        self.mission_spawn_timer += dt

        modifier_interval = 12.0 * modifier_system.get_spawn_interval_multiplier()
        if self.modifier_spawn_timer >= modifier_interval:
            self.modifier_spawn_timer = 0.0
            self.spawn_enemy(modifier_system.get_modifier_enemy_type(), avoid_rect=player.rect)

        if self.mission_spawn_timer >= 14.0:
            self.mission_spawn_timer = 0.0
            mission_enemy = self._get_mission_enemy_type(mission_manager)
            if mission_enemy is not None:
                self.spawn_enemy(mission_enemy, avoid_rect=player.rect)

        for enemy in list(self.enemies):
            enemy.lifetime -= dt
            if enemy.lifetime <= 0:
                self.enemies.remove(enemy)
                continue

            previous_rect = enemy.rect.copy()
            enemy.rect.x += round(enemy.velocity.x * dt)
            enemy.rect.y += round(enemy.velocity.y * dt)
            if enemy.rect.left <= self.world_bounds.left or enemy.rect.right >= self.world_bounds.right:
                enemy.velocity.x *= -1
            if enemy.rect.top <= self.world_bounds.top or enemy.rect.bottom >= self.world_bounds.bottom:
                enemy.velocity.y *= -1
            enemy.rect.clamp_ip(self.world_bounds)
            if self.walkable_rects and not self._is_on_walkable_path(enemy.rect):
                enemy.rect = previous_rect
                enemy.velocity *= -1

            interaction_rect = enemy.rect.inflate(36, 36)
            if not interaction_rect.colliderect(player.rect):
                continue

            if enemy.enemy_type == "Deadline Blob":
                stats.apply_change(
                    "stress",
                    14.0 * modifier_system.get_stress_gain_multiplier() * powerup_manager.get_stress_gain_multiplier() * dt,
                )
            elif enemy.enemy_type == "Social Media Swarm":
                stats.apply_change(
                    "focus",
                    -7.0 * modifier_system.get_focus_loss_multiplier() * powerup_manager.get_focus_damage_multiplier() * dt,
                )
            elif enemy.enemy_type == "Freeloader Phantom":
                mission_manager.apply_progress_penalty(4.0 * dt)
            elif enemy.enemy_type == "Sleep Debt Slime":
                self.player_speed_multiplier = min(self.player_speed_multiplier, 0.6)
                stats.apply_change("energy", -7.0 * dt)

    def draw(self, surface: pygame.Surface, draw_offset: tuple[int, int] = (0, 0), clip_rect: pygame.Rect | None = None) -> None:
        previous_clip = surface.get_clip()
        if clip_rect is not None:
            surface.set_clip(clip_rect)
        for enemy in self.enemies:
            screen_rect = enemy.rect.move(draw_offset)
            border_radius = 14
            pygame.draw.rect(surface, enemy.color, screen_rect, border_radius=border_radius)
            pygame.draw.rect(surface, (240, 242, 245), screen_rect, width=2, border_radius=border_radius)
            label_surface = self.font.render(enemy.enemy_type, True, (248, 249, 251))
            surface.blit(label_surface, (screen_rect.x + 8, screen_rect.y + 8))
        surface.set_clip(previous_clip)

    def spawn_enemy(self, enemy_type: str, avoid_rect: pygame.Rect | None = None) -> None:
        if enemy_type not in ENEMY_COLORS or len(self.enemies) >= ENEMY_LIMIT:
            return

        if sum(enemy.enemy_type == enemy_type for enemy in self.enemies) >= 2:
            return

        width = 72
        height = 48
        velocity = pygame.Vector2(random.choice([-90, -70, 70, 90]), random.choice([-75, -55, 55, 75]))
        lifetime = 18.0

        spawn_rect: pygame.Rect | None = None
        for _ in range(20):
            x = random.randint(self.world_bounds.left + 40, max(self.world_bounds.left + 40, self.world_bounds.right - width - 40))
            y = random.randint(self.world_bounds.top + 40, max(self.world_bounds.top + 40, self.world_bounds.bottom - height - 40))
            candidate_rect = pygame.Rect(x, y, width, height)
            if avoid_rect is not None and candidate_rect.colliderect(avoid_rect.inflate(80, 80)):
                continue
            if self.walkable_rects and not self._is_on_walkable_path(candidate_rect):
                continue
            spawn_rect = candidate_rect
            break

        if spawn_rect is None:
            return

        self.enemies.append(
            Enemy(
                enemy_type=enemy_type,
                rect=spawn_rect,
                color=ENEMY_COLORS[enemy_type],
                velocity=velocity,
                lifetime=lifetime,
            )
        )

    def _get_mission_enemy_type(self, mission_manager) -> str | None:
        current_step = mission_manager.get_current_step()
        if current_step is None:
            return None

        if current_step.step_type == "STAY":
            zone_enemy_map = {
                "Library": "Deadline Blob",
                "Lecture Hall": "Deadline Blob",
                "Cafe": "Social Media Swarm",
                "Club Room": "Social Media Swarm",
                "Print Room": "Freeloader Phantom",
                "Part-Time Job": "Freeloader Phantom",
                "Dorm": "Sleep Debt Slime",
                "Park": "Sleep Debt Slime",
            }
            return zone_enemy_map.get(current_step.target)

        if current_step.step_type == "CONDITION":
            return "Freeloader Phantom"

        return None

    def _is_on_walkable_path(self, rect: pygame.Rect) -> bool:
        return any(rect.colliderect(path_rect) for path_rect in self.walkable_rects)
