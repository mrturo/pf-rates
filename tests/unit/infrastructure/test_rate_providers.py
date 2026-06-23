"""Tests for rate providers."""

import socket
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError


from financial_data.application.dto import (
    EconomicIndexWriteDTO,
    ExchangeRateWriteDTO,
    IncomeTaxBracketWriteDTO,
)
from financial_data.infrastructure.rate_providers.chained_provider import (
    ChainedEconomicIndexProvider,
    ChainedFxProvider,
)
from financial_data.infrastructure.rate_providers.official_providers import (
    BcchSeriesProvider,
    MindicadorRateProvider,
    SiiIncomeTaxBracketProvider,
    SiiIndicatorsProvider,
    _build_monthly_income_tax_brackets,
    _extract_income_tax_month_rows,
    _extract_sii_rows,
    _fetch_url,
    _proxy_is_reachable,
    _resolve_proxy_handler,
    make_fetcher,
    _parse_chilean_amount,
    _parse_chilean_decimal,
    _parse_month_heading,
)


def _rate_entries(
    currency_code: str, requested_dates: list[date], source: str
) -> list[ExchangeRateWriteDTO]:
    """Build ExchangeRateWriteDTO list at a fixed value of 950.12 CLP."""
    return [
        ExchangeRateWriteDTO(
            currency_code=currency_code,
            rate_date=requested_date,
            value_clp=Decimal("950.12"),
            source=source,
        )
        for requested_date in requested_dates
    ]


def _index_entries(
    code: str, requested_periods: list[tuple[int, int]], source: str
) -> list[EconomicIndexWriteDTO]:
    """Build EconomicIndexWriteDTO list at a fixed value of 109.71."""
    return [
        EconomicIndexWriteDTO(
            code=code,
            period_year=period_year,
            period_month=period_month,
            index_value=Decimal("109.71"),
            source=source,
        )
        for period_year, period_month in requested_periods
    ]


async def test_mindicador_rate_provider_parses_year_series_and_unknown_indicator() -> (
    None
):
    """Test parsing a year series and ignoring unknown indicators."""
    provider = MindicadorRateProvider(
        fetcher=lambda url, timeout: (
            """
        {"serie":[
          {"fecha":"2026-01-31T03:00:00.000Z","valor":38000},
          {"fecha":"2026-01-30T03:00:00.000Z","valor":37900}
        ]}
        """
        ),
    )

    result = await provider.fetch_rate("UF", date(2026, 1, 31))
    missing = await provider.fetch_rate("CLP", date(2026, 1, 31))
    entry = await provider.fetch_rate_entry("UF", date(2026, 1, 31))
    entries = await provider.fetch_rate_entries(
        "UF", [date(2026, 1, 29), date(2026, 1, 30), date(2026, 1, 31)]
    )
    missing_entry = await provider.fetch_rate_entry("CLP", date(2026, 1, 31))

    assert result == Decimal("38000")
    assert missing is None
    assert missing_entry is None
    assert entry == ExchangeRateWriteDTO(
        currency_code="UF",
        rate_date=date(2026, 1, 31),
        value_clp=Decimal("38000"),
        source="mindicador",
    )
    assert entries == [
        ExchangeRateWriteDTO(
            currency_code="UF",
            rate_date=date(2026, 1, 30),
            value_clp=Decimal("37900"),
            source="mindicador",
        ),
        ExchangeRateWriteDTO(
            currency_code="UF",
            rate_date=date(2026, 1, 31),
            value_clp=Decimal("38000"),
            source="mindicador",
        ),
    ]
    assert await provider.fetch_rate_entries("CLP", [date(2026, 1, 31)]) == []


async def test_mindicador_rate_provider_returns_none_on_invalid_payload() -> None:
    """Test mindicador rate provider returns none on invalid payload."""
    provider = MindicadorRateProvider(fetcher=lambda url, timeout: "{")

    assert await provider.fetch_rate("USD", date(2026, 1, 31)) is None
    provider = MindicadorRateProvider(fetcher=lambda url, timeout: '{"serie":{}}')
    assert await provider.fetch_rate("USD", date(2026, 1, 31)) is None
    assert await provider.fetch_rate_entries("USD", []) == []


