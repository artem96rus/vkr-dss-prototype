"""
as_is.py - расчёт стоимости при текущем распределении и при рекомендации МИАС.


Соответствие значений колонки ЦП и схем модели:
    ПД       -> схема S2 (Региональный пулинг)
    ТРЦ      -> схема S1 (ЦП ТРЦ)
    ТРЦ PBL  -> схема S1 (ЦП ТРЦ через PBL)
"""
import math

import numpy as np
import pandas as pd

from costs import CAP_TRUCK, UTIL_S1, UTIL_S2
from optimizer import VOL_COL


# Маппинг значений ЦП на схемы модели
CP_TO_SCHEME = {
    "ПД":      "S2",
    "ТРЦ":     "S1",
    "ТРЦ PBL": "S1",
}


def _calc_cost_components(df):
    """Считает компоненты стоимости  с проставленными
    бинарными колонками x_S1 и x_S2.

    Магистральные рейсы пересчитываются заново округлением вверх,
    что позволяет применять функцию и к подмножеству пар.
    """
    n = len(df)
    cities = sorted(df["город"].unique())

    V = df[VOL_COL].to_numpy()
    c1 = df["c1_local"].to_numpy()
    c2 = df["c2_local"].to_numpy()
    is_s1 = (df["x_S1"] == 1).to_numpy()
    is_s2 = (df["x_S2"] == 1).to_numpy()

    # Локальная часть затрат (без магистрали)
    local_s1 = float((c1 * V * is_s1).sum())
    local_s2 = float((c2 * V * is_s2).sum())
    var_cost = local_s1 + local_s2

    # Магистральная часть: считаем число фур и стоимость по каждому РЦ
    n_trucks_s1 = {}
    n_trucks_s2 = {}
    ftl_breakdown = {}
    ftl_s1_total = 0.0
    ftl_s2_total = 0.0

    for c in cities:
        mask_c = (df["город"] == c).to_numpy()
        truck_cost = float(df.loc[df["город"] == c, "c_ftl_truck"].iloc[0])

        vol_s1 = float(V[mask_c & is_s1].sum())
        vol_s2 = float(V[mask_c & is_s2].sum())

        n1 = math.ceil(vol_s1 / (CAP_TRUCK * UTIL_S1)) if vol_s1 > 0 else 0
        n2 = math.ceil(vol_s2 / (CAP_TRUCK * UTIL_S2)) if vol_s2 > 0 else 0

        n_trucks_s1[c] = n1
        n_trucks_s2[c] = n2

        cost_s1 = truck_cost * n1
        cost_s2 = truck_cost * n2
        ftl_breakdown[c] = cost_s1 + cost_s2
        ftl_s1_total += cost_s1
        ftl_s2_total += cost_s2

    ftl_cost = ftl_s1_total + ftl_s2_total
    obj = var_cost + ftl_cost

    return {
        "obj":           obj,
        "var_cost":      var_cost,
        "ftl_cost":      ftl_cost,
        "local_s1":      local_s1,
        "local_s2":      local_s2,
        "ftl_s1":        ftl_s1_total,
        "ftl_s2":        ftl_s2_total,
        "n_trucks_s1":   n_trucks_s1,
        "n_trucks_s2":   n_trucks_s2,
        "ftl_breakdown": ftl_breakdown,
        "n_pairs":       n,
    }


def eval_cp_column(df_costs, cp_column, label):
    """Считает стоимость при назначении схем по значениям указанной колонки.
    Возвращает словарь в формате результата solve_milp.
    Все пары должны иметь значение в моделируемом множестве схем
    """
    df = df_costs.copy()
    df["scheme_mapped"] = df[cp_column].map(CP_TO_SCHEME)

    # После фильтрации  все значения должны быть валидны
    if df["scheme_mapped"].isna().any():
        n_bad = df["scheme_mapped"].isna().sum()
        raise ValueError(
            f"Найдено {n_bad} пар с неизвестным значением {cp_column}. "
            f"Проверьте, что filter.py применил фильтр на Действующую ЦП."
        )

    # Проставляем бинарные колонки x_S1 и x_S2
    df["x_S1"] = (df["scheme_mapped"] == "S1").astype(int)
    df["x_S2"] = (df["scheme_mapped"] == "S2").astype(int)
    df["scheme"] = np.where(df["x_S1"] == 1, "ЦП ТРЦ", "Региональный пулинг")
    df["pair_cost"] = (
        df["x_S1"] * df["c1_local"] + df["x_S2"] * df["c2_local"]
    ) * df[VOL_COL]

    components = _calc_cost_components(df)

    return {
        "scenario":     label,
        "status":       "Manual",
        "time":         0.0,
        "df":           df,
        "n_pairs_used": components["n_pairs"],
        **components,
    }


