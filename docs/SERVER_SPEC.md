# MCP Server Specification — Sync Licensing Assistant

Server name: `synclicense-mcp`
Transport: **stdio** (newline-delimited JSON-RPC 2.0 messages)
Protocol versions supported: `2025-11-25`, `2025-06-18`

This document is the contract of the server: transport framing, protocol methods,
tool signatures, business rules and error codes. It is written against the MCP
specification, but **every message is built by hand** — no MCP SDK is used.

---

## 1. Transport

The server reads JSON-RPC messages from `stdin` and writes them to `stdout`.

* One message per line, terminated by `\n`.
* UTF-8 encoded. A message must never contain an embedded newline
  (the JSON encoder is called with `ensure_ascii=False` and no indentation).
* `stdout` carries **protocol traffic only**. All diagnostics go to `stderr`,
  so a host that pipes stdout is never corrupted by log lines.
* The server exits cleanly when stdin reaches EOF.

## 2. Protocol methods

| Method | Type | Result |
|---|---|---|
| `initialize` | request | Negotiated `protocolVersion`, `capabilities`, `serverInfo`, `instructions` |
| `notifications/initialized` | notification | none (consumed silently; marks the session as ready) |
| `ping` | request | `{}` |
| `tools/list` | request | `{ "tools": [ ... 5 tool descriptors ... ] }` |
| `tools/call` | request | `{ "content": [...], "structuredContent": {...}, "isError": bool }` |
| anything else | request | JSON-RPC error `-32601` |

### 2.1 Handshake

```
client → {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
            "protocolVersion":"2025-11-25",
            "capabilities":{},
            "clientInfo":{"name":"mcp-cli","version":"0.1.0"}}}
server → {"jsonrpc":"2.0","id":1,"result":{
            "protocolVersion":"2025-11-25",
            "capabilities":{"tools":{"listChanged":false}},
            "serverInfo":{"name":"synclicense-mcp","version":"0.1.0"},
            "instructions":"..."}}
client → {"jsonrpc":"2.0","method":"notifications/initialized"}
```

If the client requests a protocol version the server does not know, the server
answers with its own preferred version (`2025-11-25`) and lets the client decide
whether to continue.

Any request other than `initialize` or `ping` sent **before** the handshake is
rejected with error `-32002` (`Server not initialized`).

## 3. Error codes

| Code | Meaning | When it is emitted |
|---|---|---|
| `-32700` | Parse error | The received line is not valid JSON |
| `-32600` | Invalid request | Missing `jsonrpc: "2.0"`, missing `method`, or malformed envelope |
| `-32601` | Method not found | Unknown protocol method |
| `-32602` | Invalid params | Missing/ill-typed argument, unknown enum value, unknown tool name |
| `-32603` | Internal error | Unexpected server-side exception |
| `-32002` | Server not initialized | A request arrived before `initialize` completed |

**Protocol errors vs. business errors.** A malformed call is a JSON-RPC `error`
object. A *valid* call that is refused by the licensing rules (blocked track,
expired quote, unknown contract) is a **successful** JSON-RPC response whose
result carries `isError: true` and a human-readable explanation. This is the
distinction the MCP specification makes so the model can read and recover from
the failure.

## 4. Tools

### 4.1 `buscar_pista`
Search the catalog by creative and budget criteria.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `mood` | string | no | `alegre`, `epico`, `melancolico`, `relajado`, `tenso`, `energetico`, `inspirador`, `oscuro` |
| `genero` | string | no | `pop`, `rock`, `electronica`, `hip_hop`, `jazz`, `clasica`, `folk`, `ambient`, `cinematica`, `latina` |
| `instrumental` | boolean | no | `true` = no vocals |
| `duracion_seg_min` | integer | no | lower bound in seconds |
| `duracion_seg_max` | integer | no | upper bound in seconds |
| `presupuesto_max` | number | no | filters by `tarifa_base` in USD |
| `limite` | integer | no | 1–20, default 5 |

Returns `{ "total_encontradas": int, "pistas": [ {pista_id, titulo, artista, duracion_seg, genero, mood, instrumental, tarifa_base_usd, popularidad} ] }`.
Excludes tracks whose rights status is `bloqueada`, because they cannot be licensed.