async def test_mindicador_rate_provider_fetch_rate_is_exact_match_only() -> None:
    """fetch_rate returns None for dates not published in the series.

    fetch_rate no longer uses carry-forward semantics so that callers like the
    on-demand /value endpoint don't receive stale values for unpublished dates.
    fetch_rate_entries preserves carry-forward for bulk sync operations.
    """

    def fetcher(url: str, timeout: int) -> str:
        if url.endswith("/dolar/2025"):
            return """
            {"serie":[
              {"fecha":"2025-12-31T03:00:00.000Z","valor":950.12}
            ]}
            """
        if url.endswith("/dolar/2026"):
            return """
            {"serie":[
              {"fecha":"2026-01-02T03:00:00.000Z","valor":960.34}
            ]}
            """
        return '{"serie":[]}'

    provider = MindicadorRateProvider(fetcher=fetcher)

    # 2026-01-01 is not in the 2026 series → None (no carry-forward in fetch_rate)
    assert await provider.fetch_rate("USD", date(2026, 1, 1)) is None
    # 2026-01-02 is in the series → exact match
    assert await provider.fetch_rate("USD", date(2026, 1, 2)) == Decimal("960.34")
    # fetch_rate_entries still carries forward for bulk sync use
    assert await provider.fetch_rate_entries(
        "USD", [date(2026, 1, 1), date(2026, 1, 2)]
    ) == [
        ExchangeRateWriteDTO(
            currency_code="USD",
            rate_date=date(2026, 1, 1),
            value_clp=Decimal("950.12"),
            source="mindicador",
        ),
        ExchangeRateWriteDTO(
            currency_code="USD",
            rate_date=date(2026, 1, 2),
            value_clp=Decimal("960.34"),
            source="mindicador",
        ),
    ]
    # Within-year carry-forward: 2026-01-03 not in series, carries 2026-01-02 value
    assert await provider.fetch_rate_entries("USD", [date(2026, 1, 3)]) == [
        ExchangeRateWriteDTO(
            currency_code="USD",
            rate_date=date(2026, 1, 3),
            value_clp=Decimal("960.34"),
            source="mindicador",
        ),
    ]


async def test_mindicador_rate_provider_returns_none_for_unpublished_year() -> None:
    """Test that no cross-year carry-forward is returned for a year with no data.

    When an entire year series is empty (e.g. far-future dates), the provider
    must return None rather than carrying forward the last value from a prior year.
    """

    def fetcher(url: str, timeout: int) -> str:
        if url.endswith("/uf/2026"):
            return """
            {"serie":[
              {"fecha":"2026-07-09T03:00:00.000Z","valor":40844.79}
            ]}
            """
        # 2027 and beyond: no data published yet
        return '{"serie":[]}'

    provider = MindicadorRateProvider(fetcher=fetcher)

    assert await provider.fetch_rate("UF", date(2027, 7, 28)) is None
    assert await provider.fetch_rate_entries("UF", [date(2027, 7, 28)]) == []


