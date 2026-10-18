"""Generate backend/src/nexscout/domain/geo_data/countries.json (run once; the output is committed).

    uv run --no-project --with pycountry --with pycountry-convert python scripts/gen_countries.py

Source: ISO 3166-1 via pycountry (all 249 assigned codes) and continents via pycountry-convert.
Added by hand (below): common and local-language names, major cities for matching free-text
locations ("Espoo", "München"), and groups people search by (EU, Nordics, DACH, …).
"""

from __future__ import annotations

import json
from pathlib import Path

import pycountry
import pycountry_convert as pc

OUT = Path(__file__).resolve().parents[1] / "backend/src/nexscout/domain/geo_data/countries.json"

CONTINENTS = {"AF": "Africa", "AN": "Antarctica", "AS": "Asia", "EU": "Europe",
              "NA": "North America", "OC": "Oceania", "SA": "South America"}

ALIASES: dict[str, list[str]] = {
    "GB": ["UK", "U.K.", "Great Britain", "Britain", "England", "Scotland", "Wales",
           "Northern Ireland"],
    "US": ["USA", "U.S.", "U.S.A.", "United States of America"],
    "AE": ["UAE", "Emirates"], "KR": ["South Korea", "Korea"], "KP": ["North Korea"],
    "RU": ["Russia"], "IR": ["Iran"], "SY": ["Syria"], "VN": ["Vietnam"], "LA": ["Laos"],
    "TW": ["Taiwan"], "TZ": ["Tanzania"], "BO": ["Bolivia"], "VE": ["Venezuela"],
    "MD": ["Moldova"], "CZ": ["Czech Republic", "Czechia", "Česko", "Česká republika"],
    "TR": ["Turkey", "Türkiye", "Turkiye"], "NL": ["Holland", "The Netherlands", "Nederland"],
    "DE": ["Deutschland", "Germany"], "AT": ["Österreich", "Oesterreich"],
    "CH": ["Schweiz", "Suisse", "Svizzera", "Swiss"], "FI": ["Suomi"], "SE": ["Sverige"],
    "NO": ["Norge", "Noreg"], "DK": ["Danmark"], "IS": ["Ísland"], "ES": ["España", "Espana"],
    "IT": ["Italia"], "PL": ["Polska"], "BE": ["België", "Belgique", "Belgien"],
    "IE": ["Éire", "Republic of Ireland"], "HU": ["Magyarország"], "RO": ["România"],
    "GR": ["Ελλάδα", "Hellas"], "PT": ["Portugal"], "FR": ["France"], "HR": ["Hrvatska"],
    "SI": ["Slovenija"], "SK": ["Slovensko"], "EE": ["Eesti"], "LV": ["Latvija"],
    "LT": ["Lietuva"], "LU": ["Lëtzebuerg", "Luxemburg"], "BG": ["България"],
    "RS": ["Srbija"], "UA": ["Ukraine", "Україна"], "CN": ["China", "PRC"],
    "HK": ["Hong Kong"], "MO": ["Macau", "Macao"], "IN": ["India", "Bharat"],
    "MK": ["Macedonia", "North Macedonia"], "CD": ["DR Congo", "Congo-Kinshasa"],
    "CG": ["Congo-Brazzaville"], "CI": ["Ivory Coast", "Côte d'Ivoire"], "PS": ["Palestine"],
    "BN": ["Brunei"], "FM": ["Micronesia"], "VA": ["Vatican", "Holy See"],
}

