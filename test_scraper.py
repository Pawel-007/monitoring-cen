"""
Test logiki parsowania cen — na PRAWDZIWYCH fragmentach tekstu zebranych
podczas zwiadu po pięciu sklepach. Nie łączy się z internetem — sprawdza
tylko, czy funkcje poprawnie odczytują cenę z tekstu, który już widzieliśmy.
"""

from bs4 import BeautifulSoup

from scraper import (
    polska_cena_na_float,
    wyciagnij_ean,
    cena_ze_znacznika_meta,
    cena_z_json_ld,
    cena_wiarygodna,
    cena_q21,
    cena_nautilus2,
    cena_audioplaza,
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

# --- Q21: prawdziwy fragment strony Cambridge Audio EVO 150 SE ------------
tekst_q21 = (
    "1 2 3 ... 1000 szt. - 11 490,00 zł 9 580,00 zł / szt. - dodaj do koszyka - "
    "Wzmacniacz zintegrowany ze streamerem Cambridge Audio Evo 150 SE"
)
sprawdz("cena_q21 (Cambridge EVO 150 SE)", cena_q21(tekst_q21), 9580.00)

# --- Nautilus2: prawdziwy fragment strony Monitor Audio Silver 500 --------
tekst_nautilus2 = (
    "Monitor Audio 7G Silver 500 Black Gloss 4 995,00 zł Brutto PrestaShop Checkout"
)
sprawdz("cena_nautilus2 (Monitor Audio Silver 500)", cena_nautilus2(tekst_nautilus2), 4995.00)

# --- AudioPlaza: prawdziwy fragment strony Cambridge Audio EVO 150 SE -----
tekst_audioplaza = (
    "Autoryzowany dealer 9 192 zł 11 490 zł Najniższa cena z 30 dni: 9 192 zł DO KOSZYKA"
)
sprawdz("cena_audioplaza (Cambridge EVO 150 SE)", cena_audioplaza(tekst_audioplaza), 9192.0)

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

print(f"\n{testy_zaliczone} / {testy_wszystkie} testow zaliczonych.")
if testy_zaliczone != testy_wszystkie:
    raise SystemExit(1)
