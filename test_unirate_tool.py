"""Mock test suite for the UniRate Open WebUI tool.

Runs with the Python standard library only — no pytest, no pydantic, no
network. The tool's transport seam is replaced with a canned function so every
endpoint and error mapping is exercised offline. Exits non-zero on any failure
(so a negative control / CI can detect regressions).
"""

import asyncio
import json
import sys

from unirate_converter import Tools, UniRateError, _default_transport

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def make_tool(responses):
    """responses: dict[path_substring] -> (status, body_dict_or_str)."""
    t = Tools()
    t.valves.api_key = "test-key"

    def fake(url, headers, timeout):
        # sanity: Accept header must always be JSON (gotcha #2)
        assert headers.get("Accept") == "application/json", "missing Accept header"
        assert "api_key=test-key" in url, "api_key not in query"
        for frag, (status, payload) in responses.items():
            if frag in url:
                body = payload if isinstance(payload, str) else json.dumps(payload)
                return status, body
        return 404, json.dumps({"error": "not found"})

    t._transport = fake
    return t


def run(coro):
    return asyncio.run(coro)


# --- happy paths ------------------------------------------------------------

def test_get_rate():
    t = make_tool({"/api/rates": (200, {"rate": "0.92"})})
    out = run(t.get_exchange_rate("usd", "eur"))
    check("get_exchange_rate returns rate", "0.92" in out and "USD" in out and "EUR" in out)


def test_convert():
    t = make_tool({"/api/convert": (200, {"result": "92.50"})})
    out = run(t.convert_currency(100, "usd", "eur"))
    check("convert_currency returns result", "92.50" in out and "EUR" in out)


def test_currencies():
    t = make_tool({"/api/currencies": (200, {"currencies": ["USD", "EUR", "GBP"]})})
    out = run(t.list_supported_currencies())
    check("list_supported_currencies lists codes", "USD" in out and "3 currencies" in out)


def test_vat():
    t = make_tool(
        {"/api/vat/rates": (200, {"country": "DE", "vat_data": {"country_code": "DE", "country_name": "Germany", "vat_rate": 19.0}})}
    )
    out = run(t.get_vat_rate("de"))
    check("get_vat_rate returns rate", "19.0" in out and "Germany" in out)


# --- input handling ---------------------------------------------------------

def test_uppercases_codes():
    seen = {}
    t = Tools()
    t.valves.api_key = "test-key"

    def fake(url, headers, timeout):
        seen["url"] = url
        return 200, json.dumps({"rate": "1.0"})

    t._transport = fake
    run(t.get_exchange_rate("usd", "gbp"))
    check("codes are uppercased in query", "from=USD" in seen["url"] and "to=GBP" in seen["url"])


def test_missing_key():
    t = Tools()  # no api_key set
    out = run(t.get_exchange_rate("USD", "EUR"))
    check("missing key returns friendly message", "API key" in out)


def test_user_valve_override():
    t = Tools()
    t.valves.api_key = "admin-key"
    seen = {}

    def fake(url, headers, timeout):
        seen["url"] = url
        return 200, json.dumps({"rate": "1.0"})

    t._transport = fake

    class UV:
        api_key = "user-key"

    run(t.get_exchange_rate("USD", "EUR", __user__={"valves": UV()}))
    check("per-user key overrides admin key", "api_key=user-key" in seen["url"])


def test_blank_currency():
    t = make_tool({"/api/rates": (200, {"rate": "1.0"})})
    out = run(t.get_exchange_rate("USD", ""))
    check("blank target currency rejected", "both" in out.lower())


def test_bad_amount():
    t = make_tool({"/api/convert": (200, {"result": "1"})})
    out = run(t.convert_currency("not-a-number", "USD", "EUR"))
    check("non-numeric amount rejected", "number" in out.lower())


# --- error mappings ---------------------------------------------------------

def test_auth_error():
    t = make_tool({"/api/rates": (401, {})})
    out = run(t.get_exchange_rate("USD", "EUR"))
    check("401 -> auth message", "invalid API key" in out)


def test_pro_gate():
    t = make_tool({"/api/rates": (403, {})})
    out = run(t.get_exchange_rate("USD", "EUR"))
    check("403 -> Pro subscription message", "Pro" in out)


def test_not_found():
    t = make_tool({"/api/rates": (404, {})})
    out = run(t.get_exchange_rate("USD", "ZZZ"))
    check("404 -> currency-not-found message", "not found" in out)


def test_rate_limit():
    t = make_tool({"/api/convert": (429, {})})
    out = run(t.convert_currency(1, "USD", "EUR"))
    check("429 -> rate-limit message", "Rate limit" in out)


def test_service_unavailable():
    t = make_tool({"/api/currencies": (503, {})})
    out = run(t.list_supported_currencies())
    check("503 -> service-unavailable message", "unavailable" in out)


def test_transport_error():
    t = Tools()
    t.valves.api_key = "test-key"

    def boom(url, headers, timeout):
        raise OSError("network down")

    t._transport = boom
    out = run(t.get_exchange_rate("USD", "EUR"))
    check("transport failure -> reachability message", "reach" in out.lower())


def test_non_json():
    t = make_tool({"/api/rates": (200, "<html>not json</html>")})
    out = run(t.get_exchange_rate("USD", "EUR"))
    check("non-JSON 200 -> error", "non-JSON" in out or "Error" in out)


def test_empty_result():
    t = make_tool({"/api/convert": (200, {})})
    out = run(t.convert_currency(5, "USD", "EUR"))
    check("missing result field handled", "Could not convert" in out)


# --- internal error-raising path (spec parity) ------------------------------

def test_call_raises_on_error():
    t = make_tool({"/api/rates": (401, {})})
    raised = False
    try:
        t._call("/api/rates", {"from": "USD", "to": "EUR"}, "test-key")
    except UniRateError:
        raised = True
    check("_call raises UniRateError on 401", raised)


def test_default_transport_is_stdlib():
    # Proves the shipped default transport is the stdlib one (no injected mock
    # leaking into production) without making a network call.
    check("default transport is _default_transport", Tools()._transport is _default_transport)


def main():
    for fn in [
        test_get_rate,
        test_convert,
        test_currencies,
        test_vat,
        test_uppercases_codes,
        test_missing_key,
        test_user_valve_override,
        test_blank_currency,
        test_bad_amount,
        test_auth_error,
        test_pro_gate,
        test_not_found,
        test_rate_limit,
        test_service_unavailable,
        test_transport_error,
        test_non_json,
        test_empty_result,
        test_call_raises_on_error,
        test_default_transport_is_stdlib,
    ]:
        fn()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
