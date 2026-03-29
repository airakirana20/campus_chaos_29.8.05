import math
import sys
from functools import lru_cache
from pathlib import Path

import pygame

from settings import SCREEN_HEIGHT, SCREEN_WIDTH


_BASE_WIDTH = 1280
_BASE_HEIGHT = 720
_DEFAULT_FONT_SCALE = 0.82
_MIN_FONT_SCALE = 0.76
_MAX_FONT_SCALE = 1.1


def ui_scale() -> float:
    scale_ratio = min(SCREEN_WIDTH / _BASE_WIDTH, SCREEN_HEIGHT / _BASE_HEIGHT)
    scaled_ratio = math.pow(scale_ratio, 0.92) * _DEFAULT_FONT_SCALE
    return max(_MIN_FONT_SCALE, min(_MAX_FONT_SCALE, scaled_ratio))


def scaled_ui(value: int) -> int:
    return max(1, int(round(value * ui_scale())))


def _resolve_asset_root(asset_root: str = "assets") -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    candidate = Path(asset_root)
    if candidate.is_absolute():
        return candidate
    bundled_path = base_path / candidate
    if bundled_path.exists():
        return bundled_path
    return Path(__file__).resolve().parents[1] / candidate


@lru_cache(maxsize=None)
def _font_path(bold: bool) -> str | None:
    asset_root = _resolve_asset_root()
    preferred_names = (
        ("font_bold.ttf", "ui_bold.ttf", "font_regular.ttf", "ui_regular.ttf")
        if bold
        else ("font_regular.ttf", "ui_regular.ttf")
    )
    for file_name in preferred_names:
        full_path = asset_root / "ui" / file_name
        if full_path.is_file():
            return str(full_path)

    ui_dir = asset_root / "ui"
    if ui_dir.is_dir():
        font_files = sorted(
            path
            for path in ui_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".ttf", ".otf"}
        )
        if bold:
            for path in font_files:
                if "bold" in path.stem.lower():
                    return str(path)
        else:
            for path in font_files:
                stem = path.stem.lower()
                if "regular" in stem or "medium" in stem or "book" in stem:
                    return str(path)
        if font_files:
            return str(font_files[0])
    return None


@lru_cache(maxsize=None)
def ui_font(size: int, bold: bool = False) -> pygame.font.Font:
    scaled_size = scaled_ui(size)
    font = pygame.font.Font(_font_path(bold), scaled_size)
    if _font_path(bold) is None and bold:
        font.set_bold(True)
    return font
