PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS repositories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_url TEXT NOT NULL,
  provider TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (canonical_url, provider)
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  run_started_at TEXT NOT NULL,
  run_finished_at TEXT,
  mode TEXT NOT NULL, -- incremental|integrity_refetch
  tool_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  category TEXT NOT NULL, -- contributor|governance|release|dependency|integrity
  event_type TEXT NOT NULL,
  source TEXT NOT NULL, -- github_api|git|registry|refetch_compare|manual
  source_event_id TEXT,
  source_timestamp TEXT,
  observed_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedup
ON events(repo_id, source, source_event_id)
WHERE source_event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_events_repo_observed_at
ON events(repo_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_events_repo_category_observed_at
ON events(repo_id, category, observed_at);

CREATE TABLE IF NOT EXISTS cursors (
  repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  cursor_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (repo_id, source)
);

CREATE TABLE IF NOT EXISTS integrity_refetches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  refetched_at TEXT NOT NULL,
  subjects_json TEXT NOT NULL,
  summary_json TEXT NOT NULL
);