# Major cities (and a few well-known regions) per country, for free-text locations.
CITIES: dict[str, list[str]] = {
    "FI": ["Helsinki", "Espoo", "Tampere", "Vantaa", "Oulu", "Turku", "Jyväskylä", "Jyvaskyla",
           "Lahti", "Kuopio", "Lappeenranta", "Joensuu", "Vaasa", "Pori", "Rovaniemi", "Otaniemi"],
    "SE": ["Stockholm", "Gothenburg", "Göteborg", "Malmö", "Malmo", "Uppsala", "Lund",
           "Linköping", "Linkoping", "Umeå", "Umea", "Västerås", "Örebro"],
    "NO": ["Oslo", "Bergen", "Trondheim", "Stavanger", "Tromsø", "Tromso"],
    "DK": ["Copenhagen", "København", "Aarhus", "Odense", "Aalborg", "Lyngby"],
    "IS": ["Reykjavik", "Reykjavík"],
    "EE": ["Tallinn", "Tartu"], "LV": ["Riga"], "LT": ["Vilnius", "Kaunas"],
    "DE": ["Berlin", "Munich", "München", "Muenchen", "Hamburg", "Frankfurt", "Cologne", "Köln",
           "Stuttgart", "Düsseldorf", "Dusseldorf", "Dresden", "Leipzig", "Heidelberg",
           "Karlsruhe", "Darmstadt", "Aachen", "Bonn", "Tübingen", "Tuebingen", "Freiburg",
           "Hanover", "Hannover", "Nuremberg", "Nürnberg", "Bremen", "Mannheim", "Saarbrücken",
           "Saarbruecken", "Erlangen", "Göttingen", "Jena", "Potsdam", "Bavaria", "Bayern"],
    "AT": ["Vienna", "Wien", "Graz", "Linz", "Salzburg", "Innsbruck", "Klosterneuburg"],
    "CH": ["Zurich", "Zürich", "Geneva", "Genève", "Basel", "Lausanne", "Bern", "Lugano",
           "Zug"],
    "NL": ["Amsterdam", "Rotterdam", "The Hague", "Den Haag", "Utrecht", "Eindhoven", "Delft",
           "Leiden", "Groningen", "Nijmegen", "Enschede", "Tilburg", "Maastricht", "Wageningen"],
    "BE": ["Brussels", "Bruxelles", "Brussel", "Antwerp", "Antwerpen", "Ghent", "Gent",
           "Leuven", "Louvain", "Liège", "Liege"],
    "LU": ["Luxembourg City", "Esch-sur-Alzette"],
    "FR": ["Paris", "Lyon", "Marseille", "Toulouse", "Grenoble", "Nice", "Sophia Antipolis",
           "Bordeaux", "Lille", "Nantes", "Strasbourg", "Montpellier", "Rennes", "Saclay"],
    "GB": ["London", "Cambridge", "Oxford", "Manchester", "Edinburgh", "Glasgow", "Bristol",
           "Birmingham", "Leeds", "Sheffield", "Belfast", "Cardiff", "Nottingham",
           "Southampton", "Liverpool", "Newcastle", "Reading", "Guildford", "Bath", "York"],
    "IE": ["Dublin", "Cork", "Galway", "Limerick"],
    "ES": ["Madrid", "Barcelona", "Valencia", "Seville", "Sevilla", "Bilbao", "Málaga",
           "Malaga", "Granada", "Zaragoza", "San Sebastián"],
    "PT": ["Lisbon", "Lisboa", "Porto", "Braga", "Coimbra", "Aveiro"],
    "IT": ["Rome", "Roma", "Milan", "Milano", "Turin", "Torino", "Bologna", "Florence",
           "Firenze", "Naples", "Napoli", "Pisa", "Padua", "Padova", "Genoa", "Genova", "Trento",
           "Trieste"],
    "PL": ["Warsaw", "Warszawa", "Kraków", "Krakow", "Wrocław", "Wroclaw", "Gdańsk", "Gdansk",
           "Poznań", "Poznan", "Łódź", "Lodz", "Katowice"],
    "CZ": ["Prague", "Praha", "Brno", "Ostrava"], "SK": ["Bratislava", "Košice"],
    "HU": ["Budapest", "Debrecen", "Szeged"], "RO": ["Bucharest", "București", "Cluj-Napoca",
                                                      "Iași", "Timișoara"],
    "BG": ["Sofia"], "GR": ["Athens", "Thessaloniki", "Heraklion"],
    "HR": ["Zagreb", "Split"], "SI": ["Ljubljana"], "RS": ["Belgrade", "Novi Sad"],
    "CY": ["Nicosia", "Limassol"], "MT": ["Valletta"], "UA": ["Kyiv", "Kiev", "Lviv"],
    "TR": ["Istanbul", "Ankara", "Izmir"],
    "US": ["New York", "San Francisco", "Seattle", "Boston", "Los Angeles", "Austin",
           "Chicago", "Palo Alto", "Mountain View", "Menlo Park", "Cupertino", "San Jose",
           "Sunnyvale", "Redmond", "Pittsburgh", "Washington, DC", "Atlanta", "Denver",
           "San Diego", "Bay Area", "Silicon Valley", "California", "Texas", "Massachusetts"],
    "CA": ["Toronto", "Vancouver", "Montreal", "Montréal", "Ottawa", "Calgary", "Waterloo",
           "Edmonton", "Quebec", "Ontario", "British Columbia", "Alberta"],
    "IN": ["Bengaluru", "Bangalore", "Mumbai", "Delhi", "New Delhi", "Hyderabad", "Pune",
           "Chennai", "Kolkata", "Gurgaon", "Gurugram", "Noida", "Ahmedabad"],
    "SG": ["Singapore"], "JP": ["Tokyo", "Osaka", "Kyoto"], "KR": ["Seoul"],
    "CN": ["Beijing", "Shanghai", "Shenzhen", "Hangzhou"], "AU": ["Sydney", "Melbourne",
                                                                   "Brisbane", "Perth"],
    "NZ": ["Auckland", "Wellington"], "AE": ["Dubai", "Abu Dhabi"], "IL": ["Tel Aviv", "Haifa"],
    "BR": ["São Paulo", "Sao Paulo", "Rio de Janeiro"], "MX": ["Mexico City", "Guadalajara"],
    "AR": ["Buenos Aires"], "ZA": ["Cape Town", "Johannesburg"], "EG": ["Cairo"],
    "NG": ["Lagos"], "KE": ["Nairobi"],
}

