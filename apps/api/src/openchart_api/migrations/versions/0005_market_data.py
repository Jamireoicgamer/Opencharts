# SPDX-License-Identifier: AGPL-3.0-or-later
"""Market data: a shared candle cache, data-source settings, and the narrow
functions the background market-data hub uses (milestone M3).

* ``candles`` caches price history fetched from providers. It holds no
  personal data, so every signed-in user can read it; the API can add and
  refresh rows but never delete them.
* ``data_sources`` is server-wide configuration: which providers are on,
  their order, terms-of-use acceptance and an optional sealed API key. Only
  owners and admins can see or change it through RLS.
* The hub runs without a user, so RLS gives it nothing. It reaches exactly
  what it needs through SECURITY DEFINER functions:
  - ``market_data_sources()``: enabled providers and their sealed keys
    (ciphertext only; the master key never touches the database);
  - ``market_alert_instruments()``: which instruments have armed alerts
    (instrument ids only);
  - ``market_trigger_alerts()``: marks crossed alerts as triggered and
    returns who to notify.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

from openchart_api.migrations.sql import app_role, run

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = """
CREATE TABLE candles (
    instrument_id text NOT NULL REFERENCES instruments (id),
    interval text NOT NULL CHECK (interval IN ('5m', '1h', '1d')),
    t timestamptz NOT NULL,
    open numeric(28, 10) NOT NULL CHECK (open >= 0),
    high numeric(28, 10) NOT NULL CHECK (high >= 0),
    low numeric(28, 10) NOT NULL CHECK (low >= 0),
    close numeric(28, 10) NOT NULL CHECK (close >= 0),
    volume numeric(38, 10) CHECK (volume >= 0),
    source text NOT NULL CHECK (source ~ '^[a-z0-9]{1,32}$'),
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, interval, t)
);

-- Which time range of each series has been fetched, so the cache asks
-- providers only for what it does not have (markets have gaps, so the
-- candles alone cannot say).
CREATE TABLE candle_ranges (
    instrument_id text NOT NULL REFERENCES instruments (id),
    interval text NOT NULL CHECK (interval IN ('5m', '1h', '1d')),
    covered_from timestamptz NOT NULL,
    covered_to timestamptz NOT NULL CHECK (covered_to >= covered_from),
    PRIMARY KEY (instrument_id, interval)
);

CREATE TABLE data_sources (
    provider text PRIMARY KEY CHECK (provider IN ('coinbase', 'kraken', 'yahoo', 'twelvedata')),
    enabled boolean NOT NULL DEFAULT false,
    priority integer NOT NULL CHECK (priority BETWEEN 1 AND 100),
    tos_accepted_at timestamptz,
    tos_accepted_by uuid REFERENCES users (id) ON DELETE SET NULL,
    key_ciphertext bytea,
    key_nonce bytea,
    key_wrapped_dek bytea,
    key_dek_nonce bytea,
    key_version integer,
    key_hint text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- A key is stored whole or not at all.
    CHECK (num_nulls(key_ciphertext, key_nonce, key_wrapped_dek, key_dek_nonce, key_version)
           IN (0, 5))
);

-- Keyless crypto is on out of the box. The keyless delayed equity source
-- needs the owner to accept its terms; the key-based one needs a key.
INSERT INTO data_sources (provider, enabled, priority) VALUES
    ('coinbase', true, 10),
    ('kraken', true, 20),
    ('yahoo', false, 30),
    ('twelvedata', false, 40);

ALTER TABLE candles ENABLE ROW LEVEL SECURITY;
CREATE POLICY candles_read ON candles FOR SELECT USING (true);
CREATE POLICY candles_insert ON candles FOR INSERT WITH CHECK (true);
CREATE POLICY candles_update ON candles FOR UPDATE USING (true) WITH CHECK (true);

ALTER TABLE candle_ranges ENABLE ROW LEVEL SECURITY;
CREATE POLICY candle_ranges_all ON candle_ranges FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE data_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY data_sources_admin ON data_sources FOR ALL
    USING (app_user_role() IN ('owner', 'admin'))
    WITH CHECK (app_user_role() IN ('owner', 'admin'));

CREATE FUNCTION market_data_sources()
RETURNS TABLE (provider text, priority integer, tos_accepted boolean,
               key_ciphertext bytea, key_nonce bytea, key_wrapped_dek bytea,
               key_dek_nonce bytea, key_version integer)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT d.provider, d.priority, d.tos_accepted_at IS NOT NULL,
          d.key_ciphertext, d.key_nonce, d.key_wrapped_dek, d.key_dek_nonce, d.key_version
   FROM data_sources d WHERE d.enabled ORDER BY d.priority $$;

CREATE FUNCTION market_alert_instruments() RETURNS SETOF text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT DISTINCT a.instrument_id FROM alerts a
   JOIN users u ON u.id = a.user_id
   WHERE a.active AND a.triggered_at IS NULL AND u.disabled_at IS NULL $$;

CREATE FUNCTION market_trigger_alerts(p_instrument_id text, p_price numeric)
RETURNS TABLE (alert_id uuid, user_id uuid, direction text, price numeric, note text)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ UPDATE alerts a SET triggered_at = now(), active = false
   WHERE a.instrument_id = p_instrument_id
     AND a.active AND a.triggered_at IS NULL
     AND p_price > 0
     AND ((a.direction = 'above' AND p_price >= a.price)
          OR (a.direction = 'below' AND p_price <= a.price))
   RETURNING a.id, a.user_id, a.direction, a.price, a.note $$;

REVOKE ALL ON FUNCTION market_data_sources() FROM PUBLIC;
REVOKE ALL ON FUNCTION market_alert_instruments() FROM PUBLIC;
REVOKE ALL ON FUNCTION market_trigger_alerts(text, numeric) FROM PUBLIC;
"""

GRANTS = """
GRANT SELECT, INSERT, UPDATE ON candles, candle_ranges TO {role};
GRANT SELECT, UPDATE ON data_sources TO {role};
GRANT EXECUTE ON FUNCTION market_data_sources() TO {role};
GRANT EXECUTE ON FUNCTION market_alert_instruments() TO {role};
GRANT EXECUTE ON FUNCTION market_trigger_alerts(text, numeric) TO {role};
"""

DROP = """
DROP FUNCTION market_trigger_alerts(text, numeric);
DROP FUNCTION market_alert_instruments();
DROP FUNCTION market_data_sources();
DROP TABLE data_sources, candle_ranges, candles;
"""


def upgrade() -> None:
    run(op, SCHEMA)
    run(op, GRANTS.format(role=app_role()))


def downgrade() -> None:
    run(op, DROP)
