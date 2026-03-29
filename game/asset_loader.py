import sys
from pathlib import Path

import pygame


class AssetLoader:
    def __init__(self, asset_root: str = "assets") -> None:
        self.asset_root = self._resolve_asset_root(asset_root)
        self._image_cache: dict[tuple[str, tuple[int, int] | None], pygame.Surface | None] = {}

    def _resolve_asset_root(self, asset_root: str) -> Path:
        base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        candidate = Path(asset_root)
        if candidate.is_absolute():
            return candidate
        bundled_path = base_path / candidate
        if bundled_path.exists():
            return bundled_path
        return Path(__file__).resolve().parents[1] / candidate

    def load_image(
        self,
        relative_path: str,
        size: tuple[int, int] | None = None,
    ) -> pygame.Surface | None:
        cache_key = (relative_path, size)
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        asset_path = self.asset_root / relative_path
        if not asset_path.is_file():
            self._image_cache[cache_key] = None
            return None

        try:
            image = pygame.image.load(str(asset_path)).convert_alpha()
            if size is not None:
                image = pygame.transform.smoothscale(image, size)
        except (pygame.error, FileNotFoundError):
            image = None

        self._image_cache[cache_key] = image
        return image
