#!/usr/bin/env python3
"""
KLOCEK 2 — Scraper cen
========================
Wejście:  katalog_produktow_pilotaz.csv  (Klocek 1 — lista produktów i URL-i)
Wyjście:  ceny_dzisiaj.csv               (jeden wiersz = jeden produkt w jednym sklepie)
          dashboard_podglad.csv          (tabela: produkty w wierszach, sklepy w kolumnach)

Jak to działa w skrócie:
1. Wczytujemy katalog produktów.
2. Dla każdego wiersza ze statusem "znaleziony" (czyli mamy URL) — wchodzimy na stronę.
3. Próbujemy wyciągnąć cenę na dwa sposoby, w kolejności:
   a) znacznik meta "product:price:amount" (jeśli sklep go ma — najbardziej niezawodne)
   b) wzorzec tekstowy dopasowany do konkretnej platformy sklepu
4. Zapisujemy wynik — łącznie z informacją, czy się udało, czy nie.

WAŻNE: ten skrypt wymaga realnego dostępu do internetu, żeby faktycznie
zescrapować ceny. Można go uruchomić lokalnie na własnym komputerze albo
(docelowo) w Kloku 4 — na harmonogramie GitHub Actions.
"""

import csv
import re
import sys
from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Ustawienia ogólne
# ---------------------------------------------------------------------------

# Przedstawiamy się jako zwykła przeglądarka — bez tego część sklepów
# od razu odmawia odpowiedzi.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT_SECONDS = 15
KATALOG_PLIK = "katalog_produktow_pilotaz.csv"
WYNIK_DLUGI_PLIK = f"ceny_{date.today().isoformat()}.csv"
WYNIK_DASHBOARD_PLIK = "dashboard_podglad.csv"


@dataclass
class WynikScrapingu:
    data: str
    product_name: str
    ean: str
    sklep: str
    typ_sklepu: str
    url: str
    cena_pln: Optional[float]
    status_scrapingu: str  # ok / brak_w_ofercie / blad_pobierania / cena_nieznaleziona / niezgodny_ean


# ---------------------------------------------------------------------------
# Narzędzia do parsowania polskich cen
# ---------------------------------------------------------------------------

def polska_cena_na_float(tekst: str) -> Optional[float]:
    """Zamienia string typu '11 490,00' albo '9 192' na liczbę 11490.00 / 9192.0."""
    if not tekst:
        return None
    tekst = tekst.replace("\xa0", "").replace(" ", "").strip()
    tekst = tekst.replace(",", ".")
    try:
        return float(tekst)
    except ValueError:
        return None


def wyciagnij_ean(tekst: str) -> Optional[str]:
    """
    Szuka w tekście strony numeru EAN. Obsługuje dwa spotkane warianty:
    'EAN produktu: 5055300423948' (Q21) oraz 'EAN13 0747192138721' (SalonyDenon),
    gdzie '13' w drugim przypadku to część etykiety (EAN-13), a nie część numeru.
    """
    dopasowanie = re.search(r"EAN\d{0,2}\D{1,20}?(\d{8,14})", tekst)
    return dopasowanie.group(1) if dopasowanie else None


# ---------------------------------------------------------------------------
# Strategia 1: znacznik meta (najbardziej niezawodna, gdy jest dostępna)
# ---------------------------------------------------------------------------

def cena_ze_znacznika_meta(soup: BeautifulSoup) -> Optional[float]:
    """
    Niektóre platformy (np. PrestaShop na SalonyDenon) wpisują cenę wprost
    w niewidocznym znaczniku <meta property="product:price:amount" content="4199">.
    To najpewniejsze źródło — sprawdzamy je zawsze w pierwszej kolejności.
    """
    tag = soup.find("meta", attrs={"property": "product:price:amount"})
    if tag is None:
        tag = soup.find("meta", attrs={"name": "product:price:amount"})
    if tag and tag.get("content"):
        try:
            return float(tag["content"])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Strategia 2: wzorce tekstowe dopasowane do konkretnego sklepu
