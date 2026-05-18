"""
optimizer.py - расчёт мощностей узлов и решение MILP-задачи
выбора схем поставки (параграф 3.1.4 ВКР).

Множества:
    Pairs  - пары (Артикул, РЦ ПД)
    Cities - города РЦ ПД (5 штук)

Переменные решения:
    x1[i], x2[i] - выбор схемы S1 или S2 для пары i (бинарные)
    N1[c], N2[c] - число магистральных фур на плече ТРЦ - РЦ ПД c

Целевая функция:
    min  сумма (c1[i]*V[i]*x1[i] + c2[i]*V[i]*x2[i]) + сумма c_ftl[c]*(N1[c]+N2[c])

Ограничения (по нумерации параграфа 3.1.4 ВКР):
    (6)  x1[i] + x2[i] = 1                              балансовое
    (7)  сумма V[i]*x2[i] <= cap_pd[c]                  мощность РЦ ПД (только S2)
    (8)  сумма V[i]*(x1[i]+x2[i]) <= cap_trc            мощность ТРЦ
    (9)  UTIL_S1 * CAP * N1[c] >= сумма V[i]*x1[i]      утилизация S1
    (10) UTIL_S2 * CAP * N2[c] >= сумма V[i]*x2[i]      утилизация S2
"""
import time

import numpy as np
import pandas as pd
import pulp

from costs import CAP_TRUCK, UTIL_S1, UTIL_S2


VOL_COL = "отгрузки по РЦ-ТП сред знач за 3 мес, пал"
TRC_COL = "отгрузки по ТРЦ-ТП сред знач за 3 мес, пал"

TYPE_LDC = "LDC"
TYPE_RDC = "RDC"

CITIES_PD = ["Тольятти", "Зеленодольск", "Пенза", "Киров", "Энгельс"]


def _extract_city(rc_name):
    """Достаёт имя города из имени РЦ. Возвращает None если не нашли."""
    name = str(rc_name)
    for city in CITIES_PD + ["Самара"]:
        if city in name:
            return city
    return None


def calc_capacities(df_full, df_pairs, df_capacity, safety_factor=1.10,
                    verbose=False):
    """Считает доступную мощность каждого РЦ ПД и ТРЦ Самара.

    Мощность узла = (МО * норма_фактическая * запас) - чужой_поток,
    где чужой поток = полный поток минус наш отфильтрованный.
    """
    # Полный поток зоны Основной склад через ТРЦ Самара
    mask = (
        (df_full["РЦ Транзитный"] == "РЦ Самара (а)") &
        (df_full["Тип склада"] == "Основной склад")
    )
    full_zone = df_full[mask].copy()
    full_zone["город"] = full_zone["РЦ Географический"].apply(_extract_city)
    full_zone = full_zone[full_zone["город"].isin(CITIES_PD)]

    full_pd_per_rc = full_zone.groupby("город")[VOL_COL].sum()
    full_trc_total = float(full_zone[TRC_COL].sum())

    # Наш поток после фильтрации
    if "город" not in df_pairs.columns:
        df_pairs = df_pairs.copy()
        df_pairs["город"] = df_pairs["РЦ Географический"].apply(_extract_city)
    our_pd_per_rc = df_pairs.groupby("город")[VOL_COL].sum()

    # Места отбора из справочника мощностей
    df_cap = df_capacity.copy()
    df_cap["город"] = df_cap["РЦ"].apply(_extract_city)

    mo_pd = {}
    mo_trc = None
    for _, row in df_cap.iterrows():
        city = row["город"]
        if city is None:
            continue
        if row["тип РЦ"] == TYPE_LDC and city in CITIES_PD:
            mo_pd[city] = float(row["Основной склад"])
        elif row["тип РЦ"] == TYPE_RDC and city == "Самара":
            mo_trc = float(row["Основной склад"])

    if mo_trc is None:
        raise ValueError("Не нашли ТРЦ Самара в таблице мощностей")

    cap_pd = {}
    diag_rows = []
    for city in CITIES_PD:
        full_vol = float(full_pd_per_rc[city])
        our_vol = float(our_pd_per_rc.get(city, 0))
        mo = mo_pd[city]
        norm_rc = full_vol / mo
        full_cap = mo * norm_rc * safety_factor
        available = full_cap - (full_vol - our_vol)
        cap_pd[city] = available

        diag_rows.append({
            "РЦ": city,
            "МО": int(mo),
            "норма": round(norm_rc, 2),
            "полный_поток": round(full_vol),
            "наш_поток": round(our_vol),
            "полная_мощн": round(full_cap),
            "доступно_нам": round(available),
            "загрузка_%": round(100 * our_vol / available, 1),
        })

    # ТРЦ Самара - отдельная норма из-за другого режима работы
    norm_trc = full_trc_total / mo_trc
    full_trc_cap = mo_trc * norm_trc * safety_factor
    our_trc_total = float(our_pd_per_rc.sum())
    cap_trc = full_trc_cap - (full_trc_total - our_trc_total)

    if cap_trc <= 0:
        raise ValueError(f"Мощность ТРЦ отрицательная: sf={safety_factor} мал")

    if verbose:
        print("=" * 80)
        print(f"РАСЧЁТ МОЩНОСТЕЙ (safety_factor = {safety_factor})")
        print("=" * 80)
        print(pd.DataFrame(diag_rows).to_string(index=False))
        print()
        print(f"ТРЦ Самара: МО={int(mo_trc)}, норма={norm_trc:.2f} пал/мес/МО")
        print(f"  полный поток: {full_trc_total:>10,.0f} пал/мес")
        print(f"  наш поток:    {our_trc_total:>10,.0f} пал/мес")
        print(f"  полная мощн:  {full_trc_cap:>10,.0f} пал/мес")
        print(f"  доступно:     {cap_trc:>10,.0f} пал/мес  "
              f"(загр. {100*our_trc_total/cap_trc:.1f}%)")

    return cap_pd, cap_trc


