"""Live free-tier tests for the UniRate Open WebUI tool.

Gated by the UNIRATE_API_KEY env var and self-skips when it is absent, so the
default (mock) gate never hits the network. Only exercises free-tier endpoints
(rates / convert / currencies / vat) — never the Pro-gated historical ones.

Run:  UNIRATE_API_KEY=... python test_live.py
"""

import asyncio
import os
import sys

from unirate_converter import Tools

KEY = os.environ.get("UNIRATE_API_KEY")

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}  {detail}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail}")


def main():
    if not KEY:
        print("UNIRATE_API_KEY not set — skipping live tests.")
        return
    t = Tools()
    t.valves.api_key = KEY

    out = asyncio.run(t.get_exchange_rate("USD", "EUR"))
    check("live get_exchange_rate USD->EUR", "USD" in out and "EUR" in out and "Error" not in out, out)

    out = asyncio.run(t.convert_currency(100, "USD", "JPY"))
    check("live convert 100 USD->JPY", "JPY" in out and "Error" not in out, out)

    out = asyncio.run(t.list_supported_currencies())
    check("live list_supported_currencies", "currencies:" in out and "Error" not in out, out[:60])

    out = asyncio.run(t.get_vat_rate("DE"))
    check("live get_vat_rate DE", "VAT" in out and "Error" not in out, out)

    out = asyncio.run(t.get_exchange_rate("GBP", "USD"))
    check("live get_exchange_rate GBP->USD", "GBP" in out and "Error" not in out, out)

    out = asyncio.run(t.convert_currency(1, "EUR", "USD"))
    check("live convert 1 EUR->USD", "EUR" in out and "Error" not in out, out)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
