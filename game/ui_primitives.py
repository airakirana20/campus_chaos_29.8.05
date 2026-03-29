import pygame


def draw_smooth_panel(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fill_color: tuple[int, int, int],
    border_color: tuple[int, int, int] | None = None,
    border_width: int = 2,
    border_radius: int = 12,
) -> None:
    scale = 2
    scaled_size = (max(2, rect.width * scale), max(2, rect.height * scale))
    panel_surface = pygame.Surface(scaled_size, pygame.SRCALPHA)
    scaled_rect = panel_surface.get_rect()

    pygame.draw.rect(
        panel_surface,
        fill_color,
        scaled_rect,
        border_radius=border_radius * scale,
    )
    if border_color is not None and border_width > 0:
        pygame.draw.rect(
            panel_surface,
            border_color,
            scaled_rect,
            width=border_width * scale,
            border_radius=border_radius * scale,
        )

    smoothed = pygame.transform.smoothscale(panel_surface, rect.size)
    surface.blit(smoothed, rect)
