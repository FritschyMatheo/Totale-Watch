#!/usr/bin/env python3
"""
Collecteur : interroge le flux instantané prix-carburants (API Opendatasoft du
ministère de l'Économie) pour les stations listées dans stations.json, calcule
l'état par carburant, détecte les débuts et fins de rupture, et écrit :

  data/latest.json  état courant de chaque station (lu par index.html)
  data/events.json  journal des événements (début / fin de rupture)
  data/state.json   état interne pour le diff entre deux relevés

Le flux instantané ne contient que les ruptures EN COURS : une fin de rupture
se détecte par disparition de l'entrée entre deux relevés. D'où le cron.

Usage : python3 collect.py            (appel réseau)
        python3 collect.py --from f.json   (rejoue une réponse API sauvegardée)
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
API = ("https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
       "prix-des-carburants-en-france-flux-instantane-v2/records")
TZ = ZoneInfo("Europe/Paris")
FUELS = ["Gazole", "E10", "SP98", "SP95", "E85", "GPLc"]
MAX_EVENTS = 5000


def now_iso():
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def flux_time(s):
    """Les horodatages bruts du flux ('2026-09-08 09:08:37') sont en heure de Paris."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ).isoformat()
    except ValueError:
        return s


def geo(v):
    """Coordonnées PTV_GEODECIMAL du flux : diviser par 100 000 pour obtenir du WGS84."""
    try:
        return round(float(v) / 100000, 6)
    except (TypeError, ValueError):
        return None


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def as_list(v):
    """Les champs 'prix' et 'rupture' sont des chaînes JSON : objet seul ou liste."""
    if v is None or v == "":
        return []
    if isinstance(v, str):
        v = json.loads(v)
    return v if isinstance(v, list) else [v]


def fetch(ids):
    where = "id in (" + ",".join(str(i) for i in ids) + ")"
    url = API + "?" + urllib.parse.urlencode({"where": where, "limit": 100})
    req = urllib.request.Request(url, headers={"User-Agent": "total-watch/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def station_state(rec):
    """Retourne {carburant: {status, prix, prix_maj, rupture_debut, rupture_type}}."""
    prix = {p["@nom"]: p for p in as_list(rec.get("prix"))}
    rupt = {r["@nom"]: r for r in as_list(rec.get("rupture"))}
    out = {}
    for f in FUELS:
        r = rupt.get(f)
        p = prix.get(f)
        if r and r.get("@type") == "definitive":
            status = "non_vendu"
        elif r:
            status = "rupture"
        else:
            # pas de rupture déclarée : disponible (certaines stations ne publient pas de prix)
            status = "ok"
        out[f] = {
            "status": status,
            "prix": float(p["@valeur"]) if p and p.get("@valeur") else None,
            "prix_maj": flux_time(p.get("@maj")) if p else None,
            "rupture_debut": flux_time(r.get("@debut")) if r else None,
            "rupture_type": r.get("@type") if r else None,
        }
    return out


def diff(prev, cur, sid, nom, ts):
    """Compare l'état précédent et l'état courant d'une station -> liste d'événements."""
    events = []
    for f in FUELS:
        a = (prev or {}).get(f)
        b = cur[f]
        if a is None:
            continue  # première observation : pas d'événement
        if a["status"] == "rupture" and b["status"] == "ok":
            events.append({"ts": ts, "type": "fin_rupture", "station": sid, "nom": nom,
                           "carburant": f, "rupture_debut": a["rupture_debut"],
                           "prix": b["prix"]})
        elif a["status"] != "rupture" and b["status"] == "rupture":
            events.append({"ts": ts, "type": "debut_rupture", "station": sid, "nom": nom,
                           "carburant": f, "rupture_debut": b["rupture_debut"],
                           "rupture_type": b["rupture_type"]})
        elif (a["status"] == "rupture" and b["status"] == "rupture"
              and a["rupture_debut"] != b["rupture_debut"]):
            # rupture close puis rouverte entre deux relevés
            events.append({"ts": ts, "type": "fin_rupture", "station": sid, "nom": nom,
                           "carburant": f, "rupture_debut": a["rupture_debut"],
                           "prix": b["prix"], "approx": True})
            events.append({"ts": ts, "type": "debut_rupture", "station": sid, "nom": nom,
                           "carburant": f, "rupture_debut": b["rupture_debut"],
                           "rupture_type": b["rupture_type"]})
    return events


def notify(events):
    """Point d'extension pour les alertes (e-mail, Telegram…). Volontairement vide en v1."""
    return


def main():
    cfg = load(os.path.join(ROOT, "stations.json"), {"stations": []})
    stations = cfg["stations"]
    ids = [s["id"] for s in stations]
    if not ids:
        print("stations.json vide", file=sys.stderr)
        return 1

    if len(sys.argv) >= 3 and sys.argv[1] == "--from":
        resp = load(sys.argv[2], {})
    else:
        resp = fetch(ids)
    records = {r["id"]: r for r in resp.get("results", [])}

    ts = now_iso()
    state = load(os.path.join(DATA, "state.json"), {})
    events = load(os.path.join(DATA, "events.json"), [])
    new_events = []
    latest = {"collected_at": ts, "source": API, "stations": []}

    for s in stations:
        sid = str(s["id"])
        rec = records.get(s["id"])
        if rec is None:
            latest["stations"].append({**s, "absent": True, "carburants": state.get(sid, {}).get("carburants", {})})
            continue
        cur = station_state(rec)
        prev = state.get(sid, {}).get("carburants")
        new_events += diff(prev, cur, s["id"], s["nom"], ts)
        state[sid] = {"carburants": cur, "seen": ts}
        latest["stations"].append({
            **s,
            "absent": False,
            "h24": rec.get("horaires_automate_24_24"),
            "lat": geo(rec.get("latitude")), "lon": geo(rec.get("longitude")),
            "carburants": cur,
        })

    events = (events + new_events)[-MAX_EVENTS:]
    save(os.path.join(DATA, "state.json"), state)
    save(os.path.join(DATA, "events.json"), events)
    save(os.path.join(DATA, "latest.json"), latest)
    if new_events:
        notify(new_events)
    print(f"{ts} : {len(records)}/{len(ids)} stations, {len(new_events)} événement(s)")
    for e in new_events:
        print("  ", e["type"], e["nom"], e["carburant"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
