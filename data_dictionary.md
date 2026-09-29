# Data Dictionary

File `data/pharmacy_demand.csv`. One row per medicine, fulfillment center, and day from January 1 to December 31, 2025. 26,280 rows and 21 columns. Synthetic data with no patient or personally identifiable information.

| Field | Type | Unit | Business meaning |
|---|---|---|---|
| date | Date (YYYY-MM-DD) | Day | Calendar day the record covers |
| medicine_id | Text | ID | Unique medicine code such as MED-001 |
| medicine_name | Text | Name | Product name and strength such as Acetaminophen 500mg |
| category | Text (categorical) | Category | Medicine group used for the category filter. Pain Relief, Allergy, Vitamins, Gastrointestinal, Cold and Flu, Skin Care, Wellness, Travel Health, First Aid |
| fulfillment_center | Text (categorical) | Location | Fulfillment center holding the stock. FC-West, FC-Central, FC-East |
| supplier_id | Text | ID | Supplier used for replenishment on that day |
| primary_supplier_id | Text | ID | Default supplier for this medicine and center |
| primary_supplier_lead_time_days | Integer | Days | Days from order to delivery with the primary supplier |
| primary_supplier_unit_cost | Decimal | USD per unit | Purchase cost per unit from the primary supplier |
| backup_supplier_id | Text | ID | Alternate supplier, or "No backup supplier" |
| backup_supplier_lead_time_days | Integer | Days | Days from order to delivery with the backup supplier |
| backup_supplier_unit_cost | Decimal | USD per unit | Purchase cost per unit from the backup supplier |
| opening_inventory | Integer | Units | Units on hand at the start of the day |
| units_sold | Integer | Units | Units sold that day. This is the demand signal |
| inbound_units | Integer | Units | Units received from suppliers that day |
| inventory_adjustment_units | Integer | Units | Corrections for damage, expiry, or counts. Zero or negative |
| ending_inventory | Integer | Units | Opening inventory − units sold + inbound units + adjustments |
| current_inventory | Integer | Units | Units on hand at the end of the day. The app uses the last date as current stock |
| supplier_lead_time_days | Integer | Days | Lead time of the supplier in use. Drives lead time demand |
| unit_cost | Decimal | USD per unit | Cost of the supplier in use. Drives inventory value and order cost |
| promotion_flag | Integer (0 or 1) | Flag | 1 when the medicine was on promotion that day, which can lift demand |

## Calculated fields in the app

| Field | Unit | Definition |
|---|---|---|
| Average daily demand | Units per day | Mean units sold over the last 28 days × (1 + growth) |
| Demand standard deviation | Units per day | Standard deviation of units sold over the last 28 days × (1 + growth) |
| Lead time demand | Units | Average daily demand × supplier lead time |
| Safety stock | Units | Demand standard deviation × 1.65 |
| Reorder point | Units | Lead time demand + safety stock |
| Days of inventory | Days | Current inventory ÷ average daily demand |
| Inventory value | USD | Current inventory × unit cost |
| Risk level | Category | Critical stockout risk, Reorder soon, Sufficient inventory, or Excess inventory |
| Recommended order quantity | Units | Units needed to reach the reorder point plus 30 days of demand |
