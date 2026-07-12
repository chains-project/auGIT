PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS package_links (
  package_repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  github_repo_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  source_field TEXT NOT NULL,
  raw_url TEXT NOT NULL,
  linked_at TEXT NOT NULL,
  PRIMARY KEY (package_repo_id)
);

CREATE INDEX IF NOT EXISTS idx_package_links_github
ON package_links(github_repo_id);
