import math
import random
import threading
from dataclasses import dataclass, field

import pygame

from game.asset_loader import AssetLoader
from game.audio_manager import AudioManager
from game.cafe_interior import CafeInteriorMap
from game.enemy_manager import EnemyManager
from game.event_manager import EventManager
from game.friend_system import FriendSystem
from game.map import GameMap
from game.mission_manager import MissionManager, MissionStep
from game.modifier_system import ModifierSystem
from game.player import Player
from game.powerup_manager import PowerupManager
from game.stats import Stats
from game.temptation_manager import TemptationManager
from game.ui_fonts import ui_font
from game.ui_primitives import draw_smooth_panel
from game.zone_data import ZONE_TEMPLATES, format_effects
from llm.llm_client import generate_dream_mission, generate_event, get_llm_status
from settings import BACKGROUND_COLOR, FPS, SCREEN_HEIGHT, SCREEN_WIDTH, WINDOW_TITLE


DAY_DURATION_SECONDS = 60.0
SUMMARY_DURATION_SECONDS = 2.6
DREAM_PHASE_MIN_SECONDS = 16.0
DREAM_PHASE_MAX_SECONDS = 24.0
TOTAL_DAYS = 7
TARGET_MISSION_SCORE = 10


@dataclass
class DreamMissionState:
    title: str = ""
    steps: list[MissionStep] = field(default_factory=list)
    time_limit: int = 0
    time_remaining: float = 0.0
    phase_remaining: float = 0.0
    completed: bool = False
    failed: bool = False


@dataclass
class SessionLoadState:
    session: "GameSession"
    worker: threading.Thread | None = None
    status_text: str = "Contacting AI director..."
    ready: bool = False
    error: str | None = None


@dataclass
class GameSession:
    asset_loader: AssetLoader
    game_map: GameMap
    cafe_interior: CafeInteriorMap | None
    player: Player
    stats: Stats
    modifier_system: ModifierSystem
    mission_manager: MissionManager
    powerup_manager: PowerupManager
    enemy_manager: EnemyManager
    event_manager: EventManager
    temptation_manager: TemptationManager
    friend_manager: FriendSystem
    queued_mission_payload: dict | None = None
    game_over: bool = False
    mission_reward_message: str = ""
    mission_reward_timer: float = 0.0
    money_spent_message: str = ""
    money_spent_timer: float = 0.0
    combo_streak: int = 0
    rng: random.Random = field(default_factory=random.Random)
    phase: str = "day"
    current_day: int = 1
    total_days: int = TOTAL_DAYS
    day_time_remaining: float = DAY_DURATION_SECONDS
    day_duration: float = DAY_DURATION_SECONDS
    mission_score: int = 0
    target_score: int = TARGET_MISSION_SCORE
    missions_completed_today: int = 0
    summary_timer: float = 0.0
    summary_lines: list[str] = field(default_factory=list)
    week_seed: int = 0
    week_result: str | None = None
    dream_map: GameMap | None = None
    dream_mission: DreamMissionState = field(default_factory=DreamMissionState)
    pending_day_duration_penalty: int = 0
    pending_start_energy_penalty: int = 0
    pending_start_energy_bonus: int = 0
    pressure_state: str = "stable"
    director_cooldown: float = 0.0
    ai_call_message: str = ""
    ai_call_timer: float = 0.0
    last_seen_llm_call_id: int = 0
    day_load_state: "SessionLoadState | None" = None
    current_area: str = "overworld"
    overworld_return_position: tuple[int, int] | None = None
    area_message: str = ""
    area_message_timer: float = 0.0
    cafe_interaction_cooldowns: dict[str, float] = field(default_factory=dict)
    mika_in_cafe: bool = False


def _get_active_day_map(session: GameSession):
    if session.current_area == "cafe_interior" and session.cafe_interior is not None:
        return session.cafe_interior
    return session.game_map


def _get_active_map(session: GameSession):
    if session.phase == "dream" and session.dream_map is not None:
        return session.dream_map
    return _get_active_day_map(session)


def _route_anchor_rect(session: GameSession) -> tuple[GameMap, pygame.Rect]:
    if session.current_area != "cafe_interior":
        return session.game_map, session.player.rect.copy()

    anchor_position = session.overworld_return_position or session.game_map.get_cafe_outdoor_spawn()
    anchor_rect = session.player.rect.copy()
    anchor_rect.center = anchor_position
    return session.game_map, anchor_rect


def _build_game_state(session: GameSession) -> dict:
    active_map = _get_active_map(session)
    time_left = session.dream_mission.time_remaining if session.phase == "dream" else session.day_time_remaining
    route_map, route_rect = _route_anchor_rect(session)
    player_speed = session.player.base_speed * session.player.speed_multiplier
    return {
        "phase": session.phase,
        "day": session.current_day,
        "time_left": int(round(time_left)),
        "day_time_remaining": round(session.day_time_remaining, 1),
        "mission_score": session.mission_score,
        "target_score": session.target_score,
        "energy": round(session.stats.energy),
        "stress": round(session.stats.stress),
        "money": round(session.stats.money),
        "focus": round(session.stats.focus),
        "score": round(session.stats.score),
        "map_name": active_map.layout.name,
        "player_location": active_map.get_current_location_label(session.player.rect),
        "route_time_to_zones": route_map.get_route_time_estimates(route_rect, player_speed),
        "active_zones": sorted(active_map.active_zone_names),
        "mission_title": session.mission_manager.title,
        "mission_type": session.mission_manager.mission_type,
        "mission_difficulty": session.mission_manager.difficulty,
        "mission_time_left": round(session.mission_manager.time_remaining, 1),
        "mission_targets": [step.target for step in session.mission_manager.steps],
        "mission_step": session.mission_manager.get_current_step_text(),
        "dream_targets": [step.target for step in session.dream_mission.steps],
        "dream_time_left": round(session.dream_mission.time_remaining, 1),
        "mission_choice_targets": {
            choice_id: offer["steps"][0]["target"]
            for choice_id, offer in session.mission_manager.choice_offers.items()
        },
        "mission_complete": session.mission_manager.completed,
        "combo": _current_combo_multiplier(session),
        "combo_multiplier": min(3, session.combo_streak + 1),
        "panic_mode": session.stats.stress > 80,
        "temptation": session.temptation_manager.active_temptation.title if session.temptation_manager.active_temptation else None,
        "modifier": session.modifier_system.active_modifier,
        "powerups": session.powerup_manager.get_active_names(),
        "enemy_count": len(session.enemy_manager.enemies),
        "pressure_state": session.pressure_state,
    }


def _class_live_now(session: GameSession) -> bool:
    if session.phase != "day":
        return False
    elapsed = session.day_duration - session.day_time_remaining
    return 10.0 <= elapsed <= min(session.day_duration - 8.0, 42.0)


def _build_friend_context(session: GameSession) -> dict:
    active_map = _get_active_day_map(session)
    return {
        "energy": int(round(session.stats.energy)),
        "stress": int(round(session.stats.stress)),
        "knowledge": int(round(session.stats.focus)),
        "money": int(round(session.stats.money)),
        "current_location": active_map.get_current_location_label(session.player.rect),
        "class_live_now": _class_live_now(session),
        "recent_actions": session.friend_manager.recent_actions[-3:],
    }


def _create_game_session(asset_loader: AssetLoader, bootstrap_live: bool = True) -> GameSession:
    week_seed = random.randint(0, 9999)
    game_map = GameMap(
        SCREEN_WIDTH,
        SCREEN_HEIGHT,
        asset_loader=asset_loader,
        layout_index=week_seed,
    )
    player = Player(width=34, height=34, asset_loader=asset_loader)
    player.set_center(*game_map.get_spawn_position())

    session = GameSession(
        asset_loader=asset_loader,
        game_map=game_map,
        cafe_interior=None,
        player=player,
        stats=Stats(),
        modifier_system=ModifierSystem(),
        mission_manager=MissionManager(),
        powerup_manager=PowerupManager(),
        enemy_manager=EnemyManager(SCREEN_WIDTH, SCREEN_HEIGHT),
        event_manager=EventManager(),
        temptation_manager=TemptationManager(),
        friend_manager=FriendSystem(asset_loader=asset_loader),
        week_seed=week_seed,
    )
    session.friend_manager.reset_for_day(game_map)
    session.enemy_manager.set_navigation_bounds(session.game_map.world_rect, session.game_map.get_walkable_rects())
    session.event_manager.event_interval = 9999.0
    _prepare_day(session, reset_stats=False)
    if bootstrap_live:
        _finish_day_bootstrap(session)
    return session


