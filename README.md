# Struja preko granica Srbije

Interaktivna 3D mapa prekograničnih tokova električne energije za zonu Srbije (BZN|RS), sat po sat.
Podaci se svakog jutra automatski preuzimaju sa ENTSO-E Transparency Platform, a stranica se objavljuje na GitHub Pages.

- **Stvarno**: Cross-Border Physical Flows (12.1.G)
- **Plan**: Scheduled Commercial Exchanges (12.1.F, Total)
- **Potrošnja**: Actual Total Load (6.1.A)
- **Provera**: zbir Day-ahead plana po granicama u poređenju sa neto pozicijom Srbije

## Struktura

```
scripts/entsoe_srbija.py        preuzima podatke i pravi JSON po danu
docs/index.html                 stranica (deck.gl, 3D lukovi)
docs/data/zemlje.geojson        granice (Natural Earth)
docs/data/dani/YYYY-MM-DD.json  podaci po danu (puni ih skripta)
docs/data/index.json            spisak dostupnih dana
.github/workflows/osvezi.yml    dnevno osvežavanje i objava
```

## Podešavanje (jednom)

1. Napravi **javni** repozitorijum na GitHubu i ubaci sve ove fajlove.
2. **Settings → Secrets and variables → Actions → New repository secret**
   Name: `ENTSOE_TOKEN`, Secret: tvoj ENTSO-E token.
3. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. **Actions → „Osvezi podatke i objavi mapu” → Run workflow**
   `od`: `2026-10-25`, `do`: prazno. Ovo puni istoriju od prelaska na zimsko vreme.
5. Kada se završi, mapa je na `https://<korisnik>.github.io/<repozitorijum>/`.

Posle toga workflow se pokreće sam svakog jutra i ponovo preuzima poslednja 3 dana
(ENTSO-E naknadno ispravlja vrednosti).

## Lokalno pokretanje

```
pip install -r requirements.txt
# PowerShell:  $env:ENTSOE_TOKEN="tvoj_token"
python scripts/entsoe_srbija.py --od 2026-10-25
cd docs && python -m http.server 8000
```

Otvori `http://localhost:8000`. Link čuva dan, sat i režim, npr. `#2026-11-03/8/razlika`.

## Napomene

- Predznak: pozitivno = neto uvoz u Srbiju, negativno = izvoz.
- Prikazane su zone trgovanja ENTSO-E. Kosovo i Metohija su na mapi deo Srbije; Kosovo* je posebna zona u podacima ENTSO-E.
- Albanija ima oznaku „n/e” (podatak se ne objavljuje) i prikazuje se sivom linijom.
- Token se nikad ne upisuje u kod, samo u GitHub Secrets ili u promenljivu okruženja.
