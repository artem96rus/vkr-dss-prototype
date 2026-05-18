"""
load.py - чтение трёх входных файлов прототипа.
"""
from pathlib import Path
import pandas as pd


# Имена файлов в папке data/
F_VOLUMES  = "Ротация_ТП_РЦ_Самара.csv"           # объёмы пар
F_CAPACITY = "Ограничение_по_местам_отборки.xlsx" # мощности РЦ


def load_data(data_dir=None):
    """
    Читает три файла и возвращает сырые DataFrame.
    Если data_dir не задан - ищет папку data/ в типичных местах.
    """
    if data_dir is None:
        candidates = [
            Path("data"),                              # запуск из корня проекта
            Path("..") / "data",                       # запуск из src/
            Path(__file__).parent / "data",            # рядом с самим скриптом
            Path(__file__).parent.parent / "data",     # на уровень выше скрипта
        ]
        for c in candidates:
            if c.is_dir():
                data_dir = c
                break
        if data_dir is None:
            raise FileNotFoundError(
                "Папка data/ не найдена. Искал здесь:\n" +
                "\n".join(f"  {c.resolve()}" for c in candidates)
            )
    else:
        data_dir = Path(data_dir)
        if not data_dir.is_dir():
            raise FileNotFoundError(f"Папка не найдена: {data_dir.resolve()}")

    df_volumes  = pd.read_csv(data_dir / F_VOLUMES, low_memory=False)
    df_capacity = pd.read_excel(data_dir / F_CAPACITY, engine="calamine")

    return df_volumes, df_capacity


if __name__ == "__main__":
    df_v, df_c = load_data()
    print(f"Объёмы:    {df_v.shape[0]:>6} строк, {df_v.shape[1]:>3} колонок")
    print(f"Мощности:  {df_c.shape[0]:>6} строк, {df_c.shape[1]:>3} колонок")
