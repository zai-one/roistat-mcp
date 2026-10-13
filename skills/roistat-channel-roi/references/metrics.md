# Roistat metrics (allowlisted names)

| Metric | Meaning | Formula / note |
|---|---|---|
| `visits` / `visitCount` | visits | |
| `leads` / `leadCount` | leads (orders created) | |
| `sales` | paid orders | |
| `revenue` | revenue of sales | |
| `profit` | profit as calculated by Roistat (depends on project cost-price settings) | |
| `marketing_cost` | ad spend (imported or manual) | |
| `roi` | return on marketing spend, % | calculated by Roistat; do not recompute |
| `cpc` | cost per click | marketing_cost / clicks |
| `cpl` | cost per lead | marketing_cost / leads |
| `cpo` | cost per order (sale) | marketing_cost / sales |
| `average_sale` / `averageRevenue` | average order value | revenue / sales |
| `impressions`, `ctr` | ad impressions, click-through rate | |
| `conversion_visits_to_leads` (`visits2leads`, `cv1`) | visit → lead conversion | |
| `conversion_leads_to_sales` (`leads2orders`, `cv2`) | lead → sale conversion | |

Attribution models: `default`, `first_click`, `last_click`, `last_paid_click`, `u_shape`, `linear`, …
(full list: `roistat_analytics_catalog`). Max 12 metrics, 2 dimensions per report.
Prefer Roistat's own `roi`/`cpl`/`cpo` over recomputing; if you compute, show the formula.
