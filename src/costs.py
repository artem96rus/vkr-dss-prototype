"""
costs.py - расчёт удельных стоимостей по схемам.


Значения тарифных параметров (RATE_FTL, BETA, GAMMA, K_DOROG, LM_PD_KM,
CAP_TRUCK, UTIL_S1, UTIL_S2) подтягиваются из локального config.py,
если он существует, иначе из config_example.py со синтетическими
значениями. 

Производные величины:
    c1_local    - стоимость пары на пал. в схеме ЦП ТРЦ, без магистрали
    c2_local    - стоимость пары на пал. в схеме Региональный пулинг, без магистрали
    c_ftl_truck - стоимость одной фуры на магистрали ТРЦ - РЦ ПД (одна для обеих схем)
"""
import pandas as pd

from distances import CITY_COORDS, haversine_km, city_from_rc



# Загрузка параметров тарифной модели

# Сначала пытаемся подтянуть локальный config.py с реальными значениями.

try:
    from config import (
        RATE_FTL, CAP_TRUCK, UTIL_S1, UTIL_S2,
        BETA, GAMMA, K_DOROG, LM_PD_KM,
    )
    _CONFIG_SOURCE = "config.py (локальные корпоративные значения)"
except ImportError:
    from config_example import (
        RATE_FTL, CAP_TRUCK, UTIL_S1, UTIL_S2,
        BETA, GAMMA, K_DOROG, LM_PD_KM,
    )
    _CONFIG_SOURCE = "config_example.py (синтетические значения)"


# Производный параметр - удельный тариф LTL на плече "РЦ ПД -> ТТ",
# выводится через эффективную ёмкость фуры в режиме PBL 
ALPHA = RATE_FTL / (CAP_TRUCK * UTIL_S1)


def calc_costs(df_pairs):
    """Добавляет к df_pairs колонки удельных стоимостей по формулам. 
    """
    df = df_pairs.copy()

    df["город"] = df["РЦ Географический"].apply(city_from_rc)

    # Магистральное плечо ТРЦ Самара -> РЦ ПД с поправкой на k_d
    samara = CITY_COORDS["Самара"]
    dist_trc_pd = {}
    for city, coords in CITY_COORDS.items():
        if city == "Самара":
            continue
        dist_trc_pd[city] = haversine_km(samara, coords) * K_DOROG

    df["dist_pd_km"] = df["город"].map(dist_trc_pd)

    # плечо "РЦ ПД -> ТТ" с поправкой на k_d
    df["LM_PD_km"] = df["город"].map(LM_PD_KM) * K_DOROG

    # Удельные стоимости
    df["c1_local"] = ALPHA * df["LM_PD_km"] + BETA
    df["c2_local"] = ALPHA * df["LM_PD_km"] + GAMMA

    # Стоимость одного магистрального рейса
    df["c_ftl_truck"] = df["dist_pd_km"] * RATE_FTL

    return df


if __name__ == "__main__":
    from load import load_data
    from filter import apply_filters, aggregate_to_pairs

    print("Загрузка и фильтрация...")
    df_v, _ = load_data()
    df_pairs = aggregate_to_pairs(apply_filters(df_v))
    df_costs = calc_costs(df_pairs)

    print(f"\nИсточник параметров: {_CONFIG_SOURCE}")
    print(f"\nЗаданные параметры (таблица 22 ВКР):")
    print(f"  R_FTL  = {RATE_FTL:.2f} руб./(км*фура)")
    print(f"  Q      = {CAP_TRUCK} пал./фура")
    print(f"  eta1   = {UTIL_S1:.2f}  (PBL, схема ЦП ТРЦ)")
    print(f"  eta2   = {UTIL_S2:.2f}  (FTL, схема Региональный пулинг)")
    print(f"  alpha  = R_FTL / (Q * eta1) = {ALPHA:.4f} руб./(пал*км)")
    print(f"  beta   = {BETA:.1f} руб./пал.")
    print(f"  gamma  = {GAMMA:.1f} руб./пал.")
    print(f"  k_d    = {K_DOROG:.2f}")

    print(f"\nУдельные стоимости по РЦ:")
    summary = df_costs.groupby("город").agg(
        пар=("Код ТП", "count"),
        dist_pd=("dist_pd_km", "first"),
        LM_PD=("LM_PD_km", "first"),
        c1=("c1_local", "first"),
        c2=("c2_local", "first"),
        c_ftl=("c_ftl_truck", "first"),
    ).round(2)
    print(summary.to_string())

    delta_per_km = RATE_FTL / CAP_TRUCK * (1 / UTIL_S1 - 1 / UTIL_S2)
    indiff_dist = (GAMMA - BETA) / delta_per_km
    print(f"\nТочка безразличия S1=S2: магистраль {indiff_dist:.0f} км")
