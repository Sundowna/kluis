"""Locations for the Home map, all offline (HANDOVER §2: never a geo-IP service).

* VPN on  → country code from the NetworkManager connection name → capital city (table below).
* VPN off → "Home location" from Settings, else the city of the system time zone (zone1970.tab).
* Proton Drive data → Zürich.
"""
from __future__ import annotations

import os
import re

CLOUD = ("Zürich", 47.37, 8.54)

# ISO 3166 code → (capital, lat, lon). Covers every country Proton VPN lists plus neighbours.
CAPITALS = {
    "AD": ("Andorra la Vella", 42.51, 1.52), "AE": ("Abu Dhabi", 24.45, 54.38), "AF": ("Kabul", 34.53, 69.17),
    "AL": ("Tirana", 41.33, 19.82), "AM": ("Yerevan", 40.18, 44.51), "AO": ("Luanda", -8.84, 13.23),
    "AR": ("Buenos Aires", -34.60, -58.38), "AT": ("Vienna", 48.21, 16.37), "AU": ("Canberra", -35.28, 149.13),
    "AZ": ("Baku", 40.41, 49.87), "BA": ("Sarajevo", 43.86, 18.41), "BD": ("Dhaka", 23.81, 90.41),
    "BE": ("Brussels", 50.85, 4.35), "BG": ("Sofia", 42.70, 23.32), "BH": ("Manama", 26.23, 50.59),
    "BO": ("La Paz", -16.49, -68.12), "BR": ("Brasília", -15.79, -47.88), "BS": ("Nassau", 25.05, -77.35),
    "BT": ("Thimphu", 27.47, 89.64), "BY": ("Minsk", 53.90, 27.56), "BZ": ("Belmopan", 17.25, -88.77),
    "CA": ("Ottawa", 45.42, -75.70), "CD": ("Kinshasa", -4.44, 15.27), "CH": ("Bern", 46.95, 7.45),
    "CI": ("Yamoussoukro", 6.83, -5.29), "CL": ("Santiago", -33.45, -70.67), "CM": ("Yaoundé", 3.85, 11.50),
    "CN": ("Beijing", 39.90, 116.40), "CO": ("Bogotá", 4.71, -74.07), "CR": ("San José", 9.93, -84.09),
    "CY": ("Nicosia", 35.19, 33.38), "CZ": ("Prague", 50.08, 14.44), "DE": ("Berlin", 52.52, 13.40),
    "DK": ("Copenhagen", 55.68, 12.57), "DO": ("Santo Domingo", 18.49, -69.93), "DZ": ("Algiers", 36.75, 3.06),
    "EC": ("Quito", -0.18, -78.47), "EE": ("Tallinn", 59.44, 24.75), "EG": ("Cairo", 30.04, 31.24),
    "ES": ("Madrid", 40.42, -3.70), "ET": ("Addis Ababa", 9.03, 38.74), "FI": ("Helsinki", 60.17, 24.94),
    "FR": ("Paris", 48.86, 2.35), "GB": ("London", 51.51, -0.13), "GE": ("Tbilisi", 41.72, 44.79),
    "GH": ("Accra", 5.60, -0.19), "GR": ("Athens", 37.98, 23.73), "GT": ("Guatemala City", 14.63, -90.51),
    "HK": ("Hong Kong", 22.32, 114.17), "HN": ("Tegucigalpa", 14.07, -87.19), "HR": ("Zagreb", 45.82, 15.98),
    "HU": ("Budapest", 47.50, 19.04), "ID": ("Jakarta", -6.21, 106.85), "IE": ("Dublin", 53.35, -6.26),
    "IL": ("Jerusalem", 31.77, 35.21), "IN": ("New Delhi", 28.61, 77.21), "IQ": ("Baghdad", 33.31, 44.36),
    "IR": ("Tehran", 35.69, 51.39), "IS": ("Reykjavík", 64.15, -21.94), "IT": ("Rome", 41.90, 12.50),
    "JM": ("Kingston", 18.02, -76.80), "JO": ("Amman", 31.95, 35.93), "JP": ("Tokyo", 35.68, 139.69),
    "KE": ("Nairobi", -1.29, 36.82), "KG": ("Bishkek", 42.87, 74.59), "KH": ("Phnom Penh", 11.56, 104.93),
    "KR": ("Seoul", 37.57, 126.98), "KW": ("Kuwait City", 29.38, 47.99), "KZ": ("Astana", 51.17, 71.45),
    "LA": ("Vientiane", 17.98, 102.63), "LB": ("Beirut", 33.89, 35.50), "LK": ("Colombo", 6.93, 79.86),
    "LT": ("Vilnius", 54.69, 25.28), "LU": ("Luxembourg", 49.61, 6.13), "LV": ("Riga", 56.95, 24.11),
    "LY": ("Tripoli", 32.89, 13.19), "MA": ("Rabat", 34.02, -6.83), "MD": ("Chișinău", 47.01, 28.86),
    "ME": ("Podgorica", 42.43, 19.26), "MK": ("Skopje", 41.99, 21.43), "MM": ("Naypyidaw", 19.76, 96.08),
    "MN": ("Ulaanbaatar", 47.89, 106.91), "MO": ("Macau", 22.20, 113.54), "MT": ("Valletta", 35.90, 14.51),
    "MU": ("Port Louis", -20.16, 57.50), "MX": ("Mexico City", 19.43, -99.13), "MY": ("Kuala Lumpur", 3.14, 101.69),
    "MZ": ("Maputo", -25.97, 32.57), "NG": ("Abuja", 9.08, 7.40), "NL": ("Amsterdam", 52.37, 4.90),
    "NO": ("Oslo", 59.91, 10.75), "NP": ("Kathmandu", 27.72, 85.32), "NZ": ("Wellington", -41.29, 174.78),
    "OM": ("Muscat", 23.59, 58.41), "PA": ("Panama City", 8.98, -79.52), "PE": ("Lima", -12.05, -77.04),
    "PH": ("Manila", 14.60, 120.98), "PK": ("Islamabad", 33.68, 73.05), "PL": ("Warsaw", 52.23, 21.01),
    "PR": ("San Juan", 18.47, -66.11), "PT": ("Lisbon", 38.72, -9.14), "PY": ("Asunción", -25.26, -57.58),
    "QA": ("Doha", 25.29, 51.53), "RO": ("Bucharest", 44.43, 26.10), "RS": ("Belgrade", 44.79, 20.45),
    "RU": ("Moscow", 55.76, 37.62), "RW": ("Kigali", -1.94, 30.06), "SA": ("Riyadh", 24.71, 46.68),
    "SD": ("Khartoum", 15.50, 32.56), "SE": ("Stockholm", 59.33, 18.07), "SG": ("Singapore", 1.35, 103.82),
    "SI": ("Ljubljana", 46.06, 14.51), "SK": ("Bratislava", 48.15, 17.11), "SN": ("Dakar", 14.72, -17.47),
    "SO": ("Mogadishu", 2.05, 45.32), "SV": ("San Salvador", 13.69, -89.22), "SY": ("Damascus", 33.51, 36.28),
    "TH": ("Bangkok", 13.76, 100.50), "TJ": ("Dushanbe", 38.56, 68.79), "TM": ("Ashgabat", 37.96, 58.33),
    "TN": ("Tunis", 36.81, 10.18), "TR": ("Ankara", 39.93, 32.86), "TT": ("Port of Spain", 10.66, -61.51),
    "TW": ("Taipei", 25.03, 121.57), "TZ": ("Dodoma", -6.16, 35.75), "UA": ("Kyiv", 50.45, 30.52),
    "UG": ("Kampala", 0.35, 32.58), "US": ("Washington", 38.91, -77.04), "UY": ("Montevideo", -34.90, -56.16),
    "UZ": ("Tashkent", 41.30, 69.24), "VE": ("Caracas", 10.48, -66.90), "VN": ("Hanoi", 21.03, 105.85),
    "YE": ("Sanaa", 15.37, 44.19), "ZA": ("Pretoria", -25.75, 28.19), "ZM": ("Lusaka", -15.39, 28.32),
    "ZW": ("Harare", -17.83, 31.05), "UK": ("London", 51.51, -0.13),
}
SECURE_CORE_ENTRIES = {"CH", "IS", "SE"}
ZONE_TAB = "/usr/share/zoneinfo/zone1970.tab"


