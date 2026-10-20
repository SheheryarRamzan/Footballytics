"""A fictional 20-club league with ~400 players.

Everything here is invented: club names, colours, players and attributes. No real clubs,
players or league marks are used (hackathon rules require synthetic data and forbid
third-party trademarks in submissions).
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

# name, short code, primary colour, secondary colour, home ground, style, strength (0..1)
_CLUBS: list[tuple[str, str, str, str, str, str, float]] = [
    ("Riverside Rovers", "RIV", "#1d3a8a", "#8ec5ff", "Riverside Park", "possession", 0.92),
    ("Kingsbridge Athletic", "KGA", "#c8102e", "#ffffff", "The Bridgeworks", "high_press", 0.90),
    ("Northgate United", "NGU", "#111111", "#f2c230", "Northgate Lane", "balanced", 0.86),
    ("Harbour City", "HBC", "#0f766e", "#e6fffa", "Quayside Stadium", "possession", 0.84),
    ("Thornbury Wanderers", "THW", "#15803d", "#ffffff", "Thornbury Road", "direct", 0.78),
    ("Ironvale", "IRV", "#7a1f3d", "#7cc6ff", "The Foundry Ground", "high_press", 0.80),
    ("Ashcombe Albion", "ASA", "#f97316", "#1f2937", "Ashcombe Fields", "balanced", 0.74),
    ("Eastmoor Town", "EMT", "#6d28d9", "#ede9fe", "Moorside Arena", "low_block", 0.70),
    ("Blackwater", "BLW", "#0b0b0b", "#ef4444", "Blackwater Mill", "direct", 0.72),
    ("Westbrook Rangers", "WRA", "#2563eb", "#ffffff", "Brookside", "balanced", 0.76),
    ("Highfield Park", "HFP", "#dc2626", "#111827", "Highfield", "high_press", 0.73),
    ("Silverlake", "SLK", "#94a3b8", "#0f172a", "Lakeside Stadium", "possession", 0.77),
    ("Marlow Heath", "MLH", "#facc15", "#1e3a8a", "Heath Road", "low_block", 0.66),
    ("Stonebridge City", "SBC", "#0ea5e9", "#ffffff", "Stonebridge Arena", "balanced", 0.75),
    ("Redcliffe", "RDC", "#b91c1c", "#fde68a", "Cliff Top", "direct", 0.68),
    ("Oakhurst United", "OKU", "#166534", "#fbbf24", "Oakhurst Green", "low_block", 0.64),
    ("Falconridge", "FCR", "#334155", "#f472b6", "Ridgeway", "high_press", 0.71),
    ("Port Ellis", "PTE", "#0369a1", "#fef08a", "The Docks", "direct", 0.65),
    ("Greyhaven Athletic", "GHA", "#475569", "#22d3ee", "Haven Park", "possession", 0.69),
    ("Fenwick Vale", "FNV", "#9d174d", "#fce7f3", "Vale Meadow", "low_block", 0.62),
]

# Tactical archetypes: press = pressing intensity, line = defensive line height,
# directness = long-ball tendency, tempo = speed of decisions, width, crossing tendency.
STYLES: dict[str, dict[str, float]] = {
    "possession": {"press": 0.65, "line": 0.70, "directness": 0.15, "tempo": 0.45, "width": 0.70, "crossing": 0.30},
    "high_press": {"press": 0.90, "line": 0.80, "directness": 0.40, "tempo": 0.75, "width": 0.60, "crossing": 0.40},
    "balanced": {"press": 0.55, "line": 0.55, "directness": 0.35, "tempo": 0.55, "width": 0.60, "crossing": 0.45},
    "direct": {"press": 0.50, "line": 0.45, "directness": 0.70, "tempo": 0.65, "width": 0.65, "crossing": 0.70},
    "low_block": {"press": 0.38, "line": 0.32, "directness": 0.48, "tempo": 0.50, "width": 0.55, "crossing": 0.50},
}

FORMATION_BY_STYLE = {
    "possession": "4-3-3",
    "high_press": "4-3-3",
    "balanced": "4-2-3-1",
    "direct": "4-4-2",
    "low_block": "5-3-2",
}

_FIRST = [
    "Aaron", "Adebayo", "Ali", "Amir", "Andre", "Ben", "Bruno", "Callum", "Carlos", "Chidi", "Conor", "Daniel",
    "Dario", "Declan", "Diego", "Elias", "Emile", "Ethan", "Faisal", "Felix", "Gabriel", "Hamza", "Hugo", "Ibrahim",
    "Isaac", "Jamal", "Javier", "Jonas", "Jude", "Kai", "Kenji", "Kofi", "Liam", "Lucas", "Luis", "Malik", "Marco",
    "Mateo", "Max", "Mikel", "Moussa", "Nathan", "Nico", "Noah", "Omar", "Oscar", "Owen", "Pablo", "Rafael", "Reece",
    "Rui", "Ryan", "Sami", "Santiago", "Sergio", "Seun", "Tariq", "Theo", "Tom", "Tomas", "Victor", "Wesley",
    "Xavi", "Yasin", "Yusuf", "Zane", "Arlo", "Rhys", "Eitan", "Joao", "Kwame", "Leon", "Matias", "Bilal",
]
_LAST = [
    "Abara", "Achterberg", "Adeyemi", "Almeida", "Andersson", "Ashworth", "Bakari", "Balogun", "Barrett", "Bauer",
    "Bellamy", "Benali", "Blackwood", "Bosch", "Brennan", "Caldwell", "Carvalho", "Castell", "Chen", "Coulibaly",
    "Dalton", "Delacroix", "Diallo", "Dorsey", "Ekwueme", "Ellery", "Fairbanks", "Fontaine", "Garrido", "Haddad",
    "Halloran", "Hartley", "Ishikawa", "Jansen", "Kamara", "Kaplan", "Keane", "Kowalski", "Laurent", "Lindqvist",
    "Lombardi", "Mahrez-Sy", "Marsh", "Mensah", "Moreau", "Nakamura", "Novak", "Obi", "Okafor", "Oyelaran",
    "Pereira", "Petrov", "Quaresma", "Rahman", "Rinaldi", "Rossi", "Saltzman", "Sandoval", "Sato", "Silva-Reid",
    "Sorensen", "Stavros", "Tavares", "Thornton", "Toure", "Underwood", "Vasquez", "Venter", "Wakefield", "Whitlock",
    "Yamamoto", "Yilmaz", "Zielinski", "Ferreira", "Ogunleye", "Henriksen", "Castellano", "Mbeki", "Duarte",
]

# Squad template: (position group, detailed role, count)
_SQUAD = [
    ("GK", "GK", 2),
    ("DEF", "CB", 4), ("DEF", "FB", 4),
    ("MID", "DM", 2), ("MID", "CM", 3), ("MID", "AM", 2),
    ("FWD", "W", 3), ("FWD", "ST", 2),
]

# Attribute emphasis per role: (pace, passing, shooting, dribbling, defending, vision, gk)
_ROLE_PROFILE = {
    "GK": (0.35, 0.55, 0.15, 0.25, 0.30, 0.40, 1.00),
    "CB": (0.65, 0.65, 0.30, 0.45, 1.00, 0.55, 0.0),
    "FB": (0.90, 0.75, 0.40, 0.70, 0.85, 0.65, 0.0),
    "DM": (0.65, 0.85, 0.50, 0.65, 0.90, 0.80, 0.0),
    "CM": (0.70, 0.95, 0.65, 0.80, 0.70, 0.90, 0.0),
    "AM": (0.80, 0.95, 0.85, 0.95, 0.45, 1.00, 0.0),
    "W": (1.00, 0.80, 0.85, 1.00, 0.40, 0.85, 0.0),
    "ST": (0.90, 0.70, 1.00, 0.85, 0.35, 0.75, 0.0),
}

FANTASY_BASE_PRICE = {"GK": 4.0, "DEF": 4.0, "MID": 4.5, "FWD": 4.5}
_PRICE_SLOPE = {"GK": 0.12, "DEF": 0.16, "MID": 0.36, "FWD": 0.40}
_ROLE_NUMBERS = {
    "GK": [1, 13], "CB": [4, 5, 15, 24], "FB": [2, 3, 12, 22], "DM": [6, 16],
    "CM": [8, 14, 18], "AM": [10, 20], "W": [7, 11, 17], "ST": [9, 19],
}


@dataclass
class Player:
    id: str
    name: str
    club_id: str
    group: str  # GK / DEF / MID / FWD
    role: str  # GK / CB / FB / DM / CM / AM / W / ST
    number: int
    pace: float
    passing: float
    shooting: float
    dribbling: float
    defending: float
    vision: float
    goalkeeping: float
    stamina: float
    composure: float
    rating: float
    price: float

    @property
    def short_name(self) -> str:
        return self.name.split(" ", 1)[-1]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["short_name"] = self.short_name
        return d


@dataclass
class Club:
    id: str
    name: str
    primary: str
    secondary: str
    ground: str
    style: str
    formation: str
    strength: float
    tactics: dict[str, float]
    players: list[Player] = field(default_factory=list)

    def to_dict(self, with_players: bool = False) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "primary": self.primary,
            "secondary": self.secondary,
            "ground": self.ground,
            "style": self.style,
            "formation": self.formation,
            "strength": self.strength,
            "tactics": self.tactics,
        }
        if with_players:
            d["players"] = [p.to_dict() for p in self.players]
        return d


@dataclass
class League:
    name: str
    clubs: dict[str, Club]
    players: dict[str, Player]

    def to_dict(self) -> dict:
        return {"name": self.name, "clubs": [c.to_dict(with_players=True) for c in self.clubs.values()]}


def _attr(rng: random.Random, level: float, emphasis: float) -> float:
    """An attribute on a 1..99 scale from club level (0..1) and role emphasis (0..1)."""
    base = 38 + 50 * level * (0.45 + 0.55 * emphasis)
    return round(max(20.0, min(97.0, rng.gauss(base, 5.5))), 1)


def generate_league(seed: int = 7, name: str = "Footballytics Premier Division") -> League:
    rng = random.Random(seed)
    used_names: set[str] = set()
    clubs: dict[str, Club] = {}
    players: dict[str, Player] = {}
    for club_name, code, primary, secondary, ground, style, strength in _CLUBS:
        tactics = {k: round(min(1.0, max(0.0, v + rng.uniform(-0.06, 0.06))), 2) for k, v in STYLES[style].items()}
        club = Club(code, club_name, primary, secondary, ground, style, FORMATION_BY_STYLE[style], strength, tactics)
        for group, role, count in _SQUAD:
            generated: list[Player] = []
            for i in range(count):
                while True:
                    full = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
                    if full not in used_names:
                        used_names.add(full)
                        break
                # First choices are stronger than back-ups.
                level = strength * (1.0 if i == 0 else rng.uniform(0.86, 0.97))
                prof = _ROLE_PROFILE[role]
                pace, passing, shooting, dribbling, defending, vision, gk = (_attr(rng, level, e) for e in prof)
                if role != "GK":
                    gk = round(rng.uniform(10, 20), 1)
                stamina = _attr(rng, level, 0.85 if role in ("FB", "CM", "DM", "W") else 0.6)
                composure = _attr(rng, level, 0.7)
                key_attrs = {
                    "GK": (gk,), "CB": (defending,), "FB": (defending, pace), "DM": (defending, passing),
                    "CM": (passing, vision), "AM": (vision, dribbling), "W": (pace, dribbling), "ST": (shooting,),
                }[role]
                key = sum(key_attrs) / len(key_attrs)
                rating = round(0.6 * key + 0.4 * (passing + composure) / 2, 1)
                price = FANTASY_BASE_PRICE[group] + max(0.0, rating - 62) * _PRICE_SLOPE[group]
                price = round(min(14.5, price + rng.uniform(-0.3, 0.3)) * 2) / 2
                generated.append(Player("", full, code, group, role, 0, pace, passing, shooting, dribbling,
                                        defending, vision, gk, stamina, composure, rating, price))
            # Best player in each role gets the classic shirt number.
            for p, number in zip(sorted(generated, key=lambda p: -p.rating), _ROLE_NUMBERS[role]):
                p.number = number
                p.id = f"{code}-{number:02d}"
                club.players.append(p)
                players[p.id] = p
        clubs[code] = club
    return League(name, clubs, players)


def pick_lineup(club: Club) -> tuple[list[Player], list[Player]]:
    """Pick 11 starters for the club's formation plus 7 substitutes, best-rated first."""
    by_role: dict[str, list[Player]] = {}
    for p in sorted(club.players, key=lambda p: -p.rating):
        by_role.setdefault(p.role, []).append(p)
    need = FORMATION_ROLES[club.formation]
    starters: list[Player] = []
    for role in need:
        pool = by_role.get(role) or []
        if not pool:  # fall back to any outfielder of a related role
            alt = {"DM": "CM", "AM": "CM", "W": "AM", "FB": "CB", "ST": "W", "CM": "DM", "CB": "FB"}[role]
            pool = by_role.get(alt) or []
        starters.append(pool.pop(0))
    rest = sorted((p for ps in by_role.values() for p in ps), key=lambda p: -p.rating)
    gk_sub = next((p for p in rest if p.role == "GK"), None)
    subs = [p for p in rest if p.role != "GK"][:6]
    if gk_sub:
        subs.insert(0, gk_sub)
    return starters, subs


