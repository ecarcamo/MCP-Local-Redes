# Sync Licensing MCP Server

A local **Model Context Protocol** server that exposes the catalog and the
business logic of a music **sync-licensing** platform: searching tracks by
creative brief, checking their rights clearance, quoting a licence under
conditional pricing rules, issuing the contract and registering the usage.

Built for CC3067 *Redes* (Universidad del Valle de Guatemala), Project 1.
The MCP message flow is implemented **directly on top of JSON-RPC 2.0** — no
MCP SDK, no FastMCP, no framework. The server package depends on the Python
standard library only.

---

## Table of contents

1. [The business case](#1-the-business-case)
2. [Architecture](#2-architecture)
3. [Requirements](#3-requirements)
4. [Installation](#4-installation)
5. [Building the catalog](#5-building-the-catalog)
6. [Usage](#6-usage)
7. [Tool reference](#7-tool-reference)
8. [Pricing rules](#8-pricing-rules)
9. [Protocol details](#9-protocol-details)
10. [Where the data comes from](#10-where-the-data-comes-from)
11. [Testing](#11-testing)
12. [Project layout](#12-project-layout)
13. [Project status](#13-project-status)

---

## 1. The business case

Sync licensing is the business model of platforms such as Epidemic Sound,
Artlist and Musicbed: a creator or an ad agency must buy a licence before using
a track in audiovisual content. The process has three frictions:

* **Finding** a track that fits the creative brief *and* the budget is slow.
* The **legal status** of a track is not obvious — it may contain samples that
  were never cleared, or be frozen by an authorship dispute.
* The **price is not fixed**. The same track costs one thing for an Instagram
  post and something else entirely for a national TV campaign.

This server turns that workflow into five tools an assistant can chain. It is
not a search engine with a price list attached: the fee is computed from
conditional rules, and the tools refuse operations that would put the client at
legal risk.

## 2. Architecture

```
        ┌────────────────────────┐
        │  Host (chatbot / CLI)  │
        └───────────┬────────────┘
                    │  spawns as a subprocess
        ┌───────────▼────────────┐
        │   MCP client           │   client/mcp_cli.py
        └───────────┬────────────┘
                    │  JSON-RPC 2.0 over stdio
                    │  (one JSON object per line)
        ┌───────────▼────────────┐
        │   MCP server           │   synclicense_mcp/
        │                        │
        │   jsonrpc.py  framing  │
        │   server.py   dispatch │
        │   tools.py    5 tools  │
        │   pricing.py  rate card│
        │   contracts.py contracts
        │   catalog.py  catalog  │
        └───────────┬────────────┘
                    │
        ┌───────────▼────────────┐
        │  data/catalog.json     │  built by scripts/seed_catalog.py
        │  data/usage_log.jsonl  │  append-only audit log
        └────────────────────────┘
```

`stdout` carries protocol traffic only; every diagnostic the server prints goes
to `stderr`, so piping the server's output never corrupts the stream.

## 3. Requirements

* **Python 3.10 or newer** (developed on 3.11).
* No other dependency to run the server.
* `requests` is only needed to pull real metadata from Jamendo, and `pytest`
  only to run the test suite. Both are in `requirements.txt`.

## 4. Installation

```bash
git clone https://github.com/ecarcamo/MCP-Local-Redes.git
cd MCP-Local-Redes

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

The package is **not installed**: it is imported from the repository root, so
every command below is run from the project directory.

## 5. Building the catalog

The repository already ships a generated catalog at `data/catalog.json`
(800 tracks), so you can skip this section and go straight to
[Usage](#6-usage). Rebuild it if you want a different size or a different seed.

### Offline mode (default, no credentials, no network)

```bash
python scripts/seed_catalog.py --offline --count 800
```

Deterministic: the same `--seed` always produces the same catalog.

### Jamendo mode (real Creative Commons metadata)

Register at <https://devportal.jamendo.com> to get a `client_id`, then:

```bash
cp .env.example .env
# edit .env and set JAMENDO_CLIENT_ID=your_client_id

python scripts/seed_catalog.py --jamendo --count 800
```

| Option | Default | Description |
|---|---|---|
| `--offline` / `--jamendo` | `--offline` | Source of the track metadata |
| `--count N` | `800` | How many tracks to write |
| `--seed N` | `23016` | Seed for the simulated business layer |
| `--output PATH` | `data/catalog.json` | Where to write the catalog |

## 6. Usage

### 6.1 Run the guided demo (start here)

The fastest way to see the whole thing working. It spawns the server, runs the
complete licensing conversation, and prints **every JSON-RPC message** that
crosses the wire (`-->` sent, `<--` received):

```bash
python client/mcp_cli.py --demo
```

The demo walks through: handshake → `tools/list` → search a track → check its
clearance → quote it → issue the contract → register the usage → and three
failure cases (a blocked track, a quote that belongs to another track, and an
invalid argument).

Add `--quiet` to hide the raw protocol trace and see only the answers:

```bash
python client/mcp_cli.py --demo --quiet
```

### 6.2 Interactive session

A REPL to call any tool by hand:

```bash
python client/mcp_cli.py --interactive
```

```
mcp> list
mcp> schema calcular_costo_licencia
mcp> call buscar_pista {"mood": "epico", "genero": "cinematica", "presupuesto_max": 80}
mcp> call verificar_clearance {"pista_id": "TRK-00001"}
mcp> call calcular_costo_licencia {"pista_id": "TRK-00001", "tipo_uso": "tv_nacional", "territorio": "mundial", "exclusividad": "sectorial", "duracion_meses": 12}
mcp> raw ping
mcp> quit
```

| Command | Description |
|---|---|
| `list` | Tools published by the server |
| `schema <tool>` | JSON Schema of one tool |
| `call <tool> <json>` | Call a tool with JSON arguments |
| `ping` | Send a JSON-RPC ping |
| `raw <method> [json]` | Send any JSON-RPC method by hand |
| `quit` | Close the session |

### 6.3 Run the server on its own

```bash
python -m synclicense_mcp
```

It then waits for JSON-RPC messages on `stdin`. Use `--catalog PATH` to point it
at a different catalog file.

### 6.4 Talk to it with no client at all

Because the transport is just newline-delimited JSON, you can drive the server
straight from the shell:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"shell","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"verificar_clearance","arguments":{"pista_id":"TRK-00001"}}}' \
  | python -m synclicense_mcp
```

## 7. Tool reference

| Tool | Required arguments | Returns |
|---|---|---|
| `buscar_pista` | *(none — every filter is optional)* | Candidate tracks with id, title, artist, duration and base fee |
| `verificar_clearance` | `pista_id` | Legal status: cleared, samples pending, or blocked |
| `calcular_costo_licencia` | `pista_id`, `tipo_uso`, `territorio`, `exclusividad`, `duracion_meses` | Full fee breakdown, total in USD, and a `cotizacion_id` |
| `generar_contrato` | `pista_id`, `cliente`, `cotizacion_id` | Contract with scope, term, amount, restrictions, and a `contrato_id` |
| `registrar_uso` | `contrato_id`, `plataforma`, `url_proyecto` | Usage record filed for royalties and audit |

### 7.1 `buscar_pista`

Optional filters: `mood`, `genero`, `instrumental`, `duracion_seg_min`,
`duracion_seg_max`, `presupuesto_max`, `limite` (1–20, default 5).

* `mood`: `alegre`, `epico`, `melancolico`, `relajado`, `tenso`, `energetico`,
  `inspirador`, `oscuro`
* `genero`: `pop`, `rock`, `electronica`, `hip_hop`, `jazz`, `clasica`, `folk`,
  `ambient`, `cinematica`, `latina`

Tracks blocked by an authorship dispute are excluded: they cannot be licensed,
so offering them would be a false positive.

### 7.2 `verificar_clearance`

| Status | Licensable | Effect |
|---|---|---|
| `libre` | yes | No encumbrance |
| `samples_pendientes` | yes | +15% escrow surcharge and a hold-back clause |
| `bloqueada` | **no** | Authorship dispute; quoting and contracting are refused |

### 7.3 `calcular_costo_licencia`

| Argument | Allowed values |
|---|---|
| `tipo_uso` | `redes_sociales`, `evento_interno`, `podcast`, `web_corporativo`, `publicidad_online`, `videojuego`, `tv_nacional`, `cine` |
| `territorio` | `local`, `latam`, `europa`, `norteamerica`, `mundial` |
| `exclusividad` | `no`, `sectorial`, `total` |
| `duracion_meses` | `0` (perpetual) or 1–120 |

Example request and response:

```json
--> {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{
      "name":"calcular_costo_licencia",
      "arguments":{"pista_id":"TRK-00001","tipo_uso":"redes_sociales",
                   "territorio":"local","exclusividad":"no","duracion_meses":6}}}

<-- {"jsonrpc":"2.0","id":5,"result":{
      "content":[{"type":"text","text":"Quote for TRK-00001 \"Sunburst\" ... TOTAL USD 45.00"}],
      "structuredContent":{
        "ok":true,
        "cotizacion_id":"COT-3D18B1547D",
        "pista_id":"TRK-00001",
        "alcance":{"tipo_uso":"redes_sociales","territorio":"local",
                   "exclusividad":"no","duracion_meses":6},
        "desglose":{"tarifa_base_usd":45.0,
                    "multiplicadores":{"tipo_uso":1.0,"territorio":1.0,
                                       "exclusividad":1.0,"vigencia":1.0},
                    "subtotal_usd":45.0,"recargo_escrow_usd":0.0,
                    "total_usd":45.0,"moneda":"USD"},
        "valida_hasta":"2026-09-19T18:15:54+00:00"},
      "isError":false}}
```

### 7.4 Tool chaining

The tools are stateful within a session, which is the point of the use case:

```
buscar_pista ──► pista_id
                    ├──► verificar_clearance      (can stop the whole flow)
                    └──► calcular_costo_licencia ──► cotizacion_id
                                                        └──► generar_contrato ──► contrato_id
                                                                                     └──► registrar_uso
```

`generar_contrato` rejects a quote that does not exist, has expired (30 days),
or was issued for a different track. `registrar_uso` rejects an unknown or
inactive contract. Quotes and contracts belong to one connection and are not
shared between sessions.

## 8. Pricing rules

```
subtotal = tarifa_base × mult_use × mult_territory × mult_exclusivity × mult_term
total    = subtotal + escrow surcharge (15% when the track has pending samples)
```

| Type of use | × | Territory | × | Exclusivity | × | Term | × |
|---|---|---|---|---|---|---|---|
| `redes_sociales` | 1.0 | `local` | 1.0 | `no` | 1.0 | ≤ 3 months | 0.8 |
| `evento_interno` | 1.1 | `latam` | 1.8 | `sectorial` | 2.0 | ≤ 6 months | 1.0 |
| `podcast` | 1.3 | `europa` | 2.2 | `total` | 4.5 | ≤ 12 months | 1.5 |
| `web_corporativo` | 1.6 | `norteamerica` | 2.4 | | | ≤ 24 months | 2.2 |
| `publicidad_online` | 2.5 | `mundial` | 3.2 | | | ≤ 36 months | 2.8 |
| `videojuego` | 4.0 | | | | | > 36 months | 3.2 |
| `tv_nacional` | 6.0 | | | | | perpetual | 3.5 |
| `cine` | 8.0 | | | | | | |

Six months is the reference term, which is why it sits at 1.0. A quote holds
its price for 30 days.

## 9. Protocol details

**Transport.** stdio, one JSON-RPC 2.0 message per line, UTF-8, no embedded
newlines. The server exits cleanly on EOF.

**Protocol versions.** `2025-11-25` (preferred) and `2025-06-18`. If the client
asks for anything else, the server answers with its preferred version instead
of failing the handshake.

**Methods.**

| Method | Result |
|---|---|
| `initialize` | Negotiated version, capabilities, server info, instructions |
| `notifications/initialized` | *(notification — no response)* |
| `ping` | `{}` |
| `tools/list` | The five tool descriptors with their JSON Schemas |
| `tools/call` | `content`, `structuredContent`, `isError` |

**Error codes.**

| Code | Meaning |
|---|---|
| `-32700` | Parse error — the line is not valid JSON |
| `-32600` | Invalid request — bad envelope |
| `-32601` | Method not found |
| `-32602` | Invalid params — missing, ill-typed or out-of-enum argument, or unknown tool |
| `-32603` | Internal error |
| `-32002` | Server not initialized — a request arrived before the handshake |

**Protocol errors vs. business errors.** A malformed call comes back as a
JSON-RPC `error`. A well-formed call that the licensing rules refuse — a blocked
track, an expired quote, an unknown contract — comes back as a **successful**
response carrying `isError: true` and a readable explanation, so a model can
read the reason and correct course instead of seeing a transport failure.

A full specification is in [docs/SERVER_SPEC.md](docs/SERVER_SPEC.md).

## 10. Where the data comes from

**Track metadata** (title, artist, duration, genre, mood, licence) comes from
the public [Jamendo API](https://developer.jamendo.com/v3.0), which exposes a
Creative Commons catalog. The offline generator produces the same shape locally
so the project runs without credentials or network access.

**The business layer is simulated, on purpose.** No platform publishes its rate
card or the internal legal status of each track, so `tarifa_base_usd` and
`estado_derechos` are generated from a fixed seed with a realistic distribution
(82% cleared, 13% samples pending, 5% blocked). The rate-card multipliers were
designed from the public royalty-free rate cards of platforms such as
[Jamendo Licensing](https://licensing.jamendo.com/en/royalty-free-music).
This scope was reviewed and approved by the course instructor.

## 11. Testing

```bash
python -m pytest tests/ -v
```

The suite covers the rate-card rules, the JSON-RPC framing, the handshake, the
error codes, the tool chain and its refusals, and one end-to-end test that
launches the real server process and speaks the stdio transport to it.

## 12. Project layout

```
MCP-Local-Redes/
├── synclicense_mcp/          MCP server package (standard library only)
│   ├── __main__.py           entry point: python -m synclicense_mcp
│   ├── jsonrpc.py            JSON-RPC 2.0 framing over stdio
│   ├── server.py             MCP method dispatch
│   ├── tools.py              the five tools: schemas, validation, handlers
│   ├── pricing.py            conditional rate card
│   ├── contracts.py          contracts and usage registration
│   ├── catalog.py            catalog loading and search
│   └── errors.py             business-rule failures
├── client/mcp_cli.py         manual JSON-RPC client (demo + REPL)
├── scripts/seed_catalog.py   catalog builder (offline / Jamendo)
├── data/catalog.json         generated catalog
├── tests/                    pytest suite
└── docs/                     proposal, assignment brief, server specification
```

## 13. Project status

Delivered in this stage:

* Local MCP server over stdio with the five tools of the approved use case.
* JSON-RPC 2.0 and the MCP handshake implemented by hand.
* Command-line client with a scripted demo and an interactive REPL.
* Catalog seeding, in both offline and Jamendo modes.
* Test suite.

Planned for the rest of the project:

* Chatbot host on the Anthropic API, with session context and a visible log of
  every MCP interaction.
* Integration with the official Filesystem and Git MCP servers.
* The same server deployed remotely over HTTP.
* Wireshark capture and layer-by-layer analysis of the remote traffic.

---

**Author:** Esteban Cárcamo (23016) — CC3067 Redes, Section 20
