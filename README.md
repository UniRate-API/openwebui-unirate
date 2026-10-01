# UniRate Currency Converter — Open WebUI Tool

A single-file [Open WebUI](https://openwebui.com) **Tool** that gives your local
LLM live currency exchange rates, currency conversion, and VAT rates via the
free [UniRate API](https://unirateapi.com).

> **Zero third-party dependencies.** The tool is written against the Python
> standard library only (`urllib`, `json`, `asyncio`). It declares no
> `requirements:`, so installing it pulls **nothing** from PyPI. `pydantic`
> (used only for the Valves config UI) is provided by the Open WebUI runtime,
> with a stdlib fallback if it is ever missing.

## What the model can do

Once installed and enabled for a model, the assistant can call:

| Tool function | What it does |
|---|---|
| `get_exchange_rate(from_currency, to_currency)` | Current rate between two currencies |
| `convert_currency(amount, from_currency, to_currency)` | Convert an amount at the current rate |
| `list_supported_currencies()` | List every supported currency code |
| `get_vat_rate(country_code)` | A country's VAT rate (ISO 3166-1 alpha-2) |

Example prompts:

- "What's the EUR to USD rate right now?"
- "Convert 250 CAD to Japanese yen."
- "Which currencies does the converter support?"
- "What's the VAT rate in Germany?"

## Install

1. Get a free API key at <https://unirateapi.com>.
2. In Open WebUI, go to **Workspace → Tools → Import/Create**, paste the contents
   of [`unirate_converter.py`](./unirate_converter.py), and save. (Or install it
   from the Open WebUI community site.)
3. Open the tool's **Valves** and set **`api_key`**. Optionally set a per-user key
   in **UserValves**.
4. Enable the tool on any model that supports tool/function calling.

## Configuration (Valves)

| Valve | Default | Description |
|---|---|---|
| `api_key` | `""` | Your UniRate API key (stored as a password field) |
| `base_url` | `https://api.unirateapi.com` | API base URL |
| `timeout_seconds` | `30` | Per-request timeout |

Per-user `UserValves.api_key` overrides the admin `api_key` when set.

## Error handling

HTTP errors are mapped to clear, model-friendly messages rather than raised
exceptions, so the assistant can relay them:

| Status | Message |
|---|---|
| 401 | Missing or invalid API key |
| 403 | Endpoint requires a UniRate Pro subscription |
| 404 | Currency not found or no data available |
| 429 | Rate limit exceeded |
| 503 | Service temporarily unavailable |
| network | "Could not reach the UniRate API" |

Only free-tier endpoints are used (`/api/rates`, `/api/convert`,
`/api/currencies`, `/api/vat/rates`). Historical/time-series endpoints are
Pro-gated and intentionally not exposed by this tool.

## Testing

```bash
# Mock suite — stdlib only, no network, no pytest:
python test_unirate_tool.py

# Live free-tier suite (self-skips without a key):
UNIRATE_API_KEY=your-key python test_live.py
```

## Related UniRate clients

Full client libraries in 20+ languages and framework integrations:
<https://github.com/UniRate-API>

## License

MIT © 2026 Unirate Team