def _sync_audio(audio_manager: AudioManager, current_screen: str, session: GameSession | None) -> None:
    if current_screen == "home":
        audio_manager.play_music("home")
        return

    if current_screen == "loading":
        audio_manager.play_music("loading")
        return

    if session is None:
        audio_manager.stop_music()
        return

    if session.phase == "day_loading":
        audio_manager.play_music("loading")
    elif session.phase == "dream":
        audio_manager.play_music("dream")
    elif session.phase == "week_complete":
        audio_manager.play_music("week_win" if session.week_result == "WIN" else "week_lose")
    else:
        audio_manager.play_music("day")


def _layout_index_for_day(session: GameSession, day_number: int) -> int:
    return session.week_seed + day_number - 1


def _tick_banner_timers(session: GameSession, dt: float) -> None:
    if session.mission_reward_timer > 0:
        session.mission_reward_timer = max(0.0, session.mission_reward_timer - dt)
    if session.money_spent_timer > 0:
        session.money_spent_timer = max(0.0, session.money_spent_timer - dt)
    if session.event_manager.message_timer > 0:
        session.event_manager.message_timer = max(0.0, session.event_manager.message_timer - dt)
    if session.director_cooldown > 0:
        session.director_cooldown = max(0.0, session.director_cooldown - dt)
    if session.ai_call_timer > 0:
        session.ai_call_timer = max(0.0, session.ai_call_timer - dt)
    if session.area_message_timer > 0:
        session.area_message_timer = max(0.0, session.area_message_timer - dt)
    for interaction_id, cooldown in list(session.cafe_interaction_cooldowns.items()):
        next_cooldown = max(0.0, cooldown - dt)
        if next_cooldown <= 0:
            session.cafe_interaction_cooldowns.pop(interaction_id, None)
        else:
            session.cafe_interaction_cooldowns[interaction_id] = next_cooldown


def _classify_pressure_state(session: GameSession) -> str:
    strong_signals = 0
    weak_signals = 0

    if session.stats.energy >= 72:
        strong_signals += 1
    elif session.stats.energy <= 34:
        weak_signals += 1

    if session.stats.focus >= 70:
        strong_signals += 1
    elif session.stats.focus <= 34:
        weak_signals += 1

    if session.stats.stress <= 28:
        strong_signals += 1
    elif session.stats.stress >= 76:
        weak_signals += 1

    if _current_combo_multiplier(session) >= 2:
        strong_signals += 1
    if session.stats.money <= 18 and session.day_time_remaining < 25:
        weak_signals += 1
    if session.mission_score >= max(2, session.current_day):
        strong_signals += 1

    if strong_signals >= 3 and weak_signals == 0:
        return "strong"
    if weak_signals >= 2:
        return "weak"
    return "stable"


def _request_director_update(session: GameSession, reason: str) -> dict:
    game_state = _build_game_state(session)
    session.pressure_state = _classify_pressure_state(session)
    game_state["pressure_state"] = session.pressure_state
    payload = generate_event(game_state, reason=reason)
    _capture_llm_indicator(session)
    return payload


def _current_route_time_estimates(session: GameSession) -> dict[str, float]:
    active_map = _get_active_map(session)
    if session.phase == "day" and session.current_area == "cafe_interior":
        route_map, route_rect = _route_anchor_rect(session)
        player_speed = session.player.base_speed * session.player.speed_multiplier
        return route_map.get_route_time_estimates(route_rect, player_speed)
    player_speed = session.player.base_speed * session.player.speed_multiplier
    return active_map.get_route_time_estimates(session.player.rect, player_speed)


def _capture_llm_indicator(session: GameSession) -> None:
    llm_status = get_llm_status()
    call_id = int(llm_status.get("call_id", 0))
    if call_id <= session.last_seen_llm_call_id:
        return

    session.last_seen_llm_call_id = call_id
    reason = str(llm_status.get("reason", "ai")).replace("_", " ")
    label = str(llm_status.get("label", "FALLBACK"))
    detail = str(llm_status.get("detail", ""))
    prefix = "AI call"
    if reason == "dream":
        prefix = "AI dream call"
    elif reason == "friend":
        prefix = "AI Mika call"
    elif reason == "pressure shift":
        prefix = "AI pressure call"
    elif reason == "new mission":
        prefix = "AI mission call"

    if detail:
        session.ai_call_message = f"{prefix}: {label} | {detail}"
    else:
        session.ai_call_message = f"{prefix}: {label}"
    session.ai_call_timer = 2.8


def _prefetch_followup_missions(session: GameSession) -> None:
    if session.queued_mission_payload is not None:
        return
    payload = generate_event(_build_game_state(session), reason="new_mission")
    _capture_llm_indicator(session)
    missions = payload.get("missions")
    if isinstance(missions, dict):
        session.queued_mission_payload = missions


def _apply_director_update(session: GameSession, payload: dict, allow_immediate_mission: bool) -> None:
    session.modifier_system.set_active_modifier(payload.get("modifier", "EXAM"))
    session.enemy_manager.apply_enemy_plan(payload.get("enemies", []), avoid_rect=session.player.rect)

    mission_payload = payload.get("missions")
    mission_applied = False
    if allow_immediate_mission and session.mission_manager.can_replace_mission() and isinstance(mission_payload, dict):
        session.mission_manager.refresh_choices(
            safe_mission=mission_payload.get("safe"),
            risk_mission=mission_payload.get("risk"),
            route_time_to_zones=_current_route_time_estimates(session),
        )
        mission_applied = True
    elif isinstance(mission_payload, dict):
        session.queued_mission_payload = mission_payload

    session.event_manager.show_event_message(payload, mission_applied=mission_applied)


def _prepare_day(session: GameSession, reset_stats: bool = False) -> None:
    if reset_stats:
        session.stats = Stats()

    layout_index = _layout_index_for_day(session, session.current_day)
    session.game_map = GameMap(
        SCREEN_WIDTH,
        SCREEN_HEIGHT,
        asset_loader=session.asset_loader,
        layout_index=layout_index,
    )
    session.enemy_manager.set_navigation_bounds(session.game_map.world_rect, session.game_map.get_walkable_rects())
    session.player.set_center(*session.game_map.get_spawn_position())
    session.game_map.update(session.player.rect)
    session.cafe_interior = None
    session.current_area = "overworld"
    session.overworld_return_position = None
    session.cafe_interaction_cooldowns.clear()
    session.mika_in_cafe = False
    session.area_message = ""
    session.area_message_timer = 0.0
    session.enemy_manager.enemies.clear()
    session.enemy_manager.modifier_spawn_timer = 0.0
    session.enemy_manager.mission_spawn_timer = 0.0
    session.temptation_manager.active_temptation = None
    session.temptation_manager.active_timer = 0.0
    session.queued_mission_payload = None
    session.phase = "day"
    session.summary_timer = 0.0
    session.summary_lines = []
    session.week_result = None
    session.dream_map = None
    session.dream_mission = DreamMissionState()
    session.day_duration = max(35.0, DAY_DURATION_SECONDS - session.pending_day_duration_penalty)
    session.day_time_remaining = session.day_duration
    session.pending_day_duration_penalty = 0
    session.missions_completed_today = 0
    session.combo_streak = 0
    session.pressure_state = "stable"
    session.director_cooldown = 6.0
    session.friend_manager.reset_for_day(session.game_map)
    session.mission_manager.refresh_choices(route_time_to_zones=_current_route_time_estimates(session))
    session.mission_reward_message = f"Day {session.current_day} begins"
    session.mission_reward_timer = 1.8

    if session.pending_start_energy_penalty > 0:
        session.stats.apply_change("energy", -float(session.pending_start_energy_penalty))
        session.mission_reward_message = (
            f"Overslept: -{session.pending_start_energy_penalty} energy on Day {session.current_day}"
        )
        session.mission_reward_timer = 2.4
        session.pending_start_energy_penalty = 0
    elif session.pending_start_energy_bonus > 0:
        session.stats.apply_change("energy", float(session.pending_start_energy_bonus))
        session.mission_reward_message = (
            f"Dream reward: +{session.pending_start_energy_bonus} energy on Day {session.current_day}"
        )
        session.mission_reward_timer = 2.4
        session.pending_start_energy_bonus = 0


