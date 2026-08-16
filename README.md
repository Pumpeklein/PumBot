# PumBot

PumBot ist ein Discord-Bot für Community- und Server-Management. Der Bot spricht direkt mit der MySQL-Datenbank; die Admin-Oberfläche ist seit August 2026 ein eigener Dienst (PumpeBot_Next) und läuft nicht mehr in diesem Prozess.

Der aktuelle Stand des Projekts ist kein reiner Chat-Bot, sondern ein kleines Gesamtsystem:

- Der Bot führt Slash-Commands, Event-Handler und Hintergrundjobs aus.
- Konfiguration, Tickets, Feature-Daten und Rollenrechte liegen in der MySQL-Datenbank, die sich Bot und Panel teilen.
- Beide Komponenten teilen sich dieselbe MySQL/MariaDB-Datenbank und kommunizieren zusätzlich über eine interne HTTP-API.

## Gesamtkonzept

Die Architektur besteht aus drei Schichten:

1. Discord-Bot

- Einstieg über [Bot.py](./Bot.py) und die eigentliche Laufzeit in [src/pumbot/bot.py](./src/pumbot/bot.py).
- Startet alle Command-Cogs, registriert persistente Views für Ticket-Buttons und synchronisiert Slash-Commands.
- Nutzt `discord.py`, Message-/Member-/Reaction-Events sowie einzelne `tasks.loop`-Jobs.

3. Datenhaltung

- MySQL/MariaDB-Datenbank, konfiguriert über `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- Schema in der PumpeBot_Next-Migration
- Zugriff über [src/pumbot/storage/db.py](./src/pumbot/storage/db.py)

Der Bot arbeitet fachlich gegen die interne API in [src/pumbot/services/api_client.py](./src/pumbot/services/api_client.py), statt direkt in die Datenbank zu schreiben. Dadurch bleibt die Datenlogik an einer Stelle gebündelt.

## Laufzeitmodell

Beim Start passiert im Wesentlichen Folgendes:

- `.env` wird geladen.
- Der Discord-Bot wird initialisiert.
- Der Bot lädt alle Cogs aus `src/pumbot/commands`.
- Der Bot spricht die Flask-API über `API_BASE_URL` und `LOG_API_KEY` an.

Das bedeutet: Bot und Panel gehören logisch zusammen und sind auf einen gemeinsamen Betrieb ausgelegt.

## Hauptfunktionen des Bots

### Ticketsystem

- Ticket-Panel mit Buttons für verschiedene Anfragearten
- Ticket-Erstellung in Discord-Kanälen
- Speicherung von Ticket-Metadaten im Web-Backend
- Mitschreiben von Ticket-Nachrichten in die Datenbank
- Ticket-Schließen per Slash-Command, Button oder Web-Panel
- Archivierung inklusive Transcript-HTML und optionalem externem Transcript-Link
- Web-Ansicht für Ticketverlauf, Logeinträge und Antworten aus dem Panel
- Unterstützung für Twitch-bezogene Tickets mit Validierung des Twitch-Namens

Wichtige Dateien:

- [src/pumbot/commands/TicketSystemCommand.py](./src/pumbot/commands/TicketSystemCommand.py)
- [web_logs/templates/tickets.html](./web_logs/templates/tickets.html)
- [web_logs/templates/ticket_detail.html](./web_logs/templates/ticket_detail.html)

### Selfroles

Rollenvergabe läuft über Buttons und Auswahlmenüs, nicht mehr über Reaktionen.

- Ein fester Self-Role Channel wird per Command oder Web-Panel gesetzt
  (Config-Keys `selfrole_channel_id` und `selfrole_message_id`)
- **Eine** Nachricht ohne Embed für alle Kategorien: pro Kategorie eine fette
  Überschrift und darunter die Rollen als Code-Chips
  (`⛏️ \`Minecraft\` · 🔫 \`Call of Duty\``). Darunter eine Button-Reihe mit
  einem Button je Kategorie, beschriftet mit deren Namen und Emoji