async def test_sii_indicators_provider_parses_utm_and_ipc_rows() -> None:
    """Test sii indicators provider parses utm and ipc rows."""
    html = """
    <table>
      <tr><th>Mes</th><th>UTM</th><th>UTA</th><th>IPC</th><th>Mensual</th>
      <th>Acumulado</th><th>12 meses</th></tr>
      <tr><td>Enero</td><td>69.751</td><td>837.012</td><td>109,71</td><td>0,4</td><td>0,4</td><td>2,8</td></tr>
      <tr><td>Febrero</td><td>69.611</td><td>835.332</td><td>109,70</td><td>0,0</td><td>0,4</td><td>2,4</td></tr>
    </table>
    """
    provider = SiiIndicatorsProvider(fetcher=lambda url, timeout: html)

    utm = await provider.fetch_rate("UTM", date(2026, 1, 15))
    utm_entry = await provider.fetch_rate_entry("UTM", date(2026, 1, 15))
    utm_entries = await provider.fetch_rate_entries(
        "UTM", [date(2026, 1, 1), date(2026, 2, 1)]
    )
    missing_entry = await provider.fetch_rate_entry("UF", date(2026, 1, 15))
    ipc = await provider.fetch_index("IPC_CL", 2026, 2)
    indices = await provider.fetch_indices("IPC_CL", [(2026, 1), (2026, 2)])
    unsupported = await provider.fetch_rate("UF", date(2026, 1, 15))

    assert utm == Decimal("69751")
    assert missing_entry is None
    assert utm_entry == ExchangeRateWriteDTO(
        currency_code="UTM",
        rate_date=date(2026, 1, 15),
        value_clp=Decimal("69751"),
        source="sii",
    )
    assert ipc == EconomicIndexWriteDTO(
        code="IPC_CL",
        period_year=2026,
        period_month=2,
        index_value=Decimal("109.70"),
        monthly_change=Decimal("0.0"),
        yearly_change=Decimal("2.4"),
        base_period="2023=100",
        source="sii",
    )
    assert utm_entries == [
        ExchangeRateWriteDTO(
            currency_code="UTM",
            rate_date=date(2026, 1, 1),
            value_clp=Decimal("69751"),
            source="sii",
        ),
        ExchangeRateWriteDTO(
            currency_code="UTM",
            rate_date=date(2026, 2, 1),
            value_clp=Decimal("69611"),
            source="sii",
        ),
    ]
    assert indices == [
        EconomicIndexWriteDTO(
            code="IPC_CL",
            period_year=2026,
            period_month=1,
            index_value=Decimal("109.71"),
            monthly_change=Decimal("0.4"),
            yearly_change=Decimal("2.8"),
            base_period="2023=100",
            source="sii",
        ),
        EconomicIndexWriteDTO(
            code="IPC_CL",
            period_year=2026,
            period_month=2,
            index_value=Decimal("109.70"),
            monthly_change=Decimal("0.0"),
            yearly_change=Decimal("2.4"),
            base_period="2023=100",
            source="sii",
        ),
    ]
    assert unsupported is None
    assert await provider.fetch_rate_entries("UF", [date(2026, 1, 1)]) == []


async def test_sii_indicators_provider_returns_none_for_blank_or_missing_rows() -> None:
    """Test sii indicators provider returns none for blank or missing rows."""
    provider = SiiIndicatorsProvider(
        fetcher=lambda url, timeout: (
            "<table><tr><td>Mayo</td><td>70.588</td><td></td><td></td></tr></table>"
        )
    )
    blank_ipc_provider = SiiIndicatorsProvider(
        fetcher=lambda url, timeout: (
            "<table><tr><td>Mayo</td><td>70.588</td><td>847.056</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr></table>"
        )
    )

    assert await provider.fetch_rate("UTM", date(2026, 1, 15)) is None
    assert await provider.fetch_index("IPC_CL", 2026, 5) is None
    assert await blank_ipc_provider.fetch_index("IPC_CL", 2026, 5) is None
    assert await provider.fetch_index("UF_CL", 2026, 5) is None
    assert await provider.fetch_rate_entries("UTM", []) == []
    assert await provider.fetch_indices("IPC_CL", []) == []
    assert await provider.fetch_indices("IPC_CL", [(2026, 5)]) == []
    assert await provider.fetch_rate_entries("UTM", [date(2026, 5, 1)]) == [
        ExchangeRateWriteDTO(
            currency_code="UTM",
            rate_date=date(2026, 5, 1),
            value_clp=Decimal("70588"),
            source="sii",
        )
    ]
    assert await provider.fetch_indices("UF_CL", [(2026, 5)]) == []

    missing_utm_provider = SiiIndicatorsProvider(
        fetcher=lambda url, timeout: "<table><tr><td>Mayo</td></tr></table>"
    )
    assert (
        await missing_utm_provider.fetch_rate_entries("UTM", [date(2026, 5, 1)]) == []
    )
    blank_utm_provider = SiiIndicatorsProvider(
        fetcher=lambda url, timeout: (
            "<table><tr><td>Mayo</td><td>&nbsp;</td></tr></table>"
        )
    )
    assert await blank_utm_provider.fetch_rate_entries("UTM", [date(2026, 5, 1)]) == []
    assert await blank_ipc_provider.fetch_indices("IPC_CL", [(2026, 5)]) == []


async def test_sii_indicators_provider_handles_network_failures() -> None:
    """Test sii indicators provider handles network failures."""
    provider = SiiIndicatorsProvider(
        fetcher=lambda url, timeout: (_ for _ in ()).throw(URLError("offline"))
    )

    assert await provider.fetch_rate("UTM", date(2026, 1, 15)) is None


