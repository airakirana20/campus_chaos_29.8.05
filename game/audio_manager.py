from pathlib import Path

import pygame

from settings import MUSIC_VOLUME, SFX_VOLUME


MUSIC_TRACKS = {
    "home": "audio/music/home",
    "loading": "audio/music/loading",
    "day": "audio/music/day",
    "dream": "audio/music/dream",
    "week_win": "audio/music/week_win",
    "week_lose": "audio/music/week_lose",
}

SFX_TRACKS = {
    "ui_start": "audio/sfx/ui_start",
    "mission_accept": "audio/sfx/mission_accept",
    "mission_complete": "audio/sfx/mission_complete",
    "mission_fail": "audio/sfx/mission_fail",
    "day_end": "audio/sfx/day_end",
    "dream_start": "audio/sfx/dream_start",
    "dream_success": "audio/sfx/dream_success",
    "dream_fail": "audio/sfx/dream_fail",
    "powerup": "audio/sfx/powerup",
    "loading_done": "audio/sfx/loading_done",
}

MUSIC_EXTENSIONS = (".ogg", ".mp3", ".wav")
SFX_EXTENSIONS = (".wav", ".ogg", ".mp3")


class AudioManager:
    def __init__(self, asset_root: Path) -> None:
        self.asset_root = Path(asset_root)
        self.enabled = False
        self.current_music_key: str | None = None
        self.music_volume = MUSIC_VOLUME
        self.sfx_volume = SFX_VOLUME
        self._sfx_cache: dict[str, pygame.mixer.Sound | None] = {}

        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()
            pygame.mixer.music.set_volume(self.music_volume)
            self.enabled = True
        except pygame.error:
            self.enabled = False

    def set_music_volume(self, volume: float) -> None:
        self.music_volume = max(0.0, min(1.0, volume))
        if self.enabled:
            pygame.mixer.music.set_volume(self.music_volume)

    def set_sfx_volume(self, volume: float) -> None:
        self.sfx_volume = max(0.0, min(1.0, volume))
        for sound in self._sfx_cache.values():
            if sound is not None:
                sound.set_volume(self.sfx_volume)

    def play_music(self, music_key: str, loops: int = -1) -> None:
        if not self.enabled or music_key == self.current_music_key:
            return

        asset_path = self._resolve_asset(MUSIC_TRACKS.get(music_key, ""), MUSIC_EXTENSIONS)
        if asset_path is None:
            self.stop_music()
            return

        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(str(asset_path))
            pygame.mixer.music.set_volume(self.music_volume)
            pygame.mixer.music.play(loops=loops, fade_ms=350)
            self.current_music_key = music_key
        except pygame.error:
            self.current_music_key = None

    def stop_music(self, fade_ms: int = 250) -> None:
        if not self.enabled:
            return

        if pygame.mixer.music.get_busy():
            pygame.mixer.music.fadeout(fade_ms)
        self.current_music_key = None

    def play_sfx(self, sound_key: str) -> None:
        if not self.enabled:
            return

        sound = self._get_sound(sound_key)
        if sound is None:
            return

        try:
            sound.play()
        except pygame.error:
            return

    def _get_sound(self, sound_key: str) -> pygame.mixer.Sound | None:
        if sound_key in self._sfx_cache:
            return self._sfx_cache[sound_key]

        asset_path = self._resolve_asset(SFX_TRACKS.get(sound_key, ""), SFX_EXTENSIONS)
        if asset_path is None:
            self._sfx_cache[sound_key] = None
            return None

        try:
            sound = pygame.mixer.Sound(str(asset_path))
            sound.set_volume(self.sfx_volume)
        except pygame.error:
            sound = None

        self._sfx_cache[sound_key] = sound
        return sound

    def _resolve_asset(self, stem: str, extensions: tuple[str, ...]) -> Path | None:
        if not stem:
            return None

        for extension in extensions:
            asset_path = self.asset_root / f"{stem}{extension}"
            if asset_path.is_file():
                return asset_path
        return None
