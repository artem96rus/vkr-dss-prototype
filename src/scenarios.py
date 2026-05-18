"""
scenarios.py - базовый прогон и сценарный анализ устойчивости (3.2 ВКР).

В каждом сценарии вычисляется:
    AS-IS  - стоимость распределения по Действующей ЦП при модифицированных
             параметрах сценария (объёмы, тарифы)
    TO-BE  - оптимизированное решение MILP при тех же параметрах
    Экономия - разница AS-IS и TO-BE для оценки эффекта СППР в каждом сценарии

Это позволяет оценить экономический эффект СППР во всех условиях,
а не только в базовой точке.

Сценарии воспроизводят вызовы из параграфа 1.1.1:
    Сценарий 0  - Базовый
    Сценарий 1  - Сезонно-промо рост спроса +15%   (Вызов 3)
    Сценарий 2  - Магнит Маркет -15% мощности ТРЦ  (Вызов 2)
    Сценарий 2b - Магнит Маркет -25% мощности ТРЦ  (порог устойчивости)
    Сценарий 3  - Удорожание FTL +30%              (Вызов 1)
    Сценарий 4  - Расширение сети в Кировской обл. (Вызов 4)
"""
from pathlib import Path

import pandas as pd

from load import load_data
from filter import apply_filters, aggregate_to_pairs
from costs import calc_costs
from optimizer import calc_capacities, solve_milp, VOL_COL
from as_is import eval_cp_column


# Сценарии-модификаторы. Каждая функция принимает (df, cap_pd, cap_trc)
# и возвращает изменённую тройку. Базовые данные не меняются.

def scenario_base(df, cap_pd, cap_trc):
    """Базовый сценарий, опорная точка для сравнения."""
    return df.copy(), dict(cap_pd), cap_trc


def scenario_promo_15(df, cap_pd, cap_trc):
    """Сезонно-промо рост спроса +15 процентов."""
    df_new = df.copy()
    df_new[VOL_COL] = df_new[VOL_COL] * 1.15
    return df_new, dict(cap_pd), cap_trc


def scenario_omnichannel_15(df, cap_pd, cap_trc):
    """Магнит Маркет занимает 15 процентов мощности ТРЦ."""
    return df.copy(), dict(cap_pd), cap_trc * 0.85


def scenario_omnichannel_25(df, cap_pd, cap_trc):
    """Магнит Маркет занимает 25 процентов мощности ТРЦ."""
    return df.copy(), dict(cap_pd), cap_trc * 0.75


def scenario_ftl_30(df, cap_pd, cap_trc):
    """Удорожание магистрального FTL-тарифа +30 процентов."""
    df_new = df.copy()
    df_new["c_ftl_truck"] = df_new["c_ftl_truck"] * 1.30
    return df_new, dict(cap_pd), cap_trc


def scenario_kirov_50(df, cap_pd, cap_trc):
    """Расширение сети в Кировской области: объёмы +50 процентов."""
    df_new = df.copy()
    mask = df_new["город"] == "Киров"
    df_new.loc[mask, VOL_COL] = df_new.loc[mask, VOL_COL] * 1.50
    return df_new, dict(cap_pd), cap_trc


SCENARIOS = [
    ("0. Базовый",     scenario_base),
    ("1. Спрос +15%",  scenario_promo_15),
    ("2. ТРЦ -15%",    scenario_omnichannel_15),
    ("2b. ТРЦ -25%",   scenario_omnichannel_25),
    ("3. FTL +30%",    scenario_ftl_30),
    ("4. Киров +50%",  scenario_kirov_50),
]


def run_all_scenarios():
    """Запускает все сценарии. Для каждого вычисляет AS-IS и MILP TO-BE.
    """
    print("=" * 78)
    print("СЦЕНАРНЫЙ АНАЛИЗ УСТОЙЧИВОСТИ С AS-IS СРАВНЕНИЕМ")
    print("=" * 78)

    # Подготовка данных - один раз для всех сценариев
    print("\n[Подготовка] Загрузка, фильтрация, мощности, стоимости...")
    df_v, df_c = load_data(data_dir="../data")
    df_pairs = aggregate_to_pairs(apply_filters(df_v))
    cap_pd_base, cap_trc_base = calc_capacities(
        df_v, df_pairs, df_c, safety_factor=1.10
    )
    df_costs_base = calc_costs(df_pairs)

    print(f"\n  Периметр: {len(df_costs_base):,} пар")

    results = []
    for name, modifier in SCENARIOS:
        print(f"\n{'-'*78}")
        print(f"Сценарий: {name}")
        print(f"{'-'*78}")

        # Применяем модификатор к данным и мощностям
        df_mod, cap_pd_mod, cap_trc_mod = modifier(
            df_costs_base, cap_pd_base, cap_trc_base
        )

        # AS-IS стоимость по Действующей ЦП при модифицированных параметрах
        print("\n  AS-IS (по Действующей ЦП):")
        c_dejst = eval_cp_column(df_mod, "Действующая ЦП", f"AS-IS [{name}]")
        print(f"    Затраты: {c_dejst['obj']:,.0f} руб/мес")

        # MILP оптимизация при модифицированных параметрах
        c_milp = solve_milp(df_mod, cap_pd_mod, cap_trc_mod, scenario_name=name)

        results.append({"name": name, "as_is": c_dejst, "milp": c_milp})

    return results



