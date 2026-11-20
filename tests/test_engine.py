from datetime import date

import pandas as pd
import pytest

from core import engine


def test_xirr_simple_one_year():
    r = engine.xirr([(date(2023, 1, 1), -100), (date(2024, 1, 1), 110)])
    assert r == pytest.approx(0.10, abs=1e-4)


def test_xirr_matches_excel_example():
    flows = [(date(2008, 1, 1), -10000), (date(2008, 3, 1), 2750), (date(2008, 10, 30), 4250),
             (date(2009, 2, 15), 3250), (date(2009, 4, 1), 2750)]
    assert engine.xirr(flows) == pytest.approx(0.373363, abs=1e-4)  # Excel doc value


def test_xirr_loss():
    r = engine.xirr([(date(2023, 1, 1), -100), (date(2024, 1, 1), 80)])
    assert r == pytest.approx(-0.20, abs=1e-4)


def test_sip_dates_month_end_clamp():
    d = engine.sip_dates(date(2024, 1, 31), date(2024, 4, 30), "Monthly")
    assert d == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30)]


def test_sip_dates_quarterly_weekly():
    assert len(engine.sip_dates(date(2024, 1, 5), date(2024, 12, 31), "Quarterly")) == 4
    assert len(engine.sip_dates(date(2024, 1, 1), date(2024, 1, 29), "Weekly")) == 5


def test_step_up():
    fund = {"code": 1, "sips": [{"amount": 1000, "frequency": "Monthly", "start": "2022-01-10",
                                 "end": "2024-01-10", "step_up_pct": 10}], "lumpsums": []}
    orders = engine.build_orders(fund, date(2025, 1, 1))
    amts = [o.amount for o in orders]
    assert amts[0] == 1000 and amts[11] == 1000
    assert amts[12] == pytest.approx(1100) and amts[24] == pytest.approx(1210)


def test_simulate_constant_growth():
    # NAV grows 10 %/year daily-compounded; a lumpsum must give XIRR ~10 %.
    idx = pd.bdate_range("2020-01-01", "2023-01-01")
    days = (idx - idx[0]).days
    nav = pd.Series(10 * 1.10 ** (days / 365.0), index=idx)
    fund = {"code": 1, "name": "X", "sips": [{"amount": 1000, "frequency": "Monthly", "start": "2020-01-15"}],
            "lumpsums": [{"amount": 50000, "date": "2020-01-01"}]}
    r = engine.simulate_fund(fund, {}, nav, date(2023, 1, 1))
    assert r.xirr == pytest.approx(0.10, abs=2e-3)
    assert r.invested == 50000 + 1000 * 36
    s = engine.value_series([r], date(2023, 1, 1))
    risk = engine.risk_metrics(s)
    assert risk["twr_ann"] == pytest.approx(0.10, abs=2e-3)
    assert risk["max_drawdown"] == pytest.approx(0, abs=1e-9)
    b = engine.benchmark_compare(r.flows, nav, date(2023, 1, 1))
    assert b["value"] == pytest.approx(r.value)


def test_order_on_holiday_uses_next_nav():
    nav = pd.Series([10.0, 11.0], index=pd.DatetimeIndex(["2024-01-05", "2024-01-08"]))
    fund = {"code": 1, "sips": [], "lumpsums": [{"amount": 1100, "date": "2024-01-06"}]}
    r = engine.simulate_fund(fund, {}, nav, date(2024, 1, 10))
    assert r.transactions["nav_date"].iloc[0] == date(2024, 1, 8)
    assert r.units == pytest.approx(100)


def _vshape_nav():
    # NAV 10 -> falls to 5 -> back to 20, on business days.
    idx = pd.bdate_range("2021-01-01", "2023-12-29")
    n = len(idx)
    third = n // 3
    import numpy as np
    vals = np.concatenate([np.linspace(10, 5, third), np.linspace(5, 20, n - third)])
    return pd.Series(vals, index=idx)


def test_plan_labels_and_instalment_analysis():
    nav = _vshape_nav()
    fund = {"code": 1, "name": "V", "sips": [{"amount": 1000, "frequency": "Monthly", "start": "2021-01-04"}],
            "lumpsums": [{"amount": 10000, "date": "2021-01-01"}]}
    r = engine.simulate_fund(fund, {}, nav, date(2023, 12, 29))
    assert set(r.transactions["plan"]) == {"SIP 1", "Lumpsum 1"}
    ia = engine.instalment_analysis(r)
    first = ia[ia["plan"] == "Lumpsum 1"].iloc[0]
    assert first["worst_fall_pct"] == pytest.approx(-50, abs=0.5)
    assert first["lowest_value"] == pytest.approx(5000, rel=0.01)
    assert first["current_value"] == pytest.approx(20000, rel=0.01)
    assert not first["below_cost_now"]


def test_pnl_metrics_vshape():
    nav = _vshape_nav()
    fund = {"code": 1, "name": "V", "sips": [], "lumpsums": [{"amount": 10000, "date": "2021-01-01"}]}
    r = engine.simulate_fund(fund, {}, nav, date(2023, 12, 29))
    s = engine.value_series([r], date(2023, 12, 29))
    m = engine.pnl_metrics(s["Value"], s["Invested"])
    assert m["worst_pnl"] == pytest.approx(-5000, rel=0.01)
    assert m["worst_pnl_pct"] == pytest.approx(-50, abs=0.5)
    assert m["best_pnl"] == pytest.approx(10000, rel=0.01)
    assert m["biggest_fall"] == pytest.approx(-5000, rel=0.01)  # from 0 gain down to -5000
    assert not m["in_loss_now"]
    assert m["longest_loss_days"] > 300
    rows = engine.plan_summary(r)
    assert rows[0]["Plan"] == "Lumpsum 1" and rows[0]["Lowest P&L (₹)"] == pytest.approx(-5000, rel=0.01)


def test_units_value_series():
    idx = pd.DatetimeIndex(["2024-01-01", "2024-01-02", "2024-01-03"])
    nav_a = pd.Series([10.0, 12.0], index=pd.DatetimeIndex(["2024-01-01", "2024-01-03"]))  # gap is filled
    nav_b = pd.Series([1.0, 2.0, 3.0], index=idx)
    s = engine.units_value_series([(5, nav_a), (10, nav_b)], idx)
    assert list(s) == [60.0, 70.0, 90.0]
