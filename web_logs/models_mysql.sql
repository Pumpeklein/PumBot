CREATE TABLE IF NOT EXISTS users (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  discord_id VARCHAR(32) NOT NULL UNIQUE,
  discord_username VARCHAR(255) NOT NULL,
  discord_avatar TEXT,
  discord_banner TEXT,
  accent_color INT,
  locale VARCHAR(32),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_connections (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  discord_id VARCHAR(32) NOT NULL,
  connection_id VARCHAR(255) NOT NULL,
  connection_type VARCHAR(64) NOT NULL,
  name VARCHAR(255) NOT NULL,
  verified TINYINT(1) NOT NULL DEFAULT 0,
  visibility INT,
  show_activity TINYINT(1),
  two_way_link TINYINT(1),
  metadata_json LONGTEXT,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_user_connections_connection (discord_id, connection_id, connection_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS guild_members (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  user_id VARCHAR(32) NOT NULL,
  username VARCHAR(255) NOT NULL,
  global_name VARCHAR(255),
  display_name VARCHAR(255) NOT NULL,
  discriminator VARCHAR(16),
  avatar_url TEXT,
  banner_url TEXT,
  accent_color INT,
  locale VARCHAR(32),
  roles_json LONGTEXT,
  is_bot TINYINT(1) NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  presence_status VARCHAR(64),
  activity_name VARCHAR(255),
  activity_type VARCHAR(64),
  status_updated_at DATETIME NULL,
  joined_at DATETIME NULL,
  left_at DATETIME NULL,
  first_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_guild_members_guild_user (guild_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS guild_member_name_history (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  user_id VARCHAR(32) NOT NULL,
  old_username VARCHAR(255),
  old_global_name VARCHAR(255),
  old_display_name VARCHAR(255),
  new_username VARCHAR(255),
  new_global_name VARCHAR(255),
  new_display_name VARCHAR(255),
  changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS guild_messages (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  channel_id VARCHAR(32) NOT NULL,
  channel_name VARCHAR(255),
  message_id VARCHAR(32) NOT NULL,
  user_id VARCHAR(32) NOT NULL,
  original_content LONGTEXT,
  content LONGTEXT,
  attachment_count INT NOT NULL DEFAULT 0,
  jump_url TEXT,
  created_at DATETIME NOT NULL,
  edited_at DATETIME NULL,
  deleted_at DATETIME NULL,
  synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_guild_messages_message (guild_id, channel_id, message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS guild_message_history (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  channel_id VARCHAR(32) NOT NULL,
  channel_name VARCHAR(255),
  message_id VARCHAR(32) NOT NULL,
  user_id VARCHAR(32),
  event_type VARCHAR(32) NOT NULL,
  old_content LONGTEXT,
  new_content LONGTEXT,
  attachment_count INT NOT NULL DEFAULT 0,
  jump_url TEXT,
  event_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS roles (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  discord_role_id VARCHAR(32) NOT NULL,
  role_name VARCHAR(255) NOT NULL,
  permissions LONGTEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_roles_guild_role (guild_id, discord_role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS guild_config (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  config_key VARCHAR(128) NOT NULL,
  config_value LONGTEXT NOT NULL,
  UNIQUE KEY uq_guild_config_key (guild_id, config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS birthdays (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  user_id VARCHAR(32) NOT NULL,
  day INT NOT NULL,
  month INT NOT NULL,
  year INT,
  last_congrats VARCHAR(32),
  UNIQUE KEY uq_birthdays_guild_user (guild_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bot_messages (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  message_type VARCHAR(64) NOT NULL,
  message_id VARCHAR(32) NOT NULL,
  channel_id VARCHAR(32),
  meta_key VARCHAR(128),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_bot_messages_message (guild_id, message_type, message_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS warnings (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  user_id VARCHAR(32) NOT NULL,
  moderator_id VARCHAR(32) NOT NULL,
  reason TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS counting_state (
  guild_id VARCHAR(32) PRIMARY KEY,
  channel_id VARCHAR(32),
  last_number INT NOT NULL DEFAULT 0,
  last_user_id VARCHAR(32),
  highscore INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS counting_user_stats (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  user_id VARCHAR(32) NOT NULL,
  correct INT NOT NULL DEFAULT 0,
  fails INT NOT NULL DEFAULT 0,
  best_streak INT NOT NULL DEFAULT 0,
  current_streak INT NOT NULL DEFAULT 0,
  UNIQUE KEY uq_counting_user_stats_user (guild_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_publisher_channels (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  channel_id VARCHAR(32) NOT NULL,
  UNIQUE KEY uq_auto_publisher_channel (guild_id, channel_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS selfrole_panels (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  message_id VARCHAR(32) NOT NULL UNIQUE,
  channel_id VARCHAR(32) NOT NULL,
  title VARCHAR(255) NOT NULL,
  max_roles INT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS selfrole_mappings (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  panel_id BIGINT NOT NULL,
  emoji VARCHAR(255) NOT NULL,
  role_id VARCHAR(32) NOT NULL,
  UNIQUE KEY uq_selfrole_mapping (panel_id, emoji),
  CONSTRAINT fk_selfrole_mappings_panel FOREIGN KEY (panel_id) REFERENCES selfrole_panels(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS server_stats (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  category_id VARCHAR(32),
  stat_key VARCHAR(64) NOT NULL,
  channel_id VARCHAR(32) NOT NULL,
  UNIQUE KEY uq_server_stats_key (guild_id, stat_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS log_channels (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  log_type VARCHAR(64) NOT NULL,
  channel_id VARCHAR(32) NOT NULL,
  UNIQUE KEY uq_log_channels_type (guild_id, log_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS twitch_config (
  guild_id VARCHAR(32) PRIMARY KEY,
  channel_id VARCHAR(32),
  last_stream_id VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tickets (
  ticket_id VARCHAR(32) PRIMARY KEY,
  guild_id VARCHAR(32),
  channel_id VARCHAR(32),
  creator_user_id VARCHAR(32),
  creator_username VARCHAR(255),
  status VARCHAR(32) DEFAULT 'open',
  subject VARCHAR(255),
  category VARCHAR(255),
  twitch_name VARCHAR(255),
  closed_at DATETIME NULL,
  closed_by_id VARCHAR(32),
  closed_by_name VARCHAR(255),
  close_reason TEXT,
  transcript_path TEXT,
  transcript_url TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ticket_messages (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  ticket_id VARCHAR(32) NOT NULL,
  author_id VARCHAR(32) NOT NULL,
  author_name VARCHAR(255) NOT NULL,
  content LONGTEXT NOT NULL,
  source VARCHAR(64) NOT NULL DEFAULT 'discord',
  discord_message_id VARCHAR(32),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_ticket_messages_ticket FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ticket_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  ticket_id VARCHAR(32) NOT NULL,
  level VARCHAR(32),
  message TEXT,
  data_json LONGTEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS close_reasons (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  guild_id VARCHAR(32) NOT NULL,
  label VARCHAR(255) NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_close_reasons_guild ON close_reasons(guild_id);
CREATE INDEX idx_tickets_creator ON tickets(creator_user_id);
CREATE INDEX idx_tickets_status ON tickets(status);
CREATE INDEX idx_ticket_logs_ticket ON ticket_logs(ticket_id);
CREATE INDEX idx_ticket_messages_ticket ON ticket_messages(ticket_id);
CREATE INDEX idx_warnings_guild_user ON warnings(guild_id, user_id);
CREATE INDEX idx_birthdays_guild ON birthdays(guild_id);
CREATE INDEX idx_birthdays_month_day ON birthdays(month, day);
CREATE INDEX idx_bot_messages_guild_type ON bot_messages(guild_id, message_type);
CREATE INDEX idx_roles_guild ON roles(guild_id);
CREATE INDEX idx_user_connections_discord_id ON user_connections(discord_id);
CREATE INDEX idx_guild_members_guild_status ON guild_members(guild_id, status);
CREATE INDEX idx_guild_members_user ON guild_members(user_id);
CREATE INDEX idx_guild_member_name_history_user ON guild_member_name_history(guild_id, user_id, changed_at);
CREATE INDEX idx_guild_messages_guild_created ON guild_messages(guild_id, created_at);
CREATE INDEX idx_guild_messages_user ON guild_messages(guild_id, user_id, created_at);
CREATE INDEX idx_guild_messages_channel ON guild_messages(guild_id, channel_id, created_at);
CREATE INDEX idx_guild_message_history_message ON guild_message_history(guild_id, channel_id, message_id, event_at);
CREATE INDEX idx_guild_message_history_user ON guild_message_history(guild_id, user_id, event_at);
CREATE INDEX idx_guild_message_history_type ON guild_message_history(guild_id, event_type, event_at);