def _enter_cafe_interior(session: GameSession, with_mika: bool = False) -> None:
    if session.cafe_interior is None:
        session.cafe_interior = CafeInteriorMap(
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
            asset_loader=session.asset_loader,
        )
    session.current_area = "cafe_interior"
    session.overworld_return_position = session.game_map.get_cafe_outdoor_spawn()
    session.player.set_center(*session.cafe_interior.get_spawn_position())
    session.cafe_interior.update(session.player.rect)
    session.friend_manager.clear_runtime()
    session.mika_in_cafe = with_mika
    if with_mika:
        mika_center = session.cafe_interior.friend_spawn_rect.center
        session.friend_manager.place_npc(mika_center)
    session.area_message = "Mika led you inside the Cafe" if with_mika else "Entered Cafe Interior"
    session.area_message_timer = 1.6


def _exit_cafe_interior(session: GameSession) -> None:
    return_position = session.overworld_return_position or session.game_map.get_cafe_outdoor_spawn()
    session.current_area = "overworld"
    session.player.set_center(*return_position)
    session.game_map.update(session.player.rect)
    if session.mika_in_cafe:
        session.friend_manager.place_npc(return_position)
    session.mika_in_cafe = False
    session.area_message = "Back outside the Cafe"
    session.area_message_timer = 1.6


def _handle_cafe_interaction(session: GameSession, interaction_id: str) -> bool:
    cooldown = session.cafe_interaction_cooldowns.get(interaction_id, 0.0)
    if cooldown > 0:
        session.area_message = "That spot needs a moment."
        session.area_message_timer = 1.2
        return False

    if interaction_id == "counter":
        session.stats.apply_change("energy", 6.0)
        session.stats.apply_change("money", -4.0)
        session.day_time_remaining = max(0.0, session.day_time_remaining - 0.8)
        session.area_message = "Ordered a coffee: +6 energy, -$4"
        session.cafe_interaction_cooldowns[interaction_id] = 10.0
        session.area_message_timer = 1.8
        return True

    if interaction_id == "seat":
        session.stats.apply_change("stress", -5.0)
        session.stats.apply_change("focus", 2.0)
        session.day_time_remaining = max(0.0, session.day_time_remaining - 0.9)
        session.area_message = "Took a quiet seat: -5 stress, +2 focus"
        session.cafe_interaction_cooldowns[interaction_id] = 10.0
        session.area_message_timer = 1.8
        return True

    return False


def _handle_area_interaction(session: GameSession) -> bool:
    if session.phase != "day":
        return False
    if session.current_area == "overworld":
        if session.game_map.get_cafe_entrance_prompt(session.player.rect) is None:
            return False
        _enter_cafe_interior(session)
        return True

    if session.cafe_interior is None:
        return False

    prompt = session.cafe_interior.get_local_prompt(session.player.rect)
    if prompt is None:
        return False
    _, _anchor, interaction_id = prompt
    if interaction_id == "exit":
        _exit_cafe_interior(session)
        return True
    return _handle_cafe_interaction(session, interaction_id)


def _finish_day_bootstrap(session: GameSession) -> None:
    daily_payload = _request_director_update(session, reason="new_mission")
    _apply_director_update(session, daily_payload, allow_immediate_mission=True)


def _start_day(session: GameSession, reset_stats: bool = False) -> None:
    _prepare_day(session, reset_stats=reset_stats)
    _finish_day_bootstrap(session)


def _begin_summary_phase(session: GameSession, audio_manager: AudioManager | None = None) -> None:
    session.phase = "summary"
    session.friend_manager.clear_runtime()
    session.summary_timer = SUMMARY_DURATION_SECONDS
    session.summary_lines = [
        f"Day {session.current_day} complete",
        f"Missions today: {session.missions_completed_today}",
        f"Mission score: {session.mission_score}/{session.target_score}",
        f"Money ${int(round(session.stats.money))} | Energy {int(round(session.stats.energy))}",
    ]
    if audio_manager is not None:
        audio_manager.play_sfx("day_end")


def _begin_dream_phase(session: GameSession, audio_manager: AudioManager | None = None) -> None:
    session.phase = "dream"
    session.friend_manager.clear_runtime()
    if session.stats.energy < 1.0:
        session.stats.energy = 1.0
    session.dream_map = GameMap(
        SCREEN_WIDTH,
        SCREEN_HEIGHT,
        asset_loader=session.asset_loader,
        layout_index=_layout_index_for_day(session, session.current_day) + 1,
        compact=True,
        dream_mode=True,
    )
    session.player.set_center(*session.dream_map.get_spawn_position())
    session.dream_map.update(session.player.rect)

    allowed_locations = tuple(zone.name for zone in session.dream_map.zones)
    dream_state = _build_game_state(session)
    dream_state["phase"] = "dream"
    dream_state["time_left"] = int(DREAM_PHASE_MAX_SECONDS)
    dream_payload = generate_dream_mission(dream_state, allowed_locations)
    _capture_llm_indicator(session)
    session.dream_mission = DreamMissionState(
        title=dream_payload.get("title", "Dream Drift"),
        steps=[
            MissionStep(
                step_type=step["action"],
                target=step["target"],
                duration=float(step.get("duration", 0.0)),
            )
            for step in dream_payload.get("steps", [])
        ],
        time_limit=int(dream_payload.get("time_limit", 10)),
        time_remaining=float(dream_payload.get("time_limit", 10)),
        phase_remaining=float(
            max(
                DREAM_PHASE_MIN_SECONDS,
                min(
                    DREAM_PHASE_MAX_SECONDS,
                    dream_payload.get("time_limit", 10) + session.rng.uniform(5.0, 8.0),
                ),
            )
        ),
    )
    session.mission_reward_message = "Night falls. Survive the dream."
    session.mission_reward_timer = 2.0
    if audio_manager is not None:
        audio_manager.play_sfx("dream_start")


def _apply_oversleep_penalty(session: GameSession) -> str:
    session.pending_start_energy_bonus = 0
    if session.rng.random() < 0.5:
        penalty = session.rng.randint(10, 20)
        session.pending_day_duration_penalty = penalty
        session.pending_start_energy_penalty = 0
        return f"Overslept: next day loses {penalty}s"

    penalty = session.rng.randint(14, 24)
    session.pending_start_energy_penalty = penalty
    session.pending_day_duration_penalty = 0
    return f"Overslept: next day starts with -{penalty} energy"


def _apply_dream_success_bonus(session: GameSession) -> str:
    session.pending_day_duration_penalty = 0
    session.pending_start_energy_penalty = 0
    bonus = max(4, min(12, int(round(session.dream_mission.time_remaining)) + 2))
    session.pending_start_energy_bonus = bonus
    return f"Dream cleared early: next day starts with +{bonus} energy"


def _advance_after_dream(session: GameSession, success: bool, audio_manager: AudioManager | None = None) -> None:
    if not success:
        session.mission_reward_message = _apply_oversleep_penalty(session)
        session.mission_reward_timer = 2.6
    else:
        session.mission_reward_message = _apply_dream_success_bonus(session)
        session.mission_reward_timer = 2.2
    if audio_manager is not None:
        audio_manager.play_sfx("dream_success" if success else "dream_fail")

    session.current_day += 1
    if session.current_day > session.total_days:
        session.phase = "week_complete"
        session.week_result = "WIN" if session.mission_score >= session.target_score else "LOSE"
        return

    _begin_day_transition_loading(session)


