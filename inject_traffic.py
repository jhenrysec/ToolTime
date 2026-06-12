#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject_traffic.py  -  fake air-traffic injector for the offline ATC system
===========================================================================

Generates synthetic aircraft and streams them to the ATC system's injection
port (default tcp/30001) as newline-delimited JSON. Each aircraft is
dead-reckoned (great-circle) from its heading + ground speed, so tracks move
realistically across the scope.

Standard library only. Python 3.5+. No internet access required.

Examples
--------
  # 12 mixed aircraft orbiting/transiting near Fort Gordon at 1 Hz
  python3 inject_traffic.py --host 127.0.0.1 --count 12

  # Only military, faster updates, tighter area
  python3 inject_traffic.py --count 6 --type military --spread 0.25 --rate 0.5

  # One-shot static injection (place tracks once, then exit)
  python3 inject_traffic.py --count 8 --once

  # Replay a scenario file (one JSON object per line) verbatim, looping
  python3 inject_traffic.py --scenario scenario.jsonl --loop

The ATC accepts these JSON keys (aliases in parentheses):
  icao(hex), callsign(flight), lat, lon, altitude(alt), speed(gs),
  heading(track), type[civilian|military|unknown], squawk
  {"icao":"AE1101","delete":true}  removes a track immediately.
