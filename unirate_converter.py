"""
title: UniRate Currency Converter
description: Live currency exchange rates, currency conversion and VAT rates via the free UniRate API. Ask the model to convert amounts, look up a rate between two currencies, list supported currencies, or fetch a country's VAT rate. Zero third-party dependencies (Python standard library only).
author: UniRate
author_url: https://github.com/UniRate-API
funding_url: https://github.com/UniRate-API
git_url: https://github.com/UniRate-API/openwebui-unirate
version: 0.1.0
license: MIT
required_open_webui_version: 0.5.0
"""

# UniRate Currency Converter — an Open WebUI Tool.
#
# Supply-chain note: this tool imports ONLY the Python standard library
# (urllib, json, asyncio, typing). It declares NO `requirements:` above, so
# installing it pulls NOTHING from PyPI. `pydantic` is used purely for the
# optional Valves config UI and is provided by the Open WebUI host runtime —
# if it is ever absent (e.g. a bare-Python test harness) we fall back to a
# tiny stdlib shim so the tool still imports and runs. Nothing third-party is
# ever installed by this file.

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

try:
    # Provided by the Open WebUI host runtime.
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - exercised only in bare-Python gate
    # Minimal stdlib fallback so the file imports with zero third-party deps.
    def Field(default=None, **_kwargs):
        return default

    class BaseModel:  # type: ignore
        def __init__(self, **data):
            for name in getattr(type(self), "__annotations__", {}):
                setattr(self, name, data.get(name, getattr(type(self), name, None)))


VERSION = "0.1.0"
BASE_URL = "https://api.unirateapi.com"


def _default_transport(
    url: str, headers: Dict[str, str], timeout: float
) -> Tuple[int, str]:
    """Perform a GET with the standard library and return (status, body).

    Kept as a module-level function so tests can inject a fake transport onto
    a Tools instance without any mocking library.
    """
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            pass
        return exc.code, body


class UniRateError(Exception):
    """Raised when the UniRate API returns an error or is unreachable."""