# ---------------------------------------------------------------------------

def cena_q21(tekst_widoczny: str) -> Optional[float]:
    """
    Q21 (platforma SOTESHOP) pokazuje cenę jako zwykły tekst, np.:
    '11 490,00 zł 9 580,00 zł / szt.'
    Druga liczba (bliżej '/ szt.') to cena aktualna.
    """
    dopasowania = re.findall(r"(\d[\d\s\xa0]*,\d{2})\s*zł", tekst_widoczny)
    if not dopasowania:
        return None
    # Bierzemy ostatnią cenę widoczną tuż przed "/ szt." — to ta faktycznie płacona.
    return polska_cena_na_float(dopasowania[-1])


def cena_nautilus2(tekst_widoczny: str) -> Optional[float]:
    """
    Nautilus2 (PrestaShop) pokazuje cenę zaraz po tytule, tuż przed słowem 'Brutto':
    '4 995,00 zł  Brutto'
    """
    dopasowanie = re.search(r"(\d[\d\s\xa0]*,\d{2})\s*zł\s*Brutto", tekst_widoczny)
    if dopasowanie:
        return polska_cena_na_float(dopasowanie.group(1))
    return None


def cena_audioplaza(tekst_widoczny: str) -> Optional[float]:
    """
    AudioPlaza (własna platforma) pokazuje ceny BEZ grosza, np.:
    '9 192 zł  11 490 zł  Najniższa cena z 30 dni: 9 192 zł'
    Najpewniejszym punktem odniesienia jest etykieta "Najniższa cena z 30 dni".
    """
    dopasowanie = re.search(r"Najniższa cena z 30 dni:\s*(\d[\d\s\xa0]*)\s*zł", tekst_widoczny)
    if dopasowanie:
        return polska_cena_na_float(dopasowanie.group(1))
    # Fallback: pierwsza liczba z "zł" na stronie (mniej pewne).
    dopasowanie = re.search(r"(\d[\d\s\xa0]*)\s*zł", tekst_widoczny)
    if dopasowanie:
        return polska_cena_na_float(dopasowanie.group(1))
    return None


def cena_ogolna_fallback(tekst_widoczny: str) -> Optional[float]:
    """
    Ostatnia deska ratunku dla sklepów bez dedykowanej reguły (np. cyfrowedomy.pl,
    jeśli nie ma znacznika meta) — szukamy typowego polskiego zapisu ceny z groszami.
    Mniej pewne niż reguły dedykowane — traktować jako wynik do weryfikacji.
    """
    dopasowania = re.findall(r"(\d[\d\s\xa0]*,\d{2})\s*zł", tekst_widoczny)
    if dopasowania:
        return polska_cena_na_float(dopasowania[0])
    return None


# Mapa: fragment domeny -> funkcja parsująca tekst widoczny na stronie.
REGULY_TEKSTOWE = {
    "q21.pl": cena_q21,
    "nautilus2.pl": cena_nautilus2,
    "audioplaza.pl": cena_audioplaza,
}


# ---------------------------------------------------------------------------
# Główna funkcja scrapująca pojedynczy produkt
# ---------------------------------------------------------------------------

