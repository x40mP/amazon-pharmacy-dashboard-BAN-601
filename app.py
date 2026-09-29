"""Amazon Pharmacy Demand Forecasting and Stockout Prevention Dashboard.

A planning tool for pharmacy inventory managers. Uses a synthetic dataset.
It does not make medical decisions and is not an Amazon internal system.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Planning assumptions (documented in README.md)
DATA_PATH = Path(__file__).parent / "data" / "pharmacy_demand.csv"
BASELINE_DAYS = 28          # rolling window used for average daily demand
SAFETY_STOCK_FACTOR = 1.65  # roughly a 95% service level
REVIEW_PERIOD_DAYS = 30     # inventory is reviewed and ordered monthly
EXCESS_DAYS = 75            # more than this many days of stock is excess
FORECAST_WEEKS = 8          # projected weeks shown on the demand trend chart

RISK_ORDER = ["Critical stockout risk", "Reorder soon", "Sufficient inventory", "Excess inventory"]
RISK_COLORS = {
    "Critical stockout risk": "#C0392B",
    "Reorder soon": "#E67E22",
    "Sufficient inventory": "#27AE60",
    "Excess inventory": "#2E86C1",
}
RECOMMENDATIONS = {
    "Critical stockout risk": "Order now and expedite. Stock will run out before a normal order arrives.",
    "Reorder soon": "Place a replenishment order this review cycle.",
    "Sufficient inventory": "No action needed. Keep monitoring.",
    "Excess inventory": "Hold orders. Consider moving stock to another fulfillment center.",
}


@st.cache_data
def load_data(path=DATA_PATH):
    df = pd.read_csv(path, parse_dates=["date"])
    df["units_sold"] = pd.to_numeric(df["units_sold"], errors="coerce").fillna(0).clip(lower=0)
    df["current_inventory"] = pd.to_numeric(df["current_inventory"], errors="coerce").fillna(0).clip(lower=0)
    df["supplier_lead_time_days"] = pd.to_numeric(df["supplier_lead_time_days"], errors="coerce").fillna(0).clip(lower=0)
    df["unit_cost"] = pd.to_numeric(df["unit_cost"], errors="coerce").fillna(0).clip(lower=0)
    return df.dropna(subset=["date"])


def classify_risk(inventory, lead_time_demand, reorder_point, avg_daily_demand, days_of_inventory):
    """Apply the documented risk rules to one medicine at one fulfillment center."""
    if avg_daily_demand <= 0:
        return "Excess inventory" if inventory > 0 else "Sufficient inventory"
    if inventory < lead_time_demand:
        return "Critical stockout risk"
    if inventory < reorder_point + REVIEW_PERIOD_DAYS * avg_daily_demand:
        return "Reorder soon"
    if days_of_inventory > EXCESS_DAYS:
        return "Excess inventory"
    return "Sufficient inventory"


def compute_plan(df, growth=0.0):
    """Build the replenishment plan for every medicine and fulfillment center in df.

    growth is the expected demand increase as a decimal, for example 0.15 for 15%.
    """
    growth = float(np.clip(growth, 0.0, 1.0))
    if df.empty:
        return pd.DataFrame()

    last_date = df["date"].max()
    window = df[df["date"] > last_date - pd.Timedelta(days=BASELINE_DAYS)]
    keys = ["medicine_id", "medicine_name", "category", "fulfillment_center"]

    stats = window.groupby(keys).agg(
        avg_daily_demand=("units_sold", "mean"),
        demand_std=("units_sold", "std"),
    )
    latest = (
        df.sort_values("date")
        .groupby(keys)
        .last()[["current_inventory", "supplier_lead_time_days", "unit_cost"]]
    )
    plan = stats.join(latest, how="inner").reset_index()
    plan["demand_std"] = plan["demand_std"].fillna(0)

    plan["avg_daily_demand"] *= 1 + growth
    plan["demand_std"] *= 1 + growth
    plan["lead_time_demand"] = plan["avg_daily_demand"] * plan["supplier_lead_time_days"]
    plan["safety_stock"] = plan["demand_std"] * SAFETY_STOCK_FACTOR
    plan["reorder_point"] = plan["lead_time_demand"] + plan["safety_stock"]
    plan["days_of_inventory"] = np.where(
        plan["avg_daily_demand"] > 0,
        plan["current_inventory"] / plan["avg_daily_demand"].where(plan["avg_daily_demand"] > 0),
        np.inf,
    )
    plan["inventory_value"] = plan["current_inventory"] * plan["unit_cost"]

    plan["risk_level"] = [
        classify_risk(r.current_inventory, r.lead_time_demand, r.reorder_point, r.avg_daily_demand, r.days_of_inventory)
        for r in plan.itertuples()
    ]
    needs_order = plan["risk_level"].isin(["Critical stockout risk", "Reorder soon"])
    target_stock = plan["reorder_point"] + REVIEW_PERIOD_DAYS * plan["avg_daily_demand"]
    plan["recommended_order_qty"] = np.where(
        needs_order, np.ceil((target_stock - plan["current_inventory"]).clip(lower=0)), 0
    ).astype(int)
    plan["order_cost"] = plan["recommended_order_qty"] * plan["unit_cost"]
    plan["recommendation"] = plan["risk_level"].map(RECOMMENDATIONS)
    return plan


def filter_data(df, category, center):
    out = df
    if category != "All categories":
        out = out[out["category"] == category]
    if center != "All fulfillment centers":
        out = out[out["fulfillment_center"] == center]
    return out


def demand_trend_chart(filtered, growth):
    weekly = filtered.set_index("date")["units_sold"].resample("W-SUN").sum()
    weekly = weekly.iloc[1:-1] if len(weekly) > 2 else weekly  # drop partial first and last weeks
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=weekly.index, y=weekly.values, mode="lines", name="Actual weekly units sold",
                             line=dict(color="#232F3E", width=2)))
    if len(weekly) >= 4:
        baseline = weekly.iloc[-(BASELINE_DAYS // 7):].mean() * (1 + growth)
        future = pd.date_range(weekly.index[-1], periods=FORECAST_WEEKS + 1, freq="W-SUN")
        fig.add_trace(go.Scatter(x=future, y=[weekly.iloc[-1]] + [baseline] * FORECAST_WEEKS, mode="lines",
                                 name=f"Projected demand (+{growth:.0%})", line=dict(color="#FF9900", width=2, dash="dash")))
    fig.update_layout(title="Weekly demand trend", xaxis_title="Week", yaxis_title="Units sold per week",
                      legend=dict(orientation="h", y=-0.25), height=420, margin=dict(t=60, b=40))
    return fig


def inventory_vs_reorder_chart(plan, single_center, top_n=15):
    """Most urgent items on top. Urgency is current inventory divided by reorder point."""
    view = plan.assign(coverage=plan["current_inventory"] / plan["reorder_point"].where(plan["reorder_point"] > 0))
    view["coverage"] = view["coverage"].fillna(np.inf)
    if single_center:
        view["label"] = view["medicine_name"]
    else:
        view["label"] = view["medicine_name"] + " (" + view["fulfillment_center"] + ")"
        view = view.nsmallest(top_n, "coverage")
    view = view.sort_values("coverage", ascending=False)  # plotly draws the last row at the top
    fig = go.Figure()
    fig.add_trace(go.Bar(y=view["label"], x=view["current_inventory"], orientation="h",
                         name="Current inventory", marker_color="#232F3E"))
    fig.add_trace(go.Bar(y=view["label"], x=view["reorder_point"], orientation="h",
                         name="Reorder point", marker_color="#FF9900"))
    fig.update_layout(title="Current inventory versus reorder point", barmode="group",
                      xaxis_title="Units", yaxis_title=None, height=max(360, 34 * len(view) + 120),
                      legend=dict(orientation="h", y=-0.12), margin=dict(t=60, b=40, l=10))
    return fig


def risk_distribution_chart(plan):
    counts = plan["risk_level"].value_counts().reindex(RISK_ORDER, fill_value=0)
    labels = [r.replace(" ", "<br>", 1) for r in counts.index]
    fig = go.Figure(go.Bar(x=labels, y=counts.values, text=counts.values, textposition="outside",
                           marker_color=[RISK_COLORS[r] for r in counts.index]))
    fig.update_layout(title="Inventory risk distribution", xaxis_title="Risk level",
                      yaxis_title="Medicine and center pairs", xaxis_tickangle=0,
                      yaxis=dict(range=[0, max(counts.max() * 1.2, 1)]), height=420, margin=dict(t=60, b=40))
    return fig


def main():
    st.set_page_config(page_title="Amazon Pharmacy Stockout Prevention", page_icon="💊", layout="wide")
    df = load_data()

    st.title("Amazon Pharmacy Demand Forecasting and Stockout Prevention")
    st.caption(
        "Planning tool for pharmacy inventory and fulfillment center managers. Built on synthetic data. "
        "Does not make medical decisions or use patient data. Not an Amazon internal system."
    )

    # The three interactive controls
    st.sidebar.header("Filters and scenario")
    category = st.sidebar.selectbox("Medicine category", ["All categories"] + sorted(df["category"].unique()))
    center = st.sidebar.selectbox("Fulfillment center", ["All fulfillment centers"] + sorted(df["fulfillment_center"].unique()))
    growth_pct = st.sidebar.slider("Expected demand growth (%)", min_value=0, max_value=30, value=0, step=1,
                                   help="Tests how higher demand changes risk, reorder point, and order quantity.")
    growth = growth_pct / 100

    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"Data through {df['date'].max():%B %d, %Y}. Average daily demand uses the last {BASELINE_DAYS} days. "
        f"Safety stock factor is {SAFETY_STOCK_FACTOR}."
    )

    filtered = filter_data(df, category, center)
    if filtered.empty:
        st.warning("No data matches these filters. Choose a different category or fulfillment center.")
        return
    plan = compute_plan(filtered, growth)

    critical = int((plan["risk_level"] == "Critical stockout risk").sum())
    reorder = int((plan["risk_level"] == "Reorder soon").sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Critical stockout risk", critical)
    c2.metric("Reorder soon", reorder)
    c3.metric("Inventory value on hand", f"${plan['inventory_value'].sum():,.0f}")
    c4.metric("Recommended order cost", f"${plan['order_cost'].sum():,.0f}")

    if critical:
        names = plan.loc[plan["risk_level"] == "Critical stockout risk"]
        items = ", ".join(f"{r.medicine_name} at {r.fulfillment_center}" for r in names.itertuples())
        st.error(f"Order now and expedite for {items}.")

    st.subheader("Demand trend")
    st.caption("Weekly units sold for the selected filters. The dashed line projects the recent baseline forward "
               "with the expected growth applied.")
    st.plotly_chart(demand_trend_chart(filtered, growth), use_container_width=True)

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Inventory against the replenishment threshold")
        note = ("" if center != "All fulfillment centers"
                else " Showing the 15 most urgent medicine and center pairs. Pick a center to see all of its medicines.")
        st.caption("Most urgent at the top. Where the dark bar is shorter than the orange bar, "
                   "inventory is below the reorder point." + note)
        st.plotly_chart(inventory_vs_reorder_chart(plan, center != "All fulfillment centers"), use_container_width=True)
    with right:
        st.subheader("Risk distribution")
        st.caption("Each medicine is counted once per fulfillment center. Move the growth slider to see risk shift.")
        st.plotly_chart(risk_distribution_chart(plan), use_container_width=True)

    st.subheader("Replenishment recommendations")
    st.caption("Sorted by urgency. Order quantity brings stock up to the reorder point plus one month of demand.")
    table = plan.assign(risk_rank=plan["risk_level"].map({r: i for i, r in enumerate(RISK_ORDER)}))
    table = table.sort_values(["risk_rank", "days_of_inventory"])
    st.dataframe(
        table[["medicine_name", "category", "fulfillment_center", "current_inventory", "avg_daily_demand",
               "days_of_inventory", "reorder_point", "risk_level", "recommended_order_qty", "recommendation"]],
        hide_index=True, use_container_width=True,
        column_config={
            "medicine_name": "Medicine", "category": "Category", "fulfillment_center": "Center",
            "current_inventory": st.column_config.NumberColumn("Inventory", format="%d"),
            "avg_daily_demand": st.column_config.NumberColumn("Avg daily demand", format="%.1f"),
            "days_of_inventory": st.column_config.NumberColumn("Days of inventory", format="%.0f"),
            "reorder_point": st.column_config.NumberColumn("Reorder point", format="%.0f"),
            "risk_level": "Risk level",
            "recommended_order_qty": st.column_config.NumberColumn("Order qty", format="%d"),
            "recommendation": "Recommendation",
        },
    )

    with st.expander("How the numbers are calculated"):
        st.markdown(
            f"""
Lead time demand equals average daily demand times supplier lead time.
Safety stock equals the standard deviation of daily demand times {SAFETY_STOCK_FACTOR}.
Reorder point equals lead time demand plus safety stock.
Days of inventory equals current inventory divided by average daily demand.

Risk rules, checked in order

* **Critical stockout risk** means inventory is below lead time demand, so stock runs out before a new order arrives.
* **Reorder soon** means inventory is below the reorder point plus {REVIEW_PERIOD_DAYS} days of demand.
* **Excess inventory** means more than {EXCESS_DAYS} days of inventory on hand.
* **Sufficient inventory** covers everything else.

The growth slider scales average demand and demand variability by the selected percentage.
"""
        )


if __name__ == "__main__":
    main()