- Passt eine Kategorie nicht ins 2000-Zeichen-Limit, wird der Rest zu `+N`
  gekürzt – automatisch und nur so weit wie nötig
- Der Button öffnet eine nur für den Nutzer sichtbare Auswahl: Mehrfachauswahl
  bei Limit 0, Einzelauswahl bei Limit 1, dazu ein „Alle entfernen“-Button
- Die getroffene Auswahl ist der neue Endzustand; abgewählte Rollen werden
  entfernt, das Limit wird serverseitig erzwungen
- Emoji-Kaskade: Rollen-Icon → Emoji im Rollennamen → Server-Emoji mit passendem
  Namen (`Valorant` → `:valorant:`) → Stichwortliste in
  [selfroleEmojis.py](./src/pumbot/commands/selfroleEmojis.py) (Länder, Farben,
  Geschlecht, Alter, Spiele, Plattformen, Pings, Interessen) → Emoji der
  Kategorie
- Kategorien bekommen ihr Emoji ebenfalls automatisch, wenn im Titel keins steht
  (`Land` → 🌍, `Info` → ℹ️). Es erscheint in der Überschrift und auf dem Button
- Discord prüft Emojis in Buttons und Select-Menüs gegen eine ältere Liste als
  im Picker und lehnt neuere mit `50035 Invalid emoji` ab (z. B. ⚧️, U+26A7).
  Die Stichwortliste hält sich deshalb an Emoji ≤ 12.0; lehnt Discord trotzdem
  eins ab, geht die Nachricht ohne Button-Icons raus statt gar nicht, und
  `/selfroles deploy` meldet es
- Die Rollen einer Kategorie stehen in der Reihenfolge der Discord-Rollen-
  übersicht (höchste Rolle zuerst). Sammel-Rollen wie „Andere Länder",
  „Sonstige" oder „Keine Angabe" rutschen immer ans Ende
- Emojis lassen sich überschreiben – direkt beim `create` hinter der Rolle oder
  später per `/selfroles emoji`. Gesetzte Emojis überleben jeden Deploy, außer
  bei `deploy neu_mappen:True`
- Die Nachricht aktualisiert sich selbst: beim Bot-Start, bei Rollen-Umbenennung
  oder -Löschung und nach jeder Änderung an einer Kategorie
- Buttons überleben Neustarts, weil die Panel-ID in der `custom_id` steht
- Da sich alle Kategorien eine Nachricht teilen, dient `selfrole_panels.message_id`
  nur noch als eindeutiger Schlüssel; die echte Nachricht steht in `guild_config`

Commands (`/selfroles`):

| Command | Zweck |
| --- | --- |
| `channel <kanal>` | Legt den Self-Role Channel fest |
| `create <titel> <limit> <rollen>` | Neue Kategorie; je Rolle optional ein Emoji dahinter |
| `edit <kategorie> <aktion> <rolle>` | Rolle hinzufügen oder entfernen |
| `emoji <kategorie> <rolle> <emoji>` | Emoji setzen, `-` für das Kategorie-Emoji |
| `limit <kategorie> <limit>` | Auswahl-Limit ändern |
| `rename <kategorie> <titel>` | Kategorie umbenennen |
| `delete <kategorie>` | Kategorie löschen |
| `deploy [neu_senden] [neu_mappen]` | Nachricht erzeugen/aktualisieren |
| `list` | Übersicht aller Kategorien |

Wichtige Dateien:

- [src/pumbot/commands/selfrolesCommand.py](./src/pumbot/commands/selfrolesCommand.py)
- [src/pumbot/storage/db.py](./src/pumbot/storage/db.py)

### Geburtstage

- Nutzer können Geburtstage speichern und entfernen
- Staff kann Geburtstage für andere setzen
- Hintergrundjob prüft regelmäßig anstehende Geburtstage
- Gratulationen und Geburtstagsdaten werden zentral gespeichert
- Web-Panel zeigt alle Geburtstage und den konfigurierten Geburtstags-Channel

