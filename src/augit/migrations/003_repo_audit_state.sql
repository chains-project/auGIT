CREATE TABLE IF NOT EXISTS repo_audit_state (
  repo_id INTEGER PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
  checkpoint_at TEXT,
  profile_json TEXT,
  last_report_at TEXT,
  last_report_status TEXT
);
