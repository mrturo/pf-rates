"""Official and public provider adapters for Chilean market data."""

from __future__ import annotations

import asyncio
import json
import re
import socket
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from html import unescape
from collections.abc import Awaitable, Callable, Hashable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlencode
from urllib.request import ProxyHandler, build_opener, getproxies, urlopen
from typing import TypeVar

import structlog

from financial_data.application.dto import (
    EconomicIndexWriteDTO,
    ExchangeRateWriteDTO,
    IncomeTaxBracketWriteDTO,
)

_log = structlog.get_logger(__name__)

_MONTHS = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}
_MONTHLY_EXEMPT_LIMIT_UTM = Decimal("13.5")
_BRACKET_UTM_QUANT = Decimal("0.0001")
TKey = TypeVar("TKey", bound=Hashable)
TEntry = TypeVar("TEntry")


def _fetch_url(url: str, timeout_seconds: int) -> str:
    """Handle fetch url."""
    with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
        return response.read().decode(
            response.headers.get_content_charset() or "utf-8", errors="replace"
        )


def _proxy_is_reachable(proxy_url: str, timeout: float = 2.0) -> bool:
    """Return True if a TCP connection to the proxy host:port succeeds."""
    parsed = urlparse(proxy_url)
    host = parsed.hostname or ""
    port = parsed.port or 8080
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _resolve_proxy_handler(
    proxy_url: str | None,
    system_proxies: dict[str, str] | None = None,
) -> ProxyHandler:
    """Return the appropriate ProxyHandler for the given configuration.

    Args:
        proxy_url: Explicit proxy URL. Takes precedence over auto-detection.
        system_proxies: OS/environment proxy map (defaults to ``getproxies()``).
            Provide an explicit value to override auto-detection in tests.
    """
    if proxy_url is not None:
        return ProxyHandler({"http": proxy_url, "https": proxy_url})
    proxies = system_proxies if system_proxies is not None else getproxies()
    detected = proxies.get("https") or proxies.get("http")
    if detected and _proxy_is_reachable(detected):
        return ProxyHandler(proxies)
    return ProxyHandler({})


def make_fetcher(proxy_url: str | None = None) -> Callable[[str, int], str]:
    """Return a URL fetcher with explicit proxy configuration.

    Args:
        proxy_url: Explicit proxy URL (e.g. ``http://proxy.corp.example.com:8080``).
            Pass ``None`` to auto-detect: the OS/environment proxy is used only
            when it is actually reachable (TCP probe); otherwise requests go
            directly to the target host, bypassing all proxy settings.
    """

    def _fetch(url: str, timeout_seconds: int) -> str:
        opener = build_opener(_resolve_proxy_handler(proxy_url))
        with opener.open(url, timeout=timeout_seconds) as response:  # noqa: S310
            return response.read().decode(
                response.headers.get_content_charset() or "utf-8", errors="replace"
            )

    return _fetch


def _parse_json_document(raw: str) -> dict[str, object]:
    """Handle parse json document."""
    return json.loads(raw)


def _parse_iso_date(raw: str) -> date:
    """Handle parse iso date."""
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()


def _extract_observation_date(observation: dict[str, object]) -> date | None:
    """Handle extract observation date."""
    raw_date = (
        observation.get("indexDate")
        or observation.get("fecha")
        or observation.get("date")
        or observation.get("Date")
    )
    if raw_date is None:
        return None
    return _parse_iso_date(str(raw_date))


def _parse_chilean_decimal(raw: str) -> Decimal | None:
    """Handle parse chilean decimal."""
    cleaned = raw.replace("\xa0", "").strip()
    if not cleaned:
        return None
    normalized = cleaned.replace(".", "").replace(",", ".")
    return Decimal(normalized)


