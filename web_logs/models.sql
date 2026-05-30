-- ══════════════════════════════════════════════════════════════
-- PumBot Database Schema
-- Designed for easy migration to MariaDB later
-- ══════════════════════════════════════════════════════════════

-- ── Users (Discord OAuth2) ──
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  discord_id TEXT UNIQUE NOT NULL,
  discord_username TEXT NOT NULL,
  discord_avatar TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_login TEXT
);

CREATE TABLE IF NOT EXISTS guild_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  username TEXT NOT NULL,
  global_name TEXT,
  display_name TEXT NOT NULL,
  discriminator TEXT,
  avatar_url TEXT,
  is_bot INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  presence_status TEXT,
  activity_name TEXT,
  activity_type TEXT,
  status_updated_at TEXT,
  joined_at TEXT,
  left_at TEXT,
  first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS guild_member_name_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  old_username TEXT,
  old_global_name TEXT,
  old_display_name TEXT,
  new_username TEXT,
  new_global_name TEXT,
  new_display_name TEXT,
  changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS guild_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  channel_name TEXT,
  message_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  content TEXT,
  attachment_count INTEGER NOT NULL DEFAULT 0,
  jump_url TEXT,
  created_at TEXT NOT NULL,
  edited_at TEXT,
  deleted_at TEXT,
  synced_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(guild_id, channel_id, message_id)
);

-- ── Roles & Permissions ──
CREATE TABLE IF NOT EXISTS roles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  discord_role_id TEXT NOT NULL,
  role_name TEXT NOT NULL,
  permissions TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(guild_id, discord_role_id)
);

-- ── Guild Config (key-value store per guild) ──
CREATE TABLE IF NOT EXISTS guild_config (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  config_key TEXT NOT NULL,
  config_value TEXT NOT NULL DEFAULT '',
  UNIQUE(guild_id, config_key)
);

-- ── Birthdays ──
CREATE TABLE IF NOT EXISTS birthdays (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  day INTEGER NOT NULL,
  month INTEGER NOT NULL,
  year INTEGER,
  last_congrats TEXT,
  UNIQUE(guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS bot_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  message_type TEXT NOT NULL,
  message_id TEXT NOT NULL,
  channel_id TEXT,
  meta_key TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(guild_id, message_type, message_id)
);

-- ── Warnings ──
CREATE TABLE IF NOT EXISTS warnings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  moderator_id TEXT NOT NULL,
  reason TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Counting State ──
CREATE TABLE IF NOT EXISTS counting_state (
  guild_id TEXT PRIMARY KEY,
  channel_id TEXT,
  last_number INTEGER NOT NULL DEFAULT 0,
  last_user_id TEXT,
  highscore INTEGER NOT NULL DEFAULT 0
);

-- ── Counting User Stats ──
CREATE TABLE IF NOT EXISTS counting_user_stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  correct INTEGER NOT NULL DEFAULT 0,
  fails INTEGER NOT NULL DEFAULT 0,
  best_streak INTEGER NOT NULL DEFAULT 0,
  current_streak INTEGER NOT NULL DEFAULT 0,
  UNIQUE(guild_id, user_id)
);

-- ── Auto Publisher Channels ──
CREATE TABLE IF NOT EXISTS auto_publisher_channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  UNIQUE(guild_id, channel_id)
);

-- ── Selfrole Panels ──
CREATE TABLE IF NOT EXISTS selfrole_panels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  message_id TEXT NOT NULL UNIQUE,
  channel_id TEXT NOT NULL,
  title TEXT NOT NULL,
  max_roles INTEGER NOT NULL DEFAULT 0
);

-- ── Selfrole Mappings ──
CREATE TABLE IF NOT EXISTS selfrole_mappings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  panel_id INTEGER NOT NULL REFERENCES selfrole_panels(id) ON DELETE CASCADE,
  emoji TEXT NOT NULL,
  role_id TEXT NOT NULL,
  UNIQUE(panel_id, emoji)
);

-- ── Server Stats ──
CREATE TABLE IF NOT EXISTS server_stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  category_id TEXT,
  stat_key TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  UNIQUE(guild_id, stat_key)
);

-- ── Log Channels ──
CREATE TABLE IF NOT EXISTS log_channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  log_type TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  UNIQUE(guild_id, log_type)
);

-- ── Twitch Announcement Config ──
CREATE TABLE IF NOT EXISTS twitch_config (
  guild_id TEXT PRIMARY KEY,
  channel_id TEXT,
  last_stream_id TEXT
);

-- ── Tickets (enhanced) ──
CREATE TABLE IF NOT EXISTS tickets (
  ticket_id TEXT PRIMARY KEY,
  guild_id TEXT,
  channel_id TEXT,
  creator_user_id TEXT,
  creator_username TEXT,
  status TEXT DEFAULT 'open',
  subject TEXT,
  category TEXT,
  twitch_name TEXT,
  closed_at TEXT,
  closed_by_id TEXT,
  closed_by_name TEXT,
  close_reason TEXT,
  transcript_path TEXT,
  transcript_url TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Ticket Messages (for web reply feature) ──
CREATE TABLE IF NOT EXISTS ticket_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
  author_id TEXT NOT NULL,
  author_name TEXT NOT NULL,
  content TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'discord',
  discord_message_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Ticket Logs ──
CREATE TABLE IF NOT EXISTS ticket_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id TEXT NOT NULL,
  level TEXT,
  message TEXT,
  data_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Ticket Close Reasons (configurable via panel) ──
CREATE TABLE IF NOT EXISTS close_reasons (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id TEXT NOT NULL,
  label TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Indexes ──
CREATE INDEX IF NOT EXISTS idx_close_reasons_guild ON close_reasons(guild_id);
CREATE INDEX IF NOT EXISTS idx_tickets_creator ON tickets(creator_user_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_ticket_logs_ticket ON ticket_logs(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_messages_ticket ON ticket_messages(ticket_id);
CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id);
CREATE INDEX IF NOT EXISTS idx_birthdays_guild ON birthdays(guild_id);
CREATE INDEX IF NOT EXISTS idx_birthdays_month_day ON birthdays(month, day);
CREATE INDEX IF NOT EXISTS idx_bot_messages_guild_type ON bot_messages(guild_id, message_type);
CREATE INDEX IF NOT EXISTS idx_roles_guild ON roles(guild_id);
CREATE INDEX IF NOT EXISTS idx_guild_members_guild_status ON guild_members(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_guild_members_user ON guild_members(user_id);
CREATE INDEX IF NOT EXISTS idx_guild_member_name_history_user ON guild_member_name_history(guild_id, user_id, changed_at);
CREATE INDEX IF NOT EXISTS idx_guild_messages_guild_created ON guild_messages(guild_id, created_at);
CREATE INDEX IF NOT EXISTS idx_guild_messages_user ON guild_messages(guild_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_guild_messages_channel ON guild_messages(guild_id, channel_id, created_at);