async def test_sii_income_tax_bracket_provider_parses_monthly_sections() -> None:
    """Test parsing SII monthly sections into UTM brackets."""
    html = """
    <div class='meses' id='mes_enero'>
      <h3>Enero 2026</h3>
      <div class='table-responsive'>
        <table><tbody>
          <tr><td><strong>MENSUAL</strong></td><td>-.-</td><td>$ 941.638,50</td>
          <td>Exento</td><td>-.-</td><td>Exento</td></tr>
          <tr><td><strong></strong></td><td>$ 941.638,51</td><td>$ 2.092.530,00</td>
          <td>0,04</td><td>$ 37.665,54</td><td>2,20%</td></tr>
          <tr><td><strong></strong></td><td>$ 2.092.530,01</td><td>Y M&Aacute;S</td>
          <td>0,4</td><td>$ 2.708.922,84</td><td>M&Aacute;S DE 27,48%</td></tr>
          <tr><td><strong>QUINCENAL</strong></td><td>-.-</td><td>$ 470.819,25</td>
          <td>Exento</td><td>-.-</td><td>Exento</td></tr>
        </tbody></table>
      </div>
    </div>
    """
    provider = SiiIncomeTaxBracketProvider(fetcher=lambda url, timeout: html)

    result = await provider.fetch_income_tax_brackets(2026)

    assert result == [
        IncomeTaxBracketWriteDTO(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 1, 31),
            lower_bound_utm=Decimal("0.0000"),
            upper_bound_utm=Decimal("13.5000"),
            marginal_rate=Decimal("0"),
            rebate_utm=Decimal("0.0000"),
        ),
        IncomeTaxBracketWriteDTO(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 1, 31),
            lower_bound_utm=Decimal("13.5000"),
            upper_bound_utm=Decimal("30.0000"),
            marginal_rate=Decimal("0.04"),
            rebate_utm=Decimal("0.5400"),
        ),
        IncomeTaxBracketWriteDTO(
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 1, 31),
            lower_bound_utm=Decimal("30.0000"),
            upper_bound_utm=None,
            marginal_rate=Decimal("0.4"),
            rebate_utm=Decimal("38.8370"),
        ),
    ]


async def test_sii_income_tax_bracket_provider_handles_missing_rows_and_failures() -> (
    None
):
    """Test handling missing monthly rows and network failures."""
    provider = SiiIncomeTaxBracketProvider(
        fetcher=lambda url, timeout: (
            "<h3>Enero 2026</h3><div class='table-responsive'>"
            "<table><tbody></tbody></table></div>"
        )
    )
    failing = SiiIncomeTaxBracketProvider(
        fetcher=lambda url, timeout: (_ for _ in ()).throw(URLError("offline"))
    )

    assert await provider.fetch_income_tax_brackets(2026) == []
    assert await failing.fetch_income_tax_brackets(2026) == []


async def test_bcch_series_provider_parses_supported_shapes_and_missing_config() -> (
    None
):
    """Test parsing supported BCCH responses and missing credentials."""
    provider = BcchSeriesProvider(
        user="user",
        password="pass",
        series_codes={"UF": "UF_SERIES", "IPC_CL": "IPC_SERIES"},
        fetcher=lambda url, timeout: (
            '{"Series":{"Obs":[{"value":"38000","indexDate":"2026-01-31T00:00:00"}]}}'
        ),
    )
    list_provider = BcchSeriesProvider(
        user="user",
        password="pass",
        series_codes={"IPC_CL": "IPC_SERIES"},
        fetcher=lambda url, timeout: (
            '{"Series":[{"Obs":[{"Valor":"112.340000","indexDate":"2026-01-01T00:00:00"}]}]}'
        ),
    )
    missing_provider = BcchSeriesProvider(
        user=None, password=None, series_codes={"UF": None}
    )

    assert await provider.fetch_rate("UF", date(2026, 1, 31)) == Decimal("38000")
    assert await provider.fetch_rate_entry(
        "UF", date(2026, 1, 31)
    ) == ExchangeRateWriteDTO(
        currency_code="UF",
        rate_date=date(2026, 1, 31),
        value_clp=Decimal("38000"),
        source="bcch",
    )
    assert await provider.fetch_rate_entries("UF", [date(2026, 1, 31)]) == [
        ExchangeRateWriteDTO(
            currency_code="UF",
            rate_date=date(2026, 1, 31),
            value_clp=Decimal("38000"),
            source="bcch",
        )
    ]
    assert await missing_provider.fetch_rate_entry("UF", date(2026, 1, 31)) is None
    assert await list_provider.fetch_index("IPC_CL", 2026, 1) == EconomicIndexWriteDTO(
        code="IPC_CL",
        period_year=2026,
        period_month=1,
        index_value=Decimal("112.340000"),
        source="bcch",
    )
    assert await list_provider.fetch_indices("IPC_CL", [(2026, 1)]) == [
        EconomicIndexWriteDTO(
            code="IPC_CL",
            period_year=2026,
            period_month=1,
            index_value=Decimal("112.340000"),
            source="bcch",
        )
    ]
    assert await missing_provider.fetch_rate("UF", date(2026, 1, 31)) is None
    assert await provider.fetch_rate_entries("UF", []) == []
    assert await list_provider.fetch_indices("IPC_CL", []) == []