### 4.2 `verificar_clearance`
Legal status of one track.

| Parameter | Type | Required |
|---|---|---|
| `pista_id` | string | yes |

Returns `{pista_id, titulo, estado, licenciable, detalle, restricciones[], recargo_escrow_pct}`.
`estado` is one of:

* `libre` — cleared, no encumbrance.
* `samples_pendientes` — contains samples still being cleared; licensable but a
  15% escrow surcharge applies and the contract carries a hold-back clause.
* `bloqueada` — authorship dispute; **not licensable**.

### 4.3 `calcular_costo_licencia`
Applies the rate card. This is the business logic of the server.

| Parameter | Type | Required | Allowed values |
|---|---|---|---|
| `pista_id` | string | yes | |
| `tipo_uso` | string | yes | `redes_sociales`, `podcast`, `web_corporativo`, `evento_interno`, `publicidad_online`, `videojuego`, `tv_nacional`, `cine` |
| `territorio` | string | yes | `local`, `latam`, `norteamerica`, `europa`, `mundial` |
| `exclusividad` | string | yes | `no`, `sectorial`, `total` |
| `duracion_meses` | integer | yes | `0` means perpetual; otherwise 1–120 |

```
subtotal = tarifa_base × mult_uso × mult_territorio × mult_exclusividad × mult_vigencia
total    = subtotal + escrow (15% of subtotal when estado = samples_pendientes)
```

Returns the full breakdown plus a `cotizacion_id` and `valida_hasta` timestamp.
A quote is valid for 30 days. Refuses (`isError: true`) if the track is `bloqueada`.

### 4.4 `generar_contrato`
Turns an accepted quote into a licence agreement.

| Parameter | Type | Required |
|---|---|---|
| `pista_id` | string | yes |
| `cliente` | string | yes |
| `cotizacion_id` | string | yes |

Validates that the quote exists, has not expired, and belongs to `pista_id`.
Returns `{contrato_id, pista, cliente, alcance:{tipo_uso, territorio, exclusividad}, vigencia:{inicio, fin}, monto_usd, restricciones[], estado}`.

### 4.5 `registrar_uso`
Registers the actual deployment for royalty reporting and audit.

| Parameter | Type | Required |
|---|---|---|
| `contrato_id` | string | yes |
| `plataforma` | string | yes |
| `url_proyecto` | string | yes |

Validates the contract exists and is active. Appends a record to
`data/usage_log.jsonl` and returns `{registro_id, contrato_id, estado, registrado_en, ...}`.

## 5. Tool chaining

The tools are deliberately stateful across a session, which is the point of the
use case: the assistant has to carry context from one call to the next.

```
buscar_pista ──► pista_id
                    │
                    ├──► verificar_clearance   (may block the whole flow)
                    │
                    └──► calcular_costo_licencia ──► cotizacion_id
                                                        │
                                                        └──► generar_contrato ──► contrato_id
                                                                                     │
                                                                                     └──► registrar_uso
```

Quotes and contracts live in the server session (in memory); usage records are
appended to disk so they survive the process.

## 6. Data model

`data/catalog.json` is produced by `scripts/seed_catalog.py`:

```json
{
  "generado_en": "2026-08-19T21:20:00Z",
  "fuente": "offline",
  "seed": 23016,
  "pistas": [
    {
      "pista_id": "TRK-00001",
      "titulo": "Sunburst",
      "artista": "Nova Bloom",
      "duracion_seg": 187,
      "genero": "electronica",
      "mood": "energetico",
      "instrumental": true,
      "popularidad": 62,
      "licencia": "CC BY-SA 3.0",
      "tarifa_base_usd": 45.0,
      "estado_derechos": "libre",
      "detalle_derechos": "..."
    }
  ]
}
```

Track metadata (title, artist, duration, genre, mood, licence) mirrors what the
Jamendo API exposes. `tarifa_base_usd`, `estado_derechos` and `detalle_derechos`
are the **simulated business layer** — no platform publishes its rate card or its
internal legal status, so those fields are generated from a fixed seed with a
realistic distribution (82% `libre`, 13% `samples_pendientes`, 5% `bloqueada`).
The rate-card multipliers are modelled on public royalty-free rate cards such as
Jamendo Licensing.
