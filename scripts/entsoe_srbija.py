"""
Prekogranicni tokovi struje za zonu Srbije (BZN|RS) - ENTSO-E Transparency Platform

Za svaki dan povlaci:
  - stvarne fizicke tokove (Cross-Border Physical Flows, 12.1.G)
  - plan razmene (Scheduled Commercial Exchanges, 12.1.F) - Total i Day-ahead
  - potrosnju Srbije (Actual Total Load, 6.1.A)
  - neto poziciju Srbije (Day-ahead), za proveru zbira

i upisuje:
  - docs/data/dani/YYYY-MM-DD.json   jedan fajl po danu
  - docs/data/index.json             spisak dostupnih dana

Predznak svuda: pozitivno = neto uvoz u Srbiju, negativno = neto izvoz iz Srbije.

Pokretanje (token se NE upisuje u kod, nego u promenljivu ENTSOE_TOKEN):
  python scripts/entsoe_srbija.py                          # poslednja 3 zavrsena dana
  python scripts/entsoe_srbija.py --poslednjih-dana 7
  python scripts/entsoe_srbija.py --od 2026-10-25 --do 2026-11-03
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
from entsoe import EntsoePandasClient
from entsoe.exceptions import NoMatchingDataError

TZ = "Europe/Belgrade"
SRBIJA = "RS"
SUSEDI = ["HU", "RO", "BG", "MK", "XK", "ME", "BA", "HR", "AL"]
TOLERANCIJA_MW = 1.0
PARALELNO = 8      # istovremenih zahteva (ENTSO-E dozvoljava do 400 zahteva u minuti)
POKUSAJA = 3       # pokusaja po zahtevu kod privremenih gresaka servera
TOKEN = None

KOREN = Path(__file__).resolve().parent.parent
IZLAZ = KOREN / "docs" / "data"


def na_sat(serija, sati):
    """Lokalno vreme, satni prosek, poravnato na sate dana (23, 24 ili 25)."""
    if serija is None or len(serija) == 0:
        return pd.Series(index=sati, dtype=float)
    s = serija.tz_convert(TZ).resample("1h").mean()
    return s.reindex(sati)


def bez_tokena(tekst):
    """Uklanja token iz poruka o gresci, da se ni deo ne vidi u javnom logu."""
    return re.sub(r"securityToken=[^&\s]*", "securityToken=***", str(tekst))


_lokalno = threading.local()


def klijent():
    """Svaka nit ima svoj klijent (svoju HTTP sesiju)."""
    if not hasattr(_lokalno, "c"):
        # timeout: zahtev bez odgovora za 60 s se prekida (bez ovoga moze da visi zauvek)
        _lokalno.c = EntsoePandasClient(api_key=TOKEN, retry_count=2, retry_delay=5, timeout=60)
    return _lokalno.c


def privremena_greska(e):
    """Greske posle kojih ima smisla pokusati ponovo (server 5xx, istek vremena, mreza)."""
    if isinstance(e, (requests.Timeout, requests.ConnectionError)):
        return True
    odgovor = getattr(e, "response", None)
    return odgovor is not None and odgovor.status_code >= 500


def povuci(opis, metoda, sati, **kwargs):
    """Poziva API (do POKUSAJA puta); ako nema podatka vraca prazne vrednosti umesto greske."""
    t0 = time.monotonic()
    for pokusaj in range(1, POKUSAJA + 1):
        try:
            rezultat = getattr(klijent(), metoda)(**kwargs)
            break
        except NoMatchingDataError:
            print(f"    {opis}: nema podatka ({time.monotonic() - t0:.1f}s)", flush=True)
            return na_sat(None, sati), None
        except Exception as e:
            poruka = f"{type(e).__name__}: {bez_tokena(e)[:160]}"
            if pokusaj < POKUSAJA and privremena_greska(e):
                print(f"    {opis}: {poruka} - pokusavam ponovo ({pokusaj}/{POKUSAJA})", flush=True)
                time.sleep(5 * pokusaj)
                continue
            print(f"    {opis}: GRESKA {poruka} ({time.monotonic() - t0:.1f}s)", flush=True)
            return na_sat(None, sati), poruka
    print(f"    {opis}: ok ({time.monotonic() - t0:.1f}s)", flush=True)

    if isinstance(rezultat, pd.DataFrame):
        kolona = "Actual Load" if "Actual Load" in rezultat.columns else rezultat.columns[0]
        rezultat = rezultat[kolona]
    return na_sat(rezultat, sati), None


def lista(serija):
    return [None if pd.isna(v) else round(float(v), 2) for v in serija]


def jedan_dan(dan):
    start = pd.Timestamp(dan, tz=TZ)
    end = pd.Timestamp(dan + dt.timedelta(days=1), tz=TZ)
    sati = pd.date_range(start, end, freq="1h", inclusive="left", tz=TZ)
    print(f"  {dan} ({len(sati)} sati)", flush=True)

    # Svi zahtevi za dan: (kljuc, opis, metoda, parametri). Salju se paralelno.
    poslovi = []
    for s in SUSEDI:
        za_rs = dict(country_code_from=s, country_code_to=SRBIJA)
        iz_rs = dict(country_code_from=SRBIJA, country_code_to=s)
        poslovi += [
            ((s, "uvoz"), f"tok {s}->RS", "query_crossborder_flows", za_rs),
            ((s, "izvoz"), f"tok RS->{s}", "query_crossborder_flows", iz_rs),
            ((s, "p_uvoz"), f"plan {s}->RS", "query_scheduled_exchanges", {**za_rs, "dayahead": False}),
            ((s, "p_izvoz"), f"plan RS->{s}", "query_scheduled_exchanges", {**iz_rs, "dayahead": False}),
            ((s, "da_uvoz"), f"plan DA {s}->RS", "query_scheduled_exchanges", {**za_rs, "dayahead": True}),
            ((s, "da_izvoz"), f"plan DA RS->{s}", "query_scheduled_exchanges", {**iz_rs, "dayahead": True}),
        ]
    poslovi += [
        (("RS", "potrosnja"), "potrosnja RS", "query_load", dict(country_code=SRBIJA)),
        (("RS", "neto_poz"), "neto pozicija RS", "query_net_position", dict(country_code=SRBIJA, dayahead=True)),
    ]

    r, greske = {}, []
    with ThreadPoolExecutor(max_workers=PARALELNO) as ex:
        buduci = {ex.submit(povuci, opis, metoda, sati, start=start, end=end, **kw): kljuc
                  for kljuc, opis, metoda, kw in poslovi}
        for f in as_completed(buduci):
            serija, greska = f.result()
            r[buduci[f]] = serija
            if greska:
                greske.append(greska)

    granice = {}
    plan_da = {}
    for s in SUSEDI:
        uvoz, izvoz = r[(s, "uvoz")], r[(s, "izvoz")]
        p_uvoz, p_izvoz = r[(s, "p_uvoz")], r[(s, "p_izvoz")]
        da_uvoz, da_izvoz = r[(s, "da_uvoz")], r[(s, "da_izvoz")]
        granice[s] = {
            "stvarno": lista(uvoz - izvoz),
            "plan": lista(p_uvoz - p_izvoz),
            "plan_uvoz": lista(p_uvoz),
            "plan_izvoz": lista(p_izvoz),
        }
        plan_da[s] = da_uvoz - da_izvoz

    potrosnja = r[("RS", "potrosnja")]
    neto_poz = r[("RS", "neto_poz")]

    # Provera: zbir Day-ahead plana po granicama mora odgovarati neto poziciji.
    # Predznak neto pozicije na API-ju nije proveren, pa se porede apsolutne vrednosti.
    zbir_da = pd.DataFrame(plan_da).sum(axis=1, min_count=1)
    odstupanje = (zbir_da.abs() - neto_poz.abs()).abs()
    provera = ["nema podatka" if pd.isna(o) else ("ok" if o <= TOLERANCIJA_MW else "ne slaže se")
               for o in odstupanje]

    ima_tokova = any(v is not None for g in granice.values() for v in g["stvarno"])
    return {
        "datum": dan.isoformat(),
        "sati": [t.strftime("%H:%M") for t in sati],
        "vreme": [t.isoformat() for t in sati],
        "granice": granice,
        "srbija": {
            "potrosnja": lista(potrosnja),
            "neto_pozicija_da": lista(neto_poz),
            "zbir_plana_da": lista(zbir_da),
            "provera": provera,
        },
        "osvezeno": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }, ima_tokova, greske


def osvezi_index():
    dani = sorted(p.stem for p in (IZLAZ / "dani").glob("*.json"))
    index = {
        "dani": dani,
        "osvezeno": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    }
    (IZLAZ / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return dani


def main():
    p = argparse.ArgumentParser(description="ENTSO-E tokovi za Srbiju")
    p.add_argument("--od", help="prvi dan, YYYY-MM-DD")
    p.add_argument("--do", help="poslednji dan, YYYY-MM-DD (podrazumevano juce)")
    p.add_argument("--poslednjih-dana", type=int, default=3,
                   help="koliko zavrsenih dana unazad (ako --od nije zadat)")
    a = p.parse_args()

    global TOKEN
    TOKEN = os.environ.get("ENTSOE_TOKEN")
    if not TOKEN:
        sys.exit("Nije postavljen ENTSOE_TOKEN.")

    danas = pd.Timestamp.now(tz=TZ).date()
    do = dt.date.fromisoformat(a.do) if a.do else danas - dt.timedelta(days=1)
    od = dt.date.fromisoformat(a.od) if a.od else do - dt.timedelta(days=a.poslednjih_dana - 1)
    if od > do:
        sys.exit("--od mora biti pre --do")

    (IZLAZ / "dani").mkdir(parents=True, exist_ok=True)

    print(f"Povlacim {od} - {do}", flush=True)
    t0 = time.monotonic()
    upisano, preskoceno, sve_greske = 0, [], []
    dan = od
    while dan <= do:
        podaci, ima_tokova, greske = jedan_dan(dan)
        sve_greske += greske
        fajl = IZLAZ / "dani" / f"{dan.isoformat()}.json"
        if ima_tokova:
            fajl.write_text(json.dumps(podaci, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
            upisano += 1
        else:
            # Ne prepisuj postojece dobre podatke praznim (npr. kad API ne radi)
            preskoceno.append(dan.isoformat())
        dan += dt.timedelta(days=1)

    dani = osvezi_index()
    print(f"Upisano dana: {upisano}. Ukupno u arhivi: {len(dani)}. "
          f"Trajanje: {(time.monotonic() - t0) / 60:.1f} min.")
    if sve_greske:
        print(f"Zahteva sa greskom (posle ponovnih pokusaja): {len(sve_greske)}")
    if preskoceno:
        print("Bez podataka o tokovima (nije upisano):", ", ".join(preskoceno))

    # Ako nijedan dan nije uspeo zbog gresaka (npr. los token), neka GitHub Actions prijavi gresku
    if upisano == 0 and sve_greske:
        sys.exit("Nijedan dan nije upisan. Prva greska: " + sve_greske[0])


if __name__ == "__main__":
    main()
