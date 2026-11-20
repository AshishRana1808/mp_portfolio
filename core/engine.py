"""Simulation engine: SIP / lumpsum orders, units, value, XIRR and other metrics."""
from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

FREQUENCIES = ("Monthly", "Weekly", "Fortnightly", "Quarterly")


# ---------------------------------------------------------------- dates ----
def _to_date(v) -> date | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        v = v.strip()
        return date.fromisoformat(v[:10]) if v else None
    return None


def _add_months(d: date, months: int, day: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def sip_dates(start: date, end: date, frequency: str) -> list[date]:
    """All instalment dates from start to end (both inclusive)."""
    out: list[date] = []
    if start is None or end is None or start > end:
        return out
    if frequency in ("Weekly", "Fortnightly"):
        step = timedelta(days=7 if frequency == "Weekly" else 14)
        d = start
        while d <= end:
            out.append(d)
            d += step
        return out
    months = 3 if frequency == "Quarterly" else 1
    k = 0
    while True:
        d = _add_months(start, k * months, start.day)
        if d > end:
            break
        out.append(d)
        k += 1
    return out


def _full_years(start: date, d: date) -> int:
    years = d.year - start.year
    if (d.month, d.day) < (start.month, start.day):
        years -= 1
    return max(years, 0)


# ---------------------------------------------------------------- XIRR -----
def xnpv(rate: float, flows: list[tuple[date, float]]) -> float:
    t0 = flows[0][0]
    return sum(a / (1 + rate) ** ((d - t0).days / 365.0) for d, a in flows)


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annual XIRR as a fraction (0.12 = 12 %). None if it cannot be found."""
    flows = sorted((f for f in flows if abs(f[1]) > 1e-9), key=lambda f: f[0])
    if len(flows) < 2:
        return None
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    if (flows[-1][0] - flows[0][0]).days == 0:
        return None

    def f(r):
        return xnpv(r, flows)

    # Bracket the root, then use bisection (robust for all cash flow shapes).
    lo, hi = -0.9999, 1.0
    f_lo, f_hi = f(lo), f(hi)
    while f_lo * f_hi > 0 and hi < 1e6:
        hi *= 2
        f_hi = f(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = f(mid)
        if abs(f_mid) < 1e-7 or (hi - lo) < 1e-10:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


# ------------------------------------------------------------ orders -------
@dataclass
class Order:
    date: date
    amount: float
    kind: str  # "SIP (Monthly)" or "Lumpsum"
    plan: str = ""  # "SIP 1", "Lumpsum 2": the row in the fund's plan tables


def build_orders(fund: dict, as_of: date) -> list[Order]:
    orders: list[Order] = []
    for i, sip in enumerate(fund.get("sips", []), start=1):
        amount = float(sip.get("amount") or 0)
        start = _to_date(sip.get("start"))
        if amount <= 0 or start is None:
            continue
        end = _to_date(sip.get("end")) or as_of
        end = min(end, as_of)
        step = float(sip.get("step_up_pct") or 0) / 100.0
        freq = sip.get("frequency") or "Monthly"
        for d in sip_dates(start, end, freq):
            amt = amount * (1 + step) ** _full_years(start, d)
            orders.append(Order(d, round(amt, 2), f"SIP ({freq})", f"SIP {i}"))
    for j, ls in enumerate(fund.get("lumpsums", []), start=1):
        amount = float(ls.get("amount") or 0)
        d = _to_date(ls.get("date"))
        if amount > 0 and d is not None and d <= as_of:
            orders.append(Order(d, amount, "Lumpsum", f"Lumpsum {j}"))
    orders.sort(key=lambda o: o.date)
    return orders


# ------------------------------------------------------------ results ------
@dataclass
class FundResult:
    code: int
    name: str
    category: str
    transactions: pd.DataFrame  # order_date, nav_date, kind, amount, nav, units, cum_units
    skipped: list[str]
    nav: pd.Series
    valuation_date: date | None
    current_nav: float | None
    invested: float = 0.0
    units: float = 0.0
    value: float = 0.0
    xirr: float | None = None
    flows: list[tuple[date, float]] = field(default_factory=list)


def execute_orders(orders: list[Order], nav: pd.Series, as_of: date,
                   stamp_duty_pct: float = 0.0) -> tuple[pd.DataFrame, list[str]]:
    """Buy at the NAV of the order date, or of the next NAV date."""
    rows, skipped = [], []
    idx = nav.index
    as_of_ts = pd.Timestamp(as_of)
    first_nav = idx[0].date()
    for o in orders:
        pos = idx.searchsorted(pd.Timestamp(o.date), side="left")
        if pos >= len(idx) or idx[pos] > as_of_ts:
            skipped.append(f"{o.date:%d-%b-%Y} {o.kind} ₹{o.amount:,.0f}: no NAV on or after this date (up to the valuation date).")
            continue
        if o.date < first_nav:
            skipped.append(f"{o.date:%d-%b-%Y} {o.kind} ₹{o.amount:,.0f}: date is before the first NAV ({first_nav:%d-%b-%Y}).")
            continue
        nav_date = idx[pos]
        price = float(nav.iloc[pos])
        net = o.amount * (1 - stamp_duty_pct / 100.0)
        rows.append({
            "order_date": o.date, "nav_date": nav_date.date(), "kind": o.kind, "plan": o.plan,
            "amount": o.amount, "nav": price, "units": net / price,
        })
    df = pd.DataFrame(rows, columns=["order_date", "nav_date", "kind", "plan", "amount", "nav", "units"])
    df["cum_units"] = df["units"].cumsum()
    df["cum_invested"] = df["amount"].cumsum()
    return df, skipped


def simulate_fund(fund: dict, meta: dict, nav: pd.Series, as_of: date,
                  stamp_duty_pct: float = 0.0) -> FundResult:
    orders = build_orders(fund, as_of)
    tx, skipped = execute_orders(orders, nav, as_of, stamp_duty_pct)
    upto = nav[nav.index <= pd.Timestamp(as_of)]
    res = FundResult(
        code=int(fund["code"]), name=fund.get("name") or meta.get("scheme_name", str(fund["code"])),
        category=meta.get("scheme_category", ""), transactions=tx, skipped=skipped, nav=nav,
        valuation_date=upto.index[-1].date() if not upto.empty else None,
        current_nav=float(upto.iloc[-1]) if not upto.empty else None,
    )
    if tx.empty or res.current_nav is None:
        return res
    res.invested = float(tx["amount"].sum())
    res.units = float(tx["units"].sum())
    res.value = res.units * res.current_nav
    res.flows = [(d, -a) for d, a in zip(tx["nav_date"], tx["amount"])]
    res.xirr = xirr(res.flows + [(res.valuation_date, res.value)])
    return res


def fund_summary_row(r: FundResult, total_value: float) -> dict:
    tx = r.transactions
    gain = r.value - r.invested
    first = tx["nav_date"].iloc[0] if not tx.empty else None
    nav_cagr = None
    if first is not None and r.valuation_date and r.valuation_date > first:
        years = (r.valuation_date - first).days / 365.0
        start_nav = float(tx["nav"].iloc[0])
        if years > 0 and start_nav > 0:
            nav_cagr = (r.current_nav / start_nav) ** (1 / years) - 1
    return {
        "Fund": r.name,
        "Category": r.category,
        "Invested (₹)": r.invested,
        "Current value (₹)": r.value,
        "Gain (₹)": gain,
        "Absolute return %": (gain / r.invested * 100) if r.invested else None,
        "XIRR %": r.xirr * 100 if r.xirr is not None else None,
        "Fund NAV CAGR % (since first buy)": nav_cagr * 100 if nav_cagr is not None else None,
        "Weight %": (r.value / total_value * 100) if total_value else None,
        "Units": r.units,
        "Avg buy NAV": (r.invested / r.units) if r.units else None,
        "Current NAV": r.current_nav,
        "Instalments": len(tx),
        "First buy": first,
        "Valuation date": r.valuation_date,
    }


# ------------------------------------------------------- time series -------
INVESTED_SUFFIX = " | invested"


def holding_series(tx: pd.DataFrame, nav: pd.Series, idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Value, invested amount and new money (Flow) of some transactions, on each date of idx."""
    if tx.empty or len(idx) == 0:
        return pd.DataFrame({"Value": 0.0, "Invested": 0.0, "Flow": 0.0}, index=idx)
    by_day = tx.groupby(pd.to_datetime(tx["nav_date"]))[["units", "amount"]].sum()
    full = idx.union(by_day.index)
    units = by_day["units"].reindex(full, fill_value=0.0).cumsum().reindex(idx)
    amt_full = by_day["amount"].reindex(full, fill_value=0.0)
    invested = amt_full.cumsum().reindex(idx)
    flow = amt_full.reindex(idx, fill_value=0.0)
    px_ = nav.reindex(nav.index.union(idx)).ffill().reindex(idx)
    value = (units * px_).fillna(0.0)
    return pd.DataFrame({"Value": value, "Invested": invested, "Flow": flow}, index=idx)


def units_value_series(holdings: list[tuple[float, pd.Series]], idx: pd.DatetimeIndex) -> pd.Series:
    """Value on each date of idx of fixed units: [(units, nav series), ...].

    Use it with the units held today to see what today's holding was worth on past days.
    """
    total = pd.Series(0.0, index=idx)
    for units, nav in holdings:
        px_ = nav.reindex(nav.index.union(idx)).ffill().reindex(idx)
        total += (units * px_).fillna(0.0)
    return total


def pnl_metrics(value: pd.Series, invested: pd.Series) -> dict:
    """How the money moved: worst loss, gain lost from a peak, time in loss.

    P&L = value - invested. A fall from a peak of P&L is money you saw go away.
    """
    mask = invested > 0
    value, invested = value[mask], invested[mask]
    if value.empty:
        return {}
    pnl = value - invested
    pnl_pct = pnl / invested * 100
    peak = pnl.cummax().clip(lower=0)  # a peak gain; before any gain, the peak is 0
    fall = pnl - peak                   # money lost from the best gain so far (<= 0)
    in_loss = pnl < 0
    # longest calendar-day period in loss
    longest, start, longest_span = 0, None, (None, None)
    dates = pnl.index
    for d, loss in zip(dates, in_loss):
        if loss and start is None:
            start = d
        if not loss and start is not None:
            span = (d - start).days
            if span > longest:
                longest, longest_span = span, (start.date(), d.date())
            start = None
    if start is not None:
        span = (dates[-1] - start).days
        if span > longest:
            longest, longest_span = span, (start.date(), None)
    trough = fall.idxmin()
    peak_date = pnl.loc[:trough].idxmax() if fall.min() < 0 else trough
    return {
        "pnl": pnl, "pnl_pct": pnl_pct, "fall": fall,
        "worst_pnl": float(pnl.min()), "worst_pnl_date": pnl.idxmin().date(),
        "worst_pnl_pct": float(pnl_pct.min()), "worst_pnl_pct_date": pnl_pct.idxmin().date(),
        "best_pnl": float(pnl.max()), "best_pnl_date": pnl.idxmax().date(),
        "biggest_fall": float(fall.min()), "biggest_fall_peak": peak_date.date(),
        "biggest_fall_trough": trough.date(),
        "loss_days_pct": float(in_loss.mean() * 100),
        "longest_loss_days": longest, "longest_loss_span": longest_span,
        "in_loss_now": bool(in_loss.iloc[-1]),
    }


def instalment_analysis(r: FundResult) -> pd.DataFrame:
    """For each purchase: value now, return, and the lowest point after the purchase."""
    tx = r.transactions
    cols = ["current_value", "gain", "return_pct", "cagr_pct", "lowest_value", "worst_fall_pct",
            "lowest_on", "days_below_cost", "below_cost_now"]
    if tx.empty or r.current_nav is None:
        return tx.assign(**{c: None for c in cols})
    nav = r.nav[r.nav.index <= pd.Timestamp(r.valuation_date)]
    nav_v, nav_i = nav.to_numpy(), nav.index
    out = []
    for row in tx.itertuples(index=False):
        pos = nav_i.searchsorted(pd.Timestamp(row.nav_date), side="left")
        after = nav_v[pos:]
        cur = row.units * r.current_nav
        days = (r.valuation_date - row.nav_date).days
        k = int(after.argmin()) if len(after) else 0
        low_nav = float(after[k]) if len(after) else row.nav
        out.append({
            "current_value": cur,
            "gain": cur - row.amount,
            "return_pct": (cur / row.amount - 1) * 100 if row.amount else None,
            "cagr_pct": ((r.current_nav / row.nav) ** (365.0 / days) - 1) * 100 if days >= 365 else None,
            "lowest_value": row.units * low_nav,
            "worst_fall_pct": (low_nav / row.nav - 1) * 100,
            "lowest_on": nav_i[pos + k].date() if len(after) else row.nav_date,
            "days_below_cost": int((after < row.nav).sum()),
            "below_cost_now": r.current_nav < row.nav,
        })
    return pd.concat([tx.reset_index(drop=True), pd.DataFrame(out, columns=cols)], axis=1)


def plan_summary(r: FundResult) -> list[dict]:
    """One row for each SIP plan or lumpsum of a fund."""
    tx = r.transactions
    if tx.empty or r.current_nav is None:
        return []
    upto = r.nav[r.nav.index <= pd.Timestamp(r.valuation_date)]
    rows = []
    for plan, g in tx.groupby("plan", sort=False):
        invested = float(g["amount"].sum())
        value = float(g["units"].sum()) * r.current_nav
        flows = [(d, -a) for d, a in zip(g["nav_date"], g["amount"])]
        x = xirr(flows + [(r.valuation_date, value)])
        idx = upto.index[upto.index >= pd.Timestamp(g["nav_date"].min())]
        h = holding_series(g, r.nav, idx)
        m = pnl_metrics(h["Value"], h["Invested"])
        rows.append({
            "Fund": r.name, "Plan": plan, "Type": g["kind"].iloc[0],
            "From": g["nav_date"].min(), "To": g["nav_date"].max(), "Instalments": len(g),
            "Invested (₹)": invested, "Current value (₹)": value, "Gain (₹)": value - invested,
            "Absolute return %": (value / invested - 1) * 100 if invested else None,
            "XIRR %": x * 100 if x is not None else None,
            "Lowest P&L (₹)": m.get("worst_pnl"), "Lowest P&L %": m.get("worst_pnl_pct"),
            "Lowest P&L on": m.get("worst_pnl_date"),
            "Biggest fall from peak gain (₹)": m.get("biggest_fall"),
            "Days in loss %": m.get("loss_days_pct"),
        })
    return rows
def value_series(results: list[FundResult], as_of: date) -> pd.DataFrame:
    """Daily (NAV-day) series: invested, value, and value per fund."""
    active = [r for r in results if not r.transactions.empty]
    if not active:
        return pd.DataFrame()
    start = min(r.transactions["nav_date"].min() for r in active)
    idx = pd.DatetimeIndex([])
    for r in active:
        n = r.nav
        idx = idx.union(n.index[(n.index >= pd.Timestamp(start)) & (n.index <= pd.Timestamp(as_of))])
    out = pd.DataFrame(index=idx)
    invested = pd.Series(0.0, index=idx)
    flows = pd.Series(0.0, index=idx)
    total = pd.Series(0.0, index=idx)
    for r in active:
        h = holding_series(r.transactions, r.nav, idx)
        out[r.name] = h["Value"]
        out[f"{r.name}{INVESTED_SUFFIX}"] = h["Invested"]
        total += h["Value"]
        invested += h["Invested"]
        flows += h["Flow"]
    out["Invested"] = invested
    out["Value"] = total
    out["Flow"] = flows
    return out


def risk_metrics(series: pd.DataFrame) -> dict:
    """Time-weighted return, volatility and max drawdown (cash flows removed)."""
    if series.empty or len(series) < 3:
        return {}
    v = series["Value"].to_numpy()
    f = series["Flow"].to_numpy()
    prev = v[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(prev > 0, (v[1:] - f[1:]) / prev - 1, 0.0)
    r = np.nan_to_num(r)
    twr_index = pd.Series(np.concatenate([[1.0], np.cumprod(1 + r)]), index=series.index)
    days = (series.index[-1] - series.index[0]).days
    years = days / 365.0
    twr_total = twr_index.iloc[-1] - 1
    twr_ann = (twr_index.iloc[-1]) ** (1 / years) - 1 if years >= 1 else None
    dd = twr_index / twr_index.cummax() - 1
    trading_days = len(r) / max(years, 1e-9)
    vol = float(np.std(r, ddof=1) * math.sqrt(trading_days)) if len(r) > 2 else None
    return {
        "twr_total": float(twr_total),
        "twr_ann": float(twr_ann) if twr_ann is not None else None,
        "max_drawdown": float(dd.min()),
        "max_drawdown_date": dd.idxmin().date(),
        "volatility": vol,
        "twr_index": twr_index,
        "drawdown": dd,
    }


def benchmark_compare(flows: list[tuple[date, float]], bench_nav: pd.Series,
                      as_of: date) -> dict | None:
    """Put the same cash flows (same dates and amounts) into the benchmark fund."""
    idx = bench_nav.index
    upto = bench_nav[idx <= pd.Timestamp(as_of)]
    if upto.empty:
        return None
    units, invested, used, missed = 0.0, 0.0, [], 0
    for d, a in flows:
        pos = idx.searchsorted(pd.Timestamp(d), side="left")
        if pos >= len(idx) or idx[pos] > pd.Timestamp(as_of) or d < idx[0].date():
            missed += 1
            continue
        units += -a / float(bench_nav.iloc[pos])
        invested += -a
        used.append((idx[pos].date(), a))
    if not used:
        return None
    val_date, val_nav = upto.index[-1].date(), float(upto.iloc[-1])
    value = units * val_nav
    return {
        "invested": invested, "value": value, "units": units,
        "xirr": xirr(used + [(val_date, value)]),
        "abs_return": (value - invested) / invested if invested else None,
        "missed": missed, "valuation_date": val_date,
    }


def benchmark_series(flows: list[tuple[date, float]], bench_nav: pd.Series,
                     index: pd.DatetimeIndex) -> pd.Series:
    idx = bench_nav.index
    buys: dict[pd.Timestamp, float] = {}
    for d, a in flows:
        pos = idx.searchsorted(pd.Timestamp(d), side="left")
        if pos < len(idx) and d >= idx[0].date():
            buys[idx[pos]] = buys.get(idx[pos], 0.0) + (-a / float(bench_nav.iloc[pos]))
    if not buys:
        return pd.Series(dtype=float)
    u = pd.Series(buys).sort_index()
    full = idx.union(index)
    units = u.reindex(full, fill_value=0.0).cumsum()
    nav = bench_nav.reindex(full).ffill()
    return (units * nav).reindex(index)
