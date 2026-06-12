# Bridge_Usage.md — TrainTracks Operator & Adversary Guide

**Scope.** How to operate both apps in the TrainTracks lab (`rail.html` dispatcher HMI and
`trainer.html` mechanical/SCADA trainer), followed by a catalog of the **vectors of compromise** the
trainer models and an **exploitability** assessment of each. Built for 17C instruction in an
air-gapped Donovia Rail scenario.

**Important framing.** TrainTracks is a *defensive training simulator*. It contains no live protocol
stack, no real device I/O, and no exploit tooling — it is a single-page model of an idealized bridge
controller. The "attack" actions below are commands inside the trainer's own teaching console; their
real-world analogs are publicly documented ICS weakness classes (unauthenticated Modbus, forced I/O,
false-data injection) mapped to MITRE ATT&CK for ICS. The point of every vector is the **detection
signature and the resilient design that defeats it**.

---

## 1. Lab topology

| App | Role | URL (served same-origin) |
|---|---|---|
| `index.html` | Launcher | `http://<host>:8080/` |
| `rail.html` | Donovia Rail Network Control — dispatcher HMI (8 bridges, trains, signals, switches) | `/rail.html` |
| `trainer.html` | Bridge Mechanical & SCADA Trainer — Congaree (bascule) + Cooper (swing) at subsystem fidelity with a Modbus console | `/trainer.html` |

The two apps mirror **Congaree (br1)** and **Cooper (br2)** open/close state live (`localStorage` +
`BroadcastChannel`, same origin). See `INTEGRATION-README.md` for the sync mechanics.

**Scenario asset:** the **SS-24 SCALPEL** strategic missile train runs the Congaree corridor
(Columbia–Orangeburg, track `t13`), which carries the Congaree bascule bridge. That track is cleared
of civilian traffic — it is the reason the bridge and rail controls matter in this scenario.

---

## 2. Using `rail.html` (dispatcher HMI)

The operator's network-wide view.

- **Navigate the map.** Scroll/drag to pan, scroll-wheel to zoom. Trains move in real time; raise the
  **sim speed** to watch traffic flow, lower it to work a single movement.
- **Select an entity.** Click any train, bridge, switch, or signal (or use the left-panel lists). The
  right control panel populates with its state and commands.
- **Command a bridge.** Select a bridge → **Open / Close**. The HMI runs the warning sequence
  (horn → signals to STOP → gates down → unlock → move). Opening a bridge sets the protecting rail
  signals to STOP and any train on that track holds short of the span.
- **The SS-24 SCALPEL.** Rendered as a crimson **diamond** with a rotating alert ring, a `◆ SS-24
  SCALPEL` label, and a `MILITARY` tag; the control panel shows its classification, cargo, and
  movement authority. It shuttles the Congaree corridor and will **hold at the Congaree bridge** if
  that bridge is opened — the core mission-impact lever in this scenario.
- **Trains / switches / signals.** Emergency-stop or resume trains; throw switches; observe signal
  aspects. These give the dispatcher situational awareness — and define what an attacker can and
  cannot hide from that view.

**Teaching point:** the HMI shows *open/closed* and *signal* state. It does **not** show motor
current, lock position, or forced I/O. Everything in §5 that damages the bridge mechanically is
largely invisible here — which is the lesson.

---

## 3. Using `trainer.html` (mechanical & SCADA trainer)

The maintainer + attacker + defender view of one bridge at a time.

### 3.1 Layout
- **Left:** bridge selector (Congaree bascule / Cooper swing) and **subsystem telemetry** (position,
  signal, gates, horn, motor + current, brake, each lock/wedge/lift, occupancy) plus **damage bars**.
- **Center:** animated **mechanical schematic** — bascule side elevation (leaf rotates about the
  trunnion) or swing plan view (span rotates about the center pivot). Color = state
  (green seated · amber moving · red open · purple faulted).
- **Right:** **Operator Console** (sequenced Open/Close/Stop via the PLC), **Lab Conditions**
  toggles, and the live **Modbus Map**.
- **Bottom:** **Event Log** and the **Network Console** (Modbus/TCP master emulation).

### 3.2 Do this first — a correct operation
1. Select **Congaree**. Click **Open Bridge**. Watch the sequence: horn/gates → span + tail locks
   release → brake off → leaf raises to full open → brake set. No damage. **Close Bridge** reverses
   it. This is "what right looks like."
2. Repeat on **Cooper** to see the deeper swing chain (unlock rails → retract end lifts → retract
   wedges → release centering latch → swing 90°).

