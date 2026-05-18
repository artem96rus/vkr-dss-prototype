"""
distances.py - координаты городов Самарского региона
и формула гаверсинусов для расстояний по прямой.
"""
import math


# Координаты городов в формате (широта, долгота) в десятичных градусах.
# Источник: Яндекс.Карты
CITY_COORDS = {
    "Самара":       (53.2001, 50.1500),
    "Тольятти":     (53.5078, 49.4204),
    "Зеленодольск": (55.8456, 48.5519),
    "Пенза":        (53.2007, 45.0046),
    "Киров":        (58.6035, 49.6679),
    "Энгельс":      (51.4825, 46.1006),
}

EARTH_RADIUS_KM = 6371.0


def haversine_km(p1, p2):
    """
    Расстояние между двумя точками на Земле по формуле гаверсинусов, км.
    p1, p2 - кортежи (широта, долгота) в градусах.
    """
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_KM * c


def city_from_rc(rc_name):
    """
    Достаёт название города из имени РЦ.
    Например: 'РЦ ПД Тольятти' -> 'Тольятти'.
    """
    name = str(rc_name)
    for city in CITY_COORDS:
        if city in name:
            return city
    raise KeyError(f"Не нашёл город в имени РЦ: {rc_name}")


def coords_from_rc(rc_name):
    """Возвращает координаты РЦ по его имени."""
    return CITY_COORDS[city_from_rc(rc_name)]


if __name__ == "__main__":
    samara = CITY_COORDS["Самара"]
    print("Расстояния от ТРЦ Самара до РЦ ПД (км, по прямой):")
    for city, coords in CITY_COORDS.items():
        if city == "Самара":
            continue
        print(f"  {city:<14} {haversine_km(samara, coords):>6.1f}")
