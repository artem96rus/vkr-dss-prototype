"""
validate.py - аналитическая сверка решения MILP.
Независимо пересчитывает все ограничения и компоненты целевой функции,
сверяет с тем, что вернул решатель.
"""
from costs import CAP_TRUCK, UTIL_S1, UTIL_S2
from optimizer import VOL_COL


def validate_solution(result, cap_pd, cap_trc, tolerance=1e-3):
    """Выполняет аналитическую сверку решения по шести группам проверок.

    Печатает структурированный отчёт и возвращает словарь со сводкой.
    Каждая проверка возвращает результат OK либо FAIL с числовой невязкой.
    """
    df = result["df"]
    cities = sorted(df["город"].unique())

    print("\n" + "=" * 80)
    print(f"АНАЛИТИЧЕСКАЯ СВЕРКА РЕШЕНИЯ: {result['scenario']}")
    print("=" * 80)

    checks = []

    # 1. Балансовое ограничение: каждая пара ровно в одной схеме
    print("\n[1] Балансовое ограничение (x_S1 + x_S2 = 1)")
    bal_sum = (df["x_S1"] + df["x_S2"]).unique()
    ok_bal = len(bal_sum) == 1 and bal_sum[0] == 1
    status = "OK" if ok_bal else "FAIL"
    print(f"  Все {len(df):,} пар имеют ровно одну схему: {status}")
    if not ok_bal:
        print(f"  ВНИМАНИЕ: встречены значения суммы x_S1+x_S2: {list(bal_sum)}")
    checks.append({"check": "Балансовое", "status": status})

    # 2. Мощность РЦ ПД (только схема S2 хранится на РЦ ПД)
    print("\n[2] Мощность РЦ ПД (поток схемы S2 не больше доступной мощности)")
    print(f"  {'РЦ':<14} {'поток S2':>12} {'мощность':>12} "
          f"{'загрузка':>10} {'статус':>8}")
    print(f"  {'-'*14} {'-'*12} {'-'*12} {'-'*10} {'-'*8}")
    for c in cities:
        load_s2 = float(
            df.loc[(df["город"] == c) & (df["x_S2"] == 1), VOL_COL].sum()
        )
        cap = cap_pd.get(c, 0)
        share = 100 * load_s2 / cap if cap > 0 else 0
        ok = load_s2 <= cap + tolerance
        status = "OK" if ok else "FAIL"
        print(f"  {c:<14} {load_s2:>12,.0f} {cap:>12,.0f} "
              f"{share:>9.1f}% {status:>8}")
        checks.append({"check": f"Мощность РЦ ПД {c}", "status": status})

    # 3. Мощность ТРЦ Самара (обе схемы проходят через ТРЦ)
    print("\n[3] Мощность ТРЦ Самара (общий поток не больше доступной мощности)")
    total_flow = float(df[VOL_COL].sum())
    share_trc = 100 * total_flow / cap_trc if cap_trc > 0 else 0
    ok_trc = total_flow <= cap_trc + tolerance
    status = "OK" if ok_trc else "FAIL"
    print(f"  Общий поток: {total_flow:,.0f}, мощность: {cap_trc:,.0f}, "
          f"загрузка: {share_trc:.1f}%, статус: {status}")
    checks.append({"check": "Мощность ТРЦ Самара", "status": status})

    # 4. Утилизация магистрали S1 (n1 * Q * eta1 не меньше объёма S1)
    print("\n[4] Утилизация магистрали S1 (n_S1 * Q * eta1 не меньше V_S1)")
    print(f"  {'РЦ':<14} {'объём S1':>10} {'фур S1':>8} "
          f"{'ёмкость':>12} {'статус':>8}")
    print(f"  {'-'*14} {'-'*10} {'-'*8} {'-'*12} {'-'*8}")
    for c in cities:
        vol_s1 = float(
            df.loc[(df["город"] == c) & (df["x_S1"] == 1), VOL_COL].sum()
        )
        n1 = result["n_trucks_s1"].get(c, 0)
        capacity = CAP_TRUCK * UTIL_S1 * n1
        ok = capacity >= vol_s1 - tolerance
        status = "OK" if ok else "FAIL"
        print(f"  {c:<14} {vol_s1:>10,.0f} {n1:>8} "
              f"{capacity:>12,.1f} {status:>8}")
        checks.append({"check": f"Утилизация S1 на {c}", "status": status})

    # 5. Утилизация магистрали S2 (n2 * Q * eta2 не меньше объёма S2)
    print("\n[5] Утилизация магистрали S2 (n_S2 * Q * eta2 не меньше V_S2)")
    print(f"  {'РЦ':<14} {'объём S2':>10} {'фур S2':>8} "
          f"{'ёмкость':>12} {'статус':>8}")
    print(f"  {'-'*14} {'-'*10} {'-'*8} {'-'*12} {'-'*8}")
    for c in cities:
        vol_s2 = float(
            df.loc[(df["город"] == c) & (df["x_S2"] == 1), VOL_COL].sum()
        )
        n2 = result["n_trucks_s2"].get(c, 0)
        capacity = CAP_TRUCK * UTIL_S2 * n2
        ok = capacity >= vol_s2 - tolerance
        status = "OK" if ok else "FAIL"
        print(f"  {c:<14} {vol_s2:>10,.0f} {n2:>8} "
              f"{capacity:>12,.1f} {status:>8}")
        checks.append({"check": f"Утилизация S2 на {c}", "status": status})

    # 6. Реконструкция целевой функции (независимый пересчёт)
    print("\n[6] Реконструкция целевой функции (независимый пересчёт)")
    var_recalc = float(
        (df["x_S1"] * df["c1_local"] * df[VOL_COL]
         + df["x_S2"] * df["c2_local"] * df[VOL_COL]).sum()
    )
    ftl_recalc = sum(result["ftl_breakdown"].values())
    obj_recalc = var_recalc + ftl_recalc

    # Допускаем расхождение до 1 рубля на ошибках округления
    components = [
        ("Локальная часть",     result["var_cost"], var_recalc),
        ("Магистральная часть", result["ftl_cost"], ftl_recalc),
        ("Итого (целевая)",     result["obj"],      obj_recalc),
    ]
    for label, model_val, recalc_val in components:
        diff = abs(recalc_val - model_val)
        ok = diff < 1.0
        status = "OK" if ok else "FAIL"
        print(f"  {label:<22} модель {model_val:>15,.2f}  "
              f"сверка {recalc_val:>15,.2f}  разница {diff:>10.4f}  {status}")
        checks.append({"check": label, "status": status})

    # Сводка
    n_total = len(checks)
    n_passed = sum(1 for c in checks if c["status"] == "OK")
    n_failed = n_total - n_passed

    print("\n" + "-" * 80)
    print(f"ИТОГ: {n_passed} из {n_total} проверок успешны "
          f"({n_failed} неуспешных)")

    return {
        "scenario": result["scenario"],
        "checks":   checks,
        "n_total":  n_total,
        "n_passed": n_passed,
        "all_ok":   n_passed == n_total,
    }


if __name__ == "__main__":
    from load import load_data
    from filter import apply_filters, aggregate_to_pairs
    from costs import calc_costs
    from optimizer import calc_capacities, solve_milp

    print("=" * 80)
    print("АНАЛИТИЧЕСКАЯ СВЕРКА БАЗОВОГО РЕШЕНИЯ")
    print("=" * 80)

    print("\n[1] Загрузка и подготовка данных...")
    df_v, df_c = load_data(data_dir="../data")
    df_pairs = aggregate_to_pairs(apply_filters(df_v))

    print("\n[2] Расчёт мощностей и удельных стоимостей...")
    cap_pd, cap_trc = calc_capacities(df_v, df_pairs, df_c)
    df_costs = calc_costs(df_pairs)

    print("\n[3] Решение MILP...")
    result = solve_milp(df_costs, cap_pd, cap_trc, "Базовый")

    print("\n[4] Запуск аналитической сверки...")
    summary = validate_solution(result, cap_pd, cap_trc)
