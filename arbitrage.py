#!/usr/bin/env python3
"""
BONK HUB ARBITRAGE CALCULATOR - backend builder (hourly).
For a curated watchlist of liquid, haulable items, fetch buy and sell prices across the five
major trade hubs (Jita, Amarr, Dodixie, Rens, Hek) from Fuzzwork region aggregates, work out
the best cross hub spread per item two ways (instant flip into buy orders, patient relist),
and bake a self contained sortable page. Fees and freight are applied client side from editable
inputs, so the bake stores RAW prices + m3 + volume, never netted numbers.

USAGE:
    python arbitrage.py                  # build page (needs EVE_PAGE_PASSWORD to lock)
    python arbitrage.py --allow-unlocked # local only / public plaintext page
    python arbitrage.py --refresh        # force the ids + volume caches to rebuild
Pure stdlib + cryptography (page lock). Live runs need fuzzwork.co.uk + esi.evetech.net.
"""
import argparse, csv, hashlib, io, json, os, sys, time
import urllib.request
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SDE = "https://www.fuzzwork.co.uk/dump/latest/csv/"
MARKET = "https://market.fuzzwork.co.uk/aggregates/"
ESI = "https://esi.evetech.net/latest/universe/ids/?datasource=tranquility"
# Region level aggregates: each hub dominates its region's liquidity (station level is a
# flagged enhancement, not a v1 dependency).
HUBS = [("Jita", 10000002), ("Amarr", 10000043), ("Dodixie", 10000032),
        ("Rens", 10000030), ("Hek", 10000042)]
# Solar system IDs of the hub systems (for ESI /route jump distances; static, hubs do not move).
HUB_SYSTEMS = {"Jita": 30000142, "Amarr": 30002187, "Dodixie": 30002659,
               "Rens": 30002510, "Hek": 30002053}
ROUTE = "https://esi.evetech.net/latest/route/{a}/{b}/?datasource=tranquility&flag={flag}"
ROUTE_FLAGS = ["secure", "shortest"]   # highsec-only vs absolute shortest (lowsec/null allowed)
HISTORY = "https://esi.evetech.net/latest/markets/{region}/history/?type_id={tid}&datasource=tranquility"
HIST_DAYS = 7          # average daily traded volume over the last this-many days
IDS_CACHE = "ids_cache.json"
VOL_CACHE = "vol_cache.json"
ROUTES_CACHE = "routes_cache.json"
HIST_CACHE = "hist_cache.json"
HTML = "index.html"
UA = "BONK-Arbitrage/1.0 (Crown & Oak Capital; salesmaxxllc@gmail.com)"

# Page input defaults. The bake stores RAW prices; the page nets these client side so the
# operator can tune them to their skills + freight rate without a rebuild.
DEF_TAX = 3.37      # sales tax % (a market sale always pays this)
DEF_BROKER = 3.0    # broker fee % (relist model only; selling into a buy order pays none)
DEF_FREIGHT = 0.0   # ISK per m3 hauling cost (operator's own rate)
DEF_CARGO = 60000   # m3 of hold the operator fills per run (a jump freighter); drives ISK per jump
DEF_DAYS = 1        # days of the destination's traded volume you realistically move per trip
DEF_MIN_VOL = 100   # hide items the destination trades fewer than this many units per day (illiquid)
THIN = 0.30         # flag a hub's sell price "thin" when raw min and 5% percentile diverge > this

