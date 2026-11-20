# Mutual Fund Portfolio Simulator

A web app to make a portfolio of Indian mutual funds and simulate SIP, lumpsum, or both.
The app uses real historical NAV data from [mfapi.in](https://www.mfapi.in/) (AMFI data).

## Install

1. Open PowerShell in this folder.
2. Make a virtual environment: `python -m venv .venv`
3. Install the packages: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`

## Start the app

1. Run: `.\.venv\Scripts\python.exe -m streamlit run app.py`
2. Open http://localhost:8501 in your browser.

## Use the app

1. In **Build portfolio**, type a fund name and push **Add this fund**.
2. For each fund, add SIP rows and lumpsum rows in the tables.
   - SIP: amount, frequency (Monthly, Weekly, Fortnightly, Quarterly), start date, end date (optional), annual step-up %.
   - Lumpsum: amount and date. You can add many lumpsums for one fund.
3. Open **Results** to see the values.
4. Open **Transactions** to see each purchase. You can download a CSV file.
5. Push **Save** in the sidebar to keep the portfolio. Use **Load** to open it again.

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

## Rules of the simulation

- A purchase uses the NAV of the order date. If that day has no NAV (holiday), it uses the next NAV date.
- A monthly SIP on day 31 uses the last day of shorter months.
- Step-up increases the SIP amount once a year, from the SIP start date.
- The app does not buy before the first NAV of a fund. It shows these orders as "not done".
- Stamp duty (0.005 %) is optional. Exit load and tax are not included.
- The app keeps NAV data in `.cache/` for 12 hours. Push **Refresh NAV data** to get new data.
- Saved portfolios are JSON files in `portfolios/`.

## Tests

Run: `.\.venv\Scripts\python.exe -m pytest -q`
