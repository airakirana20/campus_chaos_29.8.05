import pygame

from game.asset_loader import AssetLoader
from settings import PLAYER_BASE_SPEED, PLAYER_CHIBI_SCALE, PLAYER_SPRITE_PATH


class ChibiAnimator:
    def __init__(
        self,
        image_path: str,
        scale: float = 0.42,
        cols: int = 4,
        rows: int = 3,
        alpha_threshold: int = 8,
        padding: int = 12,
    ) -> None:
        self.sheet = pygame.image.load(image_path).convert_alpha()
        self.cols = cols
        self.rows = rows
        self.alpha_threshold = alpha_threshold
        self.padding = padding
        self.scale = scale

        self.frames = self._extract_and_normalize_frames()
        self.animations = {
            "walk": [self.frames[i] for i in [0, 1, 2, 3]],
            "sleep": [self.frames[i] for i in [4, 5, 6, 7]],
            "shock": [self.frames[i] for i in [8, 9]],
            "happy": [self.frames[i] for i in [10, 11]],
            "idle": [self.frames[0]],
        }

        self.current = "idle"
        self.frame_index = 0
        self.timer = 0.0
        self.flip_x = False

        self.frame_durations = {
            "idle": 0.3,
            "walk": 0.14,
            "sleep": 0.35,
            "shock": 0.18,
            "happy": 0.22,
        }

        self.looping = {
            "idle": True,
            "walk": True,
            "sleep": True,
            "shock": False,
            "happy": True,
        }

    def _extract_and_normalize_frames(self) -> list[pygame.Surface]:
        sheet_width, sheet_height = self.sheet.get_size()
        cell_width = sheet_width // self.cols
        cell_height = sheet_height // self.rows

        raw_frames: list[pygame.Surface] = []

        for row in range(self.rows):
            for col in range(self.cols):
                cell_rect = pygame.Rect(
                    col * cell_width,
                    row * cell_height,
                    cell_width,
                    cell_height,
                )
                raw_frames.append(self._crop_visible_area(cell_rect))

        max_w = max(frame.get_width() for frame in raw_frames)
        max_h = max(frame.get_height() for frame in raw_frames)

        canvas_w = max_w + self.padding * 2
        canvas_h = max_h + self.padding * 2

        normalized: list[pygame.Surface] = []

        for frame in raw_frames:
            canvas = pygame.Surface((canvas_w, canvas_h), pygame.SRCALPHA)

            x = (canvas_w - frame.get_width()) // 2
            y = canvas_h - frame.get_height() - self.padding
            canvas.blit(frame, (x, y))

            if self.scale != 1.0:
                scaled_size = (
                    max(1, int(canvas.get_width() * self.scale)),
                    max(1, int(canvas.get_height() * self.scale)),
                )
                canvas = pygame.transform.smoothscale(canvas, scaled_size)

            normalized.append(canvas)

        return normalized

    def _crop_visible_area(self, cell_rect: pygame.Rect) -> pygame.Surface:
        sub = self.sheet.subsurface(cell_rect).copy()
        width, height = sub.get_size()

        min_x, min_y = width, height
        max_x, max_y = -1, -1

        for y in range(height):
            for x in range(width):
                if sub.get_at((x, y)).a > self.alpha_threshold:
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)

        if max_x == -1 or max_y == -1:
            return pygame.Surface((1, 1), pygame.SRCALPHA)

        crop_rect = pygame.Rect(
            min_x,
            min_y,
            max_x - min_x + 1,
            max_y - min_y + 1,
        )
        return sub.subsurface(crop_rect).copy()

    def play(self, name: str, reset: bool = False) -> None:
        if name not in self.animations:
            return

        if name != self.current or reset:
            self.current = name
            self.frame_index = 0
            self.timer = 0.0

    def update(self, dt: float) -> None:
        frames = self.animations[self.current]
        if len(frames) <= 1:
            return

        self.timer += dt
        duration = self.frame_durations.get(self.current, 0.15)

        while self.timer >= duration:
            self.timer -= duration
            if self.looping.get(self.current, True):
                self.frame_index = (self.frame_index + 1) % len(frames)
            else:
                self.frame_index = min(self.frame_index + 1, len(frames) - 1)

    def get_current_frame(self) -> pygame.Surface:
        frame = self.animations[self.current][self.frame_index]
        if self.flip_x:
            return pygame.transform.flip(frame, True, False)
        return frame


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

        self.sprite = None
        self.animator: ChibiAnimator | None = None

        self.last_move_direction = pygame.Vector2(1, 0)
        self.idle_time = 0.0
        self.sleep_after_seconds = 6.0
        self.emotion_timer = 0.0

        try:
            self.animator = ChibiAnimator(self.sprite_path, scale=PLAYER_CHIBI_SCALE)
            first_frame = self.animator.get_current_frame()
            self.rect.size = (first_frame.get_width(), first_frame.get_height())
            self.position = pygame.Vector2(x, y)
            self.rect.topleft = (round(self.position.x), round(self.position.y))
            self.previous_position = self.position.copy()
            self.previous_rect = self.rect.copy()
        except Exception:
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

        moved = self.move_with_direction(direction, dt, max_width, max_height, can_move=can_move)
        self._update_animation_state(direction, moved, dt)
        return moved

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
            moved = self.move_with_direction(
                pygame.Vector2(),
                dt,
                max_width,
                max_height,
                can_move=False,
            )
            self._update_animation_state(pygame.Vector2(), moved, dt)
            return moved

        moved = self.move_with_direction(
            offset.normalize(),
            dt,
            max_width,
            max_height,
            can_move=can_move,
        )
        self._update_animation_state(offset.normalize(), moved, dt)
        return moved

    def trigger_happy(self) -> None:
        if self.animator is None:
            return
        self.animator.play("happy", reset=True)
        self.emotion_timer = 1.2

    def trigger_shock(self) -> None:
        if self.animator is None:
            return
        self.animator.play("shock", reset=True)
        self.emotion_timer = 0.8

    def _update_animation_state(self, direction: pygame.Vector2, moved: bool, dt: float) -> None:
        if self.animator is None:
            return

        if direction.x < 0:
            self.animator.flip_x = True
            self.last_move_direction.update(direction)
        elif direction.x > 0:
            self.animator.flip_x = False
            self.last_move_direction.update(direction)

        if self.emotion_timer > 0:
            self.emotion_timer = max(0.0, self.emotion_timer - dt)
            self.animator.update(dt)
            if self.emotion_timer <= 0:
                self.animator.play("idle", reset=True)
            return

        if moved:
            self.idle_time = 0.0
            self.animator.play("walk")
        else:
            self.idle_time += dt
            if self.idle_time >= self.sleep_after_seconds:
                self.animator.play("sleep")
            else:
                self.animator.play("idle")

        self.animator.update(dt)

    def draw(self, surface: pygame.Surface, draw_rect: pygame.Rect | None = None) -> None:
        if self.animator is not None:
            frame = self.animator.get_current_frame()
            target_rect = draw_rect or self.rect
            draw_pos = frame.get_rect(midbottom=target_rect.midbottom)
            surface.blit(frame, draw_pos)
            return

        target_rect = draw_rect or self.rect
        if self.sprite is not None:
            surface.blit(self.sprite, target_rect)
            return

        pygame.draw.rect(surface, self.color, target_rect, border_radius=8)