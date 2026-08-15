"""Datenzugriff des Bots: MySQL-Schicht und Konfiguration.

Bis August 2026 lag beides unter `web_logs/` und wurde vom mitlaufenden
Flask-Panel geteilt. Das Panel ist jetzt ein eigenständiger Next.js-Dienst,
deshalb gehört die Datenschicht zum Bot.
"""

from .config import Config, DEFAULT_ADMIN_ROLE_ID, DEFAULT_GUILD_ID, TRANSCRIPTS_DIR

__all__ = ["Config", "DEFAULT_ADMIN_ROLE_ID", "DEFAULT_GUILD_ID", "TRANSCRIPTS_DIR"]