async def test_bcch_series_provider_handles_fetch_failures_and_empty_obs() -> None:
    """Test bcch series provider handles fetch failures and empty observations."""
    failing = BcchSeriesProvider(
        user="user",
        password="pass",
        series_codes={"UF": "UF_SERIES", "IPC_CL": "IPC_SERIES"},
        fetcher=lambda url, timeout: (_ for _ in ()).throw(URLError("offline")),
    )
    malformed = BcchSeriesProvider(
        user="user",
        password="pass",
        series_codes={"UF": "UF_SERIES", "IPC_CL": "IPC_SERIES"},
        fetcher=lambda url, timeout: '{"Series":{}}',
    )
    missing_values = BcchSeriesProvider(
        user="user",
        password="pass",
        series_codes={"UF": "UF_SERIES", "IPC_CL": "IPC_SERIES"},
        fetcher=lambda url, timeout: '{"Series":{"Obs":[{"value":null}]}}',
    )

    assert await failing.fetch_rate("UF", date(2026, 1, 31)) is None
    assert await malformed.fetch_index("IPC_CL", 2026, 1) is None
    assert await missing_values.fetch_rate("UF", date(2026, 1, 31)) is None
    assert await missing_values.fetch_index("IPC_CL", 2026, 1) is None
    assert await failing.fetch_rate_entries("UF", [date(2026, 1, 31)]) == []
    assert await malformed.fetch_indices("IPC_CL", [(2026, 1)]) == []
    assert await missing_values.fetch_rate_entries("UF", [date(2026, 1, 31)]) == []
    assert await missing_values.fetch_indices("IPC_CL", [(2026, 1)]) == []


async def test_chained_rate_and_index_providers_use_first_success() -> None:
    """Test chained providers stop on first success and swallow failures."""

    class FailingFx:
        """Represent Failing Fx."""

        name = "broken"

        async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
            """Handle fetch rate."""
            raise RuntimeError("boom")

        async def fetch_rate_entries(
            self, currency_code: str, requested_dates: list[date]
        ) -> list[ExchangeRateWriteDTO]:
            """Handle fetch rate entries."""
            raise RuntimeError("boom")

    class WorkingFx:
        """Represent Working Fx."""

        name = "mindicador"

        async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
            """Handle fetch rate."""
            return Decimal("950.12")

        async def fetch_rate_entries(
            self, currency_code: str, requested_dates: list[date]
        ) -> list[ExchangeRateWriteDTO]:
            """Handle fetch rate entries."""
            return _rate_entries(currency_code, requested_dates, "mindicador")

    class FailingIndex:
        """Represent Failing Index."""

        name = "broken"

        async def fetch_index(
            self, code: str, period_year: int, period_month: int
        ) -> EconomicIndexWriteDTO | None:
            """Handle fetch index."""
            raise RuntimeError("boom")

        async def fetch_indices(
            self, code: str, requested_periods: list[tuple[int, int]]
        ) -> list[EconomicIndexWriteDTO]:
            """Handle fetch indices."""
            raise RuntimeError("boom")

    class WorkingIndex:
        """Represent Working Index."""

        name = "sii"

        async def fetch_index(
            self, code: str, period_year: int, period_month: int
        ) -> EconomicIndexWriteDTO | None:
            """Handle fetch index."""
            return EconomicIndexWriteDTO(
                code=code,
                period_year=period_year,
                period_month=period_month,
                index_value=Decimal("109.71"),
                source="sii",
            )

        async def fetch_indices(
            self, code: str, requested_periods: list[tuple[int, int]]
        ) -> list[EconomicIndexWriteDTO]:
            """Handle fetch indices."""
            return _index_entries(code, requested_periods, "sii")

    fx_chain = ChainedFxProvider([FailingFx(), WorkingFx()])
    index_chain = ChainedEconomicIndexProvider([FailingIndex(), WorkingIndex()])

    assert await fx_chain.fetch_rate("USD", date(2026, 1, 31)) == Decimal("950.12")
    assert await fx_chain.fetch_rate_entry(
        "USD", date(2026, 1, 31)
    ) == ExchangeRateWriteDTO(
        currency_code="USD",
        rate_date=date(2026, 1, 31),
        value_clp=Decimal("950.12"),
        source="mindicador",
    )
    assert await index_chain.fetch_index("IPC_CL", 2026, 1) == EconomicIndexWriteDTO(
        code="IPC_CL",
        period_year=2026,
        period_month=1,
        index_value=Decimal("109.71"),
        source="sii",
    )
    assert await fx_chain.fetch_rate_entries("USD", [date(2026, 1, 31)]) == [
        ExchangeRateWriteDTO(
            currency_code="USD",
            rate_date=date(2026, 1, 31),
            value_clp=Decimal("950.12"),
            source="mindicador",
        )
    ]
    assert await index_chain.fetch_indices("IPC_CL", [(2026, 1)]) == [
        EconomicIndexWriteDTO(
            code="IPC_CL",
            period_year=2026,
            period_month=1,
            index_value=Decimal("109.71"),
            source="sii",
        )
    ]