# Сводные таблицы для xlsx 

def build_summary_table(results):
    """Сводная таблица сценариев с акцентом на экономике AS-IS vs TO-BE
    и составе решения.
    """
    rows = []
    base_as_is = results[0]["as_is"]["obj"]
    base_milp = results[0]["milp"]["obj"]

    for r in results:
        as_is = r["as_is"]
        milp = r["milp"]

        # Когда задача нерешаема, ставим прочерки в численных колонках
        if milp.get("status") in ("Infeasible", "Unbounded"):
            rows.append({
                "Сценарий":                                  r["name"],
                "Статус MILP":                               milp["status"],
                "Затраты AS-IS, млн руб./мес.":              round(as_is["obj"] / 1e6, 2),
                "Затраты TO-BE, млн руб./мес.":              "—",
                "Экономия, млн руб./мес.":                   "—",
                "Экономия, %":                               "—",
                "Изменение AS-IS к базовому, %":             round(100 * (as_is["obj"] - base_as_is) / base_as_is, 2),
                "Изменение TO-BE к базовому, %":             "—",
                "Локальная составляющая, млн руб./мес.":     "—",
                "Магистральная составляющая, млн руб./мес.": "—",
                "ЦП ТРЦ, количество пар":                    "—",
                "Региональный пулинг, количество пар":       "—",
                "Доля ЦП ТРЦ, %":                            "—",
                "Максимальная загрузка узла, %":             "—",
                "Время решения, с":                          round(milp["time"], 2),
            })
            continue

        savings = as_is["obj"] - milp["obj"]
        savings_pct = 100 * savings / as_is["obj"]

        # Максимальная загруженность узла среди всех РЦ ПД и ТРЦ
        loads = list(milp.get("node_load_pd", {}).values())
        if milp.get("node_load_trc") is not None:
            loads.append(milp["node_load_trc"])
        max_load = max(loads) if loads else 0

        n_s1 = milp["n_pairs_s1"]
        n_s2 = milp["n_pairs_s2"]
        n_total = n_s1 + n_s2

        rows.append({
            "Сценарий":                                  r["name"],
            "Статус MILP":                               milp["status"],
            "Затраты AS-IS, млн руб./мес.":              round(as_is["obj"] / 1e6, 2),
            "Затраты TO-BE, млн руб./мес.":              round(milp["obj"] / 1e6, 2),
            "Экономия, млн руб./мес.":                   round(savings / 1e6, 3),
            "Экономия, %":                               round(savings_pct, 2),
            "Изменение AS-IS к базовому, %":             round(100 * (as_is["obj"] - base_as_is) / base_as_is, 2),
            "Изменение TO-BE к базовому, %":             round(100 * (milp["obj"] - base_milp) / base_milp, 2),
            "Локальная составляющая, млн руб./мес.":     round(milp["var_cost"] / 1e6, 2),
            "Магистральная составляющая, млн руб./мес.": round(milp["ftl_cost"] / 1e6, 2),
            "ЦП ТРЦ, количество пар":                    n_s1,
            "Региональный пулинг, количество пар":       n_s2,
            "Доля ЦП ТРЦ, %":                            round(100 * n_s1 / n_total, 2) if n_total else 0,
            "Максимальная загрузка узла, %":             round(max_load, 1),
            "Время решения, с":                          round(milp["time"], 2),
        })

    return pd.DataFrame(rows)


