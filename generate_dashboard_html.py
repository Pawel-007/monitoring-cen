#!/usr/bin/env python3
"""
KLOCEK 5 — Poranny raport (strona HTML)
=========================================
Wejście:  dashboard_podglad.csv   (wygenerowany przez scraper.py — Klocek 2)
Wyjście:  docs/index.html         (strona wyświetlana przez GitHub Pages)

Uruchamiany jako ostatni krok w workflow GitHub Actions, zaraz po scraper.py,
żeby strona zawsze pokazywała najświeższe dane.
"""

import csv
from datetime import date

WLASNY_SKLEP = "cyfrowedomy.pl"
WEJSCIE = "dashboard_podglad.csv"
WYJSCIE = "docs/index.html"


def wczytaj_dashboard(sciezka: str) -> tuple[list[str], list[list[str]]]:
    with open(sciezka, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        naglowek = next(reader)
        wiersze = list(reader)
    return naglowek, wiersze


def komorka_na_liczbe(wartosc: str) -> float | None:
    try:
        return float(wartosc)
    except ValueError:
        return None


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
  .legenda { margin-top: 16px; font-size: 0.85rem; color: #6b6b68; }
"""


def zbuduj_html(naglowek: list[str], wiersze: list[list[str]]) -> str:
    sklepy = naglowek[1:]
    dzis = date.today().strftime("%d.%m.%Y")

    naglowki_kolumn = "".join(
        f'<th class="{"wlasny" if s == WLASNY_SKLEP else ""}">{s}</th>' for s in sklepy
    )

    wiersze_html = []
    for wiersz in wiersze:
        produkt = wiersz[0]
        wartosci = wiersz[1:]
        ceny_liczbowe = [komorka_na_liczbe(v) for v in wartosci]
        najnizsza = min((c for c in ceny_liczbowe if c is not None), default=None)

        komorki = []
        for sklep, wartosc, cena in zip(sklepy, wartosci, ceny_liczbowe):
            klasy = []
            if sklep == WLASNY_SKLEP:
                klasy.append("wlasny")
            if cena is not None:
                if cena == najnizsza:
                    klasy.append("najtansza")
                tresc = f"{cena:,.2f} zł".replace(",", " ").replace(".", ",", 1)
            elif wartosc == "x":
                klasy.append("brak")
                tresc = "x"
            else:
                klasy.append("blad")
                tresc = "błąd"
            klasa_attr = f' class="{" ".join(klasy)}"' if klasy else ""
            komorki.append(f"<td{klasa_attr}>{tresc}</td>")

        wiersze_html.append(f"<tr><td class=\"produkt\">{produkt}</td>{''.join(komorki)}</tr>")

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Monitoring cen — cyfrowedomy</title>
<style>{STYL_CSS}</style>
</head>
<body>
<div class="wrapper">
  <h1>Monitoring cen — cyfrowedomy</h1>
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
    x — sklep nie ma tego produktu w ofercie
  </div>
</div>
</body>
</html>
"""


def main() -> None:
    naglowek, wiersze = wczytaj_dashboard(WEJSCIE)
    html = zbuduj_html(naglowek, wiersze)
    import os
    os.makedirs("docs", exist_ok=True)
    with open(WYJSCIE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Zapisano {WYJSCIE}")


if __name__ == "__main__":
    main()
