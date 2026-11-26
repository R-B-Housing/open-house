"""Run the canonical synthetic LIHTC example."""
from openhouse_engine.models.lihtc_example import build_example, calculate_example

if __name__ == "__main__":
    result = calculate_example()
    for name in ("uses.total_development_cost", "equity.commitment", "funding.cash_funded",
                 "funding.maximum_gap", "funding.shortfall_months", "funding.final_cash",
                 "funding.final_debt_owed", "exit.sale_price", "returns.annual_irr"):
        print(f"{name}: {result.value(name)}")