# Ships: SDE volume is the ASSEMBLED size (wrong for hauling). Override with the standard
# packaged (transport) volume per hull class so ISK/m3 reflects what a freighter actually eats.
SHIPS = {
    # frigates 2,500
    "Merlin": 2500, "Rifter": 2500, "Incursus": 2500, "Punisher": 2500, "Tristan": 2500,
    "Atron": 2500, "Kestrel": 2500, "Condor": 2500, "Slasher": 2500, "Executioner": 2500,
    "Tormentor": 2500, "Breacher": 2500, "Vigil": 2500, "Navitas": 2500, "Imicus": 2500,
    "Heron": 2500, "Magnate": 2500, "Probe": 2500, "Venture": 2500,
    # destroyers 5,000
    "Catalyst": 5000, "Thrasher": 5000, "Cormorant": 5000, "Coercer": 5000,
    # cruisers 10,000
    "Caracal": 10000, "Moa": 10000, "Vexor": 10000, "Thorax": 10000, "Stabber": 10000,
    "Rupture": 10000, "Maller": 10000, "Omen": 10000, "Arbitrator": 10000, "Blackbird": 10000,
    "Celestis": 10000, "Bellicose": 10000, "Osprey": 10000, "Augoror": 10000,
    "Exequror": 10000, "Scythe": 10000,
    # battlecruisers 15,000
    "Drake": 15000, "Ferox": 15000, "Brutix": 15000, "Myrmidon": 15000, "Hurricane": 15000,
    "Cyclone": 15000, "Prophecy": 15000, "Harbinger": 15000, "Oracle": 15000, "Naga": 15000,
    "Talos": 15000, "Tornado": 15000,
    # battleships 50,000
    "Raven": 50000, "Rokh": 50000, "Scorpion": 50000, "Megathron": 50000, "Dominix": 50000,
    "Hyperion": 50000, "Tempest": 50000, "Maelstrom": 50000, "Typhoon": 50000,
    "Apocalypse": 50000, "Armageddon": 50000, "Abaddon": 50000,
    # mining barges + exhumers 3,750
    "Procurer": 3750, "Retriever": 3750, "Covetor": 3750, "Skiff": 3750, "Mackinaw": 3750,
    "Hulk": 3750,
    # haulers 20,000 (standard T1 industrial)
    "Badger": 20000, "Tayra": 20000, "Bestower": 20000, "Sigil": 20000, "Hoarder": 20000,
    "Wreathe": 20000, "Mammoth": 20000, "Iteron Mark V": 20000, "Epithal": 20000,
    "Miasmos": 20000, "Kryos": 20000, "Nereus": 20000,
}

