ALTER TABLE orders ADD COLUMN IF NOT EXISTS settled_at timestamptz;
UPDATE orders SET settled_at = now() WHERE settled_at IS NULL;
ALTER TABLE orders ALTER COLUMN settled_at SET DEFAULT now();

CREATE TABLE IF NOT EXISTS estimates (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id bigint NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    order_code varchar(20) NOT NULL,
    crew varchar(8) NOT NULL REFERENCES crews(code),
    minutes double precision NOT NULL CHECK (minutes >= 0.01 AND minutes <= 180),
    shots integer NOT NULL CHECK (shots BETWEEN 1 AND 1000),
    switches integer NOT NULL CHECK (switches BETWEEN 0 AND 1000 AND switches <= shots - 1),
    point_hours double precision NOT NULL CHECK (point_hours >= 0),
    point_model varchar(16) NOT NULL DEFAULT 'lasso',
    upper_hours double precision NOT NULL CHECK (upper_hours >= 0),
    coverage double precision NOT NULL DEFAULT 0.9 CHECK (coverage > 0 AND coverage < 1),
    calibration jsonb NOT NULL,
    created_by varchar(100) NOT NULL REFERENCES accounts(email),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (report_id, order_code)
);

CREATE INDEX IF NOT EXISTS estimates_report ON estimates (report_id, created_at);
CREATE INDEX IF NOT EXISTS estimates_order ON estimates (order_code);