def _get_home_start_button_rect(surface_width: int, hero_rect: pygame.Rect) -> pygame.Rect:
    return pygame.Rect(surface_width - 274, hero_rect.y + 60, 200, 72)


def _wrap_home_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        candidate = word if not current_line else f"{current_line} {word}"
        if font.size(candidate)[0] <= max_width:
            current_line = candidate
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def _fit_home_text(text: str, font: pygame.font.Font, max_width: int) -> str:
    if font.size(text)[0] <= max_width:
        return text
    trimmed = text
    while trimmed and font.size(trimmed + "...")[0] > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + "...") if trimmed else text


def _draw_home_route_preview(surface: pygame.Surface, preview_map: GameMap, card_rect: pygame.Rect) -> None:
    preview_rect = pygame.Rect(card_rect.x + 18, card_rect.y + 92, card_rect.width - 36, 102)
    pygame.draw.rect(surface, (16, 20, 30), preview_rect, border_radius=14)
    pygame.draw.rect(surface, (74, 97, 138), preview_rect, width=2, border_radius=14)

    scale_x = preview_rect.width / preview_map.world_rect.width
    scale_y = preview_rect.height / preview_map.world_rect.height

    for corridor_rect in preview_map.corridors:
        mini_rect = pygame.Rect(
            preview_rect.x + round(corridor_rect.x * scale_x),
            preview_rect.y + round(corridor_rect.y * scale_y),
            max(3, round(corridor_rect.width * scale_x)),
            max(3, round(corridor_rect.height * scale_y)),
        )
        pygame.draw.rect(surface, (70, 86, 112), mini_rect, border_radius=4)

    for zone in preview_map.zones:
        mini_rect = pygame.Rect(
            preview_rect.x + round(zone.rect.x * scale_x),
            preview_rect.y + round(zone.rect.y * scale_y),
            max(6, round(zone.rect.width * scale_x)),
            max(6, round(zone.rect.height * scale_y)),
        )
        pygame.draw.rect(surface, zone.template.accent_color, mini_rect, border_radius=4)

    spawn_x = preview_rect.x + round(preview_map.get_spawn_position()[0] * scale_x)
    spawn_y = preview_rect.y + round(preview_map.get_spawn_position()[1] * scale_y)
    pygame.draw.circle(surface, (255, 221, 121), (spawn_x, spawn_y), 4)


