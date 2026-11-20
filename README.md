# Mutual Fund Portfolio Simulator

A web app to make a portfolio of Indian mutual funds and simulate SIP, lumpsum, or both.
The app uses real historical NAV data from [mfapi.in](https://www.mfapi.in/) (AMFI data).

## Install

This project uses [uv](https://docs.astral.sh/uv/) to manage Python and the packages.

1. Install uv, if you do not have it: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. Open PowerShell in this folder.
3. Install the packages: `uv sync`
   - uv makes the `.venv` folder and installs the versions in `uv.lock`.
   - uv gets Python 3.12 or later if it is not on your computer.

## Start the app

1. Run: `uv run streamlit run app.py`
2. Open http://localhost:8501 in your browser.

## Use the app

1. In **Build portfolio**, type a fund name and push **Add this fund**.
2. For each fund, add SIP rows and lumpsum rows in the tables.
   - SIP: amount, frequency (Monthly, Weekly, Fortnightly, Quarterly), start date, end date (optional), annual step-up %.
   - Lumpsum: amount and date. You can add many lumpsums for one fund.
3. Open **Results** to see the values.
4. Open **Relive the journey** to see how your money moved:
   - Select the whole portfolio, one fund, or one SIP plan or lumpsum.
   - See the lowest P&L, the biggest fall from a peak gain, and the time in loss.
   - Move the date slider to see the invested amount, value and P&L on that day.
   - See each instalment: its value now, its return, and its lowest point after the purchase.
5. Open **Transactions** to see each purchase with its value now. You can download a CSV file.
6. Open **Compare** to compare the open portfolio with saved portfolios.
7. Push **Save** in the sidebar to keep the portfolio. Use **Load** to open it again.

## Fields in Results

| Field | Meaning |
|---|---|
| Total invested | Sum of all purchases up to the valuation date. |
| Current value | Units × NAV on the valuation date. |
| Absolute return % | (Value − Invested) ÷ Invested. |
| XIRR | Annual return that includes the date of each cash flow. |
| Benchmark XIRR | XIRR if the same amounts on the same dates went into the benchmark fund. |
| TWR (annual) | Time-weighted return. It removes the effect of cash flow timing. |
| Max drawdown | Largest fall from a peak, on the time-weighted index. |
| Volatility | Annual standard deviation of daily time-weighted returns. |
| Fund NAV CAGR | Growth of the fund NAV from the first purchase to the valuation date. |
| Weight % | Part of the total value in each fund. |
| P&L | Value − invested amount, on a given day. |
| Lowest P&L | The lowest P&L on any day (the worst loss you saw). |
| Fall from peak gain | Money lost from the best P&L so far. |
| Time in loss | Part of NAV days when the value was below the invested amount. |
| Worst fall % (instalment) | Largest fall of the NAV below the buy NAV after that purchase. |

## Rules of the simulation

- A purchase uses the NAV of the order date. If that day has no NAV (holiday), it uses the next NAV date.
- A monthly SIP on day 31 uses the last day of shorter months.
- Step-up increases the SIP amount once a year, from the SIP start date.
- The app does not buy before the first NAV of a fund. It shows these orders as "not done".
- Stamp duty (0.005 %) is optional. Exit load and tax are not included.
- The app keeps NAV data in `.cache/` for 12 hours. Push **Refresh NAV data** to get new data.
- Saved portfolios are JSON files in `portfolios/`.

## Tests

Run: `uv run pytest -q`

## Change the packages

- Add a package: `uv add <name>`
- Add a package for development only: `uv add --dev <name>`
- Remove a package: `uv remove <name>`
- Update all packages in the lock file: `uv lock --upgrade`, then `uv sync`

Commit `pyproject.toml` and `uv.lock` after each change.
