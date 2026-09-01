# Challenge 3 · Next intent, right moment

**Track A, a customer-facing AI product.** Everyone is building a financial assistant right now, Nu
included. The part nobody has cracked is not the interface, it is the judgment behind it: knowing what
the customer is about to want, knowing whether this is the moment to say anything, and knowing what the
recommendation is supposed to be optimizing in the first place.

**Your job:** predict the customer's next financial intent, and decide whether now is the moment to act
on it.

**Target metric:** chosen and defended by the team. That choice is the first deliverable, not a
formality. Engagement, financial health, satisfaction and revenue point at different recommendations, and
the data lets you measure all four.

---

## The three questions

1. **Next intent.** What financial action is this customer about to take? The app behavior that precedes
   an action is in the data.
2. **Right moment.** A recommendation that lands at the right time is a different product from the same
   recommendation shown at random. And the same nudge repeated is not neutral: it costs something.
3. **What are we optimizing?** Customer financial health, satisfaction, engagement with the bank,
   profitability, or a combination. Pick one, build the objective, and defend it with numbers. The
   dataset carries the consequences of each nudge over the following 90 days, so this is measurable
   rather than philosophical.

---

## What is in `data/`

Five Parquet tables, roughly 1.7M rows in total. Join key is `customer_id`, plus `nudge_id`.

### `customers.parquet` — 38,000 rows

| column | type | description |
|---|---|---|
| `customer_id` | int | primary key |
| `tenure_months`, `age`, `state`, `income_band` | | demographics |
| `monthly_income_est_mxn` | float | |
| `payday_day_of_month` | int | 1, 15 or 30. Worth using |
| `engagement_score` | float | 0 to 100 app engagement index |
| `avg_balance_mxn` | float | |
| `card_utilization_pct` | float | |
| `days_negative_90d` | int | days with a negative balance |
| `savings_rate_90d_pct` | float | |
| `revenue_ltm_mxn` | float | revenue the customer generated in the last twelve months |
| `nps_last_score` | float | null for about 70% of customers, only those who answered |
| `has_cuenta_nu`, `has_cajita_turbo`, `has_personal_loan`, `has_investments`, `has_payroll_portability` | bool | current holdings |

The financial condition columns are there so you can build an objective around financial health rather
than only around clicks.

### `app_events.parquet` — 797,304 rows (120 days)

| column | type | description |
|---|---|---|
| `event_id` | int32 | primary key |
| `customer_id` | int32 | FK |
| `event_ts` | timestamp | |
| `screen` | string | `home`, `transfer_spei`, `bill_payment`, `card_statement`, `savings_cajita`, `loan_simulation`, `limit_increase`, `investments`, `support`, `card_settings` |
| `action` | string | `view`, `start`, `abandon` |

There is no session id. Grouping events into sessions is your call and your definition.

### `financial_actions.parquet` — 566,682 rows

| column | type | description |
|---|---|---|
| `action_id` | int32 | primary key |
| `customer_id` | int32 | FK |
| `action_ts` | timestamp | |
| `action_type` | string | `spei_out`, `bill_payment`, `deposit_in`, `savings_move`, `loan_request`, `limit_increase_request`, `card_payment`, `investment_buy` |
| `amount_mxn` | float32 | |
| `is_recurring` | bool | |

**There is no ready made intent label.** You define the prediction window, pick a cut-off date, and build
the label from this table. That framing decision is part of what the panel evaluates.

### `nudges.parquet` — 285,000 rows

| column | type | description |
|---|---|---|
| `nudge_id` | int32 | primary key |
| `customer_id` | int32 | FK |
| `shown_ts` | timestamp | |
| `nudge_type` | string | `savings_goal`, `limit_increase`, `bill_reminder`, `loan_offer`, `invest_start`, `payroll_portability` |
| `surface` | string | `home_card`, `push`, `in_app_modal` |
| `exposure_no` | int16 | how many times this customer has already seen this nudge type |
| `hours_since_last_nudge` | float32 | since any nudge, null for the first one |
| `engaged` | bool | the customer acted on it |
| `dismissed` | bool | |
| `opted_out_after` | bool | the customer turned notifications off after this one |

Nudge type and surface were assigned close to at random, which is what makes acceptance readable as fit
rather than as a reflection of the old targeting.

### `nudge_outcomes.parquet` — 285,000 rows

| column | type | description |
|---|---|---|
| `nudge_id` | int32 | FK |
| `delta_card_utilization_pct_90d` | float32 | change in utilization over the 90 days after |
| `delta_savings_rate_pct_90d` | float32 | |
| `delta_days_negative_90d` | float32 | |
| `delta_revenue_mxn_90d` | float32 | |

This is the table that makes the target metric question answerable. Compare what happens after each nudge
type, and check whether the one with the best engagement is the one you would actually want to send.

---

## What the panel expects

1. An intent model with a stated framing: what window, what cut-off, what classes, and why. Report
   accuracy against the majority class baseline, not in isolation.
2. Evidence about timing and repetition, taken from the data rather than assumed.
3. A defended objective function, with at least two candidate objectives compared and the trade-off named.
4. A feature design in the app: where the recommendation appears, what it says, and when it stays quiet.

## Ground rules

- 100% synthetic data. No real Nu customer information is involved.
- `nps_last_score` is missing for most customers by design. Satisfaction is hard to optimize when you can
  barely measure it, and that is a real constraint, not a data defect.
- `gen_d3_intent.py` is the seeded generator. Use `--customers` to rescale.
