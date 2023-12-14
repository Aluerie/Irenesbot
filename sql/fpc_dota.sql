CREATE TABLE IF NOT EXISTS dota_settings (
    guild_id BIGINT PRIMARY KEY,
    guild_name TEXT,
    channel_id BIGINT,
    spoil BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS dota_players (
    lower_name TEXT PRIMARY KEY NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    twitch_id BIGINT
);

CREATE TABLE IF NOT EXISTS dota_favourite_players (
    guild_id BIGINT,
    lower_name TEXT NOT NULL,

    PRIMARY KEY(guild_id, lower_name),

    CONSTRAINT fk_guild_id
        FOREIGN KEY (guild_id)
        REFERENCES dota_settings(guild_id) ON DELETE CASCADE,
    CONSTRAINT fk_player
        FOREIGN KEY (lower_name)
        REFERENCES dota_players(lower_name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dota_favourite_characters (
    guild_id BIGINT,
    character_id INT NOT NULL,

    PRIMARY KEY(guild_id, character_id),

    CONSTRAINT fk_guild_id
        FOREIGN KEY (guild_id)
        REFERENCES dota_settings(guild_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dota_accounts (
    id BIGINT PRIMARY KEY, -- id = steam id ; name "id" to be the same with "lol_accounts"
    friend_id BIGINT,
    lower_name TEXT NOT NULL,
    CONSTRAINT fk_player
        FOREIGN KEY (lower_name)
        REFERENCES dota_players(lower_name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dota_matches (
    match_id BIGINT PRIMARY KEY,
    opendota_jobid BIGINT
);

CREATE TABLE IF NOT EXISTS dota_messages (
    message_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    match_id BIGINT NOT NULL,
    character_id INTEGER NOT NULL,

    CONSTRAINT fk_match
        FOREIGN KEY (match_id)
            REFERENCES dota_matches(match_id) ON DELETE CASCADE
);