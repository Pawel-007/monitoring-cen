"""
Test logiki parsowania cen — na PRAWDZIWYCH fragmentach tekstu zebranych
podczas zwiadu po pięciu sklepach. Nie łączy się z internetem — sprawdza
tylko, czy funkcje poprawnie odczytują cenę z tekstu, który już widzieliśmy.
"""

from unittest.mock import patch

from bs4 import BeautifulSoup

from scraper import (
    polska_cena_na_float,
    wyciagnij_ean,
    cena_ze_znacznika_meta,
    cena_z_json_ld,
    cena_wiarygodna,
    zescrapuj_produkt,
)

testy_zaliczone = 0
testy_wszystkie = 0


def sprawdz(nazwa: str, otrzymano, oczekiwano) -> None:
    global testy_zaliczone, testy_wszystkie
    testy_wszystkie += 1
    ok = otrzymano == oczekiwano
    testy_zaliczone += int(ok)
    znacznik = "OK  " if ok else "BLAD"
    print(f"[{znacznik}] {nazwa}: otrzymano={otrzymano!r}  oczekiwano={oczekiwano!r}")


# --- Podstawowa konwersja polskiego zapisu ceny ---------------------------
sprawdz("polska_cena_na_float - z groszami", polska_cena_na_float("11 490,00"), 11490.00)
sprawdz("polska_cena_na_float - bez grosza", polska_cena_na_float("9 192"), 9192.0)

# --- Q21: itemprop="price" znaleziony w PRAWDZIWYM kodzie strony (Marantz Cinema 60) ---
html_q21_itemprop = """
<html><body>
<meta itemprop="url" content="https://www.q21.pl/marantz-cinema-60-czarny.html" />
<meta itemprop="priceValidUntil" content="2026-07-24" />
<meta itemprop="price" content="4148.00" />
</body></html>
"""
soup_q21 = BeautifulSoup(html_q21_itemprop, "html.parser")
sprawdz("cena_ze_znacznika_meta (Q21, prawdziwy itemprop='price')",
        cena_ze_znacznika_meta(soup_q21), 4148.00)

# --- Nautilus2: prawdziwa struktura JSON-LD (Marantz Cinema 60) -----------
html_json_ld_nautilus2 = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Marantz CINEMA 60 Czarny",
"offers":{"availability":"https://schema.org/InStock","price":"4199.00","priceCurrency":"PLN",
"url":"https://nautilus2.pl/amplitunery-kina-domowego/31732-marantz-cinema-60-czarny-0747192138721.html"}}
</script>
</head></html>
"""
soup_nautilus2_ld = BeautifulSoup(html_json_ld_nautilus2, "html.parser")
sprawdz("cena_z_json_ld (Nautilus2, prawdziwa struktura)",
        cena_z_json_ld(soup_nautilus2_ld), 4199.00)

# --- SalonyDenon: PUŁAPKA wariantów kolorystycznych w jednym bloku JSON-LD ---
# Prawdziwa struktura: jeden blok JSON-LD opisuje NARAZ dwa warianty kolorystyczne
# (Silver-Gold i Czarny). Gdy obie ceny są takie same — ufamy wynikowi.
html_warianty_zgodne = """
<html><head>
<script type="application/ld+json">
{"@type":"Product","name":"Marantz Cinema 60",
"hasVariant":[
  {"color":"Silver-gold","offers":{"@type":"Offer","price":"4199","priceCurrency":"PLN"}},
  {"color":"Czarny","offers":{"@type":"Offer","price":"4199","priceCurrency":"PLN"}}
]}
</script>
</head></html>
"""
soup_zgodne = BeautifulSoup(html_warianty_zgodne, "html.parser")
sprawdz("cena_z_json_ld (SalonyDenon, warianty ZGODNE co do ceny -> ufamy)",
        cena_z_json_ld(soup_zgodne), 4199.0)

# Gdyby warianty miały RÓŻNE ceny — nie zgadujemy, zwracamy None zamiast złapać
# przypadkiem cenę niewłaściwego koloru.
html_warianty_rozne = """
<html><head>
<script type="application/ld+json">
{"@type":"Product","name":"Przykladowy produkt z dwoma cenami wariantow",
"hasVariant":[
  {"color":"Silver-gold","offers":{"@type":"Offer","price":"4199","priceCurrency":"PLN"}},
  {"color":"Czarny","offers":{"@type":"Offer","price":"4599","priceCurrency":"PLN"}}
]}
</script>
</head></html>
"""
soup_rozne = BeautifulSoup(html_warianty_rozne, "html.parser")
sprawdz("cena_z_json_ld (warianty RÓŻNE co do ceny -> None, nie zgadujemy)",
        cena_z_json_ld(soup_rozne), None)

# --- AudioPlaza: nie ma już dedykowanej reguły tekstowej — patrz test JSON-LD niżej ---

# --- SalonyDenon: prawdziwy znacznik meta z Marantz Cinema 60 -------------
html_salonydenon = """
<html><head>
<meta property="product:price:amount" content="4199">
<meta property="product:price:currency" content="PLN">
</head></html>
"""
soup = BeautifulSoup(html_salonydenon, "html.parser")
sprawdz("cena_ze_znacznika_meta (Marantz Cinema 60)", cena_ze_znacznika_meta(soup), 4199.0)

# --- Wyciąganie EAN: prawdziwe fragmenty z Q21 i SalonyDenon --------------
sprawdz(
    "wyciagnij_ean (Q21, format 'EAN produktu:')",
    wyciagnij_ean("EAN produktu: 5055300423948 Dane producenta:"),
    "5055300423948",
)
sprawdz(
    "wyciagnij_ean (SalonyDenon, format 'EAN13')",
    wyciagnij_ean("Specyficzne kody EAN13 0747192138721 Bezpieczeństwo produktu"),
    "0747192138721",
)

# --- USTERKA #1 (Q21): EAN z zerem wiodącym musi być uznany za ten sam ----
sprawdz(
    "EAN z zerem wiodącym == EAN bez zera (bug z prawdziwego uruchomienia)",
    int("05060565776654") == int("5060565776654"),
    True,
)

# --- USTERKA #2 (cyfrowedomy.pl): cena 0,00 zł musi być odrzucona ----------
sprawdz("cena_wiarygodna(0.0) - cena zerowa odrzucona", cena_wiarygodna(0.0), False)
sprawdz("cena_wiarygodna(None) - brak ceny odrzucony", cena_wiarygodna(None), False)
sprawdz("cena_wiarygodna(4995.0) - prawdziwa cena zaakceptowana", cena_wiarygodna(4995.0), True)

# --- USTERKA #2 (ciąg dalszy): wykrywanie ceny przez itemprop="price" ------
html_itemprop = """
<html><body>
<span itemprop="price" content="4796.00">4 796,00 zł</span>
</body></html>
"""
soup_itemprop = BeautifulSoup(html_itemprop, "html.parser")
sprawdz("cena_ze_znacznika_meta (itemprop='price', wariant Shoper)",
        cena_ze_znacznika_meta(soup_itemprop), 4796.00)

# --- USTERKA #3 (Nautilus2): prawdziwa struktura current-price z Twojego pliku HTML ---
html_current_price = """
<html><body>
<div class="product-price h5">
  <link href="https://schema.org/InStock"/>
  <meta content="PLN">
  <div class="current-price">
    <span content="9419">9&nbsp;419,00&nbsp;zł</span>
  </div>
