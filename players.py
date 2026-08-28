"""Fixed group roster. Names cannot be added or edited in the app."""

FIXED_PLAYERS = [
    "לוי",
    "שירן",
    "אבירם",
    "יגאל",
    "עידן",
    "חן",
    "רועי",
    "אורייאן",
    "מושיקו",
]

# Nicknames / old spellings stored in existing enrollments.
NAME_ALIASES = {
    "עידו": "עידן",
}


def normalize_name(raw: str) -> tuple[str, str]:
    name = " ".join((raw or "").split())
    return name, name.casefold()


def canonical_player(raw: str) -> str | None:
    name, key = normalize_name(raw)
    alias = NAME_ALIASES.get(name) or NAME_ALIASES.get(key)
    if alias:
        name, key = normalize_name(alias)
    for player in FIXED_PLAYERS:
        if normalize_name(player)[1] == key:
            return player
    return None
