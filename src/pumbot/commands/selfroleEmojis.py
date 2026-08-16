"""Stichwort-Zuordnung für Self-Role Emojis.

Rollen wie „Rote Chatfarbe", „Männlich" oder „Nintendo Switch" haben weder ein
Rollen-Icon noch ein Emoji im Namen. Damit sie trotzdem ein passendes statt
eines beliebigen Emojis bekommen, wird der normalisierte Rollenname gegen diese
Liste geprüft – der erste Treffer, dessen Emoji im Panel noch frei ist, gewinnt.

Die Reihenfolge ist wichtig: spezifische Begriffe stehen vor allgemeinen, sonst
schnappt sich „auto" das Emoji von „Grand Theft Auto".
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Umlaute vor dem Strippen falten, sonst wird aus „Weiße" ein „weie".
UMLAUT_MAP = str.maketrans(
    {
        "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
        "á": "a", "à": "a", "â": "a", "å": "a",
        "é": "e", "è": "e", "ê": "e",
        "í": "i", "ì": "i", "î": "i",
        "ó": "o", "ò": "o", "ô": "o", "ø": "o",
        "ú": "u", "ù": "u", "û": "u",
        "ñ": "n", "ç": "c",
    }
)

_STRIP_RE = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    return _STRIP_RE.sub("", (text or "").lower().translate(UMLAUT_MAP))


KEYWORD_EMOJIS: List[Tuple[Tuple[str, ...], str]] = [
    # ── Geschlecht / Pronomen ──
    (("maennlich", "male", "boy", "junge", "erihm", "hehim"), "♂️"),
    (("weiblich", "female", "girl", "maedchen", "sieihr", "sheher"), "♀️"),
    (("divers", "nonbinaer", "nonbinary", "enby", "theythem"), "⚧️"),
    (("keineangabe", "geheim", "privat"), "🤐"),

    # ── Alter ──
    (("ueber18", "ab18", "18plus", "oderaelter", "volljaehrig", "erwachsen"), "🔞"),
    (("unter18", "unter16", "unter12", "minderjaehrig"), "🧒"),
    (("jahrealt", "jahre", "alter"), "🎂"),

    # ── Chatfarben / Farben ──
    (("weiss", "white"), "⚪"),
    (("schwarz", "black"), "⚫"),
    (("lila", "violett", "purple", "flieder"), "🟣"),
    (("pink", "rosa", "magenta"), "💗"),
    (("rot", "red"), "🔴"),
    (("orange",), "🟠"),
    (("gelb", "yellow", "gold"), "🟡"),
    (("gruen", "green", "mint", "limette"), "🟢"),
    (("blau", "blue", "navy"), "🔵"),
    (("tuerkis", "cyan", "aqua", "teal"), "💠"),
    (("beige", "braun", "brown", "sand"), "🟤"),
    (("grau", "gray", "grey", "silber"), "◾"),
    (("regenbogen", "rainbow", "bunt"), "🌈"),

    # ── Spiele (vor den allgemeinen Interessen!) ──
    (("minecraft",), "⛏️"),
    (("valorant",), "🎯"),
    (("callofduty", "warzone", "modernwarfare"), "🔫"),
    (("leagueoflegends", "lolgames"), "⚔️"),
    (("counterstrike", "csgo", "cs2"), "💣"),
    (("fortnite",), "🌪️"),
    (("grandtheftauto", "gta"), "🚙"),
    (("rocketleague",), "🚀"),
    (("apexlegends", "apex"), "🔺"),
    (("deadbydaylight", "dbd"), "🩸"),
    (("clashroyale",), "👑"),
    (("clashofclans", "clash"), "🏹"),
    (("amongus",), "🔪"),
    (("goosegooseduck", "goose"), "🦆"),
    (("farmingsimulator", "landwirtschaft", "farming"), "🚜"),
    (("pokemon",), "⚡"),
    (("roblox",), "🟥"),
    (("terraria",), "🌳"),
    (("stardew",), "🌱"),
    (("fallguys",), "🫘"),
    (("palworld",), "🐣"),
    (("brawlstars", "brawl"), "💥"),
    (("overwatch",), "🧡"),
    (("rainbowsix", "siege"), "🛡️"),
    (("worldofwarcraft", "wow"), "🐉"),
    (("thesims", "sims"), "🏠"),
    (("fifa", "eafc", "efootball"), "🥅"),
    (("forza", "needforspeed", "racing", "rennspiel"), "🏁"),
    (("rust",), "🔧"),
    (("phasmophobia", "horror"), "👻"),
    (("repo", "lethalcompany"), "📦"),

    # ── Plattformen / Konsolen ──
    (("playstation", "ps5", "ps4", "psn"), "🎮"),
    (("xbox",), "🟩"),
    (("nintendo", "switch"), "🔴"),
    (("steamdeck", "handheld"), "🕹️"),
    (("pclaptop", "laptop", "desktop", "computer"), "💻"),
    (("mobile", "handy", "smartphone", "tablet", "ipad", "android", "ios"), "📱"),
    (("vrheadset", "virtualreality", "quest"), "🥽"),

    # ── Benachrichtigungen / Pings ──
    (("liveping", "livebenachrichtigung", "live"), "🔴"),
    (("eventping", "event", "termin"), "📅"),
    (("updateping", "update", "changelog"), "📢"),
    (("videoping", "video", "youtube", "upload"), "📹"),
    (("twitch", "stream"), "💜"),
    (("ankuendigung", "announcement", "news", "neuigkeiten"), "📣"),
    (("giveaway", "gewinnspiel", "verlosung"), "🎁"),
    (("umfrage", "poll", "abstimmung"), "📊"),
    (("wartung", "status"), "🛠️"),
    (("alleping", "allepings", "everything"), "🔔"),

    # ── Interessen ──
    (("musik", "music", "spotify"), "🎵"),
    (("anime", "manga", "otaku"), "🌸"),
    (("filmeserien", "filme", "serien", "movie", "kino", "netflix"), "🎬"),
    (("programmier", "coding", "developer", "entwickl", "technik", "tech"), "🖥️"),
    (("fussball", "football", "soccer"), "⚽"),
    (("sport", "fitness", "gym"), "🏋️"),
    (("kunst", "zeichnen", "malen", "art"), "🎨"),
    (("kochen", "backen", "essen", "food"), "🍳"),
    (("lesen", "buecher", "buch", "book"), "📚"),
    (("reisen", "travel", "urlaub"), "✈️"),
    (("fotografie", "foto", "photo", "kamera"), "📷"),
    (("natur", "garten", "wandern"), "🌿"),
    (("tiere", "haustier", "hund", "katze", "pets"), "🐾"),
    (("auto", "cars", "tuning", "motorrad"), "🚗"),
    (("brettspiel", "boardgame", "karten"), "🎲"),
    (("wissenschaft", "science", "space", "weltraum"), "🔭"),
    (("politik", "debatte"), "🗳️"),
    (("memes", "meme", "humor"), "😂"),

    # ── Sonstiges ──
    (("deutsch", "german", "deutschland"), "🇩🇪"),
    (("english", "englisch"), "🇬🇧"),
    (("booster", "supporter", "spender"), "💎"),
    (("gaming", "zocken", "spiele"), "🎮"),
]