def solve_milp(df_costs, cap_pd, cap_trc, scenario_name="Базовый",
               time_limit=120):
    """Строит и решает MILP-задачу по постановке параграфа 3.1.4 ВКР.

    Возвращает словарь с результатами, включая разложение целевой
    функции на четыре компоненты и оценку загруженности узлов сети.
    """
    n = len(df_costs)
    df = df_costs.reset_index(drop=True)
    cities = sorted(df["город"].unique())

    n_vars_bin = 2 * n
    n_vars_int = 2 * len(cities)
    n_vars_total = n_vars_bin + n_vars_int

    print(f"\nПостроение модели «{scenario_name}»...")
    print(f"  пар (j, r):                {n:>8,}")
    print(f"  бинарных переменных x:     {n_vars_bin:>8,}")
    print(f"  целочисл. переменных n_r:  {n_vars_int:>8}")
    print(f"  всего переменных:          {n_vars_total:>8,}")

    model = pulp.LpProblem(f"DSS_{scenario_name}", pulp.LpMinimize)

    x1 = [pulp.LpVariable(f"x1_{i}", cat=pulp.LpBinary) for i in range(n)]
    x2 = [pulp.LpVariable(f"x2_{i}", cat=pulp.LpBinary) for i in range(n)]
    N1 = {c: pulp.LpVariable(f"N1_{c}", lowBound=0, cat=pulp.LpInteger)
          for c in cities}
    N2 = {c: pulp.LpVariable(f"N2_{c}", lowBound=0, cat=pulp.LpInteger)
          for c in cities}

    ftl_per_truck = {}
    for c in cities:
        ftl_per_truck[c] = float(df.loc[df["город"] == c, "c_ftl_truck"].iloc[0])

    V = df[VOL_COL].to_numpy()
    c1 = df["c1_local"].to_numpy()
    c2 = df["c2_local"].to_numpy()

    # Целевая функция
    var_cost_expr = pulp.lpSum(
        c1[i] * V[i] * x1[i] + c2[i] * V[i] * x2[i] for i in range(n)
    )
    ftl_cost_expr = pulp.lpSum(
        ftl_per_truck[c] * (N1[c] + N2[c]) for c in cities
    )
    model += var_cost_expr + ftl_cost_expr

    # Ограничения (6) - (10) из параграфа 3.1.4 ВКР
    for i in range(n):
        model += x1[i] + x2[i] == 1, f"balance_{i}"

    for c in cities:
        idx = df.index[df["город"] == c].tolist()
        model += (pulp.lpSum(V[i] * x2[i] for i in idx) <= cap_pd.get(c, 0),
                  f"cap_pd_{c}")

    model += (pulp.lpSum(V[i] * (x1[i] + x2[i]) for i in range(n)) <= cap_trc,
              "cap_trc")

    for c in cities:
        idx = df.index[df["город"] == c].tolist()
        model += (UTIL_S1 * CAP_TRUCK * N1[c] >=
                  pulp.lpSum(V[i] * x1[i] for i in idx), f"ftl_s1_{c}")

    for c in cities:
        idx = df.index[df["город"] == c].tolist()
        model += (UTIL_S2 * CAP_TRUCK * N2[c] >=
                  pulp.lpSum(V[i] * x2[i] for i in idx), f"ftl_s2_{c}")

    # Размерность матрицы ограничений
    n_constraints = len(model.constraints)
    n_nonzeros = sum(len(c) for c in model.constraints.values())

    print(f"  ограничений:               {n_constraints:>8,}")
    print(f"  ненулевых элементов:       {n_nonzeros:>8,}")
    print(f"  лимит времени:             {time_limit:>8} с")
    print(f"  решатель:                  HiGHS")

    # Решение
    solver = pulp.HiGHS(msg=False, timeLimit=time_limit)
    t0 = time.time()
    model.solve(solver)
    t_solve = time.time() - t0

    status = pulp.LpStatus[model.status]
    obj = pulp.value(model.objective)

    print(f"\n  Статус решения:            {status}")
    print(f"  Время решения:             {t_solve:.2f} с")
    if obj is not None:
        print(f"  Целевая функция:           {obj:>15,.2f} руб/мес")

    if status in ("Infeasible", "Unbounded"):
        return {
            "scenario": scenario_name, "status": status, "time": t_solve,
            "obj": None, "var_cost": None, "ftl_cost": None,
            "local_s1": None, "local_s2": None,
            "ftl_s1": None, "ftl_s2": None,
            "df": None, "n_trucks_s1": {}, "n_trucks_s2": {},
            "ftl_breakdown": {}, "node_load_pd": {}, "node_load_trc": None,
            "n_pairs_s1": 0, "n_pairs_s2": 0,
            "n_constraints": n_constraints, "n_nonzeros": n_nonzeros,
            "n_vars_total": n_vars_total,
        }

    if status != "Optimal" and obj is not None:
        print(f"  ВНИМАНИЕ: статус {status}, берётся лучшее найденное решение")

    # Извлечение решения
    df_out = df.copy()
    df_out["x_S1"] = [int(round(x1[i].value())) for i in range(n)]
    df_out["x_S2"] = [int(round(x2[i].value())) for i in range(n)]
    df_out["scheme"] = np.where(df_out["x_S1"] == 1, "ЦП ТРЦ",
                                "Региональный пулинг")
    df_out["pair_cost"] = (df_out["x_S1"] * c1 + df_out["x_S2"] * c2) * V

    mask_s1 = (df_out["x_S1"] == 1).to_numpy()
    mask_s2 = (df_out["x_S2"] == 1).to_numpy()

    n_trucks_s1 = {c: int(round(N1[c].value())) for c in cities}
    n_trucks_s2 = {c: int(round(N2[c].value())) for c in cities}
    ftl_breakdown = {
        c: ftl_per_truck[c] * (n_trucks_s1[c] + n_trucks_s2[c]) for c in cities
    }

    # Разложение целевой функции на четыре компоненты
    local_s1 = float((c1 * V * mask_s1).sum())
    local_s2 = float((c2 * V * mask_s2).sum())
    ftl_s1 = sum(ftl_per_truck[c] * n_trucks_s1[c] for c in cities)
    ftl_s2 = sum(ftl_per_truck[c] * n_trucks_s2[c] for c in cities)

    # Загруженность узлов сети после решения
    node_load_pd = {}
    for c in cities:
        mask_c = (df_out["город"].to_numpy() == c)
        load_s2 = float(V[mask_c & mask_s2].sum())
        cap = cap_pd.get(c, 0)
        node_load_pd[c] = 100 * load_s2 / cap if cap > 0 else 0

    total_flow = float(V.sum())
    node_load_trc = 100 * total_flow / cap_trc if cap_trc > 0 else 0

    n_pairs_s1 = int(mask_s1.sum())
    n_pairs_s2 = int(mask_s2.sum())

    return {
        "scenario":      scenario_name,
        "status":        status,
        "time":          t_solve,
        "obj":           obj,
        "var_cost":      float(pulp.value(var_cost_expr)),
        "ftl_cost":      float(pulp.value(ftl_cost_expr)),
        "local_s1":      local_s1,
        "local_s2":      local_s2,
        "ftl_s1":        ftl_s1,
        "ftl_s2":        ftl_s2,
        "df":            df_out,
        "n_trucks_s1":   n_trucks_s1,
        "n_trucks_s2":   n_trucks_s2,
        "ftl_breakdown": ftl_breakdown,
        "node_load_pd":  node_load_pd,
        "node_load_trc": node_load_trc,
        "n_pairs_s1":    n_pairs_s1,
        "n_pairs_s2":    n_pairs_s2,
        "n_constraints": n_constraints,
        "n_nonzeros":    n_nonzeros,
        "n_vars_total":  n_vars_total,
    }