async def test_chained_bulk_providers_stop_after_full_match() -> None:
    """Test chained bulk providers stop once all requests are satisfied."""
    called = {"fx": 0, "index": 0}

    class FirstFx:
        """Provide all requested FX entries."""

        async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
            """Handle fetch rate."""
            return Decimal("950.12")

        async def fetch_rate_entries(
            self, currency_code: str, requested_dates: list[date]
        ) -> list[ExchangeRateWriteDTO]:
            """Handle fetch rate entries."""
            return _rate_entries(currency_code, requested_dates, "first")

    class SecondFx:
        """Fail if called after requests were already satisfied."""

        async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
            """Handle fetch rate."""
            called["fx"] += 1
            raise AssertionError("should not be called")

        async def fetch_rate_entries(
            self, currency_code: str, requested_dates: list[date]
        ) -> list[ExchangeRateWriteDTO]:
            """Handle fetch rate entries."""
            called["fx"] += 1
            raise AssertionError("should not be called")

    class FirstIndex:
        """Provide all requested index entries."""

        async def fetch_index(
            self, code: str, period_year: int, period_month: int
        ) -> EconomicIndexWriteDTO | None:
            """Handle fetch index."""
            return EconomicIndexWriteDTO(
                code=code,
                period_year=period_year,
                period_month=period_month,
                index_value=Decimal("109.71"),
                source="first",
            )

        async def fetch_indices(
            self, code: str, requested_periods: list[tuple[int, int]]
        ) -> list[EconomicIndexWriteDTO]:
            """Handle fetch indices."""
            return _index_entries(code, requested_periods, "first")

    class SecondIndex:
        """Fail if called after requests were already satisfied."""

        async def fetch_index(
            self, code: str, period_year: int, period_month: int
        ) -> EconomicIndexWriteDTO | None:
            """Handle fetch index."""
            called["index"] += 1
            raise AssertionError("should not be called")

        async def fetch_indices(
            self, code: str, requested_periods: list[tuple[int, int]]
        ) -> list[EconomicIndexWriteDTO]:
            """Handle fetch indices."""
            called["index"] += 1
            raise AssertionError("should not be called")

    assert await ChainedFxProvider([FirstFx(), SecondFx()]).fetch_rate_entries(
        "USD", [date(2026, 1, 31)]
    ) == [
        ExchangeRateWriteDTO(
            currency_code="USD",
            rate_date=date(2026, 1, 31),
            value_clp=Decimal("950.12"),
            source="first",
        )
    ]
    assert await ChainedEconomicIndexProvider(
        [FirstIndex(), SecondIndex()]
    ).fetch_indices("IPC_CL", [(2026, 1)]) == [
        EconomicIndexWriteDTO(
            code="IPC_CL",
            period_year=2026,
            period_month=1,
            index_value=Decimal("109.71"),
            source="first",
        )
    ]
    assert called == {"fx": 0, "index": 0}


