#!/usr/bin/env python3
"""
KLOCEK 5 — Poranny raport (strona HTML)
=========================================
Wejście:  ceny_YYYY-MM-DD.csv    (plik długi wygenerowany przez scraper.py — ma URL każdego produktu)
Wyjście:  docs/index.html        (strona wyświetlana przez GitHub Pages)

Uruchamiany jako ostatni krok w workflow GitHub Actions, zaraz po scraper.py,
żeby strona zawsze pokazywała najświeższe dane.

Każda cena na stronie jest linkiem do konkretnej podstrony produktu w danym
sklepie — pozwala to błyskawicznie zweryfikować "na żywo" każdą podejrzaną
wartość, bez ręcznego szukania produktu na stronie sklepu.
"""

import csv
import glob
from datetime import date

WLASNY_SKLEP = "cyfrowedomy.pl"
WYJSCIE = "docs/index.html"

# Ta sama kolejność, co w dashboard_podglad.csv — własny sklep zawsze pierwszy.
KOLEJNOSC_SKLEPOW = ["cyfrowedomy.pl", "AudioPlaza", "AudioColor", "Q21", "Nautilus2", "SalonyDenon"]


def znajdz_najnowszy_plik_cen() -> str:
    """Scraper.py zapisuje plik z datą w nazwie (ceny_2026-07-10.csv) — bierzemy najświeższy."""
    kandydaci = sorted(glob.glob("ceny_*.csv"))
    if not kandydaci:
        raise FileNotFoundError(
            "Nie znaleziono żadnego pliku ceny_*.csv — uruchom najpierw scraper.py."
        )
    return kandydaci[-1]


def wczytaj_dane(sciezka: str) -> list[dict]:
    with open(sciezka, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def komorka_na_liczbe(wartosc: str):
    try:
        return float(wartosc)
    except (ValueError, TypeError):
        return None


def zbuduj_macierz(wiersze: list[dict]):
    """Układa listę wierszy (produkt, sklep, cena, url, status) w siatkę produkt x sklep."""
    produkty = sorted({w["product_name"] for w in wiersze})
    sklepy_obecne = {w["sklep"] for w in wiersze}
    sklepy_dodatkowe = sorted(sklepy_obecne - set(KOLEJNOSC_SKLEPOW))
    sklepy = [s for s in KOLEJNOSC_SKLEPOW if s in sklepy_obecne] + sklepy_dodatkowe
    macierz = {(w["product_name"], w["sklep"]): w for w in wiersze}
    return produkty, sklepy, macierz


STYL_CSS = """
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f4;
    color: #262625;
    margin: 0;
    padding: 24px 16px 48px;
  }
  .wrapper { max-width: 1200px; margin: 0 auto; }
  h1 { font-size: 1.4rem; margin-bottom: 4px; }
  .aktualizacja { color: #6b6b68; font-size: 0.9rem; margin-bottom: 20px; }
  table {
    width: 100%;
    border-collapse: collapse;
    background: white;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }
  th, td {
    padding: 10px 14px;
    text-align: right;
    border-bottom: 1px solid #e8e6e1;
    font-variant-numeric: tabular-nums;
  }
  th { background: #cccccc; color: #f5f5f4; font-weight: 600; font-size: 0.85rem; }
  td.produkt, th:first-child { text-align: left; }
  th.wlasny { background: #555555; }
  td.wlasny { background: #eeeeee; font-weight: 600; }
  td.najtansza { color: #f33333; font-weight: 700; }
  td.brak { color: #b5b3ae; }
  td.blad { color: #f33333; font-size: 0.85rem; }
  tr:last-child td { border-bottom: none; }
  td a { color: inherit; text-decoration: none; border-bottom: 1px dotted #999; }
  td a:hover { border-bottom-style: solid; }
  .legenda { margin-top: 16px; font-size: 0.85rem; color: #6b6b68; }
"""


def zbuduj_html(produkty: list[str], sklepy: list[str], macierz: dict) -> str:
    dzis = date.today().strftime("%d.%m.%Y")

    naglowki_kolumn = "".join(
        f'<th class="{"wlasny" if s == WLASNY_SKLEP else ""}">{s}</th>' for s in sklepy
    )

    wiersze_html = []
    for produkt in produkty:
        # Najpierw ustalamy najniższą cenę w wierszu (do podświetlenia).
        ceny_w_wierszu = []
        for sklep in sklepy:
            wpis = macierz.get((produkt, sklep))
            if wpis:
                cena = komorka_na_liczbe(wpis.get("cena_pln"))
                if cena is not None:
                    ceny_w_wierszu.append(cena)
        najnizsza = min(ceny_w_wierszu) if ceny_w_wierszu else None

        komorki = []
        for sklep in sklepy:
            wpis = macierz.get((produkt, sklep))
            klasy = []
            if sklep == WLASNY_SKLEP:
                klasy.append("wlasny")

            if wpis is None:
                komorki.append(f'<td class="{" ".join(klasy) or "brak"}">—</td>')
                continue

            cena = komorka_na_liczbe(wpis.get("cena_pln"))
            url = (wpis.get("url") or "").strip()
            status = wpis.get("status_scrapingu", "")

            if cena is not None:
                if cena == najnizsza:
                    klasy.append("najtansza")
                tresc = f"{cena:,.2f} zł".replace(",", " ").replace(".", ",", 1)
            elif status == "brak_w_ofercie":
                klasy.append("brak")
                tresc = "x"
            else:
                klasy.append("blad")
                tresc = "błąd"

            # Cena albo błąd z dostępnym URL-em — owijamy w link, żeby dało się
            # jednym kliknięciem zweryfikować wartość na żywo w sklepie.
            if url:
                tresc = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{tresc}</a>'

            klasa_attr = f' class="{" ".join(klasy)}"' if klasy else ""
            komorki.append(f"<td{klasa_attr}>{tresc}</td>")

        wiersze_html.append(f"<tr><td class=\"produkt\">{produkt}</td>{''.join(komorki)}</tr>")

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Monitoring cen — ACP</title>
<style>{STYL_CSS}</style>
</head>
<body>
<div class="wrapper">
  <h1>Monitoring cen — ACP</h1>
  <div class="aktualizacja">Ostatnia aktualizacja: {dzis}</div>
  <table>
    <thead><tr><th>Produkt</th>{naglowki_kolumn}</tr></thead>
    <tbody>
      {"".join(wiersze_html)}
    </tbody>
  </table>
  <div class="legenda">
    szara kolumna — Twoja cena (cyfrowedomy.pl) &nbsp;•&nbsp;
    czerwona liczba — najniższa cena w wierszu &nbsp;•&nbsp;
    x — sklep nie ma tego produktu w ofercie &nbsp;•&nbsp;
    kliknij cenę, żeby zweryfikować ją na żywo w sklepie
  </div>
</div>
</body>
</html>
"""


def main() -> None:
    plik_wejsciowy = znajdz_najnowszy_plik_cen()
    wiersze = wczytaj_dane(plik_wejsciowy)
    produkty, sklepy, macierz = zbuduj_macierz(wiersze)
    html = zbuduj_html(produkty, sklepy, macierz)
    import os
    os.makedirs("docs", exist_ok=True)
    with open(WYJSCIE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Zapisano {WYJSCIE} na podstawie {plik_wejsciowy}")


if __name__ == "__main__":
    main()