def _strip_html(raw: str) -> str:
    """Handle strip html."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", raw))).strip()


def _parse_chilean_amount(raw: str) -> Decimal | None:
    """Handle parse chilean amount."""
    cleaned = (
        raw.replace("$", "")
        .replace("-.-", "")
        .replace("Y MÁS", "")
        .replace("Y MAS", "")
        .strip()
    )
    if not cleaned:
        return None
    return _parse_chilean_decimal(cleaned)


def _build_exchange_rate_entry(
    currency_code: str, rate_date: date, value_clp: Decimal, source: str
) -> ExchangeRateWriteDTO:
    """Build an exchange-rate write DTO."""
    return ExchangeRateWriteDTO(
        currency_code=currency_code.upper(),
        rate_date=rate_date,
        value_clp=value_clp,
        source=source,
    )


async def _rate_entry_from_rate(
    currency_code: str,
    on: date,
    fetch_rate: Callable[[str, date], Awaitable[Decimal | None]],
    source: str,
) -> ExchangeRateWriteDTO | None:
    """Build an exchange-rate entry using a fetch_rate callback."""
    value = await fetch_rate(currency_code, on)
    if value is None:
        return None
    return _build_exchange_rate_entry(currency_code, on, value, source)


def _extract_observation_value(observation: dict[str, object]) -> Decimal | None:
    """Extract a decimal value from a market-data observation."""
    raw_value = (
        observation.get("value")
        or observation.get("Valor")
        or observation.get("obs_value")
    )
    if raw_value is None:
        return None
    return Decimal(str(raw_value).replace(",", "."))


def _group_dates_by_year(requested_dates: list[date]) -> dict[int, list[date]]:
    """Group requested dates by year."""
    grouped_dates: dict[int, list[date]] = {}
    for requested_date in requested_dates:
        grouped_dates.setdefault(requested_date.year, []).append(requested_date)
    return grouped_dates


def _group_periods_by_year(
    requested_periods: list[tuple[int, int]],
) -> dict[int, list[int]]:
    """Group requested periods by year."""
    grouped_periods: dict[int, list[int]] = {}
    for period_year, period_month in requested_periods:
        grouped_periods.setdefault(period_year, []).append(period_month)
    return grouped_periods


def _ordered_entries[TKey: Hashable, TEntry](
    entries_by_key: dict[TKey, TEntry], requested_keys: list[TKey]
) -> list[TEntry]:
    """Return the requested entries preserving their original order."""
    return [
        entries_by_key[requested_key]
        for requested_key in requested_keys
        if requested_key in entries_by_key
    ]


def _extract_sii_rows(html: str) -> dict[int, list[str]]:
    """Handle extract sii rows."""
    rows_by_month: dict[int, list[str]] = {}
    for row in re.findall(
        r"<tr[^>]*>(.*?)</tr>", html, flags=re.IGNORECASE | re.DOTALL
    ):
        cells = [
            _strip_html(cell)
            for cell in re.findall(
                r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL
            )
        ]
        if not cells:
            continue
        month = _MONTHS.get(cells[0].upper())
        if month is not None:
            rows_by_month[month] = cells
    return rows_by_month


def _parse_month_heading(raw: str) -> date | None:
    """Handle parse month heading."""
    match = re.search(r"([A-Za-zÁÉÍÓÚáéíóúñÑ]+)\s+(\d{4})", raw)
    if match is None:
        return None
    month = _MONTHS.get(unescape(match.group(1)).upper())
    if month is None:
        return None
    return date(int(match.group(2)), month, 1)


def _extract_income_tax_month_rows(html: str) -> dict[date, list[list[str]]]:
    """Handle extract income tax month rows."""
    rows_by_month: dict[date, list[list[str]]] = {}
    for section in re.finditer(
        (
            r"<h3>(.*?)</h3>\s*<div class=['\"]table-responsive['\"][^>]*>"
            r".*?<tbody>(.*?)</tbody>"
        ),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        month_start = _parse_month_heading(_strip_html(section.group(1)))
        if month_start is None:
            continue
        rows_by_month[month_start] = [
            [
                _strip_html(cell)
                for cell in re.findall(
                    r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL
                )
            ]
            for row in re.findall(
                r"<tr[^>]*>(.*?)</tr>",
                section.group(2),
                flags=re.IGNORECASE | re.DOTALL,
            )
            if re.findall(
                r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL
            )
        ]
    return rows_by_month


def _quantize_bracket_utm(value: Decimal) -> Decimal:
    """Handle quantize bracket utm."""
    return value.quantize(_BRACKET_UTM_QUANT)


def _build_monthly_income_tax_brackets(
    valid_from: date,
    rows: list[list[str]],
) -> list[IncomeTaxBracketWriteDTO]:
    """Handle build monthly income tax brackets."""
    monthly_rows: list[list[str]] = []
    collecting = False
    for row in rows:
        period_label = row[0].upper() if row else ""
        if period_label:
            if period_label == "MENSUAL":
                collecting = True
            elif collecting:
                break
            else:
                continue
        if collecting:
            monthly_rows.append(row)

    if not monthly_rows:
        return []

    first_upper_clp = (
        _parse_chilean_amount(monthly_rows[0][2]) if len(monthly_rows[0]) > 2 else None
    )
    if first_upper_clp is None or first_upper_clp <= 0:
        return []

    utm_value = first_upper_clp / _MONTHLY_EXEMPT_LIMIT_UTM
    valid_to = date(
        valid_from.year,
        valid_from.month,
        monthrange(valid_from.year, valid_from.month)[1],
    )
    lower_bound_utm = Decimal("0.0000")
    brackets: list[IncomeTaxBracketWriteDTO] = []

    for row in monthly_rows:
        if len(row) < 5:
            continue
        upper_clp = _parse_chilean_amount(row[2])
        factor = (
            Decimal("0")
            if row[3].upper() == "EXENTO"
            else _parse_chilean_decimal(row[3])
        )
        if factor is None:
            continue
        rebate_clp = _parse_chilean_amount(row[4]) or Decimal("0")
        upper_bound_utm = (
            _quantize_bracket_utm(upper_clp / utm_value)
            if upper_clp is not None
            else None
        )
        brackets.append(
            IncomeTaxBracketWriteDTO(
                valid_from=valid_from,
                valid_to=valid_to,
                lower_bound_utm=lower_bound_utm,
                upper_bound_utm=upper_bound_utm,
                marginal_rate=factor,
                rebate_utm=_quantize_bracket_utm(rebate_clp / utm_value),
            )
        )
        if upper_bound_utm is not None:
            lower_bound_utm = upper_bound_utm

    return brackets


class _FetchRateEntryMixin:
    """Mixin that derives fetch_rate_entry from fetch_rate and name."""

    name: str

    async def fetch_rate(  # pragma: no cover
        self, currency_code: str, on: date
    ) -> Decimal | None:
        """Handle fetch rate."""
        raise NotImplementedError

    async def fetch_rate_entry(
        self, currency_code: str, on: date
    ) -> ExchangeRateWriteDTO | None:
        """Handle fetch rate entry."""
        return await _rate_entry_from_rate(
            currency_code, on, self.fetch_rate, self.name
        )


class MindicadorRateProvider(_FetchRateEntryMixin):
    """Provide mindicador rate provider."""

    name = "mindicador"
    _CODE_MAP = {"UF": "uf", "UTM": "utm", "USD": "dolar", "EUR": "euro"}

    def __init__(
        self,
        base_url: str = "https://mindicador.cl/api",
        timeout_seconds: int = 10,
        fetcher: Callable[[str, int], str] | None = None,
    ) -> None:
        """Initialize the instance."""
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._fetcher = fetcher or _fetch_url
        self._series_cache: dict[tuple[str, int], dict[date, Decimal]] = {}

    async def _get_year_series(self, indicator: str, year: int) -> dict[date, Decimal]:
        """Get indicator series for a whole year."""
        cache_key = (indicator, year)
        cached = self._series_cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self._base_url}/{indicator}/{year}"
        try:
            payload = _parse_json_document(
                await asyncio.to_thread(self._fetcher, url, self._timeout_seconds)
            )
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            _log.warning("mindicador_fetch_failed", indicator=indicator, year=year, error=str(exc))
            self._series_cache[cache_key] = {}
            return {}

        series = payload.get("serie")
        if not isinstance(series, list):
            self._series_cache[cache_key] = {}
            return {}

        parsed_series = {
            _parse_iso_date(str(entry["fecha"])): Decimal(str(entry["valor"]))
            for entry in series
            if isinstance(entry, dict) and "fecha" in entry and "valor" in entry
        }
        self._series_cache[cache_key] = parsed_series
        return parsed_series

    async def _get_latest_value_on_or_before(
        self, indicator: str, on: date
    ) -> Decimal | None:
        """Get the latest available value on or before the requested date."""
        series = await self._get_year_series(indicator, on.year)
        matching_dates = [
            series_date for series_date in sorted(series) if series_date <= on
        ]
        if matching_dates:
            return series[matching_dates[-1]]

        previous_year_series = await self._get_year_series(indicator, on.year - 1)
        previous_year_dates = [
            series_date
            for series_date in previous_year_series
            if series_date.year == on.year - 1
        ]
        if not previous_year_dates:
            return None
        latest_previous_year_date = max(previous_year_dates)
        return previous_year_series[latest_previous_year_date]

    async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
        """Handle fetch rate."""
        indicator = self._CODE_MAP.get(currency_code.upper())
        if indicator is None:
            return None
        return await self._get_latest_value_on_or_before(indicator, on)

    async def fetch_rate_entries(
        self, currency_code: str, requested_dates: list[date]
    ) -> list[ExchangeRateWriteDTO]:
        """Handle fetch rate entries."""
        indicator = self._CODE_MAP.get(currency_code.upper())
        if indicator is None:
            return []

        entries_by_date: dict[date, ExchangeRateWriteDTO] = {}
        for year, year_dates in _group_dates_by_year(requested_dates).items():
            series = await self._get_year_series(indicator, year)
            current_value: Decimal | None = None
            if year_dates:
                first_requested_date = min(year_dates)
                current_value = await self._get_latest_value_on_or_before(
                    indicator, first_requested_date
                )
            published_dates = sorted(series)
            published_index = 0
            for requested_date in sorted(year_dates):
                while (
                    published_index < len(published_dates)
                    and published_dates[published_index] <= requested_date
                ):
                    current_value = series[published_dates[published_index]]
                    published_index += 1
                if current_value is None:
                    continue
                entries_by_date[requested_date] = _build_exchange_rate_entry(
                    currency_code, requested_date, current_value, self.name
                )

        return _ordered_entries(entries_by_date, requested_dates)


class _SiiBaseProvider:
    """Shared HTTP-fetcher setup for SII providers."""

    def __init__(
        self,
        base_url: str = "https://www.sii.cl",
        timeout_seconds: int = 10,
        fetcher: Callable[[str, int], str] | None = None,
    ) -> None:
        """Initialize the instance."""
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._fetcher = fetcher or _fetch_url


class SiiIndicatorsProvider(_SiiBaseProvider, _FetchRateEntryMixin):
    """Provide sii indicators provider."""

    name = "sii"

    def __init__(
        self,
        base_url: str = "https://www.sii.cl",
        timeout_seconds: int = 10,
        fetcher: Callable[[str, int], str] | None = None,
    ) -> None:
        """Initialize the instance."""
        super().__init__(
            base_url=base_url, timeout_seconds=timeout_seconds, fetcher=fetcher
        )
        self._rows_cache: dict[int, dict[int, list[str]]] = {}

    async def _get_rows(self, year: int) -> dict[int, list[str]]:
        """Handle get rows."""
        cached = self._rows_cache.get(year)
        if cached is not None:
            return cached
        url = f"{self._base_url}/valores_y_fechas/utm/utm{year}.htm"
        try:
            html = await asyncio.to_thread(self._fetcher, url, self._timeout_seconds)
        except (HTTPError, URLError) as exc:
            _log.warning("sii_fetch_failed", url=url, error=str(exc))
            self._rows_cache[year] = {}
            return {}
        rows = _extract_sii_rows(html)
        self._rows_cache[year] = rows
        return rows

    async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
        """Handle fetch rate."""
        if currency_code.upper() != "UTM":
            return None
        row = (await self._get_rows(on.year)).get(on.month)
        if row is None or len(row) < 2:
            return None
        return _parse_chilean_decimal(row[1])

    async def fetch_rate_entries(
        self, currency_code: str, requested_dates: list[date]
    ) -> list[ExchangeRateWriteDTO]:
        """Handle fetch rate entries."""
        if currency_code.upper() != "UTM":
            return []

        entries_by_date: dict[date, ExchangeRateWriteDTO] = {}
        for year, year_dates in _group_dates_by_year(requested_dates).items():
            rows = await self._get_rows(year)
            for requested_date in year_dates:
                row = rows.get(requested_date.month)
                if row is None or len(row) < 2:
                    continue
                value = _parse_chilean_decimal(row[1])
                if value is None:
                    continue
                entries_by_date[requested_date] = _build_exchange_rate_entry(
                    currency_code, requested_date, value, self.name
                )

        return _ordered_entries(entries_by_date, requested_dates)

    async def fetch_index(
        self, code: str, period_year: int, period_month: int
    ) -> EconomicIndexWriteDTO | None:
        """Handle fetch index."""
        if code.upper() != "IPC_CL":
            return None
        row = (await self._get_rows(period_year)).get(period_month)
        if row is None or len(row) < 6:
            return None

        index_value = _parse_chilean_decimal(row[3])
        if index_value is None:
            return None

        return EconomicIndexWriteDTO(
            code="IPC_CL",
            period_year=period_year,
            period_month=period_month,
            index_value=index_value,
            monthly_change=_parse_chilean_decimal(row[4]),
            yearly_change=_parse_chilean_decimal(row[6]) if len(row) > 6 else None,
            base_period="2023=100",
            source=self.name,
        )

    async def fetch_indices(
        self, code: str, requested_periods: list[tuple[int, int]]
    ) -> list[EconomicIndexWriteDTO]:
        """Handle fetch indices."""
        if code.upper() != "IPC_CL":
            return []

        entries_by_period: dict[tuple[int, int], EconomicIndexWriteDTO] = {}
        for period_year, period_months in _group_periods_by_year(
            requested_periods
        ).items():
            rows = await self._get_rows(period_year)
            for period_month in period_months:
                row = rows.get(period_month)
                if row is None or len(row) < 6:
                    continue
                index_value = _parse_chilean_decimal(row[3])
                if index_value is None:
                    continue
                entries_by_period[(period_year, period_month)] = EconomicIndexWriteDTO(
                    code="IPC_CL",
                    period_year=period_year,
                    period_month=period_month,
                    index_value=index_value,
                    monthly_change=_parse_chilean_decimal(row[4]),
                    yearly_change=_parse_chilean_decimal(row[6])
                    if len(row) > 6
                    else None,
                    base_period="2023=100",
                    source=self.name,
                )

        return _ordered_entries(entries_by_period, requested_periods)


class SiiIncomeTaxBracketProvider(_SiiBaseProvider):
    """Provide sii income tax bracket provider."""

    name = "sii"

    async def fetch_income_tax_brackets(
        self, year: int
    ) -> list[IncomeTaxBracketWriteDTO]:
        """Handle fetch income tax brackets."""
        url = (
            f"{self._base_url}/valores_y_fechas/"
            f"impuesto_2da_categoria/impuesto{year}.htm"
        )
        try:
            html = await asyncio.to_thread(self._fetcher, url, self._timeout_seconds)
        except (HTTPError, URLError) as exc:
            _log.warning("sii_income_tax_fetch_failed", url=url, error=str(exc))
            return []

        brackets: list[IncomeTaxBracketWriteDTO] = []
        for valid_from, rows in sorted(_extract_income_tax_month_rows(html).items()):
            brackets.extend(_build_monthly_income_tax_brackets(valid_from, rows))
        return brackets


class BcchSeriesProvider(_FetchRateEntryMixin):
    """Provide bcch series provider."""

    name = "bcch"

    def __init__(
        self,
        user: str | None,
        password: str | None,
        series_codes: dict[str, str | None],
        base_url: str = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx",
        timeout_seconds: int = 10,
        fetcher: Callable[[str, int], str] | None = None,
    ) -> None:
        """Initialize the instance."""
        self._user = user
        self._password = password
        self._series_codes = {key.upper(): value for key, value in series_codes.items()}
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._fetcher = fetcher or _fetch_url

    async def _fetch_series(
        self, code: str, start: date, end: date
    ) -> list[dict[str, object]]:
        """Handle fetch series."""
        series_code = self._series_codes.get(code.upper())
        if not self._user or not self._password or not series_code:
            return []

        query = urlencode(
            {
                "user": self._user,
                "pass": self._password,
                "function": "GetSeries",
                "timeseries": series_code,
                "firstdate": start.strftime("%d-%m-%Y"),
                "lastdate": end.strftime("%d-%m-%Y"),
            }
        )
        url = f"{self._base_url}?{query}"
        try:
            payload = _parse_json_document(
                await asyncio.to_thread(self._fetcher, url, self._timeout_seconds)
            )
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            _log.warning("bcch_fetch_failed", code=code, error=str(exc))
            return []

        series = payload.get("Series")
        if isinstance(series, dict) and isinstance(series.get("Obs"), list):
            return [entry for entry in series["Obs"] if isinstance(entry, dict)]
        if (
            isinstance(series, list)
            and series
            and isinstance(series[0], dict)
            and isinstance(series[0].get("Obs"), list)
        ):
            return [entry for entry in series[0]["Obs"] if isinstance(entry, dict)]
        return []

    async def fetch_rate(self, currency_code: str, on: date) -> Decimal | None:
        """Handle fetch rate."""
        observations = await self._fetch_series(currency_code, on, on)
        for observation in observations:
            value = _extract_observation_value(observation)
            if value is None:
                continue
            return value
        return None

    async def fetch_rate_entries(
        self, currency_code: str, requested_dates: list[date]
    ) -> list[ExchangeRateWriteDTO]:
        """Handle fetch rate entries."""
        if not requested_dates:
            return []

        observations = await self._fetch_series(
            currency_code, min(requested_dates), max(requested_dates)
        )
        values_by_date: dict[date, Decimal] = {}
        for observation in observations:
            observation_date = _extract_observation_date(observation)
            value = _extract_observation_value(observation)
            if value is None or observation_date is None:
                continue
            values_by_date[observation_date] = value
        return _ordered_entries(
            {
                requested_date: _build_exchange_rate_entry(
                    currency_code,
                    requested_date,
                    values_by_date[requested_date],
                    self.name,
                )
                for requested_date in requested_dates
                if requested_date in values_by_date
            },
            requested_dates,
        )

    async def fetch_index(
        self, code: str, period_year: int, period_month: int
    ) -> EconomicIndexWriteDTO | None:
        """Handle fetch index."""
        month_date = date(period_year, period_month, 1)
        observations = await self._fetch_series(code, month_date, month_date)
        for observation in observations:
            raw_value = (
                observation.get("value")
                or observation.get("Valor")
                or observation.get("obs_value")
            )
            if raw_value is None:
                continue
            return EconomicIndexWriteDTO(
                code=code.upper(),
                period_year=period_year,
                period_month=period_month,
                index_value=Decimal(str(raw_value).replace(",", ".")),
                source=self.name,
            )
        return None

    async def fetch_indices(
        self, code: str, requested_periods: list[tuple[int, int]]
    ) -> list[EconomicIndexWriteDTO]:
        """Handle fetch indices."""
        if not requested_periods:
            return []

        requested_months = [
            date(period_year, period_month, 1)
            for period_year, period_month in requested_periods
        ]
        observations = await self._fetch_series(
            code, min(requested_months), max(requested_months)
        )
        values_by_month: dict[tuple[int, int], Decimal] = {}
        for observation in observations:
            raw_value = (
                observation.get("value")
                or observation.get("Valor")
                or observation.get("obs_value")
            )
            observation_date = _extract_observation_date(observation)
            if raw_value is None or observation_date is None:
                continue
            values_by_month[(observation_date.year, observation_date.month)] = Decimal(
                str(raw_value).replace(",", ".")
            )
        return [
            EconomicIndexWriteDTO(
                code=code.upper(),
                period_year=period_year,
                period_month=period_month,
                index_value=values_by_month[(period_year, period_month)],
                source=self.name,
            )
            for period_year, period_month in requested_periods
            if (period_year, period_month) in values_by_month
        ]
