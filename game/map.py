from collections import deque
from dataclasses import dataclass
from datetime import date
import heapq

import pygame

from game.asset_loader import AssetLoader
from game.ui_fonts import ui_font
from game.ui_primitives import draw_smooth_panel
from game.zone_data import ZONE_TEMPLATES, ZoneTemplate, format_effects
from settings import HUD_LEFT_WIDTH, HUD_RIGHT_WIDTH, PLAYFIELD_MARGIN, PLAYER_BASE_SPEED, ZONE_SPRITE_PATHS


BASE_WORLD_WIDTH = 1400
BASE_WORLD_HEIGHT = 1020


@dataclass(frozen=True)
class MapLayout:
    name: str
    subtitle: str
    spawn_zone: str
    room_specs: dict[str, tuple[int, int, int, int]]
    corridor_specs: tuple[tuple[int, int, int, int], ...]


DAILY_LAYOUTS = (
    MapLayout(
        name="Finals Routes",
        subtitle="Looping halls with long central connectors.",
        spawn_zone="Park",
        room_specs={
            "Library": (88, 96, 248, 138),
            "Lecture Hall": (574, 82, 254, 146),
            "Club Room": (1034, 106, 248, 138),
            "Park": (168, 456, 262, 176),
            "Print Room": (1000, 454, 242, 154),
            "Dorm": (128, 824, 264, 146),
            "Part-Time Job": (548, 818, 292, 152),
            "Cafe": (1022, 830, 228, 138),
        },
        corridor_specs=(
            (248, 186, 846, 74),
            (246, 224, 78, 334),
            (662, 214, 86, 642),
            (1088, 214, 82, 648),
            (286, 508, 832, 82),
            (246, 876, 872, 74),
        ),
    ),
    MapLayout(
        name="Rainy Crosswalks",
        subtitle="Wet detours and wide cross-campus aisles.",
        spawn_zone="Cafe",
        room_specs={
            "Cafe": (98, 104, 232, 136),
            "Library": (508, 92, 248, 138),
            "Part-Time Job": (1042, 112, 254, 134),
            "Club Room": (110, 460, 246, 150),
            "Lecture Hall": (1036, 448, 256, 156),
            "Park": (550, 470, 300, 178),
            "Print Room": (120, 818, 260, 138),
            "Dorm": (1034, 822, 230, 140),
        },
        corridor_specs=(
            (240, 176, 906, 74),
            (238, 214, 78, 344),
            (638, 214, 88, 340),
            (1070, 212, 82, 634),
            (242, 522, 906, 84),
            (244, 876, 900, 72),
            (636, 558, 90, 318),
        ),
    ),
    MapLayout(
        name="Festival Concourse",
        subtitle="Broad aisles, side spurs, and a busier outer loop.",
        spawn_zone="Dorm",
        room_specs={
            "Library": (116, 114, 250, 140),
            "Lecture Hall": (566, 92, 248, 148),
            "Club Room": (1010, 114, 244, 138),
            "Park": (94, 472, 274, 176),
            "Print Room": (1024, 470, 228, 154),
            "Dorm": (124, 824, 258, 146),
            "Part-Time Job": (558, 806, 294, 156),
            "Cafe": (1030, 828, 224, 140),
        },
        corridor_specs=(
            (246, 198, 848, 76),
            (234, 234, 82, 360),
            (656, 228, 88, 628),
            (1082, 232, 82, 624),
            (242, 540, 922, 84),
            (246, 878, 906, 72),
            (234, 910, 84, 62),
        ),
    ),
)


@dataclass
class Zone:
    template: ZoneTemplate
    rect: pygame.Rect

    @property
    def name(self) -> str:
        return self.template.name