def _draw_homepage(
    surface: pygame.Surface,
    preview_map: GameMap,
    title_font: pygame.font.Font,
    heading_font: pygame.font.Font,
    body_font: pygame.font.Font,
    small_font: pygame.font.Font,
    elapsed: float,
) -> None:
    surface.fill((14, 18, 26))
    width = surface.get_width()
    height = surface.get_height()

    for stripe_index in range(6):
        stripe_rect = pygame.Rect(0, stripe_index * 120, width, 80)
        stripe_color = (20 + stripe_index * 4, 26 + stripe_index * 5, 38 + stripe_index * 6)
        pygame.draw.rect(surface, stripe_color, stripe_rect)

    hero_rect = pygame.Rect(48, 42, width - 96, 206)
    pygame.draw.rect(surface, (24, 30, 44), hero_rect, border_radius=28)
    pygame.draw.rect(surface, (104, 149, 255), hero_rect, width=3, border_radius=28)

    title_surface = title_font.render("Campus Chaos", True, (244, 246, 250))
    subtitle_surface = heading_font.render("Outstudy the semester before it chews you alive.", True, (174, 204, 255))
    hook_surface = body_font.render(
        "Survive a 7-day week, clear enough missions, and keep your stats alive.",
        True,
        (224, 230, 240),
    )
    controls_surface = small_font.render(
        "WASD move  |  E interact  |  F1/F2 choose mission  |  1-8 powerups  |  Space or Enter start",
        True,
        (199, 206, 218),
    )

    surface.blit(title_surface, (hero_rect.x + 28, hero_rect.y + 24))
    surface.blit(subtitle_surface, (hero_rect.x + 30, hero_rect.y + 88))
    surface.blit(hook_surface, (hero_rect.x + 30, hero_rect.y + 126))
    surface.blit(controls_surface, (hero_rect.x + 30, hero_rect.y + 165))

    pulse = 0.5 + 0.5 * math.sin(elapsed * 3.0)
    button_rect = _get_home_start_button_rect(width, hero_rect)
    button_color = (
        int(70 + 40 * pulse),
        int(126 + 55 * pulse),
        int(178 + 35 * pulse),
    )
    pygame.draw.rect(surface, button_color, button_rect, border_radius=22)
    pygame.draw.rect(surface, (245, 248, 252), button_rect, width=3, border_radius=22)
    button_text = heading_font.render("Start Run", True, (250, 252, 255))
    button_text_rect = button_text.get_rect(center=button_rect.center)
    surface.blit(button_text, button_text_rect)

    info_y = 282
    info_title = heading_font.render("Today's Rotating Campus", True, (245, 247, 250))
    info_caption = small_font.render(
        "Each day lasts 60 seconds, the route can rotate, and nights throw you into a dream trial.",
        True,
        (188, 198, 214),
    )
    surface.blit(info_title, (52, info_y))
    surface.blit(info_caption, (52, info_y + 32))

    map_card_rect = pygame.Rect(52, 334, 450, 268)
    pygame.draw.rect(surface, (22, 27, 39), map_card_rect, border_radius=22)
    pygame.draw.rect(surface, (102, 139, 214), map_card_rect, width=2, border_radius=22)

    map_name = heading_font.render(preview_map.layout.name, True, (245, 247, 250))
    map_subtitle = small_font.render(preview_map.layout.subtitle, True, (183, 195, 214))
    surface.blit(map_name, (map_card_rect.x + 18, map_card_rect.y + 20))
    surface.blit(map_subtitle, (map_card_rect.x + 18, map_card_rect.y + 54))
    _draw_home_route_preview(surface, preview_map, map_card_rect)

    summary_lines = [
        "Connected hallways shift every day.",
        "Follow aisles between rooms instead of weaving through blockers.",
    ]
    summary_y = map_card_rect.y + 206
    for line in summary_lines:
        for wrapped_line in _wrap_home_text(line, small_font, map_card_rect.width - 36):
            line_surface = small_font.render(wrapped_line, True, (215, 221, 232))
            surface.blit(line_surface, (map_card_rect.x + 18, summary_y))
            summary_y += 18
        summary_y += 2

    note_rect = pygame.Rect(534, 334, width - 586, 268)
    pygame.draw.rect(surface, (22, 27, 39), note_rect, border_radius=22)
    pygame.draw.rect(surface, (102, 139, 214), note_rect, width=2, border_radius=22)

    note_title = heading_font.render("Room rules", True, (245, 247, 250))
    note_lines = [
        "Each room applies its listed effect once per run.",
        "Effects land over a short visit instead of draining forever.",
        "Hit 10 completed missions by the end of Day 7 to win the week.",
    ]
    surface.blit(note_title, (note_rect.x + 18, note_rect.y + 20))
    y = note_rect.y + 66
    for line in note_lines:
        for wrapped_line in _wrap_home_text(line, body_font, note_rect.width - 36):
            line_surface = body_font.render(wrapped_line, True, (220, 226, 235))
            surface.blit(line_surface, (note_rect.x + 18, y))
            y += 28
        y += 8

    zone_title = body_font.render("Zone highlights", True, (245, 247, 250))
    surface.blit(zone_title, (note_rect.x + 18, note_rect.bottom - 96))
    highlight_zones = ("Library", "Park", "Cafe", "Part-Time Job")
    for index, zone_name in enumerate(highlight_zones):
        zone = next(template for template in ZONE_TEMPLATES if template.name == zone_name)
        column_x = note_rect.x + 18 + (index % 2) * 290
        row_y = note_rect.bottom - 66 + (index // 2) * 28
        line_text = _fit_home_text(
            f"{zone.name}: {format_effects(zone.effects)}",
            small_font,
            250,
        )
        line_surface = small_font.render(line_text, True, zone.accent_color)
        surface.blit(line_surface, (column_x, row_y))


def _begin_loading_session(asset_loader: AssetLoader) -> SessionLoadState:
    session = _create_game_session(asset_loader, bootstrap_live=False)
    load_state = SessionLoadState(session=session, status_text="Building campus map...")

    def _bootstrap() -> None:
        try:
            load_state.status_text = "Calling AI director for Day 1..."
            _finish_day_bootstrap(session)
            load_state.status_text = "Ready to drop in."
        except Exception as exc:
            load_state.error = str(exc)
        finally:
            load_state.ready = True

    worker = threading.Thread(target=_bootstrap, daemon=True)
    load_state.worker = worker
    worker.start()
    return load_state


def _begin_day_transition_loading(session: GameSession) -> None:
    load_state = SessionLoadState(session=session, status_text=f"Preparing Day {session.current_day}...")
    session.day_load_state = load_state
    session.phase = "day_loading"

    def _bootstrap() -> None:
        try:
            load_state.status_text = f"Building Day {session.current_day} map..."
            _prepare_day(session, reset_stats=False)
            session.phase = "day_loading"
            load_state.status_text = f"Calling AI director for Day {session.current_day}..."
            _finish_day_bootstrap(session)
            load_state.status_text = "Ready to drop in."
        except Exception as exc:
            load_state.error = str(exc)
        finally:
            load_state.ready = True

    worker = threading.Thread(target=_bootstrap, daemon=True)
    load_state.worker = worker
    worker.start()


def _draw_loading_screen(
    surface: pygame.Surface,
    title_font: pygame.font.Font,
    heading_font: pygame.font.Font,
    body_font: pygame.font.Font,
    elapsed: float,
    status_text: str,
) -> None:
    surface.fill((14, 18, 26))

    panel_rect = pygame.Rect(0, 0, 520, 220)
    panel_rect.center = (surface.get_width() // 2, surface.get_height() // 2)
    draw_smooth_panel(surface, panel_rect, (24, 30, 44), (104, 149, 255), border_radius=28)

    title_surface = title_font.render("Campus Chaos", True, (244, 246, 250))
    subtitle_surface = heading_font.render("Preparing your day...", True, (174, 204, 255))
    body_surface = body_font.render(status_text, True, (220, 226, 235))

    dots = "." * (int(elapsed * 2.6) % 4)
    pulse_surface = body_font.render(f"AI director is planning{dots}", True, (195, 205, 221))

    bar_rect = pygame.Rect(panel_rect.x + 36, panel_rect.bottom - 62, panel_rect.width - 72, 16)
    fill_ratio = 0.24 + 0.76 * (0.5 + 0.5 * math.sin(elapsed * 2.8))
    fill_rect = pygame.Rect(bar_rect.x, bar_rect.y, round(bar_rect.width * fill_ratio), bar_rect.height)

    surface.blit(title_surface, (panel_rect.x + 34, panel_rect.y + 28))
    surface.blit(subtitle_surface, (panel_rect.x + 36, panel_rect.y + 92))
    surface.blit(body_surface, (panel_rect.x + 36, panel_rect.y + 126))
    surface.blit(pulse_surface, (panel_rect.x + 36, panel_rect.y + 154))

    pygame.draw.rect(surface, (50, 58, 74), bar_rect, border_radius=8)
    pygame.draw.rect(surface, (107, 176, 255), fill_rect, border_radius=8)
    pygame.draw.rect(surface, (230, 235, 240), bar_rect, width=2, border_radius=8)


def _current_combo_multiplier(session: GameSession) -> int:
    return min(3, session.combo_streak + 1)


def _choice_label(choice_id: str) -> str:
    return "safe" if choice_id == "safe" else "risk"


def _apply_friend_choice(
    session: GameSession,
    choice_number: int,
    audio_manager: AudioManager | None = None,
) -> bool:
    current_location = _get_active_day_map(session).get_current_location_label(session.player.rect)
    outcome = session.friend_manager.choose_option(
        choice_number,
        current_location=current_location,
        class_live_now=_class_live_now(session),
        energy=session.stats.energy,
    )
    if outcome is None:
        return False

    session.stats.apply_change("energy", float(outcome["energy_delta"]))
    session.stats.apply_change("stress", float(outcome["stress_delta"]))
    session.stats.apply_change("focus", float(outcome["focus_delta"]))
    session.day_time_remaining = max(0.0, session.day_time_remaining - float(outcome["time_cost"]))

    destination = outcome.get("destination")
    if isinstance(destination, str):
        session.friend_manager.start_escort(destination, _get_active_day_map(session), session.player)

    choice_name = str(outcome["choice_id"]).replace("_", " ")
    session.mission_reward_message = f"Mika: {choice_name}"
    session.mission_reward_timer = 1.8
    if audio_manager is not None:
        audio_manager.play_sfx("mission_accept")
    return True


def _update_day_session(session: GameSession, dt: float, audio_manager: AudioManager | None = None) -> None:
    session.friend_manager.update_runtime(dt)
    active_map = _get_active_day_map(session)
    in_overworld = session.current_area == "overworld"

    player_speed_multiplier = (
        session.powerup_manager.get_player_speed_multiplier() * session.enemy_manager.get_player_speed_multiplier()
    )
    session.player.set_speed_multiplier(player_speed_multiplier)

    escort_active = session.friend_manager.escort_state is not None
    if escort_active:
        is_moving = session.friend_manager.update_escort(dt, active_map, session.player)
    else:
        is_moving = session.player.update(
            dt,
            active_map.world_rect.width,
            active_map.world_rect.height,
            can_move=not session.stats.is_out_of_energy(),
        )

    active_map.update(session.player.rect)
    blocking_rects = active_map.get_blocking_rects()
    if in_overworld:
        blocking_rects.extend(session.enemy_manager.get_blocking_rects())
    session.player.resolve_blockers(blocking_rects)
    session.player.clamp_to_rect(active_map.get_player_bounds())
    active_map.keep_player_on_paths(session.player)
    active_map.update(session.player.rect)
    if in_overworld:
        session.friend_manager.update_idle(dt, active_map, session.player.rect)

    completed_destination = session.friend_manager.pop_completed_destination()
    if in_overworld and completed_destination == "Cafe":
        _enter_cafe_interior(session, with_mika=True)
        active_map = _get_active_day_map(session)
        in_overworld = False

    if session.mission_manager.has_choice_pending():
        chosen_id = session.mission_manager.auto_choose_for_zones(active_map.active_zone_names)
        if chosen_id is not None:
            session.mission_reward_message = f"Chose {_choice_label(chosen_id)} mission"
            session.mission_reward_timer = 1.6
            if audio_manager is not None:
                audio_manager.play_sfx("mission_accept")

    session.mission_manager.update(dt, active_map.active_zone_names, session.stats, session.powerup_manager)

    mission_reward = session.mission_manager.pop_completion_reward()
    if mission_reward.get("money", 0) > 0 or mission_reward.get("score", 0) > 0:
        combo_multiplier = _current_combo_multiplier(session)
        reward_money = mission_reward.get("money", 0) * combo_multiplier
        reward_score = mission_reward.get("score", 0) * combo_multiplier
        session.stats.apply_change("money", float(reward_money))
        session.stats.apply_change("score", float(reward_score))
        session.combo_streak = min(3, session.combo_streak + 1)
        session.mission_score += 1
        session.missions_completed_today += 1
        session.mission_reward_message = (
            f"Mission cleared x{combo_multiplier}: +${reward_money} | +{reward_score} score | mission {session.mission_score}"
        )
        session.mission_reward_timer = 2.5
        if audio_manager is not None:
            audio_manager.play_sfx("mission_complete")

    mission_penalty = session.mission_manager.pop_failure_penalty()
    if mission_penalty.get("stress", 0) > 0:
        session.stats.apply_change("stress", float(mission_penalty["stress"]))
        session.combo_streak = 0
        session.mission_reward_message = f"Mission failed: +{mission_penalty['stress']} stress"
        session.mission_reward_timer = 2.5
        if audio_manager is not None:
            audio_manager.play_sfx("mission_fail")

    if in_overworld:
        session.enemy_manager.update(
            dt,
            session.player,
            session.stats,
            session.mission_manager,
            session.modifier_system,
            session.powerup_manager,
        )
    session.stats.update(
        dt,
        False if escort_active else is_moving,
        active_map.active_zone_names,
        session.modifier_system,
        session.powerup_manager,
    )
    session.modifier_system.update(dt)
    session.powerup_manager.update(dt)
    session.temptation_manager.update(dt, session.stats)
    current_pressure_state = _classify_pressure_state(session)

    if session.stats.stress > 80:
        session.stats.apply_change("energy", -7.5 * dt)
        session.stats.apply_change("focus", -6.0 * dt)

    if session.mission_manager.needs_refresh():
        if isinstance(session.queued_mission_payload, dict):
            session.mission_manager.refresh_choices(
                safe_mission=session.queued_mission_payload.get("safe"),
                risk_mission=session.queued_mission_payload.get("risk"),
                route_time_to_zones=_current_route_time_estimates(session),
            )
            session.queued_mission_payload = None
        else:
            director_payload = _request_director_update(session, reason="new_mission")
            _apply_director_update(session, director_payload, allow_immediate_mission=True)

    if (
        current_pressure_state in {"strong", "weak"}
        and current_pressure_state != session.pressure_state
        and session.director_cooldown <= 0
    ):
        session.pressure_state = current_pressure_state
        director_payload = _request_director_update(session, reason="pressure_shift")
        _apply_director_update(session, director_payload, allow_immediate_mission=False)
        session.director_cooldown = 12.0
        if current_pressure_state == "strong":
            session.mission_reward_message = "AI director ramps the pressure."
        else:
            session.mission_reward_message = "AI director eases up a little."
        session.mission_reward_timer = 2.0
    elif current_pressure_state == "stable":
        session.pressure_state = "stable"

    if in_overworld:
        session.friend_manager.maybe_trigger_encounter(_build_friend_context(session))

    session.day_time_remaining = max(0.0, session.day_time_remaining - dt)
    if session.day_time_remaining <= 0:
        _begin_summary_phase(session, audio_manager=audio_manager)
        _tick_banner_timers(session, dt)
        return

    session.game_over = session.stats.is_game_over()
    money_spent = session.stats.pop_money_spent_display()
    if money_spent > 0:
        session.money_spent_message = f"Spent: -${money_spent}"
        session.money_spent_timer = 1.8
    _tick_banner_timers(session, dt)


def _update_summary_phase(session: GameSession, dt: float, audio_manager: AudioManager | None = None) -> None:
    session.summary_timer = max(0.0, session.summary_timer - dt)
    session.game_map.update(session.player.rect)
    _tick_banner_timers(session, dt)

    if session.summary_timer > 0:
        return

    if session.current_day >= session.total_days:
        session.phase = "week_complete"
        session.week_result = "WIN" if session.mission_score >= session.target_score else "LOSE"
        return

    _begin_dream_phase(session, audio_manager=audio_manager)


def _get_active_dream_step(session: GameSession) -> MissionStep | None:
    for step in session.dream_mission.steps:
        if not step.completed:
            return step
    return None


def _update_dream_session(session: GameSession, dt: float, audio_manager: AudioManager | None = None) -> None:
    if session.dream_map is None:
        _advance_after_dream(session, success=False, audio_manager=audio_manager)
        return

    session.player.set_speed_multiplier(1.0)
    session.player.update(
        dt,
        session.dream_map.world_rect.width,
        session.dream_map.world_rect.height,
        can_move=True,
    )
    session.dream_map.update(session.player.rect)
    session.player.clamp_to_rect(session.dream_map.get_player_bounds())
    session.dream_map.keep_player_on_paths(session.player)
    session.dream_map.update(session.player.rect)

    session.dream_mission.time_remaining = max(0.0, session.dream_mission.time_remaining - dt)
    session.dream_mission.phase_remaining = max(0.0, session.dream_mission.phase_remaining - dt)

    step = _get_active_dream_step(session)
    if step is not None:
        if step.step_type == "GO_TO":
            if step.target in session.dream_map.active_zone_names:
                step.completed = True
        elif step.step_type == "STAY":
            if step.target in session.dream_map.active_zone_names:
                step.progress = min(step.duration, step.progress + dt)
            else:
                step.progress = max(0.0, step.progress - dt * 0.5)
            if step.progress >= step.duration:
                step.completed = True

    if all(step.completed for step in session.dream_mission.steps):
        session.dream_mission.completed = True
        _advance_after_dream(session, success=True, audio_manager=audio_manager)
        _tick_banner_timers(session, dt)
        return

    if session.dream_mission.time_remaining <= 0 or session.dream_mission.phase_remaining <= 0:
        session.dream_mission.failed = True
        _advance_after_dream(session, success=False, audio_manager=audio_manager)

    _tick_banner_timers(session, dt)


def _get_area_prompt(session: GameSession) -> tuple[str, tuple[int, int]] | None:
    if session.phase != "day":
        return None
    if session.current_area == "overworld":
        return session.game_map.get_cafe_entrance_prompt(session.player.rect)
    if session.cafe_interior is None:
        return None
    prompt = session.cafe_interior.get_local_prompt(session.player.rect)
    if prompt is None:
        return None
    text, anchor, _interaction_id = prompt
    return text, anchor


def _draw_world_prompt(surface: pygame.Surface, active_map, prompt_text: str, anchor: tuple[int, int]) -> None:
    prompt_font = ui_font(13, bold=True)
    text_surface = prompt_font.render(prompt_text, True, (245, 247, 250))
    anchor_point = active_map.world_to_screen_point(anchor)
    bubble_rect = text_surface.get_rect(midbottom=(anchor_point[0], anchor_point[1] - 10))
    bubble_rect.inflate_ip(20, 12)
    bubble_rect.clamp_ip(active_map.playfield_rect.inflate(-10, -10))
    draw_smooth_panel(surface, bubble_rect, (35, 40, 52), (228, 233, 240), border_radius=10)
    surface.blit(text_surface, text_surface.get_rect(center=bubble_rect.center))


def _draw_play_session(
    surface: pygame.Surface,
    session: GameSession,
    overlay_font: pygame.font.Font,
    overlay_small_font: pygame.font.Font,
) -> None:
    surface.fill(BACKGROUND_COLOR)
    active_map = _get_active_map(session)
    zone_ratios = None if session.phase == "dream" else session.stats.get_zone_charge_ratios()
    active_map.draw(surface, session.player.rect, zone_ratios)

    if session.phase == "day" and session.current_area == "overworld":
        session.enemy_manager.draw(surface, active_map.get_draw_offset(), clip_rect=active_map.playfield_rect)
        session.friend_manager.draw(surface, active_map, session.player.rect)
    elif session.phase == "day" and session.current_area == "cafe_interior" and session.mika_in_cafe:
        session.friend_manager.draw(surface, active_map, session.player.rect, show_hint=False)
    session.player.draw(surface, active_map.world_to_screen_rect(session.player.rect))
    area_prompt = _get_area_prompt(session)
    if area_prompt is not None:
        prompt_text, prompt_anchor = area_prompt
        _draw_world_prompt(surface, active_map, prompt_text, prompt_anchor)
    session.stats.draw(surface)

    if session.phase == "day":
        session.modifier_system.draw(surface)
        session.mission_manager.draw(surface)
        session.powerup_manager.draw(surface)
        session.event_manager.draw(surface)
        session.temptation_manager.draw(surface)
    elif session.phase == "dream":
        _draw_dream_panel(surface, session, overlay_small_font)

    compact_status_font = ui_font(22, bold=True)
    llm_font = ui_font(14, bold=True)
    llm_detail_font = ui_font(13)
    status_start_y = 286
    status_row_gap = 32

    if session.phase == "day":
        combo_surface = overlay_small_font.render(
            f"Combo x{_current_combo_multiplier(session)}",
            True,
            (255, 216, 116) if session.combo_streak > 0 else (202, 209, 220),
        )
        surface.blit(combo_surface, (18, status_start_y))

        day_surface = compact_status_font.render(
            f"Day {session.current_day}/{session.total_days}",
            True,
            (234, 238, 244),
        )
        mission_score_surface = compact_status_font.render(
            f"Missions {session.mission_score}/{session.target_score}",
            True,
            (234, 238, 244),
        )
        timer_color = (255, 219, 125) if session.day_time_remaining > 15 else (247, 126, 142)
        timer_surface = compact_status_font.render(
            f"Day timer: {session.day_time_remaining:0.1f}s",
            True,
            timer_color,
        )
        surface.blit(day_surface, (18, status_start_y + status_row_gap))
        surface.blit(mission_score_surface, (18, status_start_y + status_row_gap * 2))
        surface.blit(timer_surface, (18, status_start_y + status_row_gap * 3))
    else:
        day_surface = compact_status_font.render(
            f"Day {session.current_day}/{session.total_days}",
            True,
            (234, 238, 244),
        )
        mission_score_surface = compact_status_font.render(
            f"Missions {session.mission_score}/{session.target_score}",
            True,
            (234, 238, 244),
        )
        timer_surface = compact_status_font.render(
            f"Dream fades in {session.dream_mission.phase_remaining:0.1f}s",
            True,
            (198, 191, 255),
        )
        surface.blit(day_surface, (18, status_start_y))
        surface.blit(mission_score_surface, (18, status_start_y + status_row_gap))
        surface.blit(timer_surface, (18, status_start_y + status_row_gap * 2))

    llm_status = get_llm_status()
    llm_live = llm_status.get("mode") == "live"
    llm_label = str(llm_status.get("label", "FALLBACK"))
    llm_detail = str(llm_status.get("detail", ""))
    badge_text = llm_font.render(f"LLM: {llm_label}", True, (247, 250, 252))
    badge_rect = badge_text.get_rect(topleft=(18, SCREEN_HEIGHT - 82))
    badge_background = badge_rect.inflate(14, 8)
    badge_color = (36, 96, 65) if llm_live else (114, 66, 42)
    badge_border = (129, 224, 151) if llm_live else (245, 176, 96)
    draw_smooth_panel(surface, badge_background, badge_color, badge_border, border_radius=9)
    surface.blit(badge_text, badge_rect)

    detail_text = llm_detail_font.render(
        _fit_home_text(llm_detail, llm_detail_font, 182),
        True,
        (205, 214, 226),
    )
    detail_y = badge_background.bottom + 6
    surface.blit(detail_text, (18, detail_y))

    active_zone_names = sorted(active_map.active_zone_names)
    if session.phase == "day" and session.current_area == "cafe_interior":
        zone_label = "Inside: Cafe Interior"
    elif active_zone_names:
        zone_label = f"Inside: {', '.join(active_zone_names)}"
    else:
        zone_label = ""
    if zone_label:
        zone_banner = overlay_small_font.render(
            zone_label,
            True,
            (232, 237, 242),
        )
        zone_banner_rect = zone_banner.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 64))
        zone_background = zone_banner_rect.inflate(26, 14)
        pygame.draw.rect(surface, (33, 39, 50), zone_background, border_radius=12)
        pygame.draw.rect(surface, (233, 237, 241), zone_background, width=2, border_radius=12)
        surface.blit(zone_banner, zone_banner_rect)

    if session.phase == "day" and session.stats.stress > 80:
        panic_overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        pulse = 60 + int(30 * abs(math.sin(pygame.time.get_ticks() / 120.0)))
        panic_overlay.fill((135, 26, 42, pulse))
        surface.blit(panic_overlay, (0, 0))

        panic_surface = overlay_font.render("PANIC MODE", True, (255, 230, 236))
        panic_rect = panic_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 30))
        surface.blit(panic_surface, panic_rect)

    if session.mission_reward_timer > 0:
        reward_surface = compact_status_font.render(session.mission_reward_message, True, (124, 217, 145))
        reward_rect = reward_surface.get_rect(center=(SCREEN_WIDTH // 2, 98))
        surface.blit(reward_surface, reward_rect)

    if session.ai_call_timer > 0 and session.ai_call_message:
        ai_live = get_llm_status().get("mode") == "live"
        ai_surface = compact_status_font.render(
            session.ai_call_message,
            True,
            (246, 249, 252),
        )
        ai_rect = ai_surface.get_rect(center=(SCREEN_WIDTH // 2, 72))
        ai_background = ai_rect.inflate(26, 14)
        ai_color = (36, 96, 65) if ai_live else (114, 66, 42)
        ai_border = (129, 224, 151) if ai_live else (245, 176, 96)
        pygame.draw.rect(surface, ai_color, ai_background, border_radius=12)
        pygame.draw.rect(surface, ai_border, ai_background, width=2, border_radius=12)
        surface.blit(ai_surface, ai_rect)

    if session.money_spent_timer > 0:
        spent_surface = compact_status_font.render(session.money_spent_message, True, (227, 93, 106))
        spent_rect = spent_surface.get_rect(center=(SCREEN_WIDTH // 2, 122))
        surface.blit(spent_surface, spent_rect)

    if session.area_message_timer > 0 and session.area_message:
        area_surface = llm_font.render(session.area_message, True, (236, 241, 247))
        area_rect = area_surface.get_rect(center=(SCREEN_WIDTH // 2, 146))
        area_background = area_rect.inflate(18, 10)
        draw_smooth_panel(surface, area_background, (44, 55, 69), (182, 197, 216), border_radius=10)
        surface.blit(area_surface, area_rect)

    if session.game_over:
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 12, 18, 178))
        surface.blit(overlay, (0, 0))

        title_surface = overlay_font.render("Game Over", True, (244, 246, 249))
        subtitle_surface = overlay_small_font.render(
            "Energy and money both hit zero.",
            True,
            (230, 235, 240),
        )
        restart_surface = overlay_small_font.render(
            "Press R to restart or Esc for the homepage.",
            True,
            (199, 207, 220),
        )
        title_rect = title_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 34))
        subtitle_rect = subtitle_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 10))
        restart_rect = restart_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 44))
        surface.blit(title_surface, title_rect)
        surface.blit(subtitle_surface, subtitle_rect)
        surface.blit(restart_surface, restart_rect)

    if session.phase == "summary":
        _draw_summary_overlay(surface, session, overlay_font, overlay_small_font)

    if session.phase == "week_complete" and not session.game_over:
        _draw_week_complete_overlay(surface, session, overlay_font, overlay_small_font)


