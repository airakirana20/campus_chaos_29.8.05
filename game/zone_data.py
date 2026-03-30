from dataclasses import dataclass


@dataclass(frozen=True)
class ZoneTemplate:
    name: str
    subtitle: str
    description: str
    fill_color: tuple[int, int, int]
    accent_color: tuple[int, int, int]
    effects: dict[str, float]
    image_path: str | None = None


ZONE_TEMPLATES = (
    ZoneTemplate(
        name="Library",
        subtitle="Quiet study",
        description="Sharp focus gains with a little pressure on the side.",
        fill_color=(57, 89, 145),
        accent_color=(116, 178, 255),
        effects={"focus": 16.0, "stress": 8.0},
    ),
    ZoneTemplate(
        name="Lecture Hall",
        subtitle="Brain on fire",
        description="Big academic boost, but it spikes your nerves.",
        fill_color=(117, 66, 162),
        accent_color=(187, 124, 255),
        effects={"focus": 22.0, "stress": 13.0},
    ),
    ZoneTemplate(
        name="Park",
        subtitle="Fresh air",
        description="A calming reset that trims stress and tops up energy a bit.",
        fill_color=(46, 114, 84),
        accent_color=(122, 226, 168),
        effects={"stress": -11.0, "energy": 3.0},
    ),
    ZoneTemplate(
        name="Club Room",
        subtitle="Social detour",
        description="You decompress here, but your study momentum drifts away.",
        fill_color=(154, 92, 48),
        accent_color=(246, 179, 96),
        effects={"stress": -13.0, "focus": -7.0},
    ),
    ZoneTemplate(
        name="Dorm",
        subtitle="Crash pad",
        description="Strong recovery space that trades a bit of focus for rest.",
        fill_color=(57, 73, 109),
        accent_color=(146, 185, 255),
        effects={"energy": 18.0, "stress": -6.0, "focus": -4.0},
    ),
    ZoneTemplate(
        name="Cafe",
        subtitle="Espresso economy",
        description="Fast energy at the cost of your wallet.",
        fill_color=(120, 76, 50),
        accent_color=(232, 170, 113),
        effects={"energy": 14.0, "money": -9.0},
    ),
    ZoneTemplate(
        name="Print Room",
        subtitle="Mission hub",
        description="Useful for campus errands and keeps your prep moving.",
        fill_color=(80, 85, 99),
        accent_color=(198, 204, 214),
        effects={"focus": 8.0, "energy": -3.0},
    ),
    ZoneTemplate(
        name="Part-Time Job",
        subtitle="Shift grind",
        description="Earn some cash, but it absolutely costs you energy.",
        fill_color=(38, 107, 120),
        accent_color=(109, 224, 239),
        effects={"money": 14.0, "energy": -11.0, "stress": 4.0},
    ),
)

ZONE_NAMES = tuple(zone.name for zone in ZONE_TEMPLATES)
ZONE_EFFECTS = {zone.name: dict(zone.effects) for zone in ZONE_TEMPLATES}
ZONE_LOOKUP = {zone.name: zone for zone in ZONE_TEMPLATES}


def format_effects(effects: dict[str, float], include_prefix: bool = False) -> str:
    stat_names = {
        "energy": "Energy",
        "stress": "Stress",
        "money": "Money",
        "focus": "Focus",
    }

    parts: list[str] = []
    for stat_name, delta in effects.items():
        sign = "+" if delta > 0 else "-"
        parts.append(f"{stat_names.get(stat_name, stat_name.title())} {sign}{abs(delta):.0f}")

    effect_text = " | ".join(parts)
    return f"Visit: {effect_text}" if include_prefix else effect_text


def get_total_effect_magnitude(effects: dict[str, float]) -> float:
    return sum(abs(delta) for delta in effects.values())