# Role list per formation, in the same order as the formation anchor templates.
FORMATION_ROLES = {
    "4-3-3": ["GK", "FB", "CB", "CB", "FB", "DM", "CM", "CM", "W", "ST", "W"],
    "4-2-3-1": ["GK", "FB", "CB", "CB", "FB", "DM", "CM", "W", "AM", "W", "ST"],
    "4-4-2": ["GK", "FB", "CB", "CB", "FB", "W", "CM", "CM", "W", "ST", "ST"],
    "5-3-2": ["GK", "FB", "CB", "CB", "CB", "FB", "CM", "DM", "CM", "ST", "ST"],
}

# Formation anchors in team frame, normalised: depth 0 = own goal line, 1 = halfway-ish
# attacking line; width 0 = right touchline, 1 = left touchline (attacking towards +x).
FORMATION_ANCHORS = {
    "4-3-3": [(0.0, 0.5), (0.18, 0.1), (0.12, 0.36), (0.12, 0.64), (0.18, 0.9), (0.38, 0.5), (0.52, 0.3),
              (0.52, 0.7), (0.82, 0.12), (0.92, 0.5), (0.82, 0.88)],
    "4-2-3-1": [(0.0, 0.5), (0.18, 0.1), (0.12, 0.36), (0.12, 0.64), (0.18, 0.9), (0.38, 0.38), (0.38, 0.62),
                (0.72, 0.14), (0.7, 0.5), (0.72, 0.86), (0.92, 0.5)],
    "4-4-2": [(0.0, 0.5), (0.16, 0.1), (0.12, 0.36), (0.12, 0.64), (0.16, 0.9), (0.5, 0.1), (0.44, 0.38),
              (0.44, 0.62), (0.5, 0.9), (0.88, 0.38), (0.88, 0.62)],
    "5-3-2": [(0.0, 0.5), (0.22, 0.06), (0.1, 0.3), (0.08, 0.5), (0.1, 0.7), (0.22, 0.94), (0.46, 0.28),
              (0.4, 0.5), (0.46, 0.72), (0.86, 0.38), (0.86, 0.62)],
}