def _draw_dream_panel(surface: pygame.Surface, session: GameSession, font: pygame.font.Font) -> None:
    del font
    title_font = ui_font(18, bold=True)
    body_font = ui_font(14, bold=True)
    meta_font = ui_font(15, bold=True)
    hint_font = ui_font(13)

    panel_rect = pygame.Rect(surface.get_width() - 288, 198, 272, 214)
    draw_smooth_panel(surface, panel_rect, (27, 28, 51), (198, 191, 255), border_radius=12)

    title_surface = title_font.render(
        _fit_home_text(session.dream_mission.title or "Dream Drift", title_font, panel_rect.width - 28),
        True,
        (244, 245, 250),
    )
    meta_surface = meta_font.render(
        f"DREAM | {session.dream_mission.time_remaining:0.1f}s",
        True,
        (198, 191, 255),
    )
    surface.blit(title_surface, (panel_rect.x + 14, panel_rect.y + 12))
    surface.blit(meta_surface, (panel_rect.x + 14, panel_rect.y + 42))

    y = panel_rect.y + 82
    for index, step in enumerate(session.dream_mission.steps[:2], start=1):
        prefix = "[x]" if step.completed else "[ ]"
        if step.step_type == "STAY":
            line = f"{prefix} {index}. Stay in {step.target} ({step.progress:.1f}/{step.duration:.1f}s)"
        else:
            line = f"{prefix} {index}. Go to {step.target}"
        for wrapped_line in _wrap_home_text(line, body_font, panel_rect.width - 28):
            line_surface = body_font.render(wrapped_line, True, (233, 236, 243))
            surface.blit(line_surface, (panel_rect.x + 14, y))
            y += 24
        y += 6

    hint_lines = _wrap_home_text("Clear the dream or oversleep tomorrow.", hint_font, panel_rect.width - 28)
    hint_y = panel_rect.bottom - 18 - len(hint_lines) * 16
    for line in hint_lines:
        hint_surface = hint_font.render(line, True, (183, 188, 220))
        surface.blit(hint_surface, (panel_rect.x + 14, hint_y))
        hint_y += 16


