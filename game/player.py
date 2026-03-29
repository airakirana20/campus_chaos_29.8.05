import pygame

from game.asset_loader import AssetLoader
from settings import PLAYER_BASE_SPEED, PLAYER_SPRITE_PATH


class Player:
    def __init__(
        self,
        x: int = 0,
        y: int = 0,
        width: int = 32,
        height: int = 32,
        asset_loader: AssetLoader | None = None,
        sprite_path: str = PLAYER_SPRITE_PATH,
        color: tuple[int, int, int] = (80, 200, 120),
    ) -> None:
        self.rect = pygame.Rect(x, y, width, height)
        self.position = pygame.Vector2(self.rect.topleft)
        self.previous_position = pygame.Vector2(self.rect.topleft)
        self.previous_rect = self.rect.copy()
        self.color = color
        self.base_speed = PLAYER_BASE_SPEED
        self.speed_multiplier = 1.0
        self.asset_loader = asset_loader or AssetLoader()
        self.sprite_path = sprite_path
        self.sprite = self.asset_loader.load_image(self.sprite_path, (width, height))

    def set_center(self, x: int, y: int) -> None:
        self.rect.center = (x, y)
        self.position.update(self.rect.topleft)
        self.previous_position.update(self.rect.topleft)
        self.previous_rect = self.rect.copy()

    def set_speed_multiplier(self, multiplier: float) -> None:
        self.speed_multiplier = max(0.35, multiplier)

    def revert_to_previous_position(self) -> None:
        self.position.update(self.previous_position)
        self.rect = self.previous_rect.copy()

    def resolve_blockers(self, blocking_rects: list[pygame.Rect]) -> None:
        for blocking_rect in blocking_rects:
            if not self.rect.colliderect(blocking_rect):
                continue

            if self.previous_rect.right <= blocking_rect.left < self.rect.right:
                self.rect.right = blocking_rect.left
            elif self.previous_rect.left >= blocking_rect.right > self.rect.left:
                self.rect.left = blocking_rect.right
            elif self.previous_rect.bottom <= blocking_rect.top < self.rect.bottom:
                self.rect.bottom = blocking_rect.top
            elif self.previous_rect.top >= blocking_rect.bottom > self.rect.top:
                self.rect.top = blocking_rect.bottom
            else:
                self.rect = self.previous_rect.copy()

            self.position.update(self.rect.topleft)

    def clamp_to_rect(self, bounds_rect: pygame.Rect) -> None:
        self.rect.clamp_ip(bounds_rect)
        self.position.update(self.rect.topleft)

    def update(self, dt: float, max_width: int, max_height: int, can_move: bool = True) -> bool:
        keys = pygame.key.get_pressed()
        direction = pygame.Vector2(0, 0)

        if keys[pygame.K_w]:
            direction.y -= 1
        if keys[pygame.K_s]:
            direction.y += 1
        if keys[pygame.K_a]:
            direction.x -= 1
        if keys[pygame.K_d]:
            direction.x += 1

        if direction.length_squared() > 0:
            direction = direction.normalize()

        return self.move_with_direction(direction, dt, max_width, max_height, can_move=can_move)

    def move_with_direction(
        self,
        direction: pygame.Vector2,
        dt: float,
        max_width: int,
        max_height: int,
        can_move: bool = True,
    ) -> bool:
        self.previous_position = self.position.copy()
        self.previous_rect = self.rect.copy()

        if not can_move:
            self.rect.topleft = (round(self.position.x), round(self.position.y))
            return False

        speed = self.base_speed * self.speed_multiplier
        self.position += direction * speed * dt
        self.position.x = max(0, min(self.position.x, max_width - self.rect.width))
        self.position.y = max(0, min(self.position.y, max_height - self.rect.height))
        self.rect.topleft = (round(self.position.x), round(self.position.y))
        return direction.length_squared() > 0

    def move_toward_point(
        self,
        target_point: tuple[float, float] | pygame.Vector2,
        dt: float,
        max_width: int,
        max_height: int,
        can_move: bool = True,
        arrive_radius: float = 8.0,
    ) -> bool:
        target_vector = pygame.Vector2(target_point)
        current_center = pygame.Vector2(self.rect.center)
        offset = target_vector - current_center
        if offset.length_squared() <= arrive_radius * arrive_radius:
            return self.move_with_direction(pygame.Vector2(), dt, max_width, max_height, can_move=False)

        return self.move_with_direction(offset.normalize(), dt, max_width, max_height, can_move=can_move)

    def draw(self, surface: pygame.Surface, draw_rect: pygame.Rect | None = None) -> None:
        target_rect = draw_rect or self.rect
        if self.sprite is not None:
            surface.blit(self.sprite, target_rect)
            return

        pygame.draw.rect(surface, self.color, target_rect, border_radius=8)
