"""One-time startup migrations and cleanup."""
import datetime as dt
import pipeline as P


def migrate():
    c = P.db()
    c.execute("UPDATE runs SET status='failed', error='Interrupted by a server restart', finished_at=? WHERE status='running'", (P.now(),))
    for ddl in ("CREATE INDEX IF NOT EXISTS idx_leads_rank ON leads(score DESC, first_seen DESC) WHERE dup_of IS NULL",
                "CREATE INDEX IF NOT EXISTS idx_leads_outreach ON leads(outreach)",
                "CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY, path TEXT NOT NULL, type TEXT, name TEXT, size BIGINT DEFAULT 0, enabled INTEGER DEFAULT 1, at TEXT)",
                "CREATE INDEX IF NOT EXISTS idx_leads_dup ON leads(dup_of)",
                "CREATE INDEX IF NOT EXISTS idx_leads_category ON leads(LOWER(category))",
                "ALTER TABLE leads ADD COLUMN IF NOT EXISTS priority BIGINT NOT NULL DEFAULT 0"):
        c.execute(ddl)
    c.execute("DELETE FROM run_events WHERE at < ?", ((dt.datetime.now() - dt.timedelta(days=30)).isoformat(timespec="seconds"),))
    c.commit(); c.close()