async def test_chained_economic_index_provider_returns_none_when_all_miss() -> None:
    """Test chained economic index provider returns none when all providers miss."""

    class MissingIndex:
        """Represent Missing Index."""

        async def fetch_index(
            self, code: str, period_year: int, period_month: int
        ) -> EconomicIndexWriteDTO | None:
            """Handle fetch index."""
            return None

        async def fetch_indices(
            self, code: str, requested_periods: list[tuple[int, int]]
        ) -> list[EconomicIndexWriteDTO]:
            """Handle fetch indices."""
            return []

    assert (
        await ChainedEconomicIndexProvider([MissingIndex()]).fetch_index(
            "IPC_CL", 2026, 1
        )
        is None
    )


def test_rate_provider_helpers_cover_local_fetch_and_edge_parsing(
    tmp_path: Path,
) -> None:
    """Test rate provider helpers cover local fetch and edge parsing."""
    sample = tmp_path / "sample.json"
    sample.write_text('{"ok": true}', encoding="utf-8")

    assert '"ok": true' in _fetch_url(sample.as_uri(), 5)

    # _proxy_is_reachable: reachable when a server listens, unreachable otherwise.
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        free_port = srv.getsockname()[1]
        assert _proxy_is_reachable(f"http://127.0.0.1:{free_port}", timeout=2.0)
    assert not _proxy_is_reachable("http://127.0.0.1:1", timeout=0.5)

    # _resolve_proxy_handler: explicit proxy URL is always used.
    explicit = _resolve_proxy_handler("http://proxy.example.com:8080")
    assert explicit.proxies == {
        "http": "http://proxy.example.com:8080",
        "https": "http://proxy.example.com:8080",
    }
    # Auto-detect with reachable proxy → uses the supplied system proxies.
    with socket.socket() as srv2:
        srv2.bind(("127.0.0.1", 0))
        srv2.listen(1)
        proxy_port = srv2.getsockname()[1]
        reachable = _resolve_proxy_handler(
            None, {"https": f"http://127.0.0.1:{proxy_port}"}
        )
    assert reachable.proxies == {"https": f"http://127.0.0.1:{proxy_port}"}
    # Auto-detect with unreachable proxy → bypass (empty proxies dict).
    bypass = _resolve_proxy_handler(None, {"https": "http://127.0.0.1:1"})
    assert bypass.proxies == {}

    # make_fetcher: both proxy paths return a callable that reads local file:// URIs
    # (proxy handlers do not affect the file:// scheme).
    assert '"ok": true' in make_fetcher()(sample.as_uri(), 5)
    assert '"ok": true' in make_fetcher("http://proxy.example.com:8080")(
        sample.as_uri(), 5
    )
    assert _parse_chilean_decimal(" ") is None
    assert _parse_chilean_amount("$ 38.613,24") == Decimal("38613.24")
    assert _parse_chilean_amount("Y MÁS") is None
    assert _parse_month_heading("Sin mes") is None
    assert _parse_month_heading("Foo 2026") is None
    assert _extract_sii_rows(
        "<table><tr></tr><tr><td>Enero</td><td>69.751</td></tr></table>"
    ) == {1: ["Enero", "69.751"]}
    assert _extract_income_tax_month_rows(
        "<h3>Marzo 2026</h3><div class='table-responsive'>"
        "<table><tbody><tr><td>MENSUAL</td></tr></tbody></table></div>"
    ) == {date(2026, 3, 1): [["MENSUAL"]]}
    assert (
        _extract_income_tax_month_rows(
            "<h3>Foo 2026</h3><div class='table-responsive'>"
            "<table><tbody><tr><td>MENSUAL</td></tr></tbody></table></div>"
        )
        == {}
    )
    assert _build_monthly_income_tax_brackets(date(2026, 3, 1), [["QUINCENAL"]]) == []
    assert (
        _build_monthly_income_tax_brackets(date(2026, 3, 1), [["MENSUAL", "-.-"]]) == []
    )
    assert _build_monthly_income_tax_brackets(
        date(2026, 3, 1),
        [
            ["MENSUAL", "-.-", "$ 1.350,00", "Exento", "-.-"],
            ["", "$ 1.350,01"],
            ["", "$ 2.000,00", "$ 3.000,00", "", "$ 100,00"],
        ],
    ) == [
        IncomeTaxBracketWriteDTO(
            valid_from=date(2026, 3, 1),
            valid_to=date(2026, 3, 31),
            lower_bound_utm=Decimal("0.0000"),
            upper_bound_utm=Decimal("13.5000"),
            marginal_rate=Decimal("0"),
            rebate_utm=Decimal("0.0000"),
        )
    ]


