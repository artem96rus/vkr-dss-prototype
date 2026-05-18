"""
main.py - точка входа в прототип.
Запускает все сценарии и сохраняет результаты в xlsx.
"""
from pathlib import Path

from scenarios import run_all_scenarios, build_summary_table, save_results


if __name__ == "__main__":
    results = run_all_scenarios()
    save_results(results, Path("../results/results.xlsx"))
