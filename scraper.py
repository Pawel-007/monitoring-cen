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
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests.impersonate import DEFAULT_CHROME
    CURL_CFFI_DOSTEPNE = True
except ImportError:
    CURL_CFFI_DOSTEPNE = False

# ---------------------------------------------------------------------------
# Ustawienia ogólne
# ---------------------------------------------------------------------------

# Przedstawiamy się jako zwykła przeglądarka — bez tego część sklepów
# od razu odmawia odpowiedzi. GitHub Actions łączy się z adresu IP centrum
# danych, więc dokładamy więcej nagłówków niż zwykle, żeby wyglądać
# maksymalnie naturalnie.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    # UWAGA: celowo bez 'br' (Brotli) w Accept-Encoding — obiecywalibyśmy serwerowi
    # obsługę kompresji, której bez dodatkowej biblioteki i tak nie umiemy rozpakować.
    # To spowodowało prawdziwą regresję na AudioPlaza (serwer odpowiadał Brotli,
    # a `requests` zwracał nieczytelny tekst zamiast strony).
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

REQUEST_TIMEOUT_SECONDS = 15
LICZBA_PROB = 3           # ile razy próbujemy, zanim uznamy sklep za niedostępny
ODSTEP_MIEDZY_PROBAMI_S = 4   # sekundy odczekania między kolejnymi próbami tego samego produktu
ODSTEP_MIEDZY_PRODUKTAMI_S = 1.5  # drobna pauza między produktami — uprzejmość wobec serwera
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


def cena_wiarygodna(cena: Optional[float]) -> bool:
    """
    Cena 0,00 zł prawie nigdy nie jest prawdziwą ceną produktu — zwykle to szum
    złapany przypadkiem (np. 'raty 0%', 'dostawa 0,00 zł'). Traktujemy ją jako
    brak wyniku, zamiast zapisywać mylącą wartość do dashboardu.
    """
    return cena is not None and cena > 0


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

def cena_z_json_ld(soup: BeautifulSoup) -> Optional[float]:
    """
    Wiele nowoczesnych sklepów (m.in. WooCommerce, PrestaShop z wtyczką Yoast SEO)
    publikuje dane produktu w formacie JSON-LD (schema.org) — ustrukturyzowanym
    bloku danych przeznaczonym do czytania maszynowego przez Google i porównywarki.
    To najbardziej wiarygodne źródło, bo nie wymaga zgadywania formatu tekstu —
    sprawdzamy je w pierwszej kolejności.
    """
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not tag.string:
            continue
        try:
            dane = json.loads(tag.string)
        except (json.JSONDecodeError, TypeError):
            continue
        cena = _szukaj_ceny_w_jsonld(dane)
        if cena is not None:
            return cena
    return None


def _szukaj_ceny_w_jsonld(wezel):
    """Przeszukuje zagnieżdżoną strukturę JSON-LD w poszukiwaniu pierwszego pola 'price'."""
    if isinstance(wezel, dict):
        if "price" in wezel:
            try:
                return float(wezel["price"])
            except (ValueError, TypeError):
                pass
        for wartosc in wezel.values():
            wynik = _szukaj_ceny_w_jsonld(wartosc)
            if wynik is not None:
                return wynik
    elif isinstance(wezel, list):
        for element in wezel:
            wynik = _szukaj_ceny_w_jsonld(element)
            if wynik is not None:
                return wynik
    return None


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
            pass

    # Drugi, bardzo rozpowszechniony standard (schema.org microdata) — spotykany
    # na wielu platformach polskich sklepów, m.in. części opartych o Shoper.
    tag = soup.find(attrs={"itemprop": "price"})
    if tag:
        surowa_wartosc = tag.get("content") or tag.get_text(strip=True)
        wynik = polska_cena_na_float(surowa_wartosc)
        if wynik is not None:
            return wynik

    # Trzeci wzorzec — potwierdzony na żywym kodzie strony PrestaShop (Nautilus2,
    # SalonyDenon): <div class="current-price"><span content="9419">...</span></div>.
    # To ten sam atrybut, którego używa własny JavaScript sklepu do obliczania rat,
    # więc jest równie niezawodny jak znacznik meta.
    div_ceny = soup.find("div", class_="current-price")
    if div_ceny:
        element_z_cena = div_ceny.find(attrs={"content": True})
        if element_z_cena:
            try:
                return float(element_z_cena["content"])
            except ValueError:
                pass

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

def pobierz_z_ponawianiem(url: str) -> requests.Response:
    """
    Próbuje pobrać stronę zwykłym `requests` do LICZBA_PROB razy — to wystarcza
    dla większości sklepów. Jeśli to się nie uda (np. sklep blokuje na podstawie
    odcisku TLS, a nie tylko nagłówków — tak jak podejrzewamy w przypadku Nautilus2),
    w ostatniej próbie sięgamy po curl_cffi, który naśladuje prawdziwą przeglądarkę
    Chrome na poziomie szyfrowania. To często wystarcza tam, gdzie same nagłówki zawodzą.
    """
    ostatni_blad: Optional[Exception] = None
    for probe in range(1, LICZBA_PROB + 1):
        try:
            odpowiedz = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
            odpowiedz.raise_for_status()
            return odpowiedz
        except requests.exceptions.RequestException as e:
            ostatni_blad = e
            if probe < LICZBA_PROB:
                time.sleep(ODSTEP_MIEDZY_PROBAMI_S)

    if CURL_CFFI_DOSTEPNE:
        try:
            odpowiedz = curl_requests.get(
                url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS,
                impersonate=DEFAULT_CHROME,
            )
            odpowiedz.raise_for_status()
            return odpowiedz  # type: ignore[return-value]
        except Exception as e:
            ostatni_blad = e

    raise ostatni_blad  # type: ignore[misc]


