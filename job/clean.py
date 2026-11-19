"""Text cleaning, language codes, phase names, ability slots and server regions for the builds feed job."""
import re
import unicodedata

import config

_TAG = re.compile(r"</?[A-Za-z][^<>]*>")   # markup such as <b> or </font ...>; "a < b > c" is text
_CURLY = re.compile(r"\{[^{}]*\}")
_SPACE = re.compile(r"\s+")
_LEAD = re.compile(r"^[#\s]+")


def clean_text(s, limit):
    """Feed text as the card may show it: no <...> markup, no {...} dialog variables, no control characters, no leading '#' (a
    Panorama Label would localize it), single spaces, at most `limit` characters (cut with an ellipsis)."""
    if s is None:
        return ""
    # control and format characters first (a zero-width space must not hide a tag), then markup and {...} until nothing changes
    # (nested "<<b>b>" or "{{x}s:y}"), then every leading '#' and space
    s = "".join(" " if ch in "\t\n\r" else ch for ch in str(s) if ch in "\t\n\r" or unicodedata.category(ch) not in ("Cc", "Cf"))
    prev = None
    while prev != s:
        prev = s
        s = _CURLY.sub("", _TAG.sub("", s))
    s = _SPACE.sub(" ", s).strip()
    s = _LEAD.sub("", s)
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


# Valve's ELanguage order (the game's build language field), as two-letter codes; English is ""
_LANGS = ("", "de", "fr", "it", "ko", "es", "zh", "zh", "ru", "th", "ja", "pt", "pl", "da", "nl", "fi", "no", "sv", "hu", "cs", "ro",
          "tr", "pt", "bg", "el", "uk", "es", "vi", "id")


def lang_code(n):
    try:
        i = int(n)
    except (TypeError, ValueError):
        return ""
    return _LANGS[i] if 0 <= i < len(_LANGS) else ""


_TOKEN = re.compile(r"^#?citadel_herobuilds_(early|mid|late)game$", re.I)
_WORD = re.compile(r"[a-z]+")


def phase_of(name):
    """An author's category name as one of the card's phases (early, mid, late, situational), else its own cleaned label."""
    raw = "" if name is None else str(name).strip()
    m = _TOKEN.match(raw)
    if m:
        return m.group(1).lower()
    words = _WORD.findall(raw.lower())
    for w in words:
        if w.startswith("early") or w in ("lane", "laning", "start", "starting", "starter", "opener"):
            return "early"
    for w in words:
        if w.startswith("mid"):
            return "mid"
    for w in words:
        if w.startswith("late") or w in ("lux", "luxury", "end", "endgame"):
            return "late"
    for w in words:
        if w.startswith("situation") or w in ("flex", "optional", "counter", "counters"):
            return "situational"
    return clean_text(raw, config.LABEL_MAX) or "Items"


def ability_slots(changes, slot_of):
    """The card's 12 ability chips: the first 12 point spends (currency type 1, negative delta) whose ability is one of the hero's four
    signature abilities, as slot numbers 1-4 (slot_of: ability item id -> slot). Unlocks (type 2), refunds and unknown ids are skipped."""
    out = []
    for c in changes or ():
        if len(out) >= 12:
            break
        try:
            if int(c.get("currency_type")) != 1 or int(c.get("delta")) >= 0:
                continue
            slot = slot_of.get(int(c.get("ability_id")))
        except (TypeError, ValueError, AttributeError):
            continue
        if slot in (1, 2, 3, 4):
            out.append(slot)
    return out


# deadlock-api /v1/players/region gives the server region of a player's matches (e.g. "eu_north", "dpkt-frankfurt", "us_east");
# the card's chips are NA, EU, Asia, SA and OCE
_REGION_EXACT = {
    "asia": "asia", "south_america": "sa", "australia": "oce", "oceania": "oce",
}
_REGION_TOKENS = (
    ("na", ("canada", "toronto", "montreal", "mexico", "seattle", "chicago", "dallas", "atlanta", "virginia", "ashburn", "losangeles",
            "los_angeles", "new_york", "newyork", "miami", "denver")),
    ("eu", ("london", "helsinki", "poland", "warsaw", "spain", "madrid", "falkenstein", "frankfurt", "amsterdam", "paris", "stockholm",
            "vienna", "germany", "france", "sweden", "finland", "netherlands", "russia", "moscow", "turkey", "istanbul", "italy", "milan",
            "romania", "bucharest", "czech", "prague", "luxembourg", "europe", "nuremberg", "lisbon", "portugal")),
    ("asia", ("hong_kong", "hongkong", "japan", "tokyo", "singapore", "korea", "seoul", "china", "shanghai", "beijing", "taiwan", "india",
              "mumbai", "chennai", "dubai", "uae", "thailand", "bangkok", "philippines", "manila", "vietnam", "indonesia", "jakarta",
              "malaysia")),
    ("sa", ("argentina", "buenos", "brazil", "sao_paulo", "saopaulo", "chile", "santiago", "peru", "lima", "colombia", "bogota",
            "south_america")),
    ("oce", ("australia", "sydney", "melbourne", "perth", "new_zealand", "auckland", "oceania")),
)


def region_of(server_region):
    if not server_region:
        return None
    r = str(server_region).strip().lower()
    if r in _REGION_EXACT:
        return _REGION_EXACT[r]
    if r.startswith("us_") or r.startswith("na_"):
        return "na"
    if r.startswith("eu_"):
        return "eu"
    for chip, tokens in _REGION_TOKENS:
        for t in tokens:
            if t in r:
                return chip
    return None
