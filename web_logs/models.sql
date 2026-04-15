-- users (Staff)
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('owner','discord_mod','twitch_mod')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- tickets archive (Ticket + Transcript)
CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY,
  guild_id TEXT,
  channel_id TEXT,
  creator_user_id TEXT,  -- Discord User ID vom Ersteller
  status TEXT,           -- open/closed
  subject TEXT,
  closed_at TEXT,
  transcript_path TEXT,  -- Pfad zur HTML Datei in data/transcripts/
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- optional: logs (für einzelne Log-Events)
CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL,
  level TEXT,
  message TEXT,
  data_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_logs_ticket_id ON logs(ticket_id);
CREATE INDEX IF NOT EXISTS idx_tickets_creator ON tickets(creator_user_id);