</div>
</body></html>
"""
soup_current_price = BeautifulSoup(html_current_price, "html.parser")
sprawdz("cena_ze_znacznika_meta (div.current-price, prawdziwy HTML Nautilus2)",
        cena_ze_znacznika_meta(soup_current_price), 9419.0)

# --- USTERKA/FUNKCJA #4 (AudioColor): dane JSON-LD, prawdziwa struktura -----
html_json_ld = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Cambridge Audio EVO 150 SE",
"brand":{"@type":"Brand","name":"Cambridge Audio"},
"offers":{"@type":"Offer","priceCurrency":"PLN","price":"11490.00",
"priceSpecification":[{"@type":"UnitPriceSpecification","price":"11490.00","priceCurrency":"PLN","validThrough":"2027-12-31"}],
"seller":{"@type":"Organization","name":"Sklep Audio Color","url":"https://sklep.audiocolor.pl"}}}
</script>
</head></html>
"""
soup_json_ld = BeautifulSoup(html_json_ld, "html.parser")
sprawdz("cena_z_json_ld (AudioColor, prawdziwa struktura)", cena_z_json_ld(soup_json_ld), 11490.00)

# --- USTERKA #5 (awaria z prawdziwego uruchomienia): błąd spoza requests.exceptions ---
class UdawanyBladCurlCffi(Exception):
    """Odtwarza curl_cffi.requests.exceptions.HTTPError — wyjątek spoza hierarchii requests."""
    pass


with patch("scraper.pobierz_z_ponawianiem", side_effect=UdawanyBladCurlCffi("HTTP Error 500")):
    cena, status = zescrapuj_produkt("https://nautilus2.pl/przyklad.html", "0000000000000")
    sprawdz("zescrapuj_produkt nie wywala się na błędzie spoza requests (bug z GH Actions)",
            (cena, status.startswith("blad_pobierania")), (None, True))

# --- AudioPlaza: ta sama strategia JSON-LD, ale cena jako liczba, nie tekst ----
html_json_ld_audioplaza = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Cambridge Audio EVO 150 SE",
"offers":{"@type":"Offer","priceCurrency":"PLN","price":9192.0,"itemCondition":"http://schema.org/NewCondition",
"availability":"http://schema.org/InStock","priceValidUntil":"2027-07-10"},
"brand":{"@type":"http://schema.org/Brand","name":"Cambridge Audio"}}
</script>
</head></html>
"""
soup_json_ld_audioplaza = BeautifulSoup(html_json_ld_audioplaza, "html.parser")
sprawdz("cena_z_json_ld (AudioPlaza, cena jako liczba JSON, nie tekst)",
        cena_z_json_ld(soup_json_ld_audioplaza), 9192.0)

print(f"\n{testy_zaliczone} / {testy_wszystkie} testow zaliczonych.")
if testy_zaliczone != testy_wszystkie:
    raise SystemExit(1)