def compare_three_way(c_dejst, c_celev, c_milp):
    """Печатает таблицу трёхуровневого сравнения и разложение экономии:
        Дельта 1 = AS-IS - Целевая МИАС (зависшие переключения)
        Дельта 2 = Целевая МИАС - MILP  (оптимизационный премиум)
        Дельта общая = AS-IS - MILP     (полный эффект внедрения)
    """
    print("\n" + "=" * 80)
    print("ТРЁХУРОВНЕВОЕ СРАВНЕНИЕ: AS-IS -> ЦЕЛЕВАЯ МИАС -> TO-BE (MILP)")
    print("=" * 80)

    rows = [
        ("AS-IS (Действующая ЦП)",         c_dejst),
        ("Целевая ЦП МИАС (правила)",      c_celev),
        ("TO-BE (рекомендация MILP)",      c_milp),
    ]

    print(f"\n{'Вариант':<32} {'Совокупн., руб/мес':>20} "
          f"{'Локальн., руб/мес':>20} {'Магистр., руб/мес':>20}")
    print("-" * 96)
    for name, r in rows:
        print(f"{name:<32} {r['obj']:>20,.0f} "
              f"{r['var_cost']:>20,.0f} {r['ftl_cost']:>20,.0f}")

    delta_1 = c_dejst["obj"] - c_celev["obj"]
    delta_2 = c_celev["obj"] - c_milp["obj"]
    delta_total = c_dejst["obj"] - c_milp["obj"]
    base = c_dejst["obj"]

    print("\nРазложение полной экономии относительно AS-IS:")
    print(f"  Дельта 1 (МИАС-правила, устранение зависших переключений): "
          f"{delta_1:>14,.0f} руб/мес ({100*delta_1/base:+5.2f}%)")
    print(f"  Дельта 2 (премиум оптимизации СППР сверх правил МИАС):     "
          f"{delta_2:>14,.0f} руб/мес ({100*delta_2/base:+5.2f}%)")
    print(f"  Дельта общая (полный эффект внедрения СППР):               "
          f"{delta_total:>14,.0f} руб/мес ({100*delta_total/base:+5.2f}%)")

    return {
        "delta_1_transition":   delta_1,
        "delta_2_optimization": delta_2,
        "delta_total":          delta_total,
        "pct_total":            100 * delta_total / base,
    }



if __name__ == "__main__":
    from load import load_data
    from filter import apply_filters, aggregate_to_pairs
    from costs import calc_costs
    from optimizer import calc_capacities, solve_milp

    print("=" * 80)
    print("РАСЧЁТ ЭКОНОМИЧЕСКОГО ЭФФЕКТА: AS-IS vs ЦЕЛЕВАЯ МИАС vs TO-BE")
    print("=" * 80)

    # Подготовка периметра (фильтрация уже включает условие на Действующую ЦП)
    print("\n[1] Загрузка и фильтрация данных...")
    df_v, df_c = load_data(data_dir="../data")
    df_pairs = aggregate_to_pairs(apply_filters(df_v))

    print("\n[2] Расчёт мощностей и удельных стоимостей...")
    cap_pd, cap_trc = calc_capacities(df_v, df_pairs, df_c)
    df_costs = calc_costs(df_pairs)
    print(f"  Периметр: {len(df_costs):,} пар")

    # AS-IS - стоимость при Действующей ЦП
    print("\n[3] AS-IS - стоимость при Действующей ЦП МИАС...")
    c_dejst = eval_cp_column(df_costs, "Действующая ЦП",
                             "AS-IS (Действующая ЦП)")
    print(f"  Совокупные затраты: {c_dejst['obj']:>15,.0f} руб/мес")
    print(f"    локальная часть:  {c_dejst['var_cost']:>15,.0f} руб/мес")
    print(f"    магистральная:    {c_dejst['ftl_cost']:>15,.0f} руб/мес")

    # Стоимость при Целевой ЦП (МИАС-правила)
    print("\n[4] Стоимость при Целевой ЦП МИАС...")
    c_celev = eval_cp_column(df_costs, "Целевая ЦП", "Целевая ЦП МИАС")
    print(f"  Совокупные затраты: {c_celev['obj']:>15,.0f} руб/мес")
    print(f"    локальная часть:  {c_celev['var_cost']:>15,.0f} руб/мес")
    print(f"    магистральная:    {c_celev['ftl_cost']:>15,.0f} руб/мес")

    # Решение MILP (TO-BE)
    print("\n[5] TO-BE - решение MILP...")
    c_milp = solve_milp(df_costs, cap_pd, cap_trc, "TO-BE")
    print(f"  Совокупные затраты: {c_milp['obj']:>15,.0f} руб/мес")
    print(f"    локальная часть:  {c_milp['var_cost']:>15,.0f} руб/мес")
    print(f"    магистральная:    {c_milp['ftl_cost']:>15,.0f} руб/мес")

    # Трёхуровневое сравнение
    summary = compare_three_way(c_dejst, c_celev, c_milp)

 
