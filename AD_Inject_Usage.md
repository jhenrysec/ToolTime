# inject_traffic.py — Usage Guide

`inject_traffic.py` generates fake air traffic and streams it to the ATC's
injection port as newline-delimited JSON. It is the primary tool for driving the
air-picture during an air-defense (AD) exercise: it can produce a continuous,
realistic raid, replay a scripted scenario, or place a fixed set of contacts.

Standard-library Python only. Python 3.5+. No internet required.

---

## Prerequisites

- The ATC (`atc_debian9_v3.py`) must be running and reachable.
- You need its **injection port** (default tcp/30001) and, for kill-feedback,
  its **web port** (default 8888).
- Runs from anywhere on the isolated network — commonly on the ATC host itself.

## Quick start

```bash
# continuous, realistic mixed traffic around the scope centre
python3 inject_traffic.py --host 127.0.0.1 --port 30001 --http-port 8888 \
  --lat 33.5557 --lon -81.7194 --count 8
```

Aircraft appear on the ATC immediately and begin flying. Press **Ctrl+C** to
stop — the injector cleanly removes the tracks it created.

## How it behaves

- **Realistic flight.** Each aircraft flies straight legs at constant heading,
  with occasional standard-rate (3°/sec) turns to new headings; it dead-reckons
  by great-circle math, so ground speed stays constant and the nose tracks
  motion. Aircraft that drift past the loiter radius are vectored back.
- **Arrival waves.** It starts with `--count` aircraft, then adds a wave of
  `--wave-min`..`--wave-max` (default 3–12) new arrivals every
  `--wave-interval-min`..`--wave-interval-max` seconds (default 120–240, i.e.
  2–4 min), up to the `--max` population cap.
- **Lifecycle.** Each aircraft is up for about `--life` seconds (default 600 ≈
  10 min, ±15%); near the end it turns outbound, falls out of range, and is
  removed — so traffic is continuously refreshed.
- **Kill-aware.** It watches the ATC feed on `--http-port`; if one of its
  aircraft is removed by the ATC (e.g. eliminated by the AD sim), it stops
  re-simulating that track and frees the slot for new arrivals. Disable with
  `--no-killcheck`.

## Command-line options

| Option | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | ATC injection host (ATC IP) |
| `--port` | `30001` | ATC injection port |
| `--lat` | `33.7490` | scope centre latitude |
| `--lon` | `-84.3880` | scope centre longitude |
| `--count` | `8` | initial seed aircraft |
| `--type` | `mixed` | `mixed` \| `military` \| `civilian` |
| `--spread` | `0.5` | initial dispersion (1.0 ≈ 60 nm radius) |
| `--rate` | `1.0` | seconds between position updates |
| `--wave-min` | `3` | min new arrivals per wave |
| `--wave-max` | `12` | max new arrivals per wave |
| `--wave-interval-min` | `120` | min seconds between waves |
| `--wave-interval-max` | `240` | max seconds between waves |
| `--life` | `600` | seconds before an aircraft departs and disappears (~10 min) |
| `--max` | `60` | population cap |
| `--http-port` | `8888` | ATC web port used for kill-feedback polling |
| `--no-killcheck` | off | do not drop tracks the ATC has removed |
| `--once` | off | place tracks once and exit (no waves, no aging) |
| `--scenario <file>` | — | replay a `.jsonl` scenario file |
| `--loop` | off | loop the scenario file |

> Set `--lat`/`--lon` to the **same centre as the ATC** so traffic appears in
> the right place. For the AD scenario, that is the Aiken area
> (`33.5557 -81.7194`).

## Common recipes

**Continuous mixed raid (default cadence):**
```bash
python3 inject_traffic.py --lat 33.5557 --lon -81.7194 --count 8
```

**Saturation raid — overwhelm the air defense.** Dense, fast-arriving military
traffic to push the AD sites past their engagement channels:
```bash
python3 inject_traffic.py --lat 33.5557 --lon -81.7194 \
  --type military --count 20 \
  --wave-min 8 --wave-max 15 \
  --wave-interval-min 20 --wave-interval-max 40 \
  --max 120 --spread 0.3
```
Pair this with `channels all 1` + `free all` in the AD console to make the
sites flip to `SATURATED` (PEREGRUZKA) and watch leakers climb.