### 3.3 Network console commands
```
help                         list commands
scan                         dump every Modbus point + live value for the target bridge
target congaree | cooper     switch target bridge
read  coil|hreg|ireg <addr>  read one point
write coil <addr> <0|1>      cmd-class (0000x) -> PLC-validated;  out-class (001xx) -> FORCE
write hreg <addr> <val>      write holding register (e.g. DRIVE_SPEED)
spoof ireg <addr> <val>      inject a false sensor value (persists until cleared)
forces                       list active forces + spoofs on the target
unforce <addr> | unforce all     release forced output coil(s)
clearspoof <addr> | clearspoof all   stop spoofing sensor(s)
```

### 3.4 Lab Conditions toggles
- **Train on span (occupancy)** — places a train on the span; sets `SPAN_OCCUPIED`.
- **PLC interlock enforcement** — when OFF, command coils behave like forced outputs (models a
  bypassed or mis-programmed PLC). Leave ON to study the difference between authorization failures
  and integrity failures.

### 3.5 Scenarios & repair
The **Training Scenarios** panel (top-right) runs the seven guided attacks below, printing each step
into the console. **Reset / Repair Selected Bridge** clears local damage, forces, and spoofs.

---

## 4. Vectors of compromise & exploitability

Each vector lists: the real-world weakness, how to reproduce it in the trainer, preconditions,
**exploitability**, impact, ATT&CK for ICS mapping, detection signature, and mitigation.

**Exploitability scale** (function of attacker preconditions, not "danger"):
`Trivial` = network reach only · `Low` = + write access · `Moderate` = + sequencing/timing or
on-path position · `High` = + multiple capabilities (write **and** MITM).

### V1 — Unauthenticated access & enumeration
- **Weakness.** Modbus/TCP has no authentication or encryption; any reachable master can read the
  full point space.
- **Reproduce.** `target congaree` → `scan` → `read ireg 30001`.
- **Preconditions.** Network reach to the controller (port 502).
- **Exploitability: Trivial.**
- **Impact.** Reconnaissance — full control-surface disclosure; no state change yet.
- **ATT&CK.** T0846 Remote System Discovery, T0888 Remote System Information Discovery.
- **Detection.** Modbus session from a non-HMI source; unusual function-code sweeps.
- **Mitigation.** Segment the control LAN; allow-list which masters may talk to each slave; alert on
  new Modbus conversations.

### V2 — Unauthorized command message
- **Weakness.** Command coils are honored regardless of who sends them; the PLC still validates
  interlocks, so the bridge moves **safely but without authorization**.
- **Reproduce.** `write coil 00001 1` (OPEN_CMD).
- **Preconditions.** Write access to command coils.
- **Exploitability: Low.**
- **Impact.** Availability/integrity — unauthorized open blocks the track on command. **This is the
  primary lever against the SS-24** (see §5).
- **ATT&CK.** T0855 Unauthorized Command Message.
- **Detection.** Command with no corresponding operator action; outside maintenance window; source IP
  not the HMI.
- **Mitigation.** Mutual auth / signed commands between HMI and PLC; command-source allow-listing;
  operations logging with alerting.

### V3 — Output forcing (interlock bypass)
- **Weakness.** Forcing a physical output coil drives the field device directly, bypassing all PLC
  ladder logic.
- **Reproduce.** `write coil 00101 1` (force MOTOR_RAISE) with locks still engaged → stall current,
  no motion, rack/pinion strips. (Swing analog: `target cooper` → `write coil 00101 1` on engaged
  end lifts → sheared lift machinery.)
- **Preconditions.** Write access to output coils (or PLC I/O-force capability).
- **Exploitability: Low–Moderate.**
- **Impact.** **Mechanical, often unrecoverable** — stripped drive train, sheared locks/jacks.
- **ATT&CK.** T0831 Manipulation of Control, T0821 Modify Controller Tasking.
- **Detection.** Forced-I/O alarms; **stall current (`30002`) with no change in position (`30001`)**;
  output state disagreeing with command logic.
- **Mitigation.** Disable/alarm on I/O forcing; motor-current and position-deviation monitoring;
  mechanical torque-limiters independent of the controller.

### V4 — Sensor / feedback spoofing (false-data injection)
- **Weakness.** PLC interlocks decide motion is safe by reading sensors. Falsify them and the
  controller authorizes a destructive command — the Stuxnet pattern.
- **Reproduce.** `spoof ireg 30005 1` + `spoof ireg 30006 1` (locks report released while physically
  engaged) → `write coil 00001 1`. The *safe* sequence now drives the motor into engaged locks.
- **Preconditions.** Ability to inject/alter input-register values (compromised RTU, on-path/MITM, or
  a compromised sensor channel).
- **Exploitability: Moderate–High.**
- **Impact.** Defeats interlocks on the **legitimate** command path; mechanical damage with the
  controller "behaving correctly."