def build_decomposition_table(results):
    """Таблица декомпозиции целевой функции на четыре компоненты по сценариям."""
    rows = []
    for r in results:
        milp = r["milp"]
        if milp.get("status") in ("Infeasible", "Unbounded"):
            rows.append({
                "Сценарий":                                                 r["name"],
                "Локальная составляющая ЦП ТРЦ, тыс. руб./мес.":            "—",
                "Локальная составляющая Региональный пулинг, тыс. руб./мес.": "—",
                "Магистральная составляющая ЦП ТРЦ, тыс. руб./мес.":        "—",
                "Магистральная составляющая Региональный пулинг, тыс. руб./мес.": "—",
                "Итого, млн руб./мес.":                                     "—",
            })
            continue

        rows.append({
            "Сценарий":                                                 r["name"],
            "Локальная составляющая ЦП ТРЦ, тыс. руб./мес.":            round(milp["local_s1"] / 1e3, 1),
            "Локальная составляющая Региональный пулинг, тыс. руб./мес.": round(milp["local_s2"] / 1e3, 1),
            "Магистральная составляющая ЦП ТРЦ, тыс. руб./мес.":        round(milp["ftl_s1"] / 1e3, 1),
            "Магистральная составляющая Региональный пулинг, тыс. руб./мес.": round(milp["ftl_s2"] / 1e3, 1),
            "Итого, млн руб./мес.":                                     round(milp["obj"] / 1e6, 2),
        })

    return pd.DataFrame(rows)


def build_loads_table(results):
    """Таблица загруженности узлов сети в процентах по каждому сценарию."""
    cities_order = ["Тольятти", "Зеленодольск", "Пенза", "Энгельс", "Киров"]
    rows = []
    for r in results:
        milp = r["milp"]
        row = {"Сценарий": r["name"]}

        if milp.get("status") in ("Infeasible", "Unbounded"):
            for c in cities_order:
                row[f"РЦ ПД {c}, %"] = "—"
            row["ТРЦ Самара, %"] = "—"
            rows.append(row)
            continue

        loads_pd = milp.get("node_load_pd", {})
        for c in cities_order:
            row[f"РЦ ПД {c}, %"] = round(loads_pd.get(c, 0), 1)
        row["ТРЦ Самара, %"] = round(milp.get("node_load_trc", 0), 1)
        rows.append(row)

    return pd.DataFrame(rows)


# Маппинг служебных имён колонок -> академических подписей для детальных листов
DETAIL_COLUMNS_RENAME = {
    "РЦ Географический":  "РЦ",
    "Код ТП":             "Код ТП",
    "город":              "Город",
    VOL_COL:              "Отгрузки по РЦ-ТП сред знач за 3 мес, пал",
    "c1_local":           "Удельная стоимость c1, руб./пал.",
    "c2_local":           "Удельная стоимость c2, руб./пал.",
    "scheme":             "Выбранная схема",
    "Целевая ЦП":         "Рекомендованная ЦП (по МИАС)",
    "Действующая ЦП":     "Действующая ЦП",
}


def save_results(results, path):
    """Сохраняет три сводные таблицы и детальные данные по каждому сценарию.
    Колонки в детальных листах переименованы в академическом стиле.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    summary = build_summary_table(results)
    decomposition = build_decomposition_table(results)
    loads = build_loads_table(results)

    detail_cols_original = list(DETAIL_COLUMNS_RENAME.keys())

    with pd.ExcelWriter(path) as wr:
        summary.to_excel(wr, sheet_name="Сводная", index=False)
        decomposition.to_excel(wr, sheet_name="Декомпозиция", index=False)
        loads.to_excel(wr, sheet_name="Загруженность", index=False)

        for r in results:
            milp = r["milp"]
            if milp.get("df") is None:
                continue
            # Имя листа - до 31 символа, без спецзнаков
            name = (r["name"][:30]
                    .replace(":", "_").replace("/", "_").replace(" ", "_")
                    .replace("%", "пр"))
            cols_keep = [c for c in detail_cols_original
                         if c in milp["df"].columns]
            df_detail = milp["df"][cols_keep].rename(columns=DETAIL_COLUMNS_RENAME)
            df_detail.to_excel(wr, sheet_name=name, index=False)

    print(f"\nРезультаты сохранены в {path.resolve()}")




if __name__ == "__main__":
    results = run_all_scenarios()

    print("\n" + "=" * 78)
    print("СВОДНАЯ ТАБЛИЦА СЦЕНАРИЕВ")
    print("=" * 78)
    summary = build_summary_table(results)
    print(summary.to_string(index=False))

    print("\n" + "=" * 78)
    print("ДЕКОМПОЗИЦИЯ ЦЕЛЕВОЙ ПО СЦЕНАРИЯМ")
    print("=" * 78)
    decomposition = build_decomposition_table(results)
    print(decomposition.to_string(index=False))

    print("\n" + "=" * 78)
    print("ЗАГРУЖЕННОСТЬ УЗЛОВ ПО СЦЕНАРИЯМ (проценты)")
    print("=" * 78)
    loads = build_loads_table(results)
    print(loads.to_string(index=False))

    save_results(results, Path("../results/results.xlsx"))