Wichtige Dateien:

- [src/pumbot/commands/birthdayCommand.py](./src/pumbot/commands/birthdayCommand.py)
- [web_logs/templates/birthdays.html](./web_logs/templates/birthdays.html)

### Counting

- Konfigurierbarer Zähl-Channel
- Validierung der Zählregeln direkt über `on_message`
- Speicherung von aktuellem Stand, Highscore und User-Statistiken
- Leaderboard im Bot und im Web-Panel

Wichtige Dateien:

- [src/pumbot/commands/countingCommand.py](./src/pumbot/commands/countingCommand.py)
- [web_logs/templates/counting.html](./web_logs/templates/counting.html)

### Verwarnungen und Moderation

- Nutzerprofil-Anzeige
- Verwarnungen setzen, auflisten und löschen
- Ban- und Timeout-Kommandos
- Web-Panel für Verwarnungsübersicht

Wichtige Dateien:

- [src/pumbot/commands/userManagementCommand.py](./src/pumbot/commands/userManagementCommand.py)
- [web_logs/templates/warnings.html](./web_logs/templates/warnings.html)

### Nachrichten- und Kanaltools

- Nachrichten in Menge löschen
- Nachrichten eines bestimmten Users löschen
- Logging für relevante Serverereignisse

Wichtige Dateien:

- [src/pumbot/commands/deleteCommand.py](./src/pumbot/commands/deleteCommand.py)
- [src/pumbot/commands/logsCommand.py](./src/pumbot/commands/logsCommand.py)

### Auto Publisher

- Verwaltung von Channels, in denen neue Inhalte automatisch veröffentlicht werden
- Speicherung der Ziel-Channels im Backend

Wichtige Dateien:

- [src/pumbot/commands/autoPublisherCommand.py](./src/pumbot/commands/autoPublisherCommand.py)

### Server-Stats

- Automatisches Einrichten und Aktualisieren von Statistik-Channels
- Typische Werte: Mitglieder, Bots, Channels, Rollen, Gesamtzahl
- Speicherung der Stat-Konfiguration im Backend

Wichtige Dateien:

- [src/pumbot/commands/serverStatsCommand.py](./src/pumbot/commands/serverStatsCommand.py)
- [web_logs/templates/server_stats.html](./web_logs/templates/server_stats.html)

### Weitere Module

- Willkommensnachrichten: [src/pumbot/commands/willkommenCommand.py](./src/pumbot/commands/willkommenCommand.py)
- Ankündigungen / Timer-Logik: [src/pumbot/commands/announcmentCommand.py](./src/pumbot/commands/announcmentCommand.py)
- Hilfe / FAQ: [src/pumbot/commands/helpCommand.py](./src/pumbot/commands/helpCommand.py)
- Serverinfos: [src/pumbot/commands/serverinfoCommand.py](./src/pumbot/commands/serverinfoCommand.py)

## Web-Panel

Das Web-Panel ist kein separates Frontend-Projekt, sondern serverseitig gerendertes Flask + Jinja mit Tailwind via CDN.

Wichtige Eigenschaften:

- Discord OAuth2 Login
- Rechteprüfung über Discord-Rollen
- interne Rollen-/Permission-Zuordnung in der Datenbank
- Ticket-Ansicht mit Nachrichtenverlauf und Web-Antwortfunktion
- Konfigurationsseiten für mehrere Bot-Features
- geschützte Transcript-Ansicht

### Aktuelle Hauptseiten

- `Tickets`
- `Rollen`
- `Counting`
- `Geburtstage`
- `Verwarnungen`
- `Log Channels`
- `Auto Publisher`
- `Server Stats`
- `Schließungsgründe`
- `Minecraft` → `Übersicht`, `Spieler`, `Strafen`, `Reports`

Die Navigation dafür liegt in [web_logs/templates/base.html](./web_logs/templates/base.html).