def _draw_summary_overlay(
    surface: pygame.Surface,
    session: GameSession,
    overlay_font: pygame.font.Font,
    overlay_small_font: pygame.font.Font,
) -> None:
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((8, 10, 18, 188))
    surface.blit(overlay, (0, 0))

    title_surface = overlay_font.render(f"Day {session.current_day} Summary", True, (244, 246, 249))
    title_rect = title_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 88))
    surface.blit(title_surface, title_rect)

    for index, line in enumerate(session.summary_lines):
        line_surface = overlay_small_font.render(line, True, (228, 233, 240))
        line_rect = line_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 18 + index * 32))
        surface.blit(line_surface, line_rect)

    footer_surface = overlay_small_font.render(
        f"Dream phase in {max(0.0, session.summary_timer):0.1f}s",
        True,
        (185, 194, 208),
    )
    footer_rect = footer_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 132))
    surface.blit(footer_surface, footer_rect)


def _draw_week_complete_overlay(
    surface: pygame.Surface,
    session: GameSession,
    overlay_font: pygame.font.Font,
    overlay_small_font: pygame.font.Font,
) -> None:
    overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((10, 12, 18, 205))
    surface.blit(overlay, (0, 0))

    won_week = session.week_result == "WIN"
    title_surface = overlay_font.render("Week Cleared" if won_week else "Week Lost", True, (244, 246, 249))
    score_surface = overlay_small_font.render(
        f"Mission score: {session.mission_score}/{session.target_score}",
        True,
        (132, 224, 159) if won_week else (241, 128, 144),
    )
    detail_surface = overlay_small_font.render(
        "Press R to restart or Esc for the homepage.",
        True,
        (205, 213, 226),
    )

    title_rect = title_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 42))
    score_rect = score_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 10))
    detail_rect = detail_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 52))
    surface.blit(title_surface, title_rect)
    surface.blit(score_surface, score_rect)
    surface.blit(detail_surface, detail_rect)


