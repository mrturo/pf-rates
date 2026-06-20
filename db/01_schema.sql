-- ============================================================
-- 1. Currencies and exchange rates
-- ============================================================
CREATE TABLE IF NOT EXISTS currencies (
    code        CHAR(3)     PRIMARY KEY,
    name        VARCHAR(60) NOT NULL,
    is_fiat     BOOLEAN     NOT NULL DEFAULT TRUE,
    unit_kind   VARCHAR(20) NOT NULL DEFAULT 'currency'
        CHECK (unit_kind IN ('currency', 'index_unit'))
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    id            BIGSERIAL     PRIMARY KEY,
    currency_code CHAR(3)       NOT NULL REFERENCES currencies(code),
    rate_date     DATE          NOT NULL,
    value_clp     NUMERIC(18,6) NOT NULL CHECK (value_clp > 0),
    source        VARCHAR(40)   NOT NULL DEFAULT 'manual',
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (currency_code, rate_date)
);

-- ============================================================
-- 2. Economic indices
-- ============================================================
CREATE TABLE IF NOT EXISTS economic_indices (
    id             BIGSERIAL     PRIMARY KEY,
    code           VARCHAR(20)   NOT NULL,
    period_year    SMALLINT      NOT NULL CHECK (period_year BETWEEN 1990 AND 2100),
    period_month   SMALLINT      NOT NULL CHECK (period_month BETWEEN 1 AND 12),
    index_value    NUMERIC(12,6) NOT NULL CHECK (index_value > 0),
    monthly_change NUMERIC(7,4),
    yearly_change  NUMERIC(7,4),
    base_period    VARCHAR(10)   NOT NULL DEFAULT 'DIC-2018',
    source         VARCHAR(40)   NOT NULL DEFAULT 'manual',
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_economic_indices UNIQUE (code, period_year, period_month)
);

-- ============================================================
-- 3. Income tax brackets
-- ============================================================
CREATE TABLE IF NOT EXISTS income_tax_brackets (
    id              BIGSERIAL     PRIMARY KEY,
    valid_from      DATE          NOT NULL,
    valid_to        DATE,
    lower_bound_utm NUMERIC(10,4) NOT NULL CHECK (lower_bound_utm >= 0),
    upper_bound_utm NUMERIC(10,4),
    marginal_rate   NUMERIC(8,6)  NOT NULL CHECK (marginal_rate >= 0 AND marginal_rate <= 1),
    rebate_utm      NUMERIC(10,4) NOT NULL DEFAULT 0 CHECK (rebate_utm >= 0),
    CONSTRAINT chk_income_tax_bracket_bounds
        CHECK (upper_bound_utm IS NULL OR upper_bound_utm > lower_bound_utm),
    UNIQUE (valid_from, lower_bound_utm)
);