### Minecraft-Server (PumpeCraft)

Der Minecraft-Server nutzt eine **eigene Datenbank**, die von den PumpeCraft-Plugins
beschrieben wird. Das Panel liest diese Datenbank ausschließlich lesend und über eine
getrennte Verbindung (`MC_DB_*` in der `.env`) – die Panel-Datenbank bleibt unberührt.

Der gesamte Zugriff liegt in [web_logs/mc_db.py](./web_logs/mc_db.py).

| Seite | Route | Inhalt |
| --- | --- | --- |
| Übersicht | `/minecraft` | Kennzahlen (Spieler, Spielzeit, Tode, offene Reports, aktive Bans/Mutes), Top-Spielzeit, Top-Tode, letzte Strafen und Reports |
| Spieler | `/minecraft/spieler` | Durchsuch- und sortierbare Spielerliste mit Spielzeit (gesamt/aktiv/AFK), Toden, Verwarnungen, Strafen, Reports und Status |
| Spieler-Detail | `/minecraft/spieler/<uuid>` | Vollständiges Profil inkl. Spielzeit-Rang, aktivem Mute, Ban-Historie, Verwarnungen, Reports, Teamnotizen und AntiCheat-Auffälligkeiten |
| Skills | `/minecraft/skills` | Sieben Skill-Karten mit Spitzenreiter, Level und Punkteverteilung |
| Skill-Detail | `/minecraft/skills/<skill>` | Bestenliste des Skills plus die serverweit häufigsten Einträge |
| Strafen | `/minecraft/strafen` | Bans, Mutes und Verwarnungen als drei filterbare Tabellen mit gemeinsamer Suche |
| Reports | `/minecraft/reports` | Spielermeldungen, filterbar nach offen/geschlossen, mit Detaildialog und Abschlussaktion |

Die Skill-Farben spiegeln die In-Game-Farben des Plugins und sind auf der dunklen
Kartenfläche geprüft: benachbarte Karten halten einen CVD-Abstand von ΔE 13,0
(Ziel 8) und ΔE 19,3 unter Normalsicht (Floor 15) ein. Farbe trägt dabei nur
Flächen – Icon-Kachel, Meter und Punkt –, während Beschriftungen in Slate bzw.
Weiß bleiben, damit nichts allein über die Farbe erkennbar sein muss.

Gelesene Tabellen: `pc_playtime`, `pc_death_counts`, `pc_reports`, `pc_mutes`,
`pc_punishments`, `pc_warnings`, `pc_players`, `pc_skill_stats` und
`flyway_schema_history` (Schema-Version).

Aufgehobene Strafen (`/unban`, `/unmute` im Plugin) erscheinen als eigener Status
„Aufgehoben" und sind separat filterbar. Die dafür nötigen Spalten kommen mit
Migration V3 des Plugins; das Panel prüft einmalig, ob sie vorhanden sind, und
läuft auch gegen eine noch nicht migrierte Datenbank.

Hinweise zum Datenmodell:

- Zeitstempel der Plugins sind Epoch-Millisekunden und werden serverseitig nach
  Europe/Berlin formatiert.
- Spielernamen speichert das Plugin nur auf Moderations-Zeilen. Für Spieler ohne
  solchen Eintrag löst das Panel den Namen optional über die Mojang-API auf
  (`MC_NAME_LOOKUP`, In-Memory-Cache). Schlägt das fehl, wird die UUID angezeigt.
- Spielerköpfe kommen von einem externen Renderer (`MC_HEAD_BASE_URL`); leer lassen
  deaktiviert die Avatare.
- Ist die Minecraft-Datenbank nicht konfiguriert oder nicht erreichbar, liefern die
  Seiten einen Hinweis mit HTTP 503 statt eines Fehlers – der Rest des Panels bleibt
  nutzbar.

## Berechtigungskonzept

Das Web-Panel arbeitet mit einem zweistufigen Rechtekonzept:

1. Discord-Rollen

- Ein eingeloggter Benutzer wird über Discord OAuth identifiziert.
- Anschließend werden die Rollen des Benutzers im konfigurierten Guild-Kontext abgefragt.

2. App-Berechtigungen

- In der Tabelle `roles` werden Discord-Rollen internen Rechten zugeordnet.
- Die vollständige Liste der aktuell definierten Rechte liegt in `web_logs/db.py` als `ALL_PERMISSIONS`.


### Permission-Tabelle

| Permission | Bedeutung | Wirkung im aktuellen System |
| --- | --- | --- |
| `admin` | Vollzugriff auf alle App-Berechtigungen. | Überschreibt alle Einzelrechte. In `get_permissions_for_discord_roles()` wird bei `admin` automatisch auf alle bekannten Rechte erweitert. Sinnvoll für Owner, Admins oder leitende Staff-Rollen. |
| `tickets.view` | Darf Tickets grundsätzlich sehen. | Aktuell im Web-Panel noch nicht als separates Gate an die Ticket-Seiten gehängt. Das Recht ist im Modell vorhanden und sollte für reine Ticket-Lesezugriffe verwendet werden. |
| `tickets.reply` | Darf in Tickets antworten. | Steuert im Web-Panel die Antwortfunktion auf der Ticket-Detailseite sowie den POST auf `/tickets/<ticket_id>/reply`. |
| `tickets.close` | Darf Tickets schließen. | Steuert im Web-Panel die Schließen-Aktion auf der Ticket-Detailseite sowie den POST auf `/tickets/<ticket_id>/close`. |
| `users.view` | Darf Nutzerdaten bzw. Moderationsdaten lesen. | Aktuell als vorbereitetes Recht im Modell vorhanden, im Web-Panel aber noch nicht separat verdrahtet. Kann künftig für Profil- oder Moderationsübersichten genutzt werden. |
| `users.warn` | Darf Verwarnungen sehen und verwalten. | Schaltet die Verwarnungsseite in der Navigation frei und schützt die Routen für Warnungsübersicht und Löschen von Warnungen. |
| `users.ban` | Darf Bann-bezogene Moderationsfunktionen nutzen. | Im Rechtemodell vorhanden und passend für Moderations-Workflows im Bot gedacht. Im Web-Panel derzeit noch nicht separat verwendet. |
| `users.timeout` | Darf Timeouts verhängen oder verwalten. | Ebenfalls im Rechtemodell vorhanden; vor allem für Moderations-Features des Bots relevant. Im Web-Panel derzeit noch nicht separat genutzt. |
| `roles.manage` | Darf Rollen-/Rechtezuordnungen im Panel verwalten. | Schaltet die Rollen-Seite frei und schützt Create-, Update- und Delete-Routen für App-Rollen. |
| `config.manage` | Darf serverweite Feature-Konfigurationen ändern. | Das zentrale Konfigurationsrecht für Counting, Geburtstage, Log-Channels, Auto Publisher, Server Stats und Schließungsgründe. Blendet mehrere Seiten im Panel ein und schützt deren Änderungsrouten. |
| `logs.view` | Darf Logs lesen. | Aktuell als vorbereitetes Recht im Modell vorhanden, aber noch nicht als eigenes Lese-Gate im Web-Panel genutzt. |
| `logs.manage` | Darf Log-Konfigurationen oder Log-bezogene Verwaltungsaktionen durchführen. | Ebenfalls vorbereitet. Derzeit werden die Log-Channel-Seiten über `config.manage` geschützt, nicht über `logs.manage`. |
| `minecraft.view` | Voller Lesezugriff auf die Minecraft-Kategorie. | Schaltet alle Minecraft-Seiten frei (Übersicht, Spieler, Strafen, Reports) und schützt die zugehörigen `/panel-api/minecraft/*`-Endpunkte. |
| `minecraft.players.view` | Darf nur Spieler und Statistiken sehen. | Schaltet Übersicht, Spielerliste und Spieler-Detail frei. Strafen und Reports bleiben gesperrt – auch die Moderationsblöcke auf der Detailseite. |
| `minecraft.moderation.view` | Darf nur Strafen und Reports sehen. | Schaltet Übersicht, Strafen-Seite und Reports-Seite frei. Die Spielerliste bleibt gesperrt. |