- **ATT&CK.** T0856 Spoof Reporting Message, T0832 Manipulation of View.
- **Detection.** Physically inconsistent readings (lock "released" while stall current present);
  feedback that never tracks command timing.
- **Mitigation.** Redundant/diverse sensing with plausibility checks; signed/authenticated sensor
  channels; cross-check encoder vs. discrete limit switches.

### V5 — Limit-switch defeat / over-travel
- **Weakness.** The PLC stops the drive when it *reads* the limit switch; spoof that input and the
  span is driven past its travel envelope into the end stops.
- **Reproduce.** `spoof ireg 30004 0` (OPEN limit reads not-reached) → `write coil 00001 1`. The
  sequence never sees full-open and over-travels → structural damage.
- **Preconditions.** Input-register spoofing **or** direct output forcing past the stop.
- **Exploitability: Moderate.**
- **Impact.** Structural damage to span, rack/pinion, and stops.
- **ATT&CK.** T0856 Spoof Reporting Message, T0879 Damage to Property.
- **Detection.** Position (`30001`) exceeding the legal envelope; limit input frozen while position
  changes.
- **Mitigation.** **Hard-wired, independent over-travel cutouts** — not PLC logic reading a spoofable
  sensor.

### V6 — Safety-interlock bypass: open under load
- **Weakness.** The track-occupancy interlock is the last line before catastrophe; spoof it and the
  span can be moved with a train on it.
- **Reproduce.** Toggle **Train on span** ON → `spoof ireg 30008 0` → `write coil 00001 1`.
- **Preconditions.** Occupancy-sensor spoofing + command/forcing access; a train present.
- **Exploitability: Moderate.**
- **Impact.** **Catastrophic** — span moved under load / derailment. Highest-consequence vector.
- **ATT&CK.** T0879 Damage to Property, T0880 Loss of Safety.
- **Detection.** Motion command while `SPAN_OCCUPIED` (or an independent track circuit) is asserted.
- **Mitigation.** Occupancy protection as a **hard-wired Safety Instrumented System** independent of
  the PLC and not network-reachable.

### V7 — Manipulation / loss of view
- **Weakness.** What the dispatcher sees is data the attacker may control; field reality and the HMI
  picture can diverge.
- **Reproduce.** Run V3 (force-damage the drive) and compare: the trainer shows FAULTED with stall
  current, while `rail.html` may still show the bridge in its last open/closed state. Or spoof
  `30001` to report a false position.
- **Preconditions.** Output forcing or input spoofing.
- **Exploitability: Moderate.**
- **Impact.** Operator blindness — response is delayed or misdirected.
- **ATT&CK.** T0832 Manipulation of View, T0856 Spoof Reporting Message.
- **Detection.** Cross-source disagreement (HMI vs. independent telemetry/historian); implausible
  steady-state values.
- **Mitigation.** Out-of-band/independent monitoring; historian anomaly detection; don't source
  safety decisions from the same channel an attacker can write.

### V8 — Denial of control / DoS
- **Weakness.** Holding outputs forced (e.g., brake released, drive energized, or STOP suppressed)
  denies the operator control of the asset.
- **Reproduce.** `write coil 00103 1` (force BRAKE_RELEASE) and leave it; on a partially-open span the
  leaf drifts (runaway / weathervane). `forces` lists what you're holding; `unforce all` clears it.
- **Preconditions.** Sustained output-forcing access.
- **Exploitability: Low–Moderate.**
- **Impact.** Loss of control/availability; possible secondary mechanical damage.
- **ATT&CK.** T0814 Denial of Service, T0831 Manipulation of Control.
- **Detection.** Persistent forced outputs; commands not clearing; brake/drive state inconsistent with
  operator intent.
- **Mitigation.** Force-expiry/watchdogs; fail-safe (spring-set) brakes; alarming on stuck forces.

### Exploitability matrix

| Vector | Preconditions | Exploitability | Impact | Detectability |
|---|---|---|---|---|
| V1 Enumeration | Network reach | Trivial | None (recon) | Low–Med |
| V2 Unauthorized command | Coil write | Low | Avail/integrity | High (if monitored) |
| V3 Output forcing | Output-coil write | Low–Mod | Mechanical damage | Med (needs I/O + current monitoring) |
| V4 Sensor spoofing | Input injection / MITM | Mod–High | Damage via "safe" path | Low–Med (needs plausibility checks) |
| V5 Limit defeat | Spoof or force | Moderate | Structural | Med |
| V6 Open under load | Spoof + command + train | Moderate | Catastrophic | High (if SIS independent) |
| V7 Manipulation of view | Force/spoof | Moderate | Operator blindness | Low (needs out-of-band view) |
| V8 Denial of control | Sustained forcing | Low–Mod | Loss of control | Med–High |

---

