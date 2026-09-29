"""Validation tests for the planning logic. Run with: python -m pytest tests"""

import math
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


def make_rows(units, inventory, lead_time=5, cost=2.0, med="MED-T1", center="FC-Test"):
    dates = pd.date_range("2025-01-01", periods=len(units), freq="D")
    return pd.DataFrame({
        "date": dates, "medicine_id": med, "medicine_name": f"Test {med}", "category": "Test",
        "fulfillment_center": center, "units_sold": units, "current_inventory": inventory,
        "supplier_lead_time_days": lead_time, "unit_cost": cost,
    })


def test_manual_calculation_matches_formulas():
    units = [10, 12, 8, 10] * 7  # 28 days, mean 10
    df = make_rows(units, inventory=[500] * 28)
    row = app.compute_plan(df).iloc[0]
    std = pd.Series(units).std()
    assert math.isclose(row.avg_daily_demand, 10)
    assert math.isclose(row.lead_time_demand, 50)
    assert math.isclose(row.safety_stock, std * app.SAFETY_STOCK_FACTOR)
    assert math.isclose(row.reorder_point, 50 + std * app.SAFETY_STOCK_FACTOR)
    assert math.isclose(row.days_of_inventory, 50)
    assert math.isclose(row.inventory_value, 1000)


def test_risk_rules():
    base = [10] * 28
    assert app.compute_plan(make_rows(base, [30] * 28)).iloc[0].risk_level == "Critical stockout risk"
    assert app.compute_plan(make_rows(base, [200] * 28)).iloc[0].risk_level == "Reorder soon"
    assert app.compute_plan(make_rows(base, [500] * 28)).iloc[0].risk_level == "Sufficient inventory"
    assert app.compute_plan(make_rows(base, [2000] * 28)).iloc[0].risk_level == "Excess inventory"


def test_order_quantity_brings_stock_to_target():
    row = app.compute_plan(make_rows([10] * 28, [30] * 28)).iloc[0]
    target = row.reorder_point + app.REVIEW_PERIOD_DAYS * row.avg_daily_demand
    assert row.recommended_order_qty == math.ceil(target - 30)
    healthy = app.compute_plan(make_rows([10] * 28, [500] * 28)).iloc[0]
    assert healthy.recommended_order_qty == 0


def test_growth_raises_reorder_point_and_order_qty():
    df = make_rows([10] * 28, [200] * 28)
    low, high = app.compute_plan(df, 0.0).iloc[0], app.compute_plan(df, 0.30).iloc[0]
    assert math.isclose(high.reorder_point, low.reorder_point * 1.3)
    assert high.recommended_order_qty > low.recommended_order_qty


def test_zero_negative_and_unusual_inputs():
    zero = app.compute_plan(make_rows([0] * 28, [0] * 28)).iloc[0]
    assert zero.risk_level == "Sufficient inventory" and zero.recommended_order_qty == 0
    idle = app.compute_plan(make_rows([0] * 28, [100] * 28)).iloc[0]
    assert idle.risk_level == "Excess inventory"
    single = app.compute_plan(make_rows([10], [5])).iloc[0]
    assert single.demand_std == 0
    clipped = app.compute_plan(make_rows([10] * 28, [200] * 28), growth=-0.5).iloc[0]
    assert math.isclose(clipped.avg_daily_demand, 10)
    assert app.compute_plan(make_rows([10] * 28, [200] * 28).iloc[0:0]).empty


def test_filters_on_real_data():
    df = app.load_data.__wrapped__()
    assert set(app.filter_data(df, "Allergy", "All fulfillment centers")["category"]) == {"Allergy"}
    assert set(app.filter_data(df, "All categories", "FC-East")["fulfillment_center"]) == {"FC-East"}
    plan = app.compute_plan(df)
    assert len(plan) == df.groupby(["medicine_id", "fulfillment_center"]).ngroups
    assert set(plan["risk_level"]) <= set(app.RISK_ORDER)