def run() -> None:
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption(WINDOW_TITLE)
    clock = pygame.time.Clock()
    title_font = ui_font(66, bold=True)
    heading_font = ui_font(30, bold=True)
    body_font = ui_font(21, bold=True)
    small_font = ui_font(18, bold=True)
    overlay_font = ui_font(48, bold=True)
    overlay_small_font = ui_font(26, bold=True)

    asset_loader = AssetLoader()
    audio_manager = AudioManager(asset_loader.asset_root)
    preview_map = GameMap(SCREEN_WIDTH, SCREEN_HEIGHT, asset_loader=asset_loader)
    session: GameSession | None = None
    session_load: SessionLoadState | None = None
    current_screen = "home"
    menu_elapsed = 0.0
    running = True

    while running:
        dt = clock.tick(FPS) / 1000.0
        menu_elapsed += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue

            if current_screen == "home":
                hero_rect = pygame.Rect(48, 42, SCREEN_WIDTH - 96, 206)
                button_rect = _get_home_start_button_rect(SCREEN_WIDTH, hero_rect)
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    audio_manager.play_sfx("ui_start")
                    session_load = _begin_loading_session(asset_loader)
                    current_screen = "loading"
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and button_rect.collidepoint(event.pos):
                    audio_manager.play_sfx("ui_start")
                    session_load = _begin_loading_session(asset_loader)
                    current_screen = "loading"
                continue

            if current_screen == "loading":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    current_screen = "home"
                    session_load = None
                continue

            if session is None:
                continue

            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                session.friend_manager.clear_runtime()
                current_screen = "home"
                session = None
                continue

            if session.game_over or session.phase == "week_complete":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    audio_manager.play_sfx("ui_start")
                    session_load = _begin_loading_session(asset_loader)
                    current_screen = "loading"
                continue

            if session.phase == "day" and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_e:
                    if _handle_area_interaction(session):
                        continue
                if (
                    session.friend_manager.has_active_choices()
                    and session.friend_manager.is_player_close(session.player.rect)
                    and event.key in (pygame.K_1, pygame.K_2, pygame.K_3)
                ):
                    choice_number = {pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3}[event.key]
                    if _apply_friend_choice(session, choice_number, audio_manager=audio_manager):
                        continue
                if event.key == pygame.K_F1:
                    if session.mission_manager.choose_mission("safe"):
                        audio_manager.play_sfx("mission_accept")
                        session.mission_reward_message = "Chose safe mission"
                        session.mission_reward_timer = 1.6
                        continue
                elif event.key == pygame.K_F2:
                    if session.mission_manager.choose_mission("risk"):
                        audio_manager.play_sfx("mission_accept")
                        session.mission_reward_message = "Chose risk mission"
                        session.mission_reward_timer = 1.6
                        continue
                elif event.key == pygame.K_t:
                    if session.temptation_manager.engage(session.stats):
                        session.mission_reward_message = "Temptation accepted"
                        session.mission_reward_timer = 1.5
                        continue
                elif event.key == pygame.K_g:
                    if session.temptation_manager.ignore():
                        session.mission_reward_message = "Temptation ignored"
                        session.mission_reward_timer = 1.5
                        continue

            if session.phase == "day":
                if session.powerup_manager.handle_event(event, session.stats, session.modifier_system):
                    audio_manager.play_sfx("powerup")

        if current_screen == "home":
            _sync_audio(audio_manager, current_screen, session)
            _draw_homepage(screen, preview_map, title_font, heading_font, body_font, small_font, menu_elapsed)
            pygame.display.flip()
            continue

        if current_screen == "loading":
            _sync_audio(audio_manager, current_screen, session)
            if session_load is None:
                current_screen = "home"
                continue
            if session_load.ready:
                session = session_load.session
                audio_manager.play_sfx("loading_done")
                if session_load.error:
                    session.mission_reward_message = "AI load hiccup. Using startup fallback."
                    session.mission_reward_timer = 2.6
                session_load = None
                current_screen = "play"
            else:
                status_text = session_load.status_text
                _draw_loading_screen(screen, title_font, heading_font, body_font, menu_elapsed, status_text)
                pygame.display.flip()
                continue

        if session is None:
            current_screen = "home"
            continue

        _sync_audio(audio_manager, current_screen, session)

        if session.phase == "day_loading":
            load_state = session.day_load_state
            if load_state is None:
                session.phase = "day"
            elif load_state.ready:
                audio_manager.play_sfx("loading_done")
                if load_state.error:
                    session.mission_reward_message = "AI load hiccup. Using transition fallback."
                    session.mission_reward_timer = 2.6
                session.day_load_state = None
                session.phase = "day"
            else:
                _draw_loading_screen(screen, title_font, heading_font, body_font, menu_elapsed, load_state.status_text)
                pygame.display.flip()
                continue

        if not session.game_over and session.phase == "day":
            _update_day_session(session, dt, audio_manager=audio_manager)
        elif not session.game_over and session.phase == "summary":
            _update_summary_phase(session, dt, audio_manager=audio_manager)
        elif not session.game_over and session.phase == "dream":
            _update_dream_session(session, dt, audio_manager=audio_manager)
        elif not session.game_over and session.phase == "day_loading":
            pass
        else:
            _get_active_map(session).update(session.player.rect)

        _draw_play_session(screen, session, overlay_font, overlay_small_font)
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    run()
