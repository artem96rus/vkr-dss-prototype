"""
filter.py - девятиэтапная фильтрация периметра задачи (3.1.2 ВКР).

Из 123 740 строк сырой ротации оставляет пары, для которых имеет смысл
выбор между S1 (ЦП ТРЦ) и S2 (Региональный пулинг), и у которых
действующая ЦП тоже относится к моделируемому множеству схем
(нужно для корректного трёхуровневого сравнения AS-IS / Целевая МИАС / TO-BE).
"""


# Параметры фильтрации (все правила сверху, чтобы их было видно)
TRC_NAME           = "РЦ Самара (а)"
WAREHOUSE_TYPE     = "Основной склад"
ALLOWED_FORMATS    = {"МД", "МИКС"}
ALLOWED_TARGET_CP  = {"ТРЦ", "ПД", "ТРЦ PBL"}
ALLOWED_CURRENT_CP = {"ТРЦ", "ПД", "ТРЦ PBL"}
MIN_VOLUME_PALLETS = 1.0
VOLUME_COL         = "отгрузки по РЦ-ТП сред знач за 3 мес, пал"



# Колонки, которые оставляем после агрегации
KEEP_COLUMNS = [
    "РЦ Географический", "Код ТП", "Наименование ТП",
    "Тип склада", "Действующая ЦП", "Целевая ЦП",
    VOLUME_COL,
]


def _step(df, mask, label):
    """Применяет маску к df, печатает сколько строк осталось."""
    n_before = len(df)
    df = df[mask].copy()
    n_after = len(df)
    diff = n_before - n_after
    pct = 100 * n_after / n_before if n_before else 0
    print(f"  - {label:<55} {n_after:>8,} строк (-{diff:>7,}, осталось {pct:5.1f}%)")
    return df


def apply_filters(df):
    """
    Последовательно применяет 9 фильтров к таблице ротации.
    На каждом шаге печатает диагностику.
    """
    print(f"\nФильтрация ТАБЛИЦЫ ОБЪЁМОВ:")
    print(f"  Начало: {len(df):>8,} строк")

    df = _step(df, df["РЦ Транзитный"] == TRC_NAME,
               f"РЦ Транзитный = '{TRC_NAME}'")
    df = _step(df, df["Тип склада"] == WAREHOUSE_TYPE,
               f"Тип склада = '{WAREHOUSE_TYPE}'")
    df = _step(df, df["Формат для диаграмм"].isin(ALLOWED_FORMATS),
               f"Формат из {sorted(ALLOWED_FORMATS)}")
    df = _step(df, df["Целевая ЦП"].isin(ALLOWED_TARGET_CP),
               f"Целевая ЦП из {sorted(ALLOWED_TARGET_CP)}")
    df = _step(df, df["Действующая ЦП"].isin(ALLOWED_CURRENT_CP),
               f"Действующая ЦП из {sorted(ALLOWED_CURRENT_CP)}")
    df = _step(df, df["СТМ"].fillna("Нет") != "Да",
               "СТМ не равен 'Да' (исключаем СТМ)")
    df = _step(df, df["Признак объемности"] == "-",
               "Объёмность = '-' (исключаем высокообъёмные)")
    df = _step(df, df["Локальность"] == "-",
               "Локальность = '-' (исключаем локальные)")
    df = _step(df, df[VOLUME_COL] >= MIN_VOLUME_PALLETS,
               f"Объём не меньше {MIN_VOLUME_PALLETS} пал/мес")

    return df.reset_index(drop=True)



def aggregate_to_pairs(df):
    """
    Сворачивает строки до уникальных пар (РЦ ПД, Артикул).
    """
    print(f"\nАгрегация до пар (РЦ x Артикул):")
    print(f"  Строк до агрегации: {len(df):>8,}")

    pair_cols = ["РЦ Географический", "Код ТП"]

    # Проверяем что у дублей одной пары объём одинаковый
    n_bad = (df.groupby(pair_cols)[VOLUME_COL].nunique() > 1).sum()
    if n_bad > 0:
        print(f"  ВНИМАНИЕ: у {n_bad} пар объёмы дублей различаются, берём первые")
    else:
        print(f"  OK: объёмы у дублей одинаковые")

    df_agg = df[KEEP_COLUMNS].groupby(pair_cols, as_index=False).first()
    print(f"  Уникальных пар: {len(df_agg):>8,}")
    return df_agg


def diagnostics(df):
    """Печатает сводку по отфильтрованному периметру."""
    print("\n" + "=" * 70)
    print("ДИАГНОСТИКА ПЕРИМЕТРА")
    print("=" * 70)

    pair_cols = ["РЦ Географический", "Код ТП"]
    n_pairs = df.groupby(pair_cols).ngroups
    print(f"\n  Строк: {len(df):>8,}")
    print(f"  Уникальных пар: {n_pairs:>8,}")

    print(f"\n  Распределение по РЦ ПД:")
    by_rc = df.groupby("РЦ Географический")[VOLUME_COL].agg(["count", "sum"])
    by_rc.columns = ["пар", "паллет/мес"]
    by_rc["паллет/мес"] = by_rc["паллет/мес"].round(0).astype(int)
    print(by_rc.to_string())

    print(f"\n  По Целевой ЦП:")
    print(df["Целевая ЦП"].value_counts().to_string())
    print(f"\n  По Действующей ЦП:")
    print(df["Действующая ЦП"].value_counts().to_string())
    print(f"\n  Суммарный объём: {df[VOLUME_COL].sum():,.0f} паллет/мес")


if __name__ == "__main__":
    from load import load_data
    df_v, df_c = load_data()
    df_filtered = apply_filters(df_v)
    df_pairs = aggregate_to_pairs(df_filtered)
    diagnostics(df_pairs)