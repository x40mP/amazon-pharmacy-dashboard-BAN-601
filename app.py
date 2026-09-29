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
TOP_N_URGENT = 10           # items shown on the inventory versus reorder point chart
PLOTLY_CONFIG = {"displayModeBar": False}  # hide zoom and download icons
CHART_HEIGHT = 310          # pixels, sized so the dashboard fits on one laptop screen

RISK_ORDER = ["Critical stockout risk", "Reorder soon", "Sufficient inventory", "Excess inventory"]
RISK_COLORS = {
    "Critical stockout risk": "#C0392B",
    "Reorder soon": "#E67E22",
    "Sufficient inventory": "#27AE60",
    "Excess inventory": "#2E86C1",
}
RECOMMENDATIONS = {
    "Critical stockout risk": "Order now and expedite",
    "Reorder soon": "Order this review cycle",
    "Sufficient inventory": "No action needed",
    "Excess inventory": "Hold orders or rebalance",
}
SHORT_ACTIONS = {
    "Critical stockout risk": "Critical. Expedite now",
    "Reorder soon": "Reorder this cycle",
    "Sufficient inventory": "Sufficient. No action",
    "Excess inventory": "Excess. Hold orders",
}
RISK_DOTS = {"Critical stockout risk": "🔴", "Reorder soon": "🟠", "Sufficient inventory": "🟢", "Excess inventory": "🔵"}


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
    plan["reorder_point"] = np.ceil(plan["lead_time_demand"] + plan["safety_stock"])  # whole units, rounded up for safety
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
    fig.add_trace(go.Scatter(x=weekly.index, y=weekly.values, mode="lines", name="Actual",
                             line=dict(color="#232F3E", width=2),
                             hovertemplate="Week of %{x|%b %d, %Y}<br>%{y:,.0f} units sold<extra></extra>"))
    if len(weekly) >= 4:
        baseline = weekly.iloc[-(BASELINE_DAYS // 7):].mean() * (1 + growth)
        future = pd.date_range(weekly.index[-1], periods=FORECAST_WEEKS + 1, freq="W-SUN")
        fig.add_trace(go.Scatter(x=future, y=[weekly.iloc[-1]] + [baseline] * FORECAST_WEEKS, mode="lines",
                                 name=f"Projected (+{growth:.0%})", line=dict(color="#FF9900", width=2, dash="dash"),
                                 hovertemplate="Projected week of %{x|%b %d, %Y}<br>%{y:,.0f} units<extra></extra>"))
    fig.update_layout(title="Weekly demand trend", xaxis_title=None, yaxis_title="Units sold per week",
                      legend=dict(orientation="h", y=1.0, x=0, yanchor="bottom", font=dict(size=11)), height=CHART_HEIGHT, margin=dict(t=60, b=10, l=10, r=10))
    return fig


def inventory_vs_reorder_chart(plan, single_center, top_n=TOP_N_URGENT):
    """Most urgent items on top. Urgency is current inventory divided by reorder point."""
    view = plan.assign(coverage=plan["current_inventory"] / plan["reorder_point"].where(plan["reorder_point"] > 0))
    view["coverage"] = view["coverage"].fillna(np.inf)
    if single_center:
        view["label"] = view["medicine_name"]
    else:
        view["label"] = view["medicine_name"] + " (" + view["fulfillment_center"].str.replace("FC-", "") + ")"
    view = view.nsmallest(top_n, "coverage")
    view = view.sort_values("coverage", ascending=False)  # plotly draws the last row at the top
    fig = go.Figure()
    fig.add_trace(go.Bar(y=view["label"], x=view["current_inventory"], orientation="h",
                         name="Inventory", marker_color="#232F3E",
                         hovertemplate="%{y}<br>Inventory %{x:,.0f} units<extra></extra>"))
    fig.add_trace(go.Bar(y=view["label"], x=view["reorder_point"], orientation="h",
                         name="Reorder point", marker_color="#FF9900",
                         hovertemplate="%{y}<br>Reorder point %{x:,.0f} units<extra></extra>"))
    fig.update_layout(title="Inventory versus reorder point", barmode="group",
                      xaxis_title=None, yaxis_title=None, yaxis_automargin=True, height=CHART_HEIGHT,
                      legend=dict(orientation="h", xref="container", x=0.02, y=0, yref="container", yanchor="bottom", font=dict(size=11)), margin=dict(t=40, b=45, l=10, r=10))
    return fig


def risk_distribution_chart(plan):
    counts = plan["risk_level"].value_counts().reindex(RISK_ORDER, fill_value=0)
    labels = [r.replace(" ", "<br>", 1) for r in counts.index]
    fig = go.Figure(go.Bar(x=labels, y=counts.values, text=counts.values, textposition="outside",
                           marker_color=[RISK_COLORS[r] for r in counts.index],
                           hovertemplate="%{y} medicine and center pairs<extra></extra>"))
    fig.update_layout(title="Inventory risk distribution", xaxis_title=None,
                      yaxis_title="Medicine and center pairs", xaxis_tickangle=0,
                      yaxis=dict(range=[0, max(counts.max() * 1.2, 1)]), height=CHART_HEIGHT, margin=dict(t=60, b=10, l=10, r=10))
    return fig


def main():
    st.set_page_config(page_title="Amazon Pharmacy Stockout Prevention", page_icon="💊", layout="wide")
    # Tighten Streamlit's default spacing so the dashboard fits on one laptop screen
    st.markdown(
        """
        <style>
        .block-container {padding-top: 2.8rem; padding-bottom: 0.5rem;}
        [data-testid="stMetricValue"] {font-size: 1.6rem;}
        [data-testid="stMetric"] {padding: 0;}
        h3 {padding-top: 0 !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    df = load_data()

    # The three interactive controls
    st.sidebar.header("Filters and scenario")
    category = st.sidebar.selectbox("Medicine category", ["All categories"] + sorted(df["category"].unique()))
    center = st.sidebar.selectbox("Fulfillment center", ["All fulfillment centers"] + sorted(df["fulfillment_center"].unique()))
    growth_pct = st.sidebar.slider("Expected demand growth (%)", min_value=0, max_value=30, value=0, step=1, format="%d%%",
                                   help="Tests how higher demand changes risk, reorder point, and order quantity.")
    growth = growth_pct / 100
    st.sidebar.markdown("---")
    st.sidebar.caption(
        f"Data through {df['date'].max():%B %d, %Y}. Average daily demand uses the last {BASELINE_DAYS} days. "
        f"Safety stock factor is {SAFETY_STOCK_FACTOR}. Synthetic data. Not an Amazon internal system and "
        "does not make medical decisions."
    )

    st.markdown("### 💊 Amazon Pharmacy Demand Forecasting and Stockout Prevention")

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

    tab_dash, tab_recs, tab_method = st.tabs(["Dashboard", "Recommendations", "How it works"])

    with tab_dash:
        if critical:
            pairs = "medicine and center pair" if critical == 1 else "medicine and center pairs"
            verb = "runs" if critical == 1 else "run"
            st.markdown(f":red[**{critical} {pairs} {verb} out before a normal order arrives.**] "
                        "Order quantities are in the Recommendations tab.")
        else:
            st.markdown(":green[**No medicine is at critical stockout risk for these filters.**]")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.plotly_chart(demand_trend_chart(filtered, growth), use_container_width=True, config=PLOTLY_CONFIG)
            st.caption("Dashed line applies the growth scenario.")
        with col2:
            st.plotly_chart(inventory_vs_reorder_chart(plan, center != "All fulfillment centers"),
                            use_container_width=True, config=PLOTLY_CONFIG)
            st.caption(f"Units. {TOP_N_URGENT} most urgent. Dark bar shorter than orange means reorder.")
        with col3:
            st.plotly_chart(risk_distribution_chart(plan), use_container_width=True, config=PLOTLY_CONFIG)
            st.caption("Each medicine counted once per center.")

    with tab_recs:
        st.caption("Sorted by urgency. Order quantity brings stock up to the reorder point plus one month of demand.")
        table = plan.assign(risk_rank=plan["risk_level"].map({r: i for i, r in enumerate(RISK_ORDER)}))
        table = table.sort_values(["risk_rank", "days_of_inventory"])
        table["days_of_inventory"] = table["days_of_inventory"].replace(np.inf, np.nan)  # no demand shows blank
        table["action"] = table["risk_level"].map(RISK_DOTS) + " " + table["risk_level"].map(SHORT_ACTIONS)
        st.dataframe(
            table[["medicine_name", "fulfillment_center", "current_inventory", "avg_daily_demand",
                   "days_of_inventory", "reorder_point", "action", "recommended_order_qty", "order_cost"]],
            hide_index=True, use_container_width=True, height=460,
            column_config={
                "medicine_name": st.column_config.TextColumn("Medicine", width=165),
                "fulfillment_center": st.column_config.TextColumn("Center", width=85),
                "current_inventory": st.column_config.NumberColumn("Inventory", format="localized", width=75),
                "avg_daily_demand": st.column_config.NumberColumn("Daily demand", format="%.1f", width=95),
                "days_of_inventory": st.column_config.NumberColumn("Days left", format="%.0f", width=70),
                "reorder_point": st.column_config.NumberColumn("Reorder point", format="localized", width=100),
                "action": st.column_config.TextColumn("Risk and action", width=175),
                "recommended_order_qty": st.column_config.NumberColumn("Order qty", format="localized", width=75),
                "order_cost": st.column_config.NumberColumn("Order cost", format="dollar", width=95),
            },
        )

    with tab_method:
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