### Praktische Zuordnung

Ein pragmatisches Setup für Rollen könnte so aussehen:

| Discord-Rolle | Empfohlene Permissions |
| --- | --- |
| Server-Admin | `admin` |
| Support-Team | `tickets.view`, `tickets.reply`, `tickets.close` |
| Moderation | `users.warn`, optional `users.ban`, `users.timeout` |
| Konfig-Team | `config.manage`, optional `roles.manage` |
| Minecraft-Team | `minecraft.view` bzw. nur `minecraft.moderation.view` für reine MC-Moderation |
| Audit / Einsicht | später z. B. `tickets.view`, `logs.view`, `users.view` ohne Schreibrechte |

### Wichtig für die Weiterentwicklung

- Nicht jedes definierte Recht ist schon vollständig an alle Seiten oder Bot-Kommandos angebunden.
- Einige Rechte sind bereits produktiv im Panel aktiv: `admin`, `tickets.reply`, `tickets.close`, `users.warn`, `roles.manage`, `config.manage`.
- Andere Rechte sind derzeit vor allem Teil des Berechtigungsmodells und eignen sich als Grundlage für eine feinere Trennung in späteren Ausbaustufen: `tickets.view`, `users.view`, `users.ban`, `users.timeout`, `logs.view`, `logs.manage`.

## Interne API

Die Flask-App stellt eine interne JSON-API bereit, die primär vom Bot genutzt wird.

Abgedeckte Bereiche:

- Guild-Konfiguration
- Geburtstage
- Verwarnungen
- Counting
- Auto Publisher
- Selfroles
- Server Stats
- Log-Channels
- Twitch-Konfiguration
- Tickets
- Ticket-Nachrichten
- Ticket-Logs
- Rollen
- Schließungsgründe

Der Zugriff ist über `LOG_API_KEY` abgesichert.

## Datenfluss zwischen Bot und Panel

Typischer Ablauf am Beispiel Tickets:

- Ein User erstellt in Discord ein Ticket.
- Der Bot erstellt Channel, Metadaten und erste Logeinträge.
- Der Bot sendet Ticketdaten per HTTP an die Flask-API.
- Die API schreibt in MySQL/MariaDB.
- Das Web-Panel liest dieselben Daten aus und stellt sie dar.
- Antworten aus dem Web-Panel können wieder an Discord zurückgesendet werden.

Das gleiche Muster wird auch für Counting, Geburtstage, Warnungen, Selfroles und Stats verwendet.

## Projektstruktur

```text
PumBot/
├─ Bot.py
├─ README.md
├─ .env.example
├─ src/
│  └─ pumbot/
│     ├─ bot.py
│     ├─ config.py
│     ├─ commands/
│     └─ services/
└─ web_logs/
   ├─ app.py
   ├─ auth.py
   ├─ config.py
   ├─ db.py
   ├─ mc_db.py
   ├─ models_mysql.sql
   ├─ templates/
   ├─ static/
   └─ data/
```

## Voraussetzungen

- Python 3.11 oder neuer
- Discord-Bot-Anwendung im Discord Developer Portal
- aktivierte Intents für den Bot
- Discord OAuth2-Konfiguration für das Web-Panel
- optional: Twitch API Zugang für Twitch-Ticketprüfung

## Installation

1. Repository klonen

```bash
git clone <repo-url>
cd PumBot
```

2. Virtuelle Umgebung anlegen und aktivieren

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Linux / macOS:

```bash
source .venv/bin/activate
```

3. Abhängigkeiten installieren