def zescrapuj_produkt(url: str, oczekiwany_ean: str) -> tuple[Optional[float], str]:
    """Zwraca (cena, status). Status wyjaśnia, co się stało, jeśli coś poszło nie tak."""
    try:
        odpowiedz = pobierz_z_ponawianiem(url)
    except Exception as e:
        # Celowo szerokie 'Exception', nie tylko requests.exceptions.RequestException —
        # pobierz_z_ponawianiem() w ostatniej próbie sięga po curl_cffi, który rzuca
        # WŁASNY, osobny typ błędu (curl_cffi.requests.exceptions.HTTPError), niezwiązany
        # z biblioteką requests. Wąskie 'except' nie łapało tego wyjątku, przez co jeden
        # niedostępny sklep wywalał cały skrypt zamiast zostać zgłoszony jako błąd wiersza.
        return None, f"blad_pobierania: {e}"

    soup = BeautifulSoup(odpowiedz.text, "html.parser")
    tekst_widoczny = soup.get_text(" ", strip=True)

    # Sprawdzenie tożsamości produktu — jeśli EAN na stronie nie zgadza się
    # z katalogiem, wolimy zgłosić problem niż zapisać cenę złego produktu.
    # Porównujemy jako liczby, nie jako tekst — niektóre sklepy (np. Q21) pokazują
    # EAN z dodatkowym zerem wiodącym (05060565776654 zamiast 5060565776654),
    # a to wciąż ten sam numer.
    znaleziony_ean = wyciagnij_ean(tekst_widoczny)
    if znaleziony_ean and oczekiwany_ean:
        try:
            eany_rozne = int(znaleziony_ean) != int(oczekiwany_ean)
        except ValueError:
            eany_rozne = znaleziony_ean != oczekiwany_ean
        if eany_rozne:
            return None, f"niezgodny_ean (strona pokazuje {znaleziony_ean})"

    # Strategia 1: dane JSON-LD (schema.org) — najbardziej wiarygodne, gdy dostępne.
    cena = cena_z_json_ld(soup)
    if cena_wiarygodna(cena):
        return cena, "ok (json-ld)"

    # Strategia 2: znacznik meta.
    cena = cena_ze_znacznika_meta(soup)
    if cena_wiarygodna(cena):
        return cena, "ok (meta)"

    # Strategia 3: reguła dopasowana do konkretnej domeny.
    domena = urlparse(url).netloc.replace("www.", "")
    for fragment_domeny, funkcja in REGULY_TEKSTOWE.items():
        if fragment_domeny in domena:
            cena = funkcja(tekst_widoczny)
            if cena_wiarygodna(cena):
                return cena, "ok (tekst)"
            return None, "cena_nieznaleziona"

    # Strategia 4: ogólny fallback dla nierozpoznanych domen.
    cena = cena_ogolna_fallback(tekst_widoczny)
    if cena_wiarygodna(cena):
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


# Stała kolejność kolumn w dashboardzie — własny sklep zawsze pierwszy,
# potem konkurenci. Jeśli kiedyś dojdzie kolejny sklep spoza tej listy,
# ląduje na końcu automatycznie, żeby nic po cichu nie zniknęło z raportu.
KOLEJNOSC_SKLEPOW = ["cyfrowedomy.pl", "AudioPlaza", "AudioColor", "Q21", "Nautilus2", "SalonyDenon"]


def zapisz_dashboard(wyniki: list[WynikScrapingu], sciezka: str) -> None:
    """Pivotuje długą listę wyników w tabelę: produkty w wierszach, sklepy w kolumnach."""
    produkty = sorted({w.product_name for w in wyniki})
    sklepy_obecne = {w.sklep for w in wyniki}
    sklepy_dodatkowe = sorted(sklepy_obecne - set(KOLEJNOSC_SKLEPOW))
    sklepy = [s for s in KOLEJNOSC_SKLEPOW if s in sklepy_obecne] + sklepy_dodatkowe

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
                elif pasujace[0].status_scrapingu == "brak_w_ofercie":
                    wiersz.append("x")
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
        time.sleep(ODSTEP_MIEDZY_PRODUKTAMI_S)

    zapisz_wynik_dlugi(wyniki, WYNIK_DLUGI_PLIK)
    zapisz_dashboard(wyniki, WYNIK_DASHBOARD_PLIK)
    print(f"\nGotowe. Zapisano {WYNIK_DLUGI_PLIK} oraz {WYNIK_DASHBOARD_PLIK}.", file=sys.stderr)


if __name__ == "__main__":
    main()