## 5. Worked attack chain — degrading the SS-24 movement

Ties the bridge controls to the scenario's reason for existing. Use both apps side by side.

1. **Recon (V1).** Trainer: `target congaree` → `scan`. Note Congaree is a bascule carrying the
   Columbia–Orangeburg corridor — the SS-24's track.
2. **Observe the mission (rail.html).** Watch the SS-24 SCALPEL approach the Congaree bridge.
3. **Choose an effect:**
   - **Mission delay (V2) — low skill, high reliability.** Trainer `write coil 00001 1` (or open from
     the HMI) as the SS-24 approaches. The bridge opens, the protecting signal goes STOP, and the
     SS-24 **holds at the span** — strategic movement stalled with no mechanical damage. Easily
     reversible (close the bridge), and visible on the HMI.
   - **Persistent denial (V3) — mechanical.** Force the drive against the locks (`write coil 00101 1`)
     to **strip the rack/pinion**. The bridge can no longer be opened *or* closed; if it was open, the
     SS-24 is stranded until field repair. Note the HMI may not reflect the fault (V7).
   - **Catastrophe (V6).** With the SS-24 on the span, spoof `30008 0` and open. Modeled as a
     span-moved-under-load event. Highest consequence; the clearest argument for an independent SIS.

**Blue-team counter-narrative.** For each branch, have students state what the dispatcher would see,
what the maintainer's telemetry would show, and which independent control (signal interlock, hard
over-travel cutout, hard occupancy SIS) would have blunted it.

---

## 6. Detection & defense quick reference

| Observable | Likely vector | Control that stops it |
|---|---|---|
| Modbus from non-HMI source | V1/V2 | Segmentation, master allow-listing |
| Command with no operator action | V2 | Command auth, ops logging |
| Forced I/O present | V3/V8 | Force alarms, periodic "no-forces" audit |
| Stall current, position static | V3 | Current + position-deviation monitoring |
| Feedback inconsistent with physics | V4/V5/V7 | Redundant/diverse sensing, plausibility checks |
| Position beyond envelope | V5 | Hard-wired over-travel cutouts |
| Motion command while occupied | V6 | Independent track-circuit SIS |
| HMI disagrees with field telemetry | V7 | Out-of-band monitoring / historian |

Full engineering and defensive detail: `BRIDGE-MECHANICAL-ANALYSIS.md` §5–§6.

---

## 7. Instructor notes

- **Run order:** correct ops (§3.2) → enumeration (V1) → authorization vs. integrity (V2 vs. V3) →
  false-data injection (V4–V6) → view/availability (V7–V8) → the SS-24 chain (§5) → defense (§6).
- **Reset between teams** with **Reset / Repair Selected Bridge**, or clear shared sync state:
  `localStorage.removeItem('scrail_bridge_sync_v1')` then reload both tabs.
- **Common injects:** "open Congaree the moment the SS-24 enters the block"; "strip the drive and
  brief the commander on recovery time"; "make the HMI show normal while the bridge is faulted."
- **Assessment prompts:** for any action a student takes, require the ATT&CK technique, the detection
  signature, and the independent control that defeats it.

---

## 8. Appendix — Modbus point reference

Addresses shown for the selected bridge; swing-specific points differ where noted.

**Command coils (PLC-validated):** `00001` OPEN_CMD · `00002` CLOSE_CMD · `00003` STOP_CMD
**Output coils (forcible — bypass PLC):**
`00101` MOTOR_RAISE / DRIVE_SWING_OPEN · `00102` MOTOR_LOWER / DRIVE_SWING_CLOSE · `00103` BRAKE_RELEASE
· bascule `00104` SPANLOCK_RELEASE / `00105` TAILLOCK_RELEASE
· swing `00104` RAILLOCK_RELEASE / `00105` ENDLIFT_RETRACT / `00106` WEDGE_RETRACT / `00107` CENTERLATCH_REL
· `00110` HORN · `00111` GATE_LOWER
**Holding register:** `40002` DRIVE_SPEED (%)
**Input registers (sensors — spoofable):**
`30001` POS_ANGLE (% open) · `30002` MOTOR_CURRENT (A) · `30003` SEATED_LS / CENTERED_LS · `30004` OPEN_LS
· bascule `30005` SPANLOCK_RELEASED / `30006` TAILLOCK_RELEASED
· swing `30005` RAILLOCK_RELEASED / `30006` ENDLIFT_RETRACTED / `30007` WEDGE_RETRACTED
· `30008` SPAN_OCCUPIED

**Class behavior recap:** command coils = unauthorized-but-interlocked (authorization failure);
output coils = direct field control (integrity failure, mechanical damage); input registers = the
truth the PLC trusts (spoof to weaponize the safe path). That three-way distinction is the entire
lesson.
