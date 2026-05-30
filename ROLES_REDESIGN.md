# Roles-Panel Redesign & Verbesserungen

Zusammenfassung aller Änderungen am Web-Panel rund um Rollen und User-Profile.

## Ziel

Die bisherige Roles-Seite war optisch und funktional schwach:
- Sidebar-Formular + Tabelle wirkten gequetscht
- Permissions waren nur als rohe Keys (`tickets.view`) sichtbar
- Modal war ein riesiger Block ohne Struktur
- Es gab **keine Möglichkeit zu sehen, wer welche Web-Rolle hat**

## Neue Roles-Seite (`web_logs/templates/roles.html`)

Komplett neu aufgebaut. Highlights:

### Übersicht
- **Stat-Header** oben: `Web Rollen`, `Mitglieder mit Web Rolle`, `Vergebene Rechte`, `Server Rollen`
- **Karten-Grid statt Tabelle**: jede Web-Rolle ist eine Card mit
  - Farbpunkt der Discord-Rolle, Anzeigename, verknüpfter Discord-Rollenname
  - Mini-Stats: Mitgliederanzahl + Rechteanzahl
  - Vorschau der ersten 4 Rechte (mit lesbaren Labels statt Keys)
  - "Admin"-Marker, wenn die Rolle Vollzugriff hat
  - Bearbeiten-Button öffnet Modal
- **Suchfeld** filtert Karten live
- **"Neue Web Rolle"-Button** oben rechts (statt Sidebar) → öffnet eigenes Create-Modal

### Create-Modal (neu)
- Eigenes Modal statt Sidebar – mehr Platz, klarer Fokus
- Auto-Fill des Anzeigenamens aus der gewählten Discord-Rolle
- Vollständiger Permission-Picker

### Edit-Modal (komplett überarbeitet)
- Header mit Farbpunkt, Name, Discord-ID
- **Interne Tabs:**
  - **Rechte & Name** – Anzeigename + Permission-Picker
  - **Mitglieder** – Live-Liste der User mit dieser Discord-Rolle (Lazy-Load via API)
- Footer pro Tab (Speichern bzw. Löschen)
- Schließen via X, Klick außerhalb, oder `Esc`

### Permission-Picker (wiederverwendbar als Macro)
- Live-Suche über Rechte
- Pro Gruppe: einklappbar (`<details>`), Counter `x/y`, "alle"-Toggle
- Globale Buttons: `Alle wählen`, `Alles leeren`
- Live-Counter "X ausgewählt"
- **Admin-Recht** als hervorgehobener gelber Block oben – schaltet bei Aktivierung alle anderen Rechte automatisch auf checked + disabled, mit klarer visueller Warnung
- Jedes Recht zeigt **lesbares Label + grauen Mono-Key** darunter

### Server-Rollen-Tab
- Suchfeld zum Filtern
- Sonst Struktur erhalten, leicht polished

## User-Detail-Seite (`web_logs/templates/user_detail.html`)

- **Web-Rollen jetzt direkt im Profil-Header** als cyan Badges sichtbar – nicht nur versteckt im Roles-Tab
- Roles-Tab: Web-Rollen-Box neu mit cyan Akzentrahmen, Admin-Pill und **lesbaren Permission-Labels** statt rohen Keys

## Users-Übersicht

Die `Web Rollen`-Spalte bestand bereits – sie ist jetzt durch die Backend-Verknüpfung sinnvoll nutzbar.

## Backend

### `web_logs/db.py`
- Neuer Lookup `PERMISSION_LABELS` + Helper `permission_label(perm)`
- `list_role_members(guild_id, discord_role_id)` – liest Member, die diese Discord-Rolle aus `guild_members.roles_json` tragen
- `count_role_members(...)` – nur Count, für die Card-Stats

### `web_logs/app.py`
- Neue Imports: `PERMISSION_LABELS`, `permission_label`, `list_role_members`, `count_role_members`, `get_role`
- Jinja-Filter `permission_label` + globale `PERMISSION_LABELS`
- `roles_page()` reichert jede Web-Rolle mit `member_count`, `discord_role` und `color` an; berechnet Summen für die Stat-Header
- **Neuer API-Endpunkt** `GET /panel-api/roles/<role_id>/members` (mit `roles.manage`-Permission), liefert JSON für das Mitglieder-Tab

## Geänderte Dateien

- `web_logs/templates/roles.html` *(neu geschrieben)*
- `web_logs/templates/user_detail.html`
- `web_logs/db.py`
- `web_logs/app.py`

## Hinweise

- Mitglieder werden aus `guild_members.roles_json` gelesen (vom Bot-Sync gepflegt). Wenn ein User noch nie synchronisiert wurde, taucht er nicht in der Liste auf – das hat aber nichts mit dem Redesign zu tun.
- Die `LIKE`-Suche auf `roles_json` ist gegen ID-Überlapp abgesichert (matcht `"id": "<id>"` mit umschließenden Quotes).
- Beim Aktivieren des `admin`-Rechts werden im Picker alle anderen Checkboxes auf "checked & disabled" gesetzt; serverseitig macht `get_permissions_for_discord_roles` ohnehin `admin → set(ALL_PERMISSIONS)`, somit konsistent.