"""

import socket
import json
import time
import math
import random
import argparse
import sys
import threading
try:
    from urllib.request import urlopen
except ImportError:  # pragma: no cover
    from urllib2 import urlopen

# kill-feedback: tracks which icaos the ATC currently shows, so the injector
# can notice when one of its aircraft was eliminated (removed by the ATC) and
# stop re-sending it -- freeing a slot for fresh arrivals.
FEED = {"present": set(), "ok": False}
FEED_LOCK = threading.Lock()


def feed_watch(host, http_port, period=3.0):
    url = "http://{0}:{1}/data/aircraft.json".format(host, http_port)
    while True:
        try:
            raw = urlopen(url, timeout=2).read().decode("utf-8", "ignore")
            data = json.loads(raw)
            present = set(a["hex"] for a in data.get("aircraft", []))
            with FEED_LOCK:
                FEED["present"] = present
                FEED["ok"] = True
        except Exception:
            with FEED_LOCK:
                FEED["ok"] = False
        time.sleep(period)

MIL = ["VIPER", "SNAKE", "EAGLE", "HAWK", "RAVEN", "GHOST", "SABER", "DAGGER"]
CIV = ["AAL", "DAL", "UAL", "SWA", "JBU", "FFT", "NKS"]
EARTH_NM = 3440.065   # nautical miles
STD_TURN_RATE = 3.0   # deg/sec (standard rate turn: 360 deg in 2 min)


class Track(object):
    """Realistic flight model: fly a straight leg at constant heading, then
    occasionally roll into a standard-rate turn to a new heading and roll out.
    When the aircraft drifts beyond max range it is vectored back toward the
    site with a normal turn (it never reverses or jitters in place)."""

    def __init__(self, center, spread, force_type=None, life=600.0):
        if force_type == 'military' or (force_type is None and random.random() < 0.4):
            self.type = 'military'
            self.callsign = random.choice(MIL) + str(random.randint(1, 99)).zfill(2)
            self.icao = "{0:06X}".format(random.randint(0xAE0000, 0xAEFFFF))
            self.speed = random.randint(300, 520)
            self.altitude = random.randint(150, 400) * 100
        else:
            self.type = 'civilian'
            self.callsign = random.choice(CIV) + str(random.randint(1000, 9999))
            self.icao = "{0:06X}".format(random.randint(0xA00000, 0xACFFFF))
            self.speed = random.randint(380, 500)
            self.altitude = random.randint(280, 400) * 100

        self.center = center
        self.max_range_nm = max(15.0, spread * 60.0)
        self.egress_nm = self.max_range_nm + 12.0     # removed once it leaves this
        brg = random.uniform(0, 360)
        rng_nm = random.uniform(2.0, self.max_range_nm * 0.6)
        self.lat, self.lon = project(center[0], center[1], brg, rng_nm)
        self.heading = random.uniform(0, 360)
        self.target_heading = self.heading
        self.turning = False
        self.clock = 0.0
        self.next_turn_at = random.uniform(25, 90)    # straight-leg duration
        # lifetime: total time from spawn to removal is ~life. The aircraft
        # loiters in-sector, begins an outbound departure a few minutes before
        # the end, and is removed once it leaves range or hits the life cap.
        self.life = life * random.uniform(0.85, 1.15)
        egress_budget = min(random.uniform(150, 210), self.life * 0.5)
        self.depart_at = self.life - egress_budget
        self.departing = False
        self.confirmed = False   # seen in the ATC feed at least once

    def _begin_turn(self, target):
        self.target_heading = target % 360
        self.turning = True

    def advance(self, dt):
        if dt <= 0:
            return
        self.clock += dt
        rng = dist_nm(self.center[0], self.center[1], self.lat, self.lon)

        if not self.departing and self.clock >= self.depart_at:
            # head outbound (away from the site) and stop loitering
            self.departing = True
            out = bearing(self.center[0], self.center[1], self.lat, self.lon)
            self._begin_turn(out + random.uniform(-15, 15))

        if not self.departing:
            if rng > self.max_range_nm and not self.turning:
                back = bearing(self.lat, self.lon, self.center[0], self.center[1])
                self._begin_turn(back + random.uniform(-20, 20))
            elif (not self.turning) and self.clock >= self.next_turn_at:
                self.next_turn_at = self.clock + random.uniform(40, 120)
                if random.random() < 0.6:
                    self._begin_turn(self.heading + random.uniform(-50, 50))

        if self.turning:
            diff = (self.target_heading - self.heading + 540) % 360 - 180
            step = STD_TURN_RATE * dt
            if abs(diff) <= step:
                self.heading = self.target_heading
                self.turning = False
            else:
                self.heading = (self.heading + (step if diff > 0 else -step)) % 360

        d_nm = self.speed * (dt / 3600.0)
        self.lat, self.lon = project(self.lat, self.lon, self.heading, d_nm)

    def expired(self):
        """Removed once it has left the sector, or at the life cap (~10 min)."""
        rng = dist_nm(self.center[0], self.center[1], self.lat, self.lon)
        return self.clock >= self.life or (self.departing and rng > self.egress_nm)

    def message(self):
        return {
            "icao": self.icao, "callsign": self.callsign,
            "lat": round(self.lat, 5), "lon": round(self.lon, 5),
            "altitude": self.altitude, "speed": self.speed,
            "heading": round(self.heading, 1), "type": self.type,
        }


def project(lat, lon, bearing_deg, d_nm):
    """Great-circle destination point from lat/lon, bearing, distance(nm)."""
    br = math.radians(bearing_deg)
    d = d_nm / EARTH_NM
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(d) +
                     math.cos(lat1) * math.sin(d) * math.cos(br))
    lon2 = lon1 + math.atan2(math.sin(br) * math.sin(d) * math.cos(lat1),
                             math.cos(d) - math.sin(lat1) * math.sin(lat2))
    return math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180


def bearing(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing from point 1 to point 2 (degrees)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def dist_nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return EARTH_NM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def connect(host, port, retries=30):
    for attempt in range(retries):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((host, port))
            return s
        except Exception as e:
            if attempt == 0:
                print("[inject] waiting for {0}:{1} ... ({2})".format(host, port, e))
            time.sleep(1.0)
    print("[inject] could not connect to {0}:{1}".format(host, port))
    sys.exit(1)


def send_line(sock, obj):
    sock.sendall((json.dumps(obj) + "\n").encode("ascii"))


def run_generated(args):
    center = (args.lat, args.lon)
    ftype = args.type if args.type != 'mixed' else None

    def make():
        return Track(center, args.spread, ftype, args.life)

    active = [make() for _ in range(args.count)]
    sock = connect(args.host, args.port)
    print("[inject] connected -> {0}:{1}  (seed {2} aircraft, cap {3})".format(
        args.host, args.port, len(active), args.max))

    if not args.no_killcheck:
        th = threading.Thread(target=feed_watch, args=(args.host, args.http_port))
        th.daemon = True
        th.start()
        print("[inject] kill-feedback watching http://{0}:{1}/data/aircraft.json".format(
            args.host, args.http_port))

    for t in active:
        send_line(sock, t.message())
    if args.once:
        print("[inject] one-shot complete ({0} tracks placed).".format(len(active)))
        sock.close()
        return

    now = time.time()
    last = now
    next_wave = now + random.uniform(args.wave_interval_min, args.wave_interval_max)

    try:
        while True:
            time.sleep(args.rate)
            now = time.time()
            dt = now - last
            last = now

            # ---- spawn a wave of new arrivals every 2-4 minutes ----
            if now >= next_wave:
                want = random.randint(args.wave_min, args.wave_max)
                room = max(0, args.max - len(active))
                n = min(want, room)
                for _ in range(n):
                    t = make()
                    active.append(t)
                    send_line(sock, t.message())
                next_wave = now + random.uniform(args.wave_interval_min,
                                                 args.wave_interval_max)
                print("[inject] +{0} arrivals  (active={1})  next wave in {2:.0f}s".format(
                    n, len(active), next_wave - now))

            # snapshot the ATC feed for kill detection
            with FEED_LOCK:
                feed_ok = FEED["ok"]
                present = FEED["present"] if feed_ok else None

            # ---- advance, transmit, retire departed + eliminated aircraft ----
            survivors = []
            departed = 0
            killed = 0
            for t in active:
                t.advance(dt)
                if t.expired():
                    try:
                        send_line(sock, {"icao": t.icao, "delete": True})
                    except Exception:
                        pass
                    departed += 1
                    continue
                # kill detection: if the ATC was showing this track and now
                # isn't, it was eliminated downstream -> stop simulating it.
                if feed_ok and present is not None:
                    if t.icao in present:
                        t.confirmed = True
                    elif t.confirmed:
                        killed += 1
                        continue
                send_line(sock, t.message())
                survivors.append(t)
            if departed:
                print("[inject] -{0} departed out of range  (active={1})".format(
                    departed, len(survivors)))
            if killed:
                print("[inject] -{0} eliminated (removed by ATC)  (active={1})".format(
                    killed, len(survivors)))
            active = survivors
    except KeyboardInterrupt:
        print("\n[inject] stopping; removing {0} tracks.".format(len(active)))
        for t in active:
            try:
                send_line(sock, {"icao": t.icao, "delete": True})
            except Exception:
                pass
        sock.close()


def run_scenario(args):
    with open(args.scenario, "r") as f:
        lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    sock = connect(args.host, args.port)
    print("[inject] connected -> {0}:{1}  (scenario: {2} lines)".format(
        args.host, args.port, len(lines)))
    try:
        while True:
            for ln in lines:
                sock.sendall((ln + "\n").encode("ascii"))
                time.sleep(args.rate)
            if not args.loop:
                break
    except KeyboardInterrupt:
        print("\n[inject] stopping.")
    sock.close()


def main():
    ap = argparse.ArgumentParser(description="Fake air-traffic injector (tcp/30001)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=30001)
    ap.add_argument("--lat", type=float, default=33.7490)
    ap.add_argument("--lon", type=float, default=-84.3880)
    ap.add_argument("--count", type=int, default=8, help="initial seed aircraft")
    ap.add_argument("--type", choices=["mixed", "military", "civilian"], default="mixed")
    ap.add_argument("--spread", type=float, default=0.5,
                    help="initial dispersion (1.0 ~= 60nm radius)")
    ap.add_argument("--rate", type=float, default=1.0, help="seconds between updates")
    ap.add_argument("--wave-min", type=int, default=3, help="min new arrivals per wave")
    ap.add_argument("--wave-max", type=int, default=12, help="max new arrivals per wave")
    ap.add_argument("--wave-interval-min", type=float, default=120.0,
                    help="min seconds between arrival waves (default 2 min)")
    ap.add_argument("--wave-interval-max", type=float, default=240.0,
                    help="max seconds between arrival waves (default 4 min)")
    ap.add_argument("--life", type=float, default=600.0,
                    help="seconds before an aircraft departs and falls out of range")
    ap.add_argument("--max", type=int, default=60, help="population cap")
    ap.add_argument("--http-port", type=int, default=8888,
                    help="ATC web port for kill-feedback polling")
    ap.add_argument("--no-killcheck", action="store_true",
                    help="do not drop tracks the ATC has removed (eliminated)")
    ap.add_argument("--once", action="store_true", help="place tracks once and exit")
    ap.add_argument("--scenario", help="replay a .jsonl scenario file")
    ap.add_argument("--loop", action="store_true", help="loop the scenario file")
    args = ap.parse_args()

    if args.scenario:
        run_scenario(args)
    else:
        run_generated(args)


if __name__ == "__main__":
    main()