**Military-only, tight area (engaged in default TIGHT ROE):**
```bash
python3 inject_traffic.py --lat 33.5557 --lon -81.7194 --type military --spread 0.25
```

**Civilian background traffic (ignored in TIGHT ROE, engaged in FREE):**
```bash
python3 inject_traffic.py --lat 33.5557 --lon -81.7194 --type civilian --count 12
```

**One-shot placement (drop a fixed set once, then exit — no waves/aging):**
```bash
python3 inject_traffic.py --lat 33.5557 --lon -81.7194 --count 10 --once
```

**Scenario replay (scripted, repeatable):**
```bash
python3 inject_traffic.py --scenario scenario_example.jsonl --loop
```

**Single manual contact (no script needed):**
```bash
printf '{"icao":"AE2001","callsign":"SABER1","lat":33.6,"lon":-81.7,"altitude":18000,"speed":420,"heading":90,"type":"military"}\n' \
  | nc 127.0.0.1 30001
```

## Wire format (what the ATC accepts on tcp/30001)

One JSON object per line, terminated by `\n`:

```json
{"icao":"AE1101","callsign":"VIPER01","lat":33.75,"lon":-81.7,"altitude":25000,"speed":420,"heading":270,"type":"military"}
```

| Field | Aliases | Notes |
|---|---|---|
| `icao` | `hex` | 6-hex track ID, required |
| `callsign` | `flight` | display label |
| `lat`, `lon` | | decimal degrees |
| `altitude` | `alt` | feet |
| `speed` | `gs` | knots |
| `heading` | `track` | degrees |
| `type` | | `military` / `civilian` / `unknown` |
| `squawk` | | optional |
| `delete` | | `{"icao":"AE1101","delete":true}` removes the track |

The same port also accepts ADS-B AVR frames (`*<28 hex>;`) for dump1090-style
realism; the JSON form above is what `inject_traffic.py` emits.

## Scenario file format

A `.jsonl` file: one JSON object per line, `#` lines ignored. Each line is sent
verbatim (so the same keys/aliases apply). Example:

```
# scenario_example.jsonl
{"icao":"AE1101","callsign":"VIPER01","lat":33.95,"lon":-81.7,"altitude":24000,"speed":420,"heading":135,"type":"military"}
{"icao":"A12345","callsign":"DAL1288","lat":33.40,"lon":-81.1,"altitude":31000,"speed":460,"heading":50,"type":"civilian"}
```

Run with `--scenario <file>` (add `--loop` to repeat). Lines are streamed at the
`--rate` interval.

## Driving the AD exercise

A few things to keep in mind when using the injector against the air-defense sim:

- **Type drives engagement, not callsign.** AD sites in **TIGHT** ROE (the
  default) engage only `type: military`. In `mixed` mode roughly 40% of aircraft
  are tagged military at random, so a "civilian-sounding" callsign may still be
  a valid target. Use `--type` to control this precisely.
- **Saturation = arrivals > channels.** Lower the AD `channels`, raise the
  arrival rate (`--wave-*`) and density (`--count`, `--max`), and tighten
  `--spread` so many tracks enter the envelope at once.
- **Kills are attrited automatically.** With kill-feedback on, destroyed tracks
  vanish and free slots; new waves replace them, so a sustained raid keeps
  pressure on the defenses.

## Stopping and cleanup

- **Ctrl+C** stops the injector and sends a delete for every track it created,
  so the scope clears.
- If the injector is killed abruptly, leftover tracks age out on the ATC's stale
  timeout, or you can clear one manually with a `delete` line (see wire format).

## Troubleshooting

- **"waiting for host:port…"** — the ATC injection port isn't reachable. Confirm
  the ATC is running and that `--host`/`--port` match it (and any firewall on
  tcp/30001).
- **Traffic appears in the wrong place** — `--lat`/`--lon` don't match the ATC
  scope centre. Use the same coordinates the ATC was started with.
- **Aircraft never get engaged** — they may be tagged `civilian` while the AD is
  in TIGHT ROE. Use `--type military`, or set the AD site to `free`.
- **Tracks reappear after being shot down** — ensure kill-feedback is on
  (it is by default) and `--http-port` matches the ATC web port; `--no-killcheck`
  disables this behavior.
