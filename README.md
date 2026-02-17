# 🤖 PumBot

Kurzbeschreibung: Dieser Discord-Bot bietet ein umfassendes Server Management, z.B. Selfroles, Geburtstage, Tickets und Server-Tools.

## ✨ Features
- 🎭 Selfroles (Rollen selbst auswählen)
- 🎂 Geburtstags-System (Eintragen + Erinnerungen)
- 🎟️ Ticket-System (Support / Bewerbung / Beschwerden etc.)
- 📊 Server-Infos / Stats
- 🛠️ Moderation-Tools (optional)

## 🧩 Voraussetzungen
- Python 3.11+
- Discord Bot Token (Developer Portal)
- Intents aktiviert (z.B. Members, Message Content falls nötig)

## 🚀 Installation
```bash
git clone <repo-url>[requirements.txt](https://github.com/user-attachments/files/25353499/requirements.txt)

cd <repo-ordner>
python -m venv .venv      
# Windows: .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt

## Konfiguration (.env)
- DISCORD_TOKEN=dein_token_hier
- GUILD_ID=123456789012345678
# Optional:
# LOG_CHANNEL_ID=123...
# DATABASE_URL=...