class GameMap:
    def __init__(
        self,
        width: int,
        height: int,
        asset_loader: AssetLoader | None = None,
        layout_index: int | None = None,
        compact: bool = False,
        dream_mode: bool = False,
    ) -> None:
        self.width = width
        self.height = height
        self.compact = compact
        self.dream_mode = dream_mode
        self.border_color = (70, 90, 120)
        title_size = 24 if compact else 28
        label_size = 19 if compact else 24
        body_size = 14 if compact else 17
        effect_size = 13 if compact else 15
        minimap_label_size = 10 if compact else 11
        self.title_font = ui_font(title_size, bold=True)
        self.label_font = ui_font(label_size, bold=True)
        self.body_font = ui_font(body_size, bold=True)
        self.effect_font = ui_font(effect_size, bold=True)
        self.minimap_font = ui_font(minimap_label_size, bold=True)
        self.asset_loader = asset_loader or AssetLoader()
        base_playfield_rect = pygame.Rect(
            HUD_LEFT_WIDTH + PLAYFIELD_MARGIN,
            72,
            width - HUD_LEFT_WIDTH - HUD_RIGHT_WIDTH - PLAYFIELD_MARGIN * 2,
            height - 144,
        )
        if compact:
            compact_width = max(380, int(base_playfield_rect.width * 0.84))
            compact_height = max(300, int(base_playfield_rect.height * 0.82))
            self.playfield_rect = pygame.Rect(0, 0, compact_width, compact_height)
            self.playfield_rect.center = (base_playfield_rect.centerx, base_playfield_rect.centery + 12)
        else:
            self.playfield_rect = base_playfield_rect
        self.layout_index = 0 if layout_index is None else layout_index
        self.layout = self._select_layout(self.layout_index)
        self.world_rect = pygame.Rect(0, 0, BASE_WORLD_WIDTH, BASE_WORLD_HEIGHT)
        if compact:
            self.world_rect.width = int(BASE_WORLD_WIDTH * 0.88)
            self.world_rect.height = int(BASE_WORLD_HEIGHT * 0.84)
        self.camera = pygame.Vector2(0, 0)
        self.zones = self._build_zones()
        self.corridors = self._build_corridors()
        self.walkable_rects = self._build_walkable_rects()
        self.navigation_points, self.navigation_edges = self._build_navigation_graph()
        self.active_zone_names: set[str] = set()

    def _get_zone_by_name(self, zone_name: str) -> Zone | None:
        for zone in self.zones:
            if zone.name == zone_name:
                return zone
        return None

    @staticmethod
    def layout_count() -> int:
        return len(DAILY_LAYOUTS)

    def _select_layout(self, layout_index: int) -> MapLayout:
        if layout_index is None:
            today = date.today()
            layout_index = today.toordinal()
        return DAILY_LAYOUTS[layout_index % len(DAILY_LAYOUTS)]

    def _world_scale(self) -> tuple[float, float]:
        return (self.world_rect.width / BASE_WORLD_WIDTH, self.world_rect.height / BASE_WORLD_HEIGHT)

    def _scale_world_rect(self, rect_spec: tuple[int, int, int, int]) -> pygame.Rect:
        x, y, width, height = rect_spec
        scale_x, scale_y = self._world_scale()
        return pygame.Rect(
            round(x * scale_x),
            round(y * scale_y),
            max(24, round(width * scale_x)),
            max(24, round(height * scale_y)),
        )

    def _build_zones(self) -> list[Zone]:
        zones: list[Zone] = []
        for template in ZONE_TEMPLATES:
            room_spec = self.layout.room_specs[template.name]
            zones.append(Zone(template=template, rect=self._scale_world_rect(room_spec)))
        return zones

    def _build_corridors(self) -> list[pygame.Rect]:
        return [self._scale_world_rect(spec) for spec in self.layout.corridor_specs]

    def _build_walkable_rects(self) -> list[pygame.Rect]:
        walkable_rects = [corridor.copy() for corridor in self.corridors]
        for zone in self.zones:
            walkable_rects.append(zone.rect.inflate(-12, -12))
        return walkable_rects

    def _build_navigation_graph(self) -> tuple[dict[str, pygame.Vector2], dict[str, list[tuple[str, float]]]]:
        navigation_rects: list[tuple[str, pygame.Rect]] = []
        for zone in self.zones:
            navigation_rects.append((f"zone:{zone.name}", zone.rect.inflate(-12, -12)))
        for index, corridor in enumerate(self.corridors):
            navigation_rects.append((f"corridor:{index}", corridor.copy()))

        points = {key: pygame.Vector2(rect.center) for key, rect in navigation_rects}
        edges: dict[str, list[tuple[str, float]]] = {key: [] for key, _ in navigation_rects}

        for index, (key_a, rect_a) in enumerate(navigation_rects):
            for key_b, rect_b in navigation_rects[index + 1 :]:
                if not rect_a.inflate(8, 8).colliderect(rect_b.inflate(8, 8)):
                    continue
                cost = max(32.0, points[key_a].distance_to(points[key_b]))
                edges[key_a].append((key_b, cost))
                edges[key_b].append((key_a, cost))

        return points, edges

    def update(self, player_rect: pygame.Rect) -> None:
        self.active_zone_names = {zone.name for zone in self.zones if zone.rect.colliderect(player_rect)}

    def center_camera_on(self, focus_rect: pygame.Rect) -> None:
        camera_x = focus_rect.centerx - self.playfield_rect.width // 2
        camera_y = focus_rect.centery - self.playfield_rect.height // 2
        self.camera.x = max(0, min(camera_x, self.world_rect.width - self.playfield_rect.width))
        self.camera.y = max(0, min(camera_y, self.world_rect.height - self.playfield_rect.height))

    def get_draw_offset(self) -> tuple[int, int]:
        return (
            self.playfield_rect.x - round(self.camera.x),
            self.playfield_rect.y - round(self.camera.y),
        )

    def world_to_screen_rect(self, world_rect: pygame.Rect) -> pygame.Rect:
        draw_x, draw_y = self.get_draw_offset()
        return world_rect.move(draw_x, draw_y)

    def world_to_screen_point(self, point: tuple[int, int]) -> tuple[int, int]:
        draw_x, draw_y = self.get_draw_offset()
        return (point[0] + draw_x, point[1] + draw_y)

    def get_player_bounds(self) -> pygame.Rect:
        return self.world_rect.copy()

    def get_blocking_rects(self) -> list[pygame.Rect]:
        return []

    def get_walkable_rects(self) -> list[pygame.Rect]:
        return [rect.copy() for rect in self.walkable_rects]

    def is_rect_on_paths(self, rect: pygame.Rect) -> bool:
        inset_rect = rect.inflate(-4, -4)
        if inset_rect.width <= 0 or inset_rect.height <= 0:
            inset_rect = rect.copy()

        target_area = inset_rect.width * inset_rect.height
        if target_area <= 0:
            return False

        covered_area = 0
        for path_rect in self.walkable_rects:
            if path_rect.contains(inset_rect):
                return True
            overlap_rect = inset_rect.clip(path_rect)
            covered_area += overlap_rect.width * overlap_rect.height

        return covered_area >= target_area * 0.92

    def keep_player_on_paths(self, player) -> None:
        if self.is_rect_on_paths(player.rect):
            return
        player.revert_to_previous_position()

    def get_current_location_label(self, player_rect: pygame.Rect) -> str:
        for zone in self.zones:
            if zone.rect.colliderect(player_rect):
                return zone.name

        nearest_zone = min(
            self.zones,
            key=lambda zone: self.estimate_route_distance(player_rect, zone.name),
            default=None,
        )
        if nearest_zone is None:
            return "Hallway"
        return f"Hallway near {nearest_zone.name}"

    def get_route_time_estimates(self, player_rect: pygame.Rect, speed: float = PLAYER_BASE_SPEED) -> dict[str, float]:
        estimates: dict[str, float] = {}
        for zone in self.zones:
            estimates[zone.name] = round(self.estimate_travel_seconds(player_rect, zone.name, speed), 1)
        return estimates

    def estimate_travel_seconds(self, player_rect: pygame.Rect, target_zone_name: str, speed: float = PLAYER_BASE_SPEED) -> float:
        distance = self.estimate_route_distance(player_rect, target_zone_name)
        if speed <= 0:
            speed = PLAYER_BASE_SPEED
        return max(1.5, distance / speed * 1.9)

    def estimate_route_distance(self, player_rect: pygame.Rect, target_zone_name: str) -> float:
        target_key = f"zone:{target_zone_name}"
        if target_key not in self.navigation_points:
            return 9999.0

        _, best_cost = self._find_navigation_path(player_rect, target_key)
        if best_cost is not None:
            return best_cost

        return pygame.Vector2(player_rect.center).distance_to(self.navigation_points[target_key]) * 1.2

    def get_zone_rect(self, zone_name: str) -> pygame.Rect | None:
        zone = self._get_zone_by_name(zone_name)
        return zone.rect.copy() if zone is not None else None

    def _pick_zone_entrance_side(self, zone_rect: pygame.Rect) -> str:
        strips = {
            "top": pygame.Rect(zone_rect.x + zone_rect.width // 4, zone_rect.y - 26, zone_rect.width // 2, 36),
            "bottom": pygame.Rect(zone_rect.x + zone_rect.width // 4, zone_rect.bottom - 10, zone_rect.width // 2, 36),
            "left": pygame.Rect(zone_rect.x - 26, zone_rect.y + zone_rect.height // 4, 36, zone_rect.height // 2),
            "right": pygame.Rect(zone_rect.right - 10, zone_rect.y + zone_rect.height // 4, 36, zone_rect.height // 2),
        }
        best_side = "bottom"
        best_score = -1
        for side, strip_rect in strips.items():
            score = 0
            for corridor_rect in self.corridors:
                overlap = strip_rect.clip(corridor_rect.inflate(10, 10))
                score += overlap.width * overlap.height
            if score > best_score:
                best_score = score
                best_side = side
        return best_side

    def get_cafe_entrance_side(self) -> str:
        cafe_rect = self.get_zone_rect("Cafe")
        if cafe_rect is None:
            return "bottom"
        return self._pick_zone_entrance_side(cafe_rect)

    def get_cafe_door_rect(self) -> pygame.Rect | None:
        cafe_rect = self.get_zone_rect("Cafe")
        if cafe_rect is None:
            return None
        side = self.get_cafe_entrance_side()
        if side == "top":
            return pygame.Rect(cafe_rect.centerx - 30, cafe_rect.y + 4, 60, 12)
        if side == "left":
            return pygame.Rect(cafe_rect.x + 4, cafe_rect.centery - 30, 12, 60)
        if side == "right":
            return pygame.Rect(cafe_rect.right - 16, cafe_rect.centery - 30, 12, 60)
        return pygame.Rect(cafe_rect.centerx - 30, cafe_rect.bottom - 16, 60, 12)

    def get_cafe_entrance_trigger(self) -> pygame.Rect | None:
        door_rect = self.get_cafe_door_rect()
        side = self.get_cafe_entrance_side()
        if door_rect is None:
            return None
        if side == "top":
            trigger = door_rect.inflate(30, 42)
            trigger.y -= 16
            return trigger
        if side == "left":
            trigger = door_rect.inflate(42, 30)
            trigger.x -= 16
            return trigger
        if side == "right":
            trigger = door_rect.inflate(42, 30)
            trigger.x += 16
            return trigger
        trigger = door_rect.inflate(30, 42)
        trigger.y += 16
        return trigger

    def get_cafe_outdoor_spawn(self) -> tuple[int, int]:
        door_rect = self.get_cafe_door_rect()
        if door_rect is None:
            return self.get_spawn_position()
        side = self.get_cafe_entrance_side()
        if side == "top":
            return (door_rect.centerx, door_rect.y - 36)
        if side == "left":
            return (door_rect.x - 36, door_rect.centery)
        if side == "right":
            return (door_rect.right + 36, door_rect.centery)
        return (door_rect.centerx, door_rect.bottom + 36)

    def get_cafe_entrance_prompt(self, player_rect: pygame.Rect) -> tuple[str, tuple[int, int]] | None:
        trigger_rect = self.get_cafe_entrance_trigger()
        door_rect = self.get_cafe_door_rect()
        if trigger_rect is None or door_rect is None:
            return None
        if not trigger_rect.colliderect(player_rect):
            return None
        return ("Press E to enter Cafe", door_rect.center)

    def get_route_points(
        self,
        start_rect: pygame.Rect,
        target_zone_name: str,
        traversal: str = "dijkstra",
    ) -> list[pygame.Vector2]:
        target_key = f"zone:{target_zone_name}"
        if target_key not in self.navigation_points:
            return []

        if traversal == "bfs":
            key_path = self._find_navigation_path_bfs(start_rect, target_key)
        else:
            key_path, _ = self._find_navigation_path(start_rect, target_key)
        if not key_path:
            zone_rect = self.get_zone_rect(target_zone_name)
            return [pygame.Vector2(zone_rect.center)] if zone_rect is not None else []

        route_points = [pygame.Vector2(start_rect.center)]
        for key in key_path:
            point = self.navigation_points[key]
            if route_points[-1].distance_to(point) > 8:
                route_points.append(point.copy())

        zone_rect = self.get_zone_rect(target_zone_name)
        if zone_rect is not None:
            final_point = pygame.Vector2(zone_rect.inflate(-20, -20).center)
            if route_points[-1].distance_to(final_point) > 6:
                route_points.append(final_point)

        return route_points

    def _get_navigation_keys_for_rect(self, rect: pygame.Rect) -> list[str]:
        keys: list[str] = []
        for zone in self.zones:
            zone_rect = zone.rect.inflate(-12, -12)
            if zone_rect.colliderect(rect):
                keys.append(f"zone:{zone.name}")
        for index, corridor in enumerate(self.corridors):
            if corridor.colliderect(rect):
                keys.append(f"corridor:{index}")
        return keys

    def _get_navigation_start_keys(self, rect: pygame.Rect, fallback_key: str) -> list[str]:
        start_keys = self._get_navigation_keys_for_rect(rect)
        if start_keys:
            return start_keys

        nearest_key = min(
            self.navigation_points.keys(),
            key=lambda key: self.navigation_points[key].distance_to(pygame.Vector2(rect.center)),
            default=fallback_key,
        )
        return [nearest_key]

    def _find_navigation_path(self, start_rect: pygame.Rect, target_key: str) -> tuple[list[str], float | None]:
        start_keys = self._get_navigation_start_keys(start_rect, target_key)
        start_center = pygame.Vector2(start_rect.center)
        distances: dict[str, float] = {}
        previous: dict[str, str | None] = {}
        frontier: list[tuple[float, str]] = []

        for start_key in start_keys:
            start_distance = start_center.distance_to(self.navigation_points[start_key])
            distances[start_key] = start_distance
            previous[start_key] = None
            heapq.heappush(frontier, (start_distance, start_key))

        while frontier:
            current_cost, current_key = heapq.heappop(frontier)
            if current_key == target_key:
                return self._reconstruct_navigation_path(previous, target_key), current_cost
            if current_cost > distances.get(current_key, float("inf")):
                continue

            for neighbor_key, edge_cost in self.navigation_edges.get(current_key, []):
                next_cost = current_cost + edge_cost
                if next_cost >= distances.get(neighbor_key, float("inf")):
                    continue
                distances[neighbor_key] = next_cost
                previous[neighbor_key] = current_key
                heapq.heappush(frontier, (next_cost, neighbor_key))

        return [], None

    def _find_navigation_path_bfs(self, start_rect: pygame.Rect, target_key: str) -> list[str]:
        start_keys = self._get_navigation_start_keys(start_rect, target_key)
        previous: dict[str, str | None] = {}
        visited: set[str] = set()
        frontier: deque[str] = deque()

        for start_key in start_keys:
            frontier.append(start_key)
            visited.add(start_key)
            previous[start_key] = None

        while frontier:
            current_key = frontier.popleft()
            if current_key == target_key:
                return self._reconstruct_navigation_path(previous, target_key)

            for neighbor_key, _edge_cost in self.navigation_edges.get(current_key, []):
                if neighbor_key in visited:
                    continue
                visited.add(neighbor_key)
                previous[neighbor_key] = current_key
                frontier.append(neighbor_key)

        return []

    def _reconstruct_navigation_path(self, previous: dict[str, str | None], target_key: str) -> list[str]:
        path: list[str] = []
        current_key: str | None = target_key
        while current_key is not None:
            path.append(current_key)
            current_key = previous.get(current_key)
        path.reverse()
        return path

    def get_spawn_position(self) -> tuple[int, int]:
        for zone in self.zones:
            if zone.name == self.layout.spawn_zone:
                return zone.rect.center
        return self.world_rect.center

    def draw(
        self,
        surface: pygame.Surface,
        player_rect: pygame.Rect,
        zone_charge_ratios: dict[str, float] | None = None,
    ) -> None:
        self.center_camera_on(player_rect)

        border_color = (59, 72, 98) if self.dream_mode else self.border_color
        playfield_color = (11, 13, 22) if self.dream_mode else (18, 23, 33)
        outline_color = (74, 83, 117) if self.dream_mode else (39, 47, 62)
        pygame.draw.rect(surface, border_color, surface.get_rect(), width=4)
        draw_smooth_panel(surface, self.playfield_rect, playfield_color, outline_color, border_radius=24)

        title_label = "Dream Drift" if self.dream_mode else "Today's Campus"
        title_surface = self.title_font.render(f"{title_label}: {self.layout.name}", True, (237, 241, 246))
        subtitle_color = (160, 168, 212) if self.dream_mode else (176, 187, 205)
        subtitle_text = "A smaller, stranger shortcut map." if self.dream_mode else self.layout.subtitle
        subtitle_surface = self.body_font.render(subtitle_text, True, subtitle_color)
        surface.blit(title_surface, (self.playfield_rect.x + 18, self.playfield_rect.y + 12))
        surface.blit(subtitle_surface, (self.playfield_rect.x + 18, self.playfield_rect.y + 38))

        previous_clip = surface.get_clip()
        surface.set_clip(self.playfield_rect)
        self._draw_world_background(surface)
        for corridor_rect in self.corridors:
            self._draw_corridor(surface, corridor_rect)
        for zone in self.zones:
            ratio = 1.0 if zone_charge_ratios is None else zone_charge_ratios.get(zone.name, 1.0)
            self._draw_zone(surface, zone, ratio)
        if self.dream_mode:
            self._draw_fog(surface)
        surface.set_clip(previous_clip)

        self._draw_minimap(surface, player_rect)

    def draw_status(self, surface: pygame.Surface) -> None:
        """No-op placeholder to preserve call sites while the map stays neutral."""

    def _draw_world_background(self, surface: pygame.Surface) -> None:
        fill_color = (10, 12, 18) if self.dream_mode else (14, 18, 28)
        view_rect = self.world_to_screen_rect(self.world_rect)
        pygame.draw.rect(surface, fill_color, view_rect)

        lane_color = (26, 31, 46) if self.dream_mode else (25, 31, 45)
        grid_spacing = 120
        for x in range(0, self.world_rect.width + grid_spacing, grid_spacing):
            start = self.world_to_screen_point((x, 0))
            end = self.world_to_screen_point((x, self.world_rect.height))
            pygame.draw.line(surface, lane_color, start, end, 1)
        for y in range(0, self.world_rect.height + grid_spacing, grid_spacing):
            start = self.world_to_screen_point((0, y))
            end = self.world_to_screen_point((self.world_rect.width, y))
            pygame.draw.line(surface, lane_color, start, end, 1)

    def _draw_corridor(self, surface: pygame.Surface, corridor_rect: pygame.Rect) -> None:
        screen_rect = self.world_to_screen_rect(corridor_rect)
        fill_color = (23, 27, 38) if self.dream_mode else (30, 37, 51)
        outline_color = (67, 76, 98) if self.dream_mode else (88, 101, 128)
        stripe_color = (88, 98, 128) if self.dream_mode else (130, 142, 172)
        pygame.draw.rect(surface, fill_color, screen_rect, border_radius=18)
        pygame.draw.rect(surface, outline_color, screen_rect, width=2, border_radius=18)

        is_horizontal = screen_rect.width >= screen_rect.height
        if is_horizontal:
            y = screen_rect.centery
            step = 48
            dash_width = 20
            for x in range(screen_rect.x + 24, screen_rect.right - 24, step):
                pygame.draw.line(surface, stripe_color, (x, y), (min(x + dash_width, screen_rect.right - 18), y), 2)
        else:
            x = screen_rect.centerx
            step = 48
            dash_height = 20
            for y in range(screen_rect.y + 24, screen_rect.bottom - 24, step):
                pygame.draw.line(surface, stripe_color, (x, y), (x, min(y + dash_height, screen_rect.bottom - 18)), 2)

    def _zone_sprite_path(self, zone_name: str) -> str:
        explicit_path = ZONE_SPRITE_PATHS.get(zone_name)
        if explicit_path:
            return explicit_path
        slug = zone_name.lower().replace("-", " ").replace(" ", "_")
        return f"tiles/{slug}.png"

    def _load_zone_sprite(self, zone_name: str, size: tuple[int, int]) -> pygame.Surface | None:
        return self.asset_loader.load_image(self._zone_sprite_path(zone_name), size)

    def _draw_zone(self, surface: pygame.Surface, zone: Zone, remaining_ratio: float) -> None:
        is_active = zone.name in self.active_zone_names
        fill_color = zone.template.fill_color
        accent_color = zone.template.accent_color
        room_rect = self.world_to_screen_rect(zone.rect)

        spent = remaining_ratio <= 0.02
        if spent and not is_active:
            panel_color = self._darken(fill_color, 0.56)
        elif is_active:
            panel_color = self._lighten(fill_color, 0.08)
        else:
            panel_color = self._darken(fill_color, 0.12)
        if self.dream_mode:
            panel_color = self._darken(panel_color, 0.28)
            accent_color = self._lighten(self._darken(accent_color, 0.18), 0.05)

        zone_sprite = self._load_zone_sprite(zone.name, room_rect.size)
        if zone_sprite is not None:
            sprite_surface = pygame.Surface(room_rect.size, pygame.SRCALPHA)
            sprite_surface.blit(zone_sprite, (0, 0))

            if spent and not is_active:
                overlay_alpha = 166
            elif is_active:
                overlay_alpha = 62
            else:
                overlay_alpha = 106
            if self.dream_mode:
                overlay_alpha = min(210, overlay_alpha + 34)

            overlay_surface = pygame.Surface(room_rect.size, pygame.SRCALPHA)
            overlay_surface.fill((*panel_color, overlay_alpha))
            sprite_surface.blit(overlay_surface, (0, 0))

            rounded_mask = pygame.Surface(room_rect.size, pygame.SRCALPHA)
            pygame.draw.rect(rounded_mask, (255, 255, 255, 255), rounded_mask.get_rect(), border_radius=18)
            sprite_surface.blit(rounded_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surface.blit(sprite_surface, room_rect)
        else:
            draw_smooth_panel(surface, room_rect, panel_color, None, border_width=0, border_radius=18)

        header_rect = pygame.Rect(room_rect.x, room_rect.y, room_rect.width, 22)
        pygame.draw.rect(surface, accent_color, header_rect, border_top_left_radius=18, border_top_right_radius=18)
        outline_surface = pygame.Surface(room_rect.size, pygame.SRCALPHA)
        pygame.draw.rect(outline_surface, (235, 239, 245), outline_surface.get_rect(), width=3, border_radius=18)
        surface.blit(outline_surface, room_rect)
        if zone.name == "Cafe":
            self._draw_cafe_entrance_marker(surface)

        label_surface = self.label_font.render(zone.name, True, (245, 247, 250))
        subtitle_surface = self.body_font.render(zone.template.subtitle, True, (236, 240, 246))
        effect_surface = self.effect_font.render(format_effects(zone.template.effects), True, accent_color)
        surface.blit(label_surface, (room_rect.x + 12, room_rect.y + 28))
        surface.blit(subtitle_surface, (room_rect.x + 12, room_rect.y + 54))
        surface.blit(effect_surface, (room_rect.x + 12, room_rect.bottom - 18))

        charge_rect = pygame.Rect(room_rect.x + 12, room_rect.bottom - 34, room_rect.width - 24, 8)
        fill_rect = pygame.Rect(charge_rect.x, charge_rect.y, round(charge_rect.width * remaining_ratio), charge_rect.height)
        pygame.draw.rect(surface, (38, 45, 58), charge_rect, border_radius=6)
        if fill_rect.width > 0:
            pygame.draw.rect(surface, accent_color, fill_rect, border_radius=6)
        pygame.draw.rect(surface, (220, 225, 233), charge_rect, width=1, border_radius=6)

        if spent:
            spent_surface = self.effect_font.render("Spent", True, (214, 220, 228))
            surface.blit(spent_surface, (room_rect.right - spent_surface.get_width() - 12, room_rect.y + 28))
        elif is_active:
            active_surface = self.effect_font.render("Active", True, (248, 250, 252))
            surface.blit(active_surface, (room_rect.right - active_surface.get_width() - 12, room_rect.y + 28))

    def _draw_cafe_entrance_marker(self, surface: pygame.Surface) -> None:
        door_rect = self.get_cafe_door_rect()
        if door_rect is None:
            return
        screen_door = self.world_to_screen_rect(door_rect)
        pygame.draw.rect(surface, (242, 246, 249), screen_door, border_radius=8)
        pygame.draw.rect(surface, (121, 168, 249), screen_door, width=2, border_radius=8)

    def _draw_minimap(self, surface: pygame.Surface, player_rect: pygame.Rect) -> None:
        map_width = 154 if self.compact else 172
        map_height = 118 if self.compact else 126
        panel_rect = pygame.Rect(
            self.playfield_rect.right - map_width - 16,
            self.playfield_rect.y + 12,
            map_width,
            map_height,
        )
        draw_smooth_panel(surface, panel_rect, (21, 24, 34), (225, 231, 238), border_radius=14)

        inner_rect = panel_rect.inflate(-14, -18)
        inner_rect.y += 6
        pygame.draw.rect(surface, (13, 15, 24), inner_rect, border_radius=10)

        scale_x = inner_rect.width / self.world_rect.width
        scale_y = inner_rect.height / self.world_rect.height

        for corridor_rect in self.corridors:
            mini_rect = pygame.Rect(
                inner_rect.x + round(corridor_rect.x * scale_x),
                inner_rect.y + round(corridor_rect.y * scale_y),
                max(3, round(corridor_rect.width * scale_x)),
                max(3, round(corridor_rect.height * scale_y)),
            )
            pygame.draw.rect(surface, (72, 86, 112), mini_rect, border_radius=4)

        for zone in self.zones:
            mini_zone = pygame.Rect(
                inner_rect.x + round(zone.rect.x * scale_x),
                inner_rect.y + round(zone.rect.y * scale_y),
                max(5, round(zone.rect.width * scale_x)),
                max(5, round(zone.rect.height * scale_y)),
            )
            pygame.draw.rect(surface, zone.template.accent_color, mini_zone, border_radius=4)
            label_surface = self.minimap_font.render(self._minimap_label(zone.name), True, (233, 237, 244))
            label_rect = label_surface.get_rect(midbottom=(mini_zone.centerx, mini_zone.y - 2))
            label_rect.clamp_ip(panel_rect.inflate(-4, -4))
            surface.blit(label_surface, label_rect)

        camera_rect = pygame.Rect(
            inner_rect.x + round(self.camera.x * scale_x),
            inner_rect.y + round(self.camera.y * scale_y),
            max(12, round(self.playfield_rect.width * scale_x)),
            max(12, round(self.playfield_rect.height * scale_y)),
        )
        pygame.draw.rect(surface, (240, 243, 247), camera_rect, width=1, border_radius=4)

        player_point = (
            inner_rect.x + round(player_rect.centerx * scale_x),
            inner_rect.y + round(player_rect.centery * scale_y),
        )
        pygame.draw.circle(surface, (255, 221, 121), player_point, 4)

        label_surface = self.effect_font.render("Mini", True, (229, 234, 241))
        surface.blit(label_surface, (panel_rect.x + 10, panel_rect.y + 6))

    def _draw_fog(self, surface: pygame.Surface) -> None:
        fog_surface = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        fog_surface.fill((8, 10, 18, 82))

        for offset_x, offset_y, radius_x, radius_y, alpha in (
            (-130, -80, 260, 140, 56),
            (90, -10, 300, 150, 44),
            (-10, 150, 320, 170, 52),
            (170, 130, 240, 132, 40),
        ):
            ellipse_rect = pygame.Rect(0, 0, radius_x, radius_y)
            ellipse_rect.center = (
                self.playfield_rect.centerx + offset_x,
                self.playfield_rect.centery + offset_y,
            )
            pygame.draw.ellipse(fog_surface, (168, 176, 220, alpha), ellipse_rect)

        pygame.draw.rect(fog_surface, (0, 0, 0, 0), self.playfield_rect.inflate(-76, -60), border_radius=24)
        surface.blit(fog_surface, (0, 0))

    def _darken(self, color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
        return tuple(max(0, int(channel * (1.0 - amount))) for channel in color)

    def _lighten(self, color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
        return tuple(min(255, int(channel + (255 - channel) * amount)) for channel in color)

    def _minimap_label(self, zone_name: str) -> str:
        short_names = {
            "Library": "Library",
            "Lecture Hall": "Lecture",
            "Club Room": "Club",
            "Park": "Park",
            "Print Room": "Print",
            "Dorm": "Dorm",
            "Part-Time Job": "Job",
            "Cafe": "Cafe",
        }
        return short_names.get(zone_name, zone_name[:7])