WATCHLIST = [
    # ---- minerals (the 8) ----
    "Tritanium", "Pyerite", "Mexallon", "Isogen", "Nocxium", "Zydrine", "Megacyte", "Morphite",
    # ---- ice products ----
    "Heavy Water", "Helium Isotopes", "Hydrogen Isotopes", "Nitrogen Isotopes",
    "Oxygen Isotopes", "Liquid Ozone", "Strontium Clathrates",
    # ---- fuel blocks ----
    "Helium Fuel Block", "Hydrogen Fuel Block", "Nitrogen Fuel Block", "Oxygen Fuel Block",
    # ---- moon materials (commonly traded) ----
    "Atmospheric Gases", "Evaporite Deposits", "Hydrocarbons", "Silicates",
    "Cobalt", "Scandium", "Titanium", "Tungsten", "Vanadium",
    "Cadmium", "Caesium", "Chromium", "Hafnium", "Mercury", "Platinum",
    "Promethium", "Neodymium", "Dysprosium", "Thulium", "Technetium",
    # ---- planetary interaction P1 ----
    "Water", "Industrial Fibers", "Reactive Metals", "Biofuels", "Precious Metals",
    "Toxic Metals", "Electrolytes", "Bacteria", "Proteins", "Biomass", "Oxygen",
    "Oxidizing Compound", "Silicon", "Plasmoids", "Chiral Structures",
    # ---- planetary interaction P2 ----
    "Biocells", "Construction Blocks", "Consumer Electronics", "Coolant", "Enriched Uranium",
    "Fertilizer", "Genetically Enhanced Livestock", "Livestock", "Mechanical Parts",
    "Microfiber Shielding", "Miniature Electronics", "Nanites", "Oxides", "Polyaramids",
    "Polytextiles", "Rocket Fuel", "Silicate Glass", "Superconductors", "Supertensile Plastics",
    "Synthetic Oil", "Test Cultures", "Transmitter", "Viral Agent", "Water-Cooled CPU",
    # ---- planetary interaction P3 ----
    "Camera Drones", "Condensates", "Cryoprotectant Solution", "Data Chips",
    "Gel-Matrix Biopaste", "Guidance Systems", "Hazmat Detection Systems", "Hermetic Membranes",
    "High-Tech Transmitters", "Industrial Explosives", "Neocoms", "Nuclear Reactors",
    "Planetary Vehicles", "Robotics", "Smartfab Units", "Supercomputers", "Synthetic Synapses",
    "Transcranial Microcontrollers", "Ukomi Superconductors", "Vaccines",
    # ---- planetary interaction P4 ----
    "Broadcast Node", "Integrity Response Drones", "Nano-Factory", "Organic Mortar Applicators",
    "Recursive Computing Module", "Self-Harmonizing Power Core", "Sterile Conduits",
    "Wetware Mainframe",
    # ---- nanite repair paste (high volume consumable) ----
    "Nanite Repair Paste",
    # ---- faction / navy charges (hybrid) ----
    "Caldari Navy Antimatter Charge S", "Caldari Navy Antimatter Charge M",
    "Caldari Navy Antimatter Charge L", "Federation Navy Antimatter Charge S",
    "Federation Navy Antimatter Charge M", "Federation Navy Antimatter Charge L",
    # ---- faction / navy charges (projectile) ----
    "Republic Fleet EMP S", "Republic Fleet EMP M", "Republic Fleet EMP L",
    "Republic Fleet Fusion S", "Republic Fleet Fusion M", "Republic Fleet Fusion L",
    "Republic Fleet Phased Plasma S", "Republic Fleet Phased Plasma M",
    "Republic Fleet Phased Plasma L",
    # ---- faction / navy charges (laser) ----
    "Imperial Navy Multifrequency S", "Imperial Navy Multifrequency M",
    "Imperial Navy Multifrequency L",
    # ---- faction / navy missiles ----
    "Caldari Navy Scourge Light Missile", "Caldari Navy Mjolnir Light Missile",
    "Caldari Navy Inferno Light Missile", "Caldari Navy Nova Light Missile",
    "Caldari Navy Scourge Heavy Missile", "Caldari Navy Mjolnir Heavy Missile",
    "Caldari Navy Inferno Heavy Missile", "Caldari Navy Nova Heavy Missile",
    "Caldari Navy Scourge Rocket", "Caldari Navy Mjolnir Rocket",
    "Caldari Navy Scourge Cruise Missile", "Caldari Navy Inferno Cruise Missile",
    # ---- T2 ammo (hybrid) ----
    "Null S", "Null M", "Null L", "Void S", "Void M", "Void L",
    # ---- T2 ammo (projectile) ----
    "Barrage S", "Barrage M", "Barrage L", "Hail S", "Hail M", "Hail L",
    # ---- T2 ammo (laser) ----
    "Scorch S", "Scorch M", "Scorch L", "Conflagration S", "Conflagration M", "Conflagration L",
    # ---- T2 missiles ----
    "Scourge Fury Heavy Missile", "Scourge Precision Heavy Missile",
    "Scourge Rage Heavy Assault Missile", "Scourge Javelin Heavy Assault Missile",
    "Scourge Rage Torpedo", "Scourge Javelin Torpedo",
    # ---- scripts ----
    "Tracking Speed Script", "Optimal Range Script", "Scan Resolution Script",
    "Targeting Range Script",
    # ---- drones T2 ----
    "Hobgoblin II", "Hammerhead II", "Ogre II", "Warrior II", "Valkyrie II", "Berserker II",
    "Acolyte II", "Infiltrator II", "Praetor II", "Vespa II", "Wasp II", "Bouncer II",
    "Curator II", "Garde II", "Hornet EC-300",
    # ---- drones T1 ----
    "Hobgoblin I", "Hammerhead I", "Ogre I", "Warrior I", "Acolyte I",
    # ---- combat boosters (commonly traded) ----
    "Standard Blue Pill Booster", "Improved Blue Pill Booster", "Strong Blue Pill Booster",
    "Standard Exile Booster", "Standard Drop Booster", "Quafe Zero Classic",
    # ---- modules: damage ----
    "Gyrostabilizer II", "Heat Sink II", "Magnetic Field Stabilizer II",
    "Ballistic Control System II", "Drone Damage Amplifier II", "Tracking Enhancer II",
    "Entropic Radiation Sink II",
    # ---- modules: armor tank ----
    "Damage Control II", "1600mm Steel Plates II", "800mm Steel Plates II",
    "400mm Steel Plates II", "Multispectrum Energized Membrane II", "Multispectrum Coating II",
    "Kinetic Armor Hardener II", "Thermal Armor Hardener II", "EM Armor Hardener II",
    "Explosive Armor Hardener II", "Large Armor Repairer II", "Medium Armor Repairer II",
    "Small Armor Repairer II", "Reactive Armor Hardener",
    # ---- modules: shield tank ----
    "Large Shield Extender II", "Medium Shield Extender II", "Small Shield Extender II",
    "Multispectrum Shield Hardener II", "Kinetic Shield Hardener II", "Thermal Shield Hardener II",
    "EM Shield Hardener II", "Explosive Shield Hardener II", "X-Large Shield Booster II",
    "Large Shield Booster II", "Medium Shield Booster II", "Shield Boost Amplifier II",
    # ---- modules: propulsion ----
    "5MN Microwarpdrive II", "50MN Microwarpdrive II", "500MN Microwarpdrive II",
    "1MN Afterburner II", "10MN Afterburner II", "100MN Afterburner II",
    # ---- modules: tackle ----
    "Warp Scrambler II", "Warp Disruptor II", "Stasis Webifier II",
    # ---- modules: ewar + sensors ----
    "Sensor Booster II", "Tracking Computer II", "Remote Sensor Dampener II",
    "Tracking Disruptor II", "Guidance Disruptor II",
    # ---- modules: capacitor + energy warfare ----
    "Cap Recharger II", "Capacitor Power Relay II", "Heavy Capacitor Booster II",
    "Medium Capacitor Booster II", "Medium Energy Neutralizer II", "Heavy Energy Neutralizer II",
    "Small Energy Neutralizer II",
    # ---- turrets: projectile ----
    "425mm AutoCannon II", "220mm Vulcan AutoCannon II", "200mm AutoCannon II",
    "800mm Repeating Cannon II", "650mm Artillery Cannon II", "1400mm Howitzer Artillery II",
    "720mm Howitzer Artillery II", "Dual 180mm AutoCannon II",
    # ---- turrets: hybrid ----
    "150mm Railgun II", "250mm Railgun II", "350mm Railgun II", "Electron Blaster Cannon II",
    "Ion Blaster Cannon II", "Neutron Blaster Cannon II", "Heavy Ion Blaster II",
    "Heavy Neutron Blaster II",
    # ---- turrets: laser ----
    "Dual Heavy Pulse Laser II", "Heavy Pulse Laser II", "Heavy Beam Laser II",
    "Mega Pulse Laser II", "Mega Beam Laser II", "Focused Medium Pulse Laser II",
    "Dual Light Pulse Laser II", "Quad Light Beam Laser II",
    # ---- launchers ----
    "Heavy Missile Launcher II", "Heavy Assault Missile Launcher II",
    "Rapid Light Missile Launcher II", "Light Missile Launcher II", "Rocket Launcher II",
    "Cruise Missile Launcher II", "Torpedo Launcher II", "Rapid Heavy Missile Launcher II",
] + list(SHIPS)