EU = ["AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT",
      "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"]
GROUPS: dict[str, dict[str, object]] = {
    "EU": {"name": "European Union", "codes": EU},
    "EEA": {"name": "EU + Iceland, Liechtenstein, Norway", "codes": [*EU, "IS", "LI", "NO"]},
    "SCHENGEN": {"name": "Schengen area", "codes": sorted(set(EU) - {"CY", "IE"} | {"IS", "LI", "NO", "CH"})},
    "NORDICS": {"name": "Nordic countries", "codes": ["DK", "FI", "IS", "NO", "SE"]},
    "BALTICS": {"name": "Baltic states", "codes": ["EE", "LV", "LT"]},
    "DACH": {"name": "Germany, Austria, Switzerland", "codes": ["DE", "AT", "CH"]},
    "BENELUX": {"name": "Belgium, Netherlands, Luxembourg", "codes": ["BE", "NL", "LU"]},
    "UKI": {"name": "UK and Ireland", "codes": ["GB", "IE"]},
    "IBERIA": {"name": "Spain and Portugal", "codes": ["ES", "PT"]},
}


def main() -> None:
    countries = []
    by_continent: dict[str, list[str]] = {}
    for c in sorted(pycountry.countries, key=lambda c: c.alpha_2):
        try:
            cont = CONTINENTS[pc.country_alpha2_to_continent_code(c.alpha_2)]
        except KeyError:
            cont = {"TL": "Asia", "EH": "Africa", "SX": "North America", "VA": "Europe",
                    "AQ": "Antarctica", "UM": "Oceania", "PN": "Oceania", "TF": "Antarctica"}.get(
                c.alpha_2, "Other")
        names = {c.name, getattr(c, "common_name", None), getattr(c, "official_name", None)}
        aliases = sorted({n for n in names if n} | set(ALIASES.get(c.alpha_2, [])))
        display = getattr(c, "common_name", None) or {
            "GB": "United Kingdom", "US": "United States", "KR": "South Korea",
            "RU": "Russia", "IR": "Iran", "TW": "Taiwan", "VN": "Vietnam", "SY": "Syria",
            "VE": "Venezuela", "BO": "Bolivia", "TZ": "Tanzania", "MD": "Moldova",
            "LA": "Laos", "KP": "North Korea", "CZ": "Czechia", "TR": "Türkiye",
        }.get(c.alpha_2, c.name)
        countries.append({"code": c.alpha_2, "alpha3": c.alpha_3, "name": display,
                          "continent": cont, "aliases": aliases,
                          "cities": CITIES.get(c.alpha_2, [])})
        by_continent.setdefault(cont, []).append(c.alpha_2)
    groups = dict(GROUPS)
    groups["EUROPE"] = {"name": "Europe (whole continent)", "codes": by_continent["Europe"]}
    for key, cont in (("AFRICA", "Africa"), ("ASIA", "Asia"), ("NORTH_AMERICA", "North America"),
                      ("SOUTH_AMERICA", "South America"), ("OCEANIA", "Oceania")):
        groups[key] = {"name": cont, "codes": by_continent[cont]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "ISO 3166-1 (pycountry) + continents (pycountry-convert)",
                               "countries": countries, "groups": groups},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(countries)} countries, {len(groups)} groups -> {OUT}")


if __name__ == "__main__":
    main()
