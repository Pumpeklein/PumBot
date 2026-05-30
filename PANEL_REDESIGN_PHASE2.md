# Web-Panel Phase 5 – Komplettüberarbeitung aller Seiten

Diese Phase folgt auf das Rollen-Redesign und überarbeitet **alle übrigen Tabs/Seiten**
des Web-Panels mit Fokus auf Informationsdichte, sinnvolle Visualisierung statt roher
Daten und einheitlichem Design.

## Globale Helfer

### `web_logs/templates/_macros.html`
- **`stat_tile(label, value, accent, sub, icon)`** – Ersetzt das alte schlichte `stat()` durch eine farbige Kachel mit
  Akzentlinie, Untertext und optionalem Icon. Akzente: `cyan`, `emerald`, `amber`, `red`, `violet`, `slate`.
- **`id_chip(value, label)`** – Mini-Pille für Discord-IDs mit One-Click-Copy + Toast.
- **`section_heading(title, description, action)`** – Einheitliche Card-Überschrift.

### `web_logs/templates/base.html`
- **Globaler Copy-Handler** für `[data-copy]` / `[data-copy-user-id]` → Clipboard + Toast.
- **Toast-System** (`window.pumbotToast(msg, variant)`), fixed bottom-right, automatisch ausgeblendet.
- Sidebar-Footer aufgeräumt („Übersichts-Panel yeah" → „Admin Panel").

### `web_logs/static/paginated-table.js`
Zwei neue Spalten-Typen:
- **`percentage`** – Akkurate Live-Quote aus `numeratorKey` / `denominatorKey` mit farbiger Mini-Bar (≥90% emerald, ≥70% cyan, ≥50% amber, sonst rot).
- **`badges`** – Array `[{label, color}]` rendert farbige Rollen-Pills mit `+N`-Overflow.

## Backend-Erweiterungen

### `web_logs/db.py`
- `count_birthdays_in_month(guild_id, month)`
- `get_upcoming_birthdays(guild_id, days=30, limit=10)` mit Jahreswechsel-Logik und `days_until`.
- `_ticket_filter_sql`, `list_tickets`, `count_tickets` akzeptieren jetzt `status="open"|"closed"`.

### `web_logs/app.py`
- `birthdays_page` liefert nun `today_count`, `today_list`, `month_count`, `upcoming` (mit display names).
- `tickets_page` liefert `open_count`, `closed_count` und akzeptiert `?status=`-Filter.
- `panel_api_tickets` filtert nach `status`.
- `panel_api_users` ergänzt jede Row um `discord_roles_badges`, `web_roles_badges` (mit echten Hex-Farben aus Discord), `presence_label`.

## Redesignte Seiten

| Seite | Highlights |
|---|---|
| **users.html** | 4 stat-tiles (Aktiv/Verlassen/Gesamt/Guild) + Status-Quick-Filter-Pills + Live-Suche + farbige Rollen-Badges (Web + Discord) statt Komma-Strings + Presence-Spalte. |
| **tickets.html** | Open/Closed Stat-Tiles + Quick-Filter-Pills + Live-Suche + extra „Erstellt"-Spalte + Ticket-IDs als Mono-Font + Status-Badge mit Variants. |
| **ticket_detail.html** | Doppelte Übersicht eliminiert. Neuer Hero-Stat-Bar, kompakter Meta-Strip mit ID-Chips, separate Karten für Close-Reason und Twitch. |
| **warnings.html** | ID-Spalte (cryptisch) entfernt – Datum jetzt führend. Reason ist nun primäre Spalte, breit, mit Fallback. Stat-Tiles + Filter-Banner. |
| **counting.html** | Hero mit 4 Stat-Tiles (Stand/Highscore/Letzter User/Channel). Fortschrittsbalken Stand→Highscore. Settings + Reset als getrennte farbige Cards. Neue **Quote-Spalte** (Richtig/Fehler %) mit Live-Bar. |
| **birthdays.html** | „Heute"-Card (grün) und „Demnächst 30 Tage"-Card (cyan) nebeneinander, klickbar zu User-Profil. Stat-Tiles inkl. Monatszahl. Listen-Nachrichten in `<details>` ausklappbar. Saubere Form-Cards. |
| **discord_logs.html** | stat_tile-basierter Hero. Log-Type Badges mit Variants. Log-Channels Liste mit ID-Chips. Live-Indikator. Tippbarer Auto-Refresh-Hinweis. |
| **log_channels.html** | Pro Log-Typ Icon + Beschreibung + Status-Badge. Inline-Edit-Form pro Karte. Stat-Tile-Hero zeigt fehlende Konfigs. |
| **server_stats.html** | Pro Statistik-Typ Icon + Beschreibung + Aktiv-Badge. Gemeinsames Save-Form. Hero mit Konfig-Stand. |
| **auto_publisher.html** | Channel-Cards mit Icon + Aktiv-Badge + Copy-ID + Add-Form als Sidebar. |
| **close_reasons.html** | Inline-Edit pro Grund (Reihenfolge + Label + Speichern + Löschen). Add-Form als Sidebar-Card. Stat-Tile-Header. |
| **stats.html** | Hero-Stat-Tiles statt schlichter `stat()`. Guild-ID als Copy-Chip. |
| **roles.html (Server-Tab)** | Server-Rollen-Tabelle: Rolle als farbig getönte Pill (Discord-Farbe), Status-Badge mit Indicator-Dot, ID als Copy-Chip. Header mit Live-Counter (verwaltbar/gesamt). |
| **user_detail.html** | Hero auf stat_tile umgestellt (mit Sub-Texten und Akzentfarben). |
| **base.html / login.html** | Branding aufgeräumt, globale Toast-/Copy-Infrastruktur. |

## Design-System (Status)

- **Hintergrund**: `#0a0f1a` (body), `#0d1320` (Cards).
- **Borders**: `border-white/[0.06]`.
- **Stat-Tiles**: Akzentfarbe als linker/oberer Border + sanfter Gradient.
- **Badges**: Variants `success` (emerald), `warning` (amber), `danger` (red), `default` (slate).
- **Pills für Filter**: `border-cyan-500/40 bg-cyan-500/15 text-cyan-200` (aktiv) vs. `border-white/10 bg-white/5 text-slate-400` (inaktiv).
- **IDs überall kopierbar** via `data-copy` Attribut.

## Was bewusst NICHT geändert wurde

- `login.html` – bereits sauber und minimal.
- `transcript.html` – nicht im Scope (separate, fertige Ticket-Transcript-Anzeige).
- Chart-Logik in `stats.html` – funktioniert, nur Header aufgewertet.
- Discord-API-abhängige Rollen-Member-Counts pro Server-Rolle – würde extra Bot-Calls erfordern.

## Testempfehlung

1. Alle Tab-Seiten kurz öffnen – jede Stat-Zeile sollte die neuen farbigen Kacheln zeigen.
2. Auf **Users** und **Tickets** die Quick-Filter-Pills durchklicken (Alle/Aktiv/…).
3. Auf **Counting** eine paar User mit Fehlern checken – die Quote-Spalte sollte farbcodiert sein.
4. Auf **Birthdays** prüfen ob „Heute" / „Demnächst" korrekt befüllt werden.
5. Auf **Log-Channels** und **Server-Stats** sehen ob die Icons & Beschreibungen pro Typ erscheinen.
6. Auf **Server-Rollen-Tab** in /roles testen ob die Rollen-Farben als getönte Pills dargestellt werden.
7. Auf einer beliebigen ID-Chip-Pille klicken → Toast „Kopiert: …" sollte erscheinen.
