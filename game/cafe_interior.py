from dataclasses import dataclass

import pygame

from game.asset_loader import AssetLoader
from game.ui_fonts import ui_font
from game.ui_primitives import draw_smooth_panel
from settings import HUD_LEFT_WIDTH, HUD_RIGHT_WIDTH, PLAYFIELD_MARGIN


@dataclass(frozen=True)
class InteriorLayout:
    name: str
    subtitle: str


@dataclass(frozen=True)
class CafeInteractionPoint:
    interaction_id: str
    prompt: str
    label: str
    rect: pygame.Rect
    anchor: tuple[int, int]
    accent_color: tuple[int, int, int]


class CafeInteriorMap:
    def __init__(self, width: int, height: int, asset_loader: AssetLoader | None = None) -> None:
        self.width = width
        self.height = height
        self.asset_loader = asset_loader or AssetLoader()
        self.layout = InteriorLayout("Cafe Interior", "A compact student cafe with coffee, booths, and a quiet corner.")
        self.world_rect = pygame.Rect(0, 0, 880, 620)
        self.playfield_rect = pygame.Rect(
            HUD_LEFT_WIDTH + PLAYFIELD_MARGIN,
            60,
            width - HUD_LEFT_WIDTH - HUD_RIGHT_WIDTH - PLAYFIELD_MARGIN * 2,
            height - 118,
        )
        self.camera = pygame.Vector2(0, 0)
        self.title_font = ui_font(26, bold=True)
        self.body_font = ui_font(15, bold=True)
        self.label_font = ui_font(17, bold=True)
        self.effect_font = ui_font(13, bold=True)
        self.minimap_font = ui_font(11, bold=True)
        self.floor_rect = pygame.Rect(44, 42, 792, 530)
        self.active_zone_names: set[str] = set()

        self.door_rect = pygame.Rect(0, 0, 72, 14)
        self.door_rect.midbottom = (self.floor_rect.centerx, self.floor_rect.bottom - 6)
        self.exit_trigger_rect = self.door_rect.inflate(44, 48)
        self.exit_trigger_rect.midtop = (self.door_rect.centerx, self.door_rect.y - 22)

        self.counter_rect = pygame.Rect(self.floor_rect.x + 48, self.floor_rect.y + 54, 286, 88)
        self.espresso_machine_rect = pygame.Rect(self.counter_rect.right - 64, self.counter_rect.y + 14, 40, 50)
        self.menu_board_rect = pygame.Rect(self.counter_rect.x + 26, self.counter_rect.y - 34, 148, 22)

        self.table_rects = [
            pygame.Rect(456, 162, 92, 66),
            pygame.Rect(626, 166, 96, 66),
            pygame.Rect(468, 332, 96, 68),
            pygame.Rect(632, 334, 96, 68),
        ]
        self.stool_rects = [
            pygame.Rect(372, 168, 22, 22),
            pygame.Rect(404, 168, 22, 22),
            pygame.Rect(436, 168, 22, 22),
        ]
        self.booth_rects = [
            pygame.Rect(self.floor_rect.right - 142, self.floor_rect.y + 144, 88, 170),
            pygame.Rect(self.floor_rect.right - 142, self.floor_rect.y + 324, 88, 156),
        ]
        self.planter_rects = [
            pygame.Rect(self.floor_rect.right - 98, self.floor_rect.y + 54, 36, 70),
            pygame.Rect(self.floor_rect.x + 58, self.floor_rect.bottom - 122, 44, 76),
        ]
        self.blocked_rects = [
            self.counter_rect,
            *self.table_rects,
            *self.stool_rects,
            *self.booth_rects,
            *self.planter_rects,
        ]

        self.interaction_points = (
            CafeInteractionPoint(
                interaction_id="counter",
                prompt="Press E to order coffee",
                label="Service Counter",
                rect=pygame.Rect(self.counter_rect.centerx - 62, self.counter_rect.bottom - 8, 124, 44),
                anchor=(self.counter_rect.centerx, self.counter_rect.bottom + 8),
                accent_color=(255, 192, 121),
            ),
            CafeInteractionPoint(
                interaction_id="seat",
                prompt="Press E to take a seat",
                label="Window Table",
                rect=pygame.Rect(610, 430, 126, 64),
                anchor=(672, 430),
                accent_color=(123, 219, 173),
            ),
        )
        self.friend_spawn_rect = pygame.Rect(498, 432, 118, 64)

    def update(self, player_rect: pygame.Rect) -> None:
        self.active_zone_names = {"Cafe"} if self.floor_rect.colliderect(player_rect) else set()

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
        return self.floor_rect.inflate(-8, -8)

    def get_blocking_rects(self) -> list[pygame.Rect]:
        return [rect.copy() for rect in self.blocked_rects]

    def get_walkable_rects(self) -> list[pygame.Rect]:
        return [self.floor_rect.inflate(-8, -8)]

    def is_rect_on_paths(self, rect: pygame.Rect) -> bool:
        inset_rect = rect.inflate(-4, -4)
        if inset_rect.width <= 0 or inset_rect.height <= 0:
            inset_rect = rect.copy()
        if not self.floor_rect.inflate(-8, -8).contains(inset_rect):
            return False
        return not any(inset_rect.colliderect(blocker) for blocker in self.blocked_rects)

    def keep_player_on_paths(self, player) -> None:
        if self.is_rect_on_paths(player.rect):
            return
        player.revert_to_previous_position()

    def get_spawn_position(self) -> tuple[int, int]:
        return (self.door_rect.centerx, self.floor_rect.bottom - 74)

    def get_current_location_label(self, player_rect: pygame.Rect) -> str:
        interaction = self.get_nearby_interaction(player_rect)
        if interaction is not None:
            return interaction.label
        if self.exit_trigger_rect.colliderect(player_rect):
            return "Cafe Entrance"
        return "Cafe Interior"

    def get_nearby_interaction(self, player_rect: pygame.Rect) -> CafeInteractionPoint | None:
        candidates = [
            point
            for point in self.interaction_points
            if point.rect.inflate(18, 18).colliderect(player_rect)
        ]
        if not candidates:
            return None
        player_center = pygame.Vector2(player_rect.center)
        return min(candidates, key=lambda point: player_center.distance_to(point.anchor))

    def get_local_prompt(self, player_rect: pygame.Rect) -> tuple[str, tuple[int, int], str] | None:
        if self.exit_trigger_rect.colliderect(player_rect):
            return ("Press E to exit Cafe", self.door_rect.midtop, "exit")
        interaction = self.get_nearby_interaction(player_rect)
        if interaction is None:
            return None
        return (interaction.prompt, interaction.anchor, interaction.interaction_id)

    def draw(
        self,
        surface: pygame.Surface,
        player_rect: pygame.Rect,
        zone_charge_ratios: dict[str, float] | None = None,
    ) -> None:
        del zone_charge_ratios
        self.center_camera_on(player_rect)
        draw_smooth_panel(surface, self.playfield_rect, (20, 20, 29), (79, 93, 118), border_radius=24)

        title_surface = self.title_font.render(self.layout.name, True, (244, 246, 249))
        subtitle_surface = self.body_font.render(self.layout.subtitle, True, (196, 205, 220))
        surface.blit(title_surface, (self.playfield_rect.x + 18, self.playfield_rect.y + 12))
        surface.blit(subtitle_surface, (self.playfield_rect.x + 18, self.playfield_rect.y + 42))

        previous_clip = surface.get_clip()
        surface.set_clip(self.playfield_rect)
        self._draw_room(surface)
        surface.set_clip(previous_clip)
        self._draw_minimap(surface, player_rect)

    def _draw_room(self, surface: pygame.Surface) -> None:
        room_rect = self.world_to_screen_rect(self.floor_rect)
        pygame.draw.rect(surface, (28, 24, 23), room_rect.inflate(18, 18), border_radius=34)
        draw_smooth_panel(surface, room_rect, (88, 72, 58), (145, 124, 109), border_radius=28)

        light_color = (255, 223, 173, 28)
        for center in (
            (self.floor_rect.x + 160, self.floor_rect.y + 92),
            (self.floor_rect.centerx, self.floor_rect.y + 86),
            (self.floor_rect.right - 156, self.floor_rect.y + 98),
        ):
            light_surface = pygame.Surface((150, 84), pygame.SRCALPHA)
            pygame.draw.ellipse(light_surface, light_color, light_surface.get_rect())
            light_rect = light_surface.get_rect(center=self.world_to_screen_point(center))
            surface.blit(light_surface, light_rect)

        tile_color = (118, 100, 85)
        for x in range(self.floor_rect.x, self.floor_rect.right, 72):
            start = self.world_to_screen_point((x, self.floor_rect.y))
            end = self.world_to_screen_point((x, self.floor_rect.bottom))
            pygame.draw.line(surface, tile_color, start, end, 1)
        for y in range(self.floor_rect.y, self.floor_rect.bottom, 72):
            start = self.world_to_screen_point((self.floor_rect.x, y))
            end = self.world_to_screen_point((self.floor_rect.right, y))
            pygame.draw.line(surface, tile_color, start, end, 1)

        rug_rect = self.world_to_screen_rect(pygame.Rect(self.floor_rect.x + 360, self.floor_rect.y + 124, 330, 320))
        draw_smooth_panel(surface, rug_rect, (82, 58, 52), None, border_width=0, border_radius=24)

        counter_rect = self.world_to_screen_rect(self.counter_rect)
        draw_smooth_panel(surface, counter_rect, (106, 74, 52), (228, 192, 154), border_radius=22)
        machine_rect = self.world_to_screen_rect(self.espresso_machine_rect)
        draw_smooth_panel(surface, machine_rect, (55, 64, 76), (178, 188, 206), border_radius=10)
        menu_rect = self.world_to_screen_rect(self.menu_board_rect)
        draw_smooth_panel(surface, menu_rect, (37, 43, 53), (186, 198, 214), border_radius=10)
        menu_text = self.effect_font.render("Specials", True, (241, 245, 249))
        surface.blit(menu_text, menu_text.get_rect(center=menu_rect.center))
        counter_label = self.effect_font.render("Service Counter", True, (248, 238, 225))
        surface.blit(counter_label, (counter_rect.x + 14, counter_rect.y + 12))

        for booth_rect in self.booth_rects:
            screen_booth = self.world_to_screen_rect(booth_rect)
            draw_smooth_panel(surface, screen_booth, (113, 140, 108), (210, 226, 204), border_radius=18)
            seat_back = pygame.Rect(screen_booth.x + 8, screen_booth.y + 8, screen_booth.width - 16, 24)
            pygame.draw.rect(surface, (84, 105, 81), seat_back, border_radius=10)

        for table_rect in self.table_rects:
            screen_table = self.world_to_screen_rect(table_rect)
            draw_smooth_panel(surface, screen_table, (136, 101, 74), (232, 214, 196), border_radius=18)
            tabletop_rect = screen_table.inflate(-20, -22)
            pygame.draw.rect(surface, (224, 205, 183), tabletop_rect, border_radius=12)

        for stool_rect in self.stool_rects:
            pygame.draw.rect(surface, (73, 84, 104), self.world_to_screen_rect(stool_rect), border_radius=8)

        for planter_rect in self.planter_rects:
            screen_planter = self.world_to_screen_rect(planter_rect)
            draw_smooth_panel(surface, screen_planter, (63, 71, 59), (163, 181, 151), border_radius=12)
            plant_top = pygame.Rect(screen_planter.x + 4, screen_planter.y + 4, screen_planter.width - 8, screen_planter.height - 22)
            pygame.draw.rect(surface, (76, 155, 108), plant_top, border_radius=12)

        for frame_rect in (
            pygame.Rect(self.floor_rect.x + 408, self.floor_rect.y + 58, 78, 52),
            pygame.Rect(self.floor_rect.x + 504, self.floor_rect.y + 58, 86, 52),
            pygame.Rect(self.floor_rect.x + 610, self.floor_rect.y + 58, 92, 52),
        ):
            screen_frame = self.world_to_screen_rect(frame_rect)
            draw_smooth_panel(surface, screen_frame, (47, 54, 68), (210, 219, 231), border_radius=10)
            inner = screen_frame.inflate(-8, -8)
            pygame.draw.rect(surface, (244, 198, 120), inner, border_radius=8)

        door_rect = self.world_to_screen_rect(self.door_rect)
        pygame.draw.rect(surface, (196, 219, 246), door_rect, border_radius=8)
        pygame.draw.rect(surface, (243, 247, 251), door_rect, width=2, border_radius=8)
        door_label = self.effect_font.render("Exit", True, (241, 245, 249))
        door_label_rect = door_label.get_rect(midbottom=(door_rect.centerx, door_rect.y - 6))
        surface.blit(door_label, door_label_rect)

        for point in self.interaction_points:
            anchor = self.world_to_screen_point(point.anchor)
            pygame.draw.circle(surface, point.accent_color, anchor, 9)
            pygame.draw.circle(surface, (243, 246, 249), anchor, 9, 2)

        social_rect = self.world_to_screen_rect(self.friend_spawn_rect)
        social_tag = self.effect_font.render("Social nook", True, (223, 229, 238))
        surface.blit(social_tag, (social_rect.x, social_rect.bottom + 8))

    def _draw_minimap(self, surface: pygame.Surface, player_rect: pygame.Rect) -> None:
        panel_rect = pygame.Rect(self.playfield_rect.right - 164, self.playfield_rect.y + 14, 148, 112)
        draw_smooth_panel(surface, panel_rect, (21, 24, 34), (225, 231, 238), border_radius=14)
        inner_rect = panel_rect.inflate(-16, -18)
        inner_rect.y += 8
        pygame.draw.rect(surface, (15, 17, 27), inner_rect, border_radius=10)

        scale_x = inner_rect.width / self.world_rect.width
        scale_y = inner_rect.height / self.world_rect.height

        mini_floor = pygame.Rect(
            inner_rect.x + round(self.floor_rect.x * scale_x),
            inner_rect.y + round(self.floor_rect.y * scale_y),
            round(self.floor_rect.width * scale_x),
            round(self.floor_rect.height * scale_y),
        )
        pygame.draw.rect(surface, (98, 82, 69), mini_floor, border_radius=8)

        for blocker in self.blocked_rects:
            mini_rect = pygame.Rect(
                inner_rect.x + round(blocker.x * scale_x),
                inner_rect.y + round(blocker.y * scale_y),
                max(4, round(blocker.width * scale_x)),
                max(4, round(blocker.height * scale_y)),
            )
            pygame.draw.rect(surface, (57, 51, 49), mini_rect, border_radius=4)

        for label, world_point in (
            ("Door", self.door_rect.midtop),
            ("Counter", self.interaction_points[0].anchor),
            ("Seats", self.interaction_points[1].anchor),
        ):
            point = (
                inner_rect.x + round(world_point[0] * scale_x),
                inner_rect.y + round(world_point[1] * scale_y),
            )
            pygame.draw.circle(surface, (241, 243, 246), point, 3)
            label_surface = self.minimap_font.render(label, True, (231, 236, 243))
            label_rect = label_surface.get_rect(midbottom=(point[0], point[1] - 5))
            label_rect.clamp_ip(panel_rect.inflate(-4, -4))
            surface.blit(label_surface, label_rect)

        player_point = (
            inner_rect.x + round(player_rect.centerx * scale_x),
            inner_rect.y + round(player_rect.centery * scale_y),
        )
        pygame.draw.circle(surface, (255, 221, 121), player_point, 4)