def zescrapuj_produkt(url: str, oczekiwany_ean: str) -> tuple[Optional[float], str]:
    """Zwraca (cena, status). Status wyjaśnia, co się stało, jeśli coś poszło nie tak."""
    try:
        odpowiedz = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        odpowiedz.raise_for_status()
    except requests.exceptions.RequestException as e:
        return None, f"blad_pobierania: {e}"

    soup = BeautifulSoup(odpowiedz.text, "html.parser")
    tekst_widoczny = soup.get_text(" ", strip=True)

    # Sprawdzenie tożsamości produktu — jeśli EAN na stronie nie zgadza się
    # z katalogiem, wolimy zgłosić problem niż zapisać cenę złego produktu.
    znaleziony_ean = wyciagnij_ean(tekst_widoczny)
    if znaleziony_ean and oczekiwany_ean and znaleziony_ean != oczekiwany_ean:
        return None, f"niezgodny_ean (strona pokazuje {znaleziony_ean})"

    # Strategia 1: znacznik meta.
    cena = cena_ze_znacznika_meta(soup)
    if cena is not None:
        return cena, "ok (meta)"

    # Strategia 2: reguła dopasowana do konkretnej domeny.
    domena = urlparse(url).netloc.replace("www.", "")
    for fragment_domeny, funkcja in REGULY_TEKSTOWE.items():
        if fragment_domeny in domena:
            cena = funkcja(tekst_widoczny)
            if cena is not None:
                return cena, "ok (tekst)"
            return None, "cena_nieznaleziona"

    # Strategia 3: ogólny fallback dla nierozpoznanych domen (np. cyfrowedomy.pl).
    cena = cena_ogolna_fallback(tekst_widoczny)
    if cena is not None:
        return cena, "ok (fallback - do weryfikacji)"

    return None, "cena_nieznaleziona"


# ---------------------------------------------------------------------------
# Główny przebieg programu
# ---------------------------------------------------------------------------

def wczytaj_katalog(sciezka: str) -> list[dict]:
    with open(sciezka, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def zapisz_wynik_dlugi(wyniki: list[WynikScrapingu], sciezka: str) -> None:
    with open(sciezka, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(wyniki[0]).keys()))
        writer.writeheader()
        for w in wyniki:
            writer.writerow(asdict(w))


def zapisz_dashboard(wyniki: list[WynikScrapingu], sciezka: str) -> None:
    """Pivotuje długą listę wyników w tabelę: produkty w wierszach, sklepy w kolumnach."""
    produkty = sorted({w.product_name for w in wyniki})
    sklepy = sorted({w.sklep for w in wyniki})

    with open(sciezka, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["produkt"] + sklepy)
        for produkt in produkty:
            wiersz = [produkt]
            for sklep in sklepy:
                pasujace = [w for w in wyniki if w.product_name == produkt and w.sklep == sklep]
                if not pasujace:
                    wiersz.append("—")
                elif pasujace[0].cena_pln is not None:
                    wiersz.append(f"{pasujace[0].cena_pln:.2f}")
                else:
                    wiersz.append(pasujace[0].status_scrapingu)
            writer.writerow(wiersz)


def main() -> None:
    katalog = wczytaj_katalog(KATALOG_PLIK)
    dzis = date.today().isoformat()
    wyniki: list[WynikScrapingu] = []

    for wiersz in katalog:
        if wiersz["status"] == "brak_w_ofercie" or not wiersz["url"]:
            wyniki.append(WynikScrapingu(
                data=dzis, product_name=wiersz["product_name"], ean=wiersz["ean"],
                sklep=wiersz["sklep"], typ_sklepu=wiersz["typ_sklepu"], url="",
                cena_pln=None, status_scrapingu="brak_w_ofercie",
            ))
            continue

        print(f"Sprawdzam: {wiersz['product_name']} @ {wiersz['sklep']} ...", file=sys.stderr)
        cena, status = zescrapuj_produkt(wiersz["url"], wiersz["ean"])
        wyniki.append(WynikScrapingu(
            data=dzis, product_name=wiersz["product_name"], ean=wiersz["ean"],
            sklep=wiersz["sklep"], typ_sklepu=wiersz["typ_sklepu"], url=wiersz["url"],
            cena_pln=cena, status_scrapingu=status,
        ))

    zapisz_wynik_dlugi(wyniki, WYNIK_DLUGI_PLIK)
    zapisz_dashboard(wyniki, WYNIK_DASHBOARD_PLIK)
    print(f"\nGotowe. Zapisano {WYNIK_DLUGI_PLIK} oraz {WYNIK_DASHBOARD_PLIK}.", file=sys.stderr)


if __name__ == "__main__":
    main()