Für den Bot und das Panel werden Python-Pakete benötigt. Falls du die Dependencies in einer zentralen `requirements.txt` pflegst, installiere diese. Zusätzlich enthält das Web-Panel aktuell eine eigene Datei unter [web_logs/requirements.txt](./web_logs/requirements.txt).

Beispiel:

```bash
pip install -r web_logs/requirements.txt
```

Wenn du eine Root-`requirements.txt` ergänzst, sollte die `README` entsprechend darauf angepasst werden.

## Konfiguration

Die wichtigsten Variablen stehen in [.env.example](./.env.example).

### Pflichtvariablen

- `DISCORD_TOKEN`
- `DISCORD_GUILD_ID`
- `FLASK_SECRET_KEY`
- `SESSION_LIFETIME_DAYS` (dauerhafter Web-Login, Standard: 30 Tage)
- `LOG_API_KEY`
- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `DISCORD_REDIRECT_URI`

### Typische Web-Panel-Konfiguration

- `BASE_URL`
- `PORT`
- `DEFAULT_ADMIN_ROLE_ID`

### Bot/API-Kommunikation

- `API_BASE_URL`
- `LOG_API_KEY`

### Twitch optional

- `TWITCH_CLIENT_ID`
- `TWITCH_AUTH_TOKEN`
- `TWITCH_USER_LOGIN`

### Minecraft-Datenbank optional

Eigene, getrennte Datenbank des Minecraft-Servers. Bleiben `MC_DB_NAME` und
`MC_DB_USER` leer, zeigen die Minecraft-Seiten einen Hinweis statt Daten.

- `MC_DB_HOST`, `MC_DB_PORT`, `MC_DB_NAME`, `MC_DB_USER`, `MC_DB_PASSWORD`, `MC_DB_CHARSET`
- `MC_SERVER_NAME`, `MC_SERVER_ADDRESS` – Anzeigename und Adresse im Panel
- `MC_HEAD_BASE_URL` – Renderer für Spielerköpfe, leer deaktiviert Avatare
- `MC_NAME_LOOKUP` – `0` deaktiviert die Mojang-Namensauflösung
- `MC_NAME_LOOKUP_TIMEOUT`, `MC_NAME_LOOKUP_MAX` – Timeout und maximale Lookups pro Anfrage

## Starten

Der normale Start erfolgt über:

```bash
python Bot.py
```

Dann gilt standardmäßig:

- Discord-Bot verbindet sich mit Discord
- Web-Panel läuft lokal auf `http://127.0.0.1:3000`

## Entwicklungshinweise

- Der Bot ist auf eine konkrete Haupt-Guild ausgelegt.
- Slash-Commands werden beim Start synchronisiert.
- Viele Features setzen voraus, dass Rollen, Channel-IDs und OAuth korrekt konfiguriert sind.
- Die Datenbank wird beim Start automatisch initialisiert bzw. bei älteren Schemata teilweise migriert.

## Bekannte Besonderheiten des aktuellen Stands

- Einige Dateien im Projekt enthalten noch ältere Encoding-/Textartefakte in Kommentaren oder Templates.
- Das Web-Panel verwendet serverseitiges Rendering und kein SPA-Frontend.
- Bot und Web-Panel laufen zusammen in einem Prozess, aber getrennten Threads / Laufzeitkontexten.
- Die interne API ist für den Bot gedacht, nicht als öffentliche externe API.

## Kurzfazit

PumBot ist aktuell ein kombiniertes Moderations-, Support- und Verwaltungswerkzeug für einen Discord-Server. Der Kern des Projekts ist nicht nur die Command-Sammlung, sondern das Zusammenspiel aus:

- Discord-Bot
- internem API-Layer
- MySQL/MariaDB-Datenmodell
- Web-Panel für Betrieb, Einsicht und Konfiguration

Wenn du das Projekt weiterentwickelst, ist diese Trennung der wichtigste Architekturgedanke: Discord erledigt Interaktion, die Flask-App bündelt Daten und Administration.