def fetch_text(url, timeout=180, retries=3):
    last = None
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8-sig", "replace")
        except Exception as e:
            last = e; time.sleep(2 * (a + 1))
    raise last


def fetch_json(url, timeout=60):
    return json.loads(fetch_text(url, timeout))


def _rows(t):
    return csv.DictReader(io.StringIO(t))


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _wl_hash():
    return hashlib.sha256("\n".join(sorted(set(WATCHLIST))).encode("utf-8")).hexdigest()[:16]


def esi_ids(names, chunk=900):
    """names -> {canonical_name: id} via ESI /universe/ids (case insensitive exact match)."""
    out = {}
    names = list(names)
    for i in range(0, len(names), chunk):
        part = names[i:i + chunk]
        try:
            body = json.dumps(part).encode("utf-8")
            req = urllib.request.Request(ESI, data=body, headers={
                "User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            for t in (d.get("inventory_types") or []):
                out[t["name"]] = t["id"]
        except Exception as e:
            print(f"    ESI ids chunk failed ({len(part)} names): {e}")
        time.sleep(0.2)
    return out


def resolve_ids(refresh=False, max_days=20):
    """Watchlist names -> {name: id}. Cached; cache invalidates if the watchlist changes."""
    if not refresh and os.path.exists(IDS_CACHE):
        try:
            obj = json.load(open(IDS_CACHE, encoding="utf-8"))
            fresh = (datetime.now(timezone.utc) - datetime.fromisoformat(obj["built"])).days < max_days
            if fresh and obj.get("watchlist_hash") == _wl_hash():
                return {k: int(v) for k, v in obj["ids"].items()}
        except Exception:
            pass
    print("  Resolving watchlist names to type IDs via ESI...")
    ids = esi_ids(sorted(set(WATCHLIST)))
    got = {k.lower() for k in ids}
    misses = [n for n in sorted(set(WATCHLIST)) if n.lower() not in got]
    if misses:
        print(f"  {len(misses)} watchlist names did not resolve: "
              + ", ".join(misses[:50]) + (" ..." if len(misses) > 50 else ""))
    print(f"  Resolved {len(ids)} of {len(set(WATCHLIST))} watchlist items.")
    try:
        json.dump({"built": datetime.now(timezone.utc).isoformat(),
                   "watchlist_hash": _wl_hash(), "ids": ids},
                  open(IDS_CACHE, "w", encoding="utf-8"))
    except Exception:
        pass
    return ids


def resolve_vols(ids, refresh=False, max_days=20):
    """{id: m3 per unit} from the EVE SDE invTypes dump. Cached by the set of ids we LOOKED UP
    (not by which had a volume), so an item with no SDE volume does not force a full re-fetch
    every run. Ship volumes are overridden by the caller."""
    want = set(int(i) for i in ids)
    if not refresh and os.path.exists(VOL_CACHE):
        try:
            obj = json.load(open(VOL_CACHE, encoding="utf-8"))
            fresh = (datetime.now(timezone.utc) - datetime.fromisoformat(obj["built"])).days < max_days
            covered = {int(i) for i in obj.get("ids", [])}
            vols = {int(k): float(v) for k, v in obj["vols"].items()}
            if fresh and want <= covered:
                return vols
        except Exception:
            pass
    print("  Fetching item volumes from EVE SDE (invTypes)...")
    vols = {}
    for r in _rows(fetch_text(SDE + "invTypes.csv")):
        try:
            tid = int(r["typeID"]); v = float(r.get("volume") or 0)
        except (ValueError, TypeError):
            continue
        if tid in want and v > 0:
            vols[tid] = v
    try:
        json.dump({"built": datetime.now(timezone.utc).isoformat(),
                   "ids": sorted(want), "vols": {str(k): v for k, v in vols.items()}},
                  open(VOL_CACHE, "w", encoding="utf-8"))
    except Exception:
        pass
    print(f"  Got volumes for {len(vols)} of {len(want)} items.")
    return vols


def get_aggregates(ids, region):
    """{typeID_str: {buy:{...}, sell:{...}}} from Fuzzwork region aggregates (raw, 100 per call)."""
    out, ids = {}, sorted({int(i) for i in ids if i})
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            data = fetch_json(f"{MARKET}?region={region}&types=" + ",".join(map(str, chunk)))
        except Exception:
            continue
        if isinstance(data, dict):
            out.update(data)
        time.sleep(0.1)
    return out


def robust_sell(sell):
    """The 5% percentile cheap sell price (robust to one fat finger order); fall back to min."""
    p = _f(sell.get("percentile"))
    return p if p > 0 else _f(sell.get("min"))


def robust_buy(buy):
    """The 5% percentile top buy price (robust); fall back to max."""
    p = _f(buy.get("percentile"))
    return p if p > 0 else _f(buy.get("max"))


def build_rows(ids_by_name, vols):
    """Returns (rows, live_hubs). rows is None if fewer than 2 hubs responded (abort the run)."""
    name_by_id = {v: k for k, v in ids_by_name.items()}
    ids = sorted(set(ids_by_name.values()))
    px, live_hubs = {}, []
    for hub, region in HUBS:
        data = get_aggregates(ids, region)
        if data:
            px[hub] = data
            live_hubs.append(hub)
        print(f"    {hub}: priced {len(data)} of {len(ids)}")
    if len(live_hubs) < 2:
        return None, live_hubs

    rows = []
    for tid in ids:
        s = str(tid)
        name = name_by_id.get(tid)
        sells, raw_min, buys, sellvol = {}, {}, {}, {}
        for hub in live_hubs:
            agg = px[hub].get(s)
            if not agg:
                continue
            sell = agg.get("sell") or {}
            buy = agg.get("buy") or {}
            rs = robust_sell(sell)
            if rs > 0:
                sells[hub] = rs
                raw_min[hub] = _f(sell.get("min"))
                sellvol[hub] = _f(sell.get("volume"))
            rb = robust_buy(buy)
            if rb > 0:
                buys[hub] = rb
        if len(sells) < 2:                       # need 2+ hubs to arbitrage
            continue
        buy_hub = min(sells, key=sells.get)      # acquire cheapest
        buy_cost = sells[buy_hub]
        bmin = raw_min.get(buy_hub, buy_cost)
        thin = buy_cost > 0 and abs(bmin - buy_cost) / buy_cost > THIN
        # MODEL A: instant flip into the best buy order at a different hub (no broker fee)
        flip_pool = {h: p for h, p in buys.items() if h != buy_hub}
        if flip_pool:
            flip_hub = max(flip_pool, key=flip_pool.get)
            flip_price = round(flip_pool[flip_hub], 2)
        else:
            flip_hub, flip_price = None, None
        # MODEL B: relist at the dearest other hub (pays broker + tax)
        list_pool = {h: p for h, p in sells.items() if h != buy_hub}
        list_hub = max(list_pool, key=list_pool.get)
        list_price = round(list_pool[list_hub], 2)
        rows.append({
            "n": name, "bh": buy_hub, "bc": round(buy_cost, 2),
            "fh": flip_hub, "fp": flip_price,
            "lh": list_hub, "lp": list_price,
            "m3": vols.get(tid), "vol": int(sellvol.get(buy_hub, 0)), "thin": thin,
        })
    rows.sort(key=lambda r: r["n"].lower())
    return rows, live_hubs


def esi_jumps(a, b, flag):
    """Jump count between two solar systems via ESI /route (len(route) - 1). None on failure."""
    try:
        d = fetch_json(ROUTE.format(a=a, b=b, flag=flag))
        if isinstance(d, list) and d:
            return len(d) - 1
    except Exception as e:
        print(f"    route {a}->{b} ({flag}) failed: {e}")
    return None


def jump_matrices(refresh=False, max_days=30):
    """{flag: {hubA: {hubB: jumps}}} for each route flag. Cached; hubs are static so the TTL is long."""
    names = [h for h, _ in HUBS]
    if not refresh and os.path.exists(ROUTES_CACHE):
        try:
            obj = json.load(open(ROUTES_CACHE, encoding="utf-8"))
            fresh = (datetime.now(timezone.utc) - datetime.fromisoformat(obj["built"])).days < max_days
            J = obj.get("jumps") or {}
            ok = all(f in J and all(a in J[f] and all(J[f][a].get(b) is not None for b in names if b != a)
                                    for a in names) for f in ROUTE_FLAGS)
            if fresh and ok:
                return J
        except Exception:
            pass
    print("  Fetching hub to hub jump distances from ESI /route...")
    J = {f: {a: {a: 0} for a in names} for f in ROUTE_FLAGS}
    for f in ROUTE_FLAGS:
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                j = esi_jumps(HUB_SYSTEMS[a], HUB_SYSTEMS[b], f)
                J[f][a][b] = j
                J[f][b][a] = j
                time.sleep(0.1)
        print(f"    {f}: " + ", ".join(f"{a}>{b}={J[f][a][b]}"
                                       for i, a in enumerate(names) for b in names[i + 1:]))
    # Only cache a COMPLETE matrix; a transient ESI miss must not freeze a null in for max_days.
    complete = all(J[f][a].get(b) is not None
                   for f in ROUTE_FLAGS for i, a in enumerate(names) for b in names[i + 1:])
    if complete:
        try:
            json.dump({"built": datetime.now(timezone.utc).isoformat(), "jumps": J},
                      open(ROUTES_CACHE, "w", encoding="utf-8"))
        except Exception:
            pass
    else:
        print("    (incomplete jump matrix; not caching, will retry next run)")
    return J


def esi_daily_volume(tid, region, days=HIST_DAYS):
    """Average units traded per day for one type in one region (ESI market history). 0 if untraded."""
    try:
        d = fetch_json(HISTORY.format(region=region, tid=tid))
        if isinstance(d, list) and d:
            last = d[-days:]
            vols = [int(x.get("volume") or 0) for x in last]
            return int(sum(vols) / len(vols)) if vols else 0
    except Exception:
        pass
    return 0


def daily_volumes(pairs, refresh=False, max_days=2):
    """{(tid, region): avg_daily_units} for the requested (type, region) pairs. Cached ~2 days
    (traded volume moves slowly), so a normal hourly run hits the cache and skips ESI history."""
    cache = {}
    if os.path.exists(HIST_CACHE):
        try:
            cache = json.load(open(HIST_CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    now = datetime.now(timezone.utc)
    out, fetched = {}, 0
    for tid, region in pairs:
        k = f"{tid}:{region}"
        c = cache.get(k)
        fresh = False
        if c:
            try:
                fresh = (now - datetime.fromisoformat(c["built"])).days < max_days
            except Exception:
                fresh = False
        if not refresh and fresh:
            out[(tid, region)] = c["v"]
        else:
            v = esi_daily_volume(tid, region)
            out[(tid, region)] = v
            cache[k] = {"built": now.isoformat(), "v": v}
            fetched += 1
            time.sleep(0.04)
    if fetched:
        try:
            json.dump(cache, open(HIST_CACHE, "w", encoding="utf-8"))
        except Exception:
            pass
    print(f"  Daily volume: {fetched} fetched from ESI history, {len(pairs) - fetched} cached.")
    return out


def main():
    ap = argparse.ArgumentParser(description="Build the hub arbitrage calculator page.")
    ap.add_argument("--refresh", action="store_true", help="force ids + volume caches to rebuild")
    ap.add_argument("--html", default=HTML)
    ap.add_argument("--allow-unlocked", action="store_true")
    args = ap.parse_args()

    print(f"\n  BONK HUB ARBITRAGE builder  {datetime.now(timezone.utc).date()}")
    pw = os.environ.get("EVE_PAGE_PASSWORD")
    if not args.allow_unlocked and not (pw or "").strip():
        print("  ERROR: EVE_PAGE_PASSWORD unset; refusing to write an unlocked page (or pass --allow-unlocked).")
        return 2

    try:
        ids_by_name = resolve_ids(refresh=args.refresh)
    except Exception as e:
        print(f"  Could not resolve watchlist ids: {e}")
        return 1
    if not ids_by_name:
        print("  No watchlist ids resolved (ESI down?).")
        return 1

    try:
        vols = resolve_vols(set(ids_by_name.values()), refresh=args.refresh)
    except Exception as e:
        print(f"  Could not fetch volumes: {e}")
        vols = {}
    for nm, m3v in SHIPS.items():            # packaged volume override for ships
        tid = ids_by_name.get(nm)
        if tid:
            vols[tid] = float(m3v)

    print(f"  Fetching prices across {len(HUBS)} hubs for {len(ids_by_name)} items...")
    rows, live_hubs = build_rows(ids_by_name, vols)
    if rows is None:
        print(f"  Only {len(live_hubs)} hub(s) responded; need 2+. Aborting, keeping last good page.")
        return 1
    if not rows:
        print("  No cross hub spreads found (every item priced at fewer than 2 hubs).")
        return 1

    try:
        jumps = jump_matrices(refresh=args.refresh)
    except Exception as e:
        print(f"  Could not fetch jump distances: {e}")
        jumps = {}

    # Daily traded volume at each row's destination hub(s): the real cap on what a single haul can
    # move without crashing the price (a thin destination, not the deep Jita source, is the limit).
    hub_region = {name: rid for name, rid in HUBS}
    pairs = set()
    for r in rows:
        tid = ids_by_name.get(r["n"])
        if tid is None:
            continue
        if r.get("lh"):
            pairs.add((tid, hub_region[r["lh"]]))
        if r.get("fh"):
            pairs.add((tid, hub_region[r["fh"]]))
    print(f"  Fetching destination daily volume for {len(pairs)} (item, hub) pairs...")
    try:
        dv = daily_volumes(pairs, refresh=args.refresh)
    except Exception as e:
        print(f"  Could not fetch daily volumes: {e}")
        dv = {}
    for r in rows:
        tid = ids_by_name.get(r["n"])
        r["ldv"] = dv.get((tid, hub_region.get(r["lh"])), 0) if r.get("lh") else 0
        r["fdv"] = (dv.get((tid, hub_region.get(r["fh"])), 0) if r.get("fh") else None)

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "item_count": len(rows), "hubs": live_hubs, "jumps": jumps,
        "defaults": {"tax": DEF_TAX, "broker": DEF_BROKER, "freight": DEF_FREIGHT,
                     "cargo": DEF_CARGO, "days": DEF_DAYS, "min_vol": DEF_MIN_VOL},
        "rows": rows,
    }
    import arbitrage_page
    arbitrage_page.write_html(args.html, data, pw, allow_plain=args.allow_unlocked)
    print(f"  Wrote page {args.html}  [{'locked' if pw else 'UNLOCKED'}]  "
          f"({len(rows)} items, hubs: {', '.join(live_hubs)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