async def test_chained_fx_fetch_rate_entry_returns_none_when_no_match() -> None:
    """fetch_rate_entry returns None when all providers return None."""

    class _NoneProvider:
        async def fetch_rate(self, currency_code: str, on: date) -> None:
            """Return None unconditionally."""
            return None

    chain = ChainedFxProvider([_NoneProvider()])  # type: ignore[arg-type]
    result = await chain.fetch_rate_entry("USD", date(2026, 1, 31))
    assert result is None


async def test_mindicador_empty_serie_returns_empty() -> None:
    """Mindicador returns empty when the API responds with an empty serie list."""
    provider = MindicadorRateProvider(fetcher=lambda url, timeout: '{"serie":[]}')

    assert await provider.fetch_rate("USD", date(2026, 1, 31)) is None
    assert await provider.fetch_rate_entries("USD", [date(2026, 1, 31)]) == []


async def test_mindicador_handles_timeout_error() -> None:
    """Mindicador returns empty/None when the fetcher raises TimeoutError."""
    provider = MindicadorRateProvider(
        fetcher=lambda url, timeout: (_ for _ in ()).throw(
            TimeoutError("read timed out")
        )
    )

    assert await provider.fetch_rate("USD", date(2026, 1, 31)) is None
    assert await provider.fetch_rate_entries("USD", [date(2026, 1, 31)]) == []


async def test_sii_indicators_provider_handles_timeout_error() -> None:
    """SII provider returns empty/None when the fetcher raises TimeoutError."""
    provider = SiiIndicatorsProvider(
        fetcher=lambda url, timeout: (_ for _ in ()).throw(
            TimeoutError("read timed out")
        )
    )

    assert await provider.fetch_rate("UTM", date(2026, 1, 15)) is None
    assert await provider.fetch_indices("IPC_CL", [(2026, 1)]) == []


async def test_bcch_series_code_not_configured_returns_empty() -> None:
    """BCCH returns empty when credentials are set but the series code is missing."""
    provider = BcchSeriesProvider(
        user="user",
        password="pass",
        series_codes={},  # no USD mapping
    )

    assert await provider.fetch_rate("USD", date(2026, 1, 31)) is None
    assert await provider.fetch_rate_entries("USD", [date(2026, 1, 31)]) == []
    assert await provider.fetch_indices("IPC_CL", [(2026, 1)]) == []


async def test_bcch_handles_timeout_error() -> None:
    """BCCH returns empty/None when the fetcher raises TimeoutError."""
    provider = BcchSeriesProvider(
        user="user",
        password="pass",
        series_codes={"USD": "USD_SERIES"},
        fetcher=lambda url, timeout: (_ for _ in ()).throw(
            TimeoutError("read timed out")
        ),
    )

    assert await provider.fetch_rate("USD", date(2026, 1, 31)) is None
    assert await provider.fetch_rate_entries("USD", [date(2026, 1, 31)]) == []


async def test_chained_provider_logs_exhausted_when_all_providers_return_empty() -> (
    None
):
    """Chain returns empty and warns when no provider fills all requested items."""

    class EmptyFx:
        """Return no entries for any request."""

        async def fetch_rate_entries(
            self, currency_code: str, requested_dates: list[date]
        ) -> list[ExchangeRateWriteDTO]:
            """Handle fetch rate entries."""
            return []

    class EmptyIndex:
        """Return no entries for any request."""

        async def fetch_indices(
            self, code: str, requested_periods: list[tuple[int, int]]
        ) -> list[EconomicIndexWriteDTO]:
            """Handle fetch indices."""
            return []

    assert (
        await ChainedFxProvider([EmptyFx()]).fetch_rate_entries(  # type: ignore[arg-type]
            "USD", [date(2026, 1, 31)]
        )
        == []
    )
    assert (
        await ChainedEconomicIndexProvider([EmptyIndex()]).fetch_indices(  # type: ignore[arg-type]
            "IPC_CL", [(2026, 1)]
        )
        == []
    )
