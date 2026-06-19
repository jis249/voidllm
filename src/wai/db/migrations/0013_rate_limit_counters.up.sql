-- Shared rate-limit counters for multi-instance / load-balanced deployments.
-- scope_type: key | team | org | ip
-- window_type: minute | day | auth (brute-force windows use fixed window_start per attempt bucket)

CREATE TABLE IF NOT EXISTS rate_limit_counters (
    scope_type    TEXT NOT NULL,
    scope_id      TEXT NOT NULL,
    window_type   TEXT NOT NULL,
    window_start  TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scope_type, scope_id, window_type, window_start)
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_counters_window
    ON rate_limit_counters (window_start);