def country_from_connection(name: str) -> str | None:
    """'ProtonVPN CH#23' → CH; 'US-NY#5' → US; Secure Core 'CH-AU#1' (via CH, exit AU) → AU."""
    m = re.search(r"\b([A-Z]{2})(?:-([A-Z]{2}))?#\d+", name or "")
    if not m:
        m = re.search(r"\b([A-Z]{2})(?:-([A-Z]{2}))?\b(?=\s*$)", (name or "").strip())
        if not m or m.group(1) not in CAPITALS:
            return None
    a, b = m.group(1), m.group(2)
    if b and a in SECURE_CORE_ENTRIES and b in CAPITALS:
        return b
    return a if a in CAPITALS else None


def _dms(s: str) -> float:
    sign = -1 if s[0] == "-" else 1
    d = s[1:]
    deg_len = 2 if len(d) in (4, 6) else 3
    deg, rest = int(d[:deg_len]), d[deg_len:]
    mins = int(rest[:2]) if rest else 0
    secs = int(rest[2:4]) if len(rest) >= 4 else 0
    return sign * (deg + mins / 60 + secs / 3600)


def zone_cities(path: str = ZONE_TAB) -> dict[str, tuple[str, float, float]]:
    """tz name → (city, lat, lon), from the system's zone1970.tab."""
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                coord, tz = parts[1], parts[2]
                m = re.match(r"([+-]\d+)([+-]\d+)", coord)
                if not m:
                    continue
                city = tz.split("/")[-1].replace("_", " ")
                out[tz] = (city, _dms(m.group(1)), _dms(m.group(2)))
    except OSError:
        pass
    return out


def system_timezone() -> str:
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz:
        return tz
    try:
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        return open("/etc/timezone").read().strip()
    except OSError:
        return ""


def home_location(home_city: str = "") -> tuple[str, float, float] | None:
    """Settings → Home location (a tz name), else the system time zone's city."""
    cities = zone_cities()
    for key in (home_city, system_timezone()):
        if key and key in cities:
            return cities[key]
    return None


def capital(code: str) -> tuple[str, float, float] | None:
    return CAPITALS.get((code or "").upper())
