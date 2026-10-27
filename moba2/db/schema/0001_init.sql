-- Esquema inicial: usuarios, tokens, salas, partidas y ratings.
CREATE TABLE users (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id          TEXT    NOT NULL UNIQUE,
    name               TEXT    NOT NULL,
    name_set           INTEGER NOT NULL DEFAULT 0,
    avatar_hero        TEXT,
    rating             REAL    NOT NULL DEFAULT 1000.0,
    games              INTEGER NOT NULL DEFAULT 0,
    wins               INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT    NOT NULL,
    last_seen_at       TEXT    NOT NULL
);
CREATE UNIQUE INDEX ux_users_name ON users(name COLLATE NOCASE);
CREATE INDEX ix_users_rating ON users(rating DESC);

CREATE TABLE tokens (
    token_hash    TEXT    PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_id     TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    expires_at    TEXT    NOT NULL,
    last_used_at  TEXT,
    revoked       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_tokens_user ON tokens(user_id);

CREATE TABLE lobbies (
    code         TEXT    PRIMARY KEY,
    owner_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    host         TEXT    NOT NULL,
    port         INTEGER NOT NULL,
    session_key  TEXT    NOT NULL,
    is_private   INTEGER NOT NULL DEFAULT 0,
    max_members  INTEGER NOT NULL DEFAULT 16,
    created_at   TEXT    NOT NULL,
    expires_at   TEXT    NOT NULL,
    closed_at    TEXT
);
CREATE INDEX ix_lobbies_owner ON lobbies(owner_id);

CREATE TABLE lobby_members (
    lobby_code  TEXT    NOT NULL REFERENCES lobbies(code) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slot        INTEGER,
    ready       INTEGER NOT NULL DEFAULT 0,
    joined_at   TEXT    NOT NULL,
    PRIMARY KEY (lobby_code, user_id)
);

CREATE TABLE matches (
    id            TEXT    PRIMARY KEY,
    mode          TEXT,
    duration_s    INTEGER NOT NULL DEFAULT 0,
    version       TEXT,
    lobby_code    TEXT,
    signature_ok  INTEGER NOT NULL DEFAULT 0,
    raw           TEXT,
    reported_at   TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);
CREATE INDEX ix_matches_reported ON matches(reported_at DESC);

CREATE TABLE match_players (
    match_id      TEXT    NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    seat          INTEGER NOT NULL,
    user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    display_name  TEXT    NOT NULL,
    hero          TEXT,
    team          TEXT,
    result        TEXT,
    kills         INTEGER NOT NULL DEFAULT 0,
    deaths        INTEGER NOT NULL DEFAULT 0,
    assists       INTEGER NOT NULL DEFAULT 0,
    rating_before REAL,
    rating_after  REAL,
    rating_delta  REAL,
    PRIMARY KEY (match_id, seat)
);
CREATE INDEX ix_mp_user ON match_players(user_id);
CREATE INDEX ix_mp_hero ON match_players(hero);

CREATE TABLE rating_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    match_id    TEXT    NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    rating_before REAL  NOT NULL,
    rating_after  REAL  NOT NULL,
    delta         REAL  NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX ix_rating_user ON rating_events(user_id, id DESC);

CREATE TABLE audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    actor_id   INTEGER,
    action     TEXT NOT NULL,
    detail     TEXT
);
