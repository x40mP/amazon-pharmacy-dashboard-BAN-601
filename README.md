# Amazon Pharmacy Demand Forecasting and Stockout Prevention Dashboard

BAN 601 group project. An interactive Streamlit dashboard that helps pharmacy inventory managers and fulfillment center managers spot medicines at risk of stockout, compare current inventory with expected demand, and decide what to reorder.

## Business problem

A pharmacy has to carry enough stock to meet customer demand without tying up cash in excess inventory. Inventory managers need a simple way to see which medicines need replenishment and how much to order.

The app answers three questions.

1. Which medicines have the highest demand?
2. Which medicines are at risk of stockout?
3. How does expected demand growth change replenishment needs?

This is a planning and exploration tool. It does not make medical decisions, use patient data, or represent an actual Amazon internal system.

## Dataset

`data/pharmacy_demand.csv` is a synthetic dataset built for this project because Amazon's internal pharmacy data is not public. It covers 24 medicines in 9 categories across 3 fulfillment centers, with one row per medicine, center, and day for all of 2025 (26,280 rows). It contains no patient information or personally identifiable information.

Every field is defined in [data_dictionary.md](data_dictionary.md).

## Interactive controls

The app has exactly three controls, all in the sidebar.

| Control | What it does |
|---|---|
| Medicine category dropdown | Filters every chart, metric, and recommendation to one category |
| Fulfillment center dropdown | Filters results to one fulfillment center |
| Expected demand growth slider | Applies a 0% to 30% demand increase and recalculates risk, reorder point, and recommended order quantity |

## Visualizations

| Chart | Business purpose |
|---|---|
| Demand trend line chart | Shows weekly units sold over 2025 plus an 8 week projection with the growth scenario applied |
| Current inventory versus reorder point bar chart | Shows which medicines are below or near their replenishment threshold, most urgent first. With all centers selected it shows the 15 most urgent medicine and center pairs |
| Inventory risk distribution chart | Counts medicines in each risk level |

The app also shows headline metrics, a stockout alert, and a replenishment table with a plain language recommendation for every medicine.

## Planning logic

Average daily demand and demand variability use a rolling 28 day window ending on the last date in the data. The growth slider scales both by the selected percentage.

| Metric | Calculation |
|---|---|
| Lead time demand | Average daily demand × supplier lead time |
| Safety stock | Standard deviation of daily demand × 1.65 (about a 95% service level) |
| Reorder point | Lead time demand + safety stock |
| Days of inventory | Current inventory ÷ average daily demand |
| Inventory value | Current inventory × unit cost |
| Recommended order quantity | Reorder point + 30 days of demand − current inventory, only when an order is needed |

Risk rules are checked in this order.

| Risk level | Rule | Recommendation |
|---|---|---|
| Critical stockout risk | Inventory is below lead time demand | Order now and expedite |
| Reorder soon | Inventory is below reorder point + 30 days of demand | Order this review cycle |
| Excess inventory | More than 75 days of inventory on hand | Hold orders or rebalance stock |
| Sufficient inventory | Everything else | No action needed |

The 30 day review period assumes inventory is reviewed and ordered monthly. All thresholds are constants at the top of `app.py` so the team can adjust them in one place.

## Run the app locally

Requires Python 3.10 or newer.

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser at http://localhost:8501.

## Testing

`tests/test_calculations.py` checks the formulas against hand calculated values, confirms each risk rule, confirms the growth slider raises reorder points and order quantities, and covers zero, negative, empty, and single day inputs.

```bash
pip install pytest
python -m pytest tests
```

## Repository contents

| Item | Purpose |
|---|---|
| `app.py` | Streamlit application and planning logic |
| `data/pharmacy_demand.csv` | Synthetic dataset |
| `requirements.txt` | Python packages needed to run the app |
| `data_dictionary.md` | Definition, type, unit, and business meaning of each field |
| `tests/` | Calculation and edge case tests |
| `screenshots/` | Screenshots of the working app |

## Team

| Member | Role |
|---|---|
| Anushree | Project coordination and planning |
| Nishta | Domain expert |
| Francis | Programming and data |
| Mira | User interface |
| Adrian | Quality assurance and GitHub integration |