def report_solution(result):
    """Печатает развёрнутый отчёт по решению.
    Включает разложение целевой функции на четыре компоненты,
    распределение пар по схемам и загруженность узлов сети.
    """
    if result is None:
        print("Решение не найдено")
        return

    if result.get("status") in ("Infeasible", "Unbounded"):
        print(f"\n{'='*78}")
        print(f"РЕЗУЛЬТАТ: {result['scenario']}")
        print(f"{'='*78}")
        print(f"  Статус: {result['status']}")
        print(f"  Время:  {result['time']:.2f} с")
        print(f"  Задача нерешаема - превышен порог устойчивости")
        return

    df = result["df"]
    n = len(df)

    print(f"\n{'='*78}")
    print(f"РЕЗУЛЬТАТ: {result['scenario']}")
    print(f"{'='*78}")
    print(f"  Статус:               {result['status']}")
    print(f"  Время решения:        {result['time']:.2f} с")
    print(f"  Целевая функция:      {result['obj']:>15,.0f} руб/мес")

    # Разложение целевой на четыре компоненты
    print(f"\n  Разложение целевой функции:")
    print(f"    {'Компонента':<28} {'Значение, руб/мес':>20} {'Доля':>8}")
    components = [
        ("Локальная часть S1",     result["local_s1"]),
        ("Локальная часть S2",     result["local_s2"]),
        ("Магистральная часть S1", result["ftl_s1"]),
        ("Магистральная часть S2", result["ftl_s2"]),
    ]
    for label, val in components:
        share = 100 * val / result["obj"] if result["obj"] > 0 else 0
        print(f"    {label:<28} {val:>20,.0f} {share:>7.1f}%")
    print(f"    {'Итого':<28} {result['obj']:>20,.0f} {100.0:>7.1f}%")

    # Распределение пар и объёмов по схемам
    vol_s1 = float(df.loc[df["x_S1"] == 1, VOL_COL].sum())
    vol_s2 = float(df.loc[df["x_S2"] == 1, VOL_COL].sum())
    vol_total = vol_s1 + vol_s2

    print(f"\n  Распределение пар и объёма по схемам:")
    print(f"    {'Схема':<22} {'пар':>7} {'%':>7}  "
          f"{'объём, пал/мес':>16} {'%':>7}")
    print(f"    {'ЦП ТРЦ (S1)':<22} {result['n_pairs_s1']:>7,} "
          f"{100*result['n_pairs_s1']/n:>6.1f}% "
          f"{vol_s1:>16,.0f} {100*vol_s1/vol_total:>6.1f}%")
    print(f"    {'Региональный пулинг':<22} {result['n_pairs_s2']:>7,} "
          f"{100*result['n_pairs_s2']/n:>6.1f}% "
          f"{vol_s2:>16,.0f} {100*vol_s2/vol_total:>6.1f}%")

    # Загруженность узлов сети
    print(f"\n  Загруженность узлов сети после решения:")
    print(f"    {'Узел':<22} {'загрузка':>10}")
    for c in sorted(result["node_load_pd"]):
        load = result["node_load_pd"][c]
        print(f"    РЦ ПД {c:<16} {load:>9.1f}%")
    print(f"    {'ТРЦ Самара':<22} {result['node_load_trc']:>9.1f}%")

    # Магистральные фуры
    print(f"\n  Магистральные фуры по РЦ ПД:")
    print(f"    {'РЦ':<14} {'S1':>6} {'S2':>6} {'FTL, руб/мес':>16}")
    for c in sorted(result["n_trucks_s1"]):
        n1 = result["n_trucks_s1"][c]
        n2 = result["n_trucks_s2"][c]
        cost = result["ftl_breakdown"][c]
        print(f"    {c:<14} {n1:>6} {n2:>6} {cost:>16,.0f}")

    # Совпадение с baseline МИАС
    if "Целевая ЦП" in df.columns:
        miac_s1 = df["Целевая ЦП"].isin(["ТРЦ", "ТРЦ PBL"])
        our_s1 = df["x_S1"] == 1
        n_match = (miac_s1 == our_s1).sum()
        print(f"\n  Совпадение решения с baseline МИАС (Целевая ЦП):")
        print(f"    совпадений:  {n_match:,} из {n:,} ({100*n_match/n:.1f}%)")
        print(f"    МИАС:        ЦП ТРЦ={miac_s1.sum():,}, "
              f"Рег. пулинг={(~miac_s1).sum():,}")
        print(f"    MILP:        ЦП ТРЦ={our_s1.sum():,}, "
              f"Рег. пулинг={(~our_s1).sum():,}")


if __name__ == "__main__":
    from load import load_data
    from filter import apply_filters, aggregate_to_pairs
    from costs import calc_costs

    print("=" * 78)
    print("САМАРСКИЙ РЕГИОН - БАЗОВЫЙ СЦЕНАРИЙ")
    print("=" * 78)

    df_v, df_c = load_data(data_dir="../data")
    df_pairs = aggregate_to_pairs(apply_filters(df_v))
    cap_pd, cap_trc = calc_capacities(df_v, df_pairs, df_c, verbose=True)
    df_costs = calc_costs(df_pairs)

    result = solve_milp(df_costs, cap_pd, cap_trc, "Базовый")
    report_solution(result)