class Tools:
    class Valves(BaseModel):
        api_key: str = Field(
            default="",
            description="Your UniRate API key (free tier at https://unirateapi.com). Can be overridden per-user.",
            json_schema_extra={"input": {"type": "password"}},
        )
        base_url: str = Field(
            default=BASE_URL,
            description="UniRate API base URL. Leave as default unless you self-host a proxy.",
        )
        timeout_seconds: int = Field(
            default=30,
            description="HTTP request timeout in seconds.",
        )

    class UserValves(BaseModel):
        api_key: str = Field(
            default="",
            description="Optional per-user UniRate API key. Overrides the admin key when set.",
            json_schema_extra={"input": {"type": "password"}},
        )

    def __init__(self):
        self.valves = self.Valves()
        # Transport seam: (url, headers, timeout) -> (status_code, body_text).
        # Swappable in tests; defaults to the stdlib implementation above.
        self._transport: Callable[[str, Dict[str, str], float], Tuple[int, str]] = (
            _default_transport
        )

    # ----- internal helpers -------------------------------------------------

    def _resolve_key(self, __user__: Optional[dict]) -> str:
        if __user__ and isinstance(__user__, dict):
            uv = __user__.get("valves")
            key = getattr(uv, "api_key", "") if uv is not None else ""
            if key:
                return key
        return self.valves.api_key or ""

    def _call(self, path: str, params: Dict[str, Any], api_key: str) -> dict:
        query = {"api_key": api_key}
        for k, v in params.items():
            if v is not None:
                query[k] = v
        url = f"{self.valves.base_url.rstrip('/')}{path}?" + urllib.parse.urlencode(
            query
        )
        headers = {
            "Accept": "application/json",  # /api/currencies returns HTML 404 without this
            "User-Agent": f"unirate-openwebui/{VERSION}",
        }
        try:
            status, body = self._transport(
                url, headers, float(self.valves.timeout_seconds)
            )
        except Exception as exc:  # network / transport failure
            raise UniRateError(f"Could not reach the UniRate API: {exc}") from exc

        if status == 200:
            try:
                return json.loads(body)
            except ValueError as exc:
                raise UniRateError("UniRate API returned a non-JSON response") from exc

        messages = {
            400: "Invalid request parameters",
            401: "Missing or invalid API key",
            403: "This endpoint requires a UniRate Pro subscription",
            404: "Currency not found or no data available",
            429: "Rate limit exceeded — slow down and retry",
            503: "UniRate service temporarily unavailable",
        }
        raise UniRateError(
            messages.get(status, f"UniRate API error (HTTP {status}): {body[:200]}")
        )

    async def _acall(self, path: str, params: Dict[str, Any], api_key: str) -> dict:
        # Run the blocking stdlib request off the event loop.
        return await asyncio.to_thread(self._call, path, params, api_key)

    async def _emit(self, emitter, description: str, done: bool) -> None:
        if emitter:
            await emitter(
                {
                    "type": "status",
                    "data": {"description": description, "done": done},
                }
            )

    # ----- tools (callable by the model) ------------------------------------

    async def get_exchange_rate(
        self,
        from_currency: str,
        to_currency: str,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        """
        Get the current exchange rate between two currencies.

        :param from_currency: The base currency's 3-letter ISO 4217 code (e.g. "USD").
        :param to_currency: The target currency's 3-letter ISO 4217 code (e.g. "EUR").
        :return: A short human-readable sentence stating the current rate.
        """
        key = self._resolve_key(__user__)
        if not key:
            return "No UniRate API key is configured. Add one in the tool's valves (get a free key at https://unirateapi.com)."
        src = (from_currency or "").strip().upper()
        dst = (to_currency or "").strip().upper()
        if not src or not dst:
            return "Please provide both a source and a target currency code."
        await self._emit(__event_emitter__, f"Fetching {src}->{dst} rate…", False)
        try:
            data = await self._acall("/api/rates", {"from": src, "to": dst}, key)
        except UniRateError as exc:
            await self._emit(__event_emitter__, "UniRate request failed", True)
            return f"Error: {exc}"
        rate = data.get("rate")
        await self._emit(__event_emitter__, "Rate retrieved", True)
        if rate is None:
            return f"No rate available for {src} to {dst}."
        return f"1 {src} = {rate} {dst} (source: UniRate)."

    async def convert_currency(
        self,
        amount: float,
        from_currency: str,
        to_currency: str,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        """
        Convert an amount of money from one currency to another at the current rate.

        :param amount: The amount of money to convert, in the source currency.
        :param from_currency: The source currency's 3-letter ISO 4217 code (e.g. "USD").
        :param to_currency: The target currency's 3-letter ISO 4217 code (e.g. "JPY").
        :return: A short human-readable sentence stating the converted amount.
        """
        key = self._resolve_key(__user__)
        if not key:
            return "No UniRate API key is configured. Add one in the tool's valves (get a free key at https://unirateapi.com)."
        src = (from_currency or "").strip().upper()
        dst = (to_currency or "").strip().upper()
        if not src or not dst:
            return "Please provide both a source and a target currency code."
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            return "The amount must be a number."
        await self._emit(
            __event_emitter__, f"Converting {amt} {src} -> {dst}…", False
        )
        try:
            data = await self._acall(
                "/api/convert", {"from": src, "to": dst, "amount": amt}, key
            )
        except UniRateError as exc:
            await self._emit(__event_emitter__, "UniRate request failed", True)
            return f"Error: {exc}"
        result = data.get("result")
        await self._emit(__event_emitter__, "Conversion complete", True)
        if result is None:
            return f"Could not convert {amt} {src} to {dst}."
        return f"{amt} {src} = {result} {dst} (source: UniRate)."

    async def list_supported_currencies(
        self,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        """
        List all currency codes supported by the UniRate API.

        :return: A comma-separated list of supported 3-letter currency codes.
        """
        key = self._resolve_key(__user__)
        if not key:
            return "No UniRate API key is configured. Add one in the tool's valves (get a free key at https://unirateapi.com)."
        await self._emit(__event_emitter__, "Fetching supported currencies…", False)
        try:
            data = await self._acall("/api/currencies", {}, key)
        except UniRateError as exc:
            await self._emit(__event_emitter__, "UniRate request failed", True)
            return f"Error: {exc}"
        currencies: List[str] = data.get("currencies", []) or []
        await self._emit(__event_emitter__, "Currencies retrieved", True)
        if not currencies:
            return "No currencies were returned by UniRate."
        return f"UniRate supports {len(currencies)} currencies: " + ", ".join(
            currencies
        )

    async def get_vat_rate(
        self,
        country_code: str,
        __user__: Optional[dict] = None,
        __event_emitter__: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> str:
        """
        Get the value-added tax (VAT) rate for a country.

        :param country_code: The country's 2-letter ISO 3166-1 alpha-2 code (e.g. "DE" for Germany).
        :return: A short human-readable sentence stating the country's VAT rate.
        """
        key = self._resolve_key(__user__)
        if not key:
            return "No UniRate API key is configured. Add one in the tool's valves (get a free key at https://unirateapi.com)."
        country = (country_code or "").strip().upper()
        if not country:
            return "Please provide a 2-letter country code (e.g. 'DE')."
        await self._emit(__event_emitter__, f"Fetching VAT rate for {country}…", False)
        try:
            data = await self._acall("/api/vat/rates", {"country": country}, key)
        except UniRateError as exc:
            await self._emit(__event_emitter__, "UniRate request failed", True)
            return f"Error: {exc}"
        vat = data.get("vat_data") or {}
        await self._emit(__event_emitter__, "VAT rate retrieved", True)
        rate = vat.get("vat_rate")
        name = vat.get("country_name", country)
        if rate is None:
            return f"No VAT rate available for {country}."
        return f"The VAT rate for {name} ({country}) is {rate}% (source: UniRate)."
