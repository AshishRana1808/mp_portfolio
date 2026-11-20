"""Mutual Fund Portfolio Simulator (Streamlit).

Run:  streamlit run app.py
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core import engine, storage
from core.nav import NavError, get_nav, search_funds

st.set_page_config(page_title="MF Portfolio Simulator", page_icon="📈", layout="wide")

DEFAULT_BENCH = {"code": 120716, "name": "UTI Nifty 50 Index Fund - Direct Plan - Growth"}
TODAY = date.today()


# ------------------------------------------------------------- helpers -----
def inr(x: float | None, dec: int = 0) -> str:
    """Indian number format: 12,34,567."""
    if x is None or pd.isna(x):
        return "—"
    neg = x < 0
    s = f"{abs(x):.{dec}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return f"{'-' if neg else ''}₹{whole}{'.' + frac if frac else ''}"


def inr_short(x: float | None) -> str:
    """Short Indian format for metric cards: ₹12.35 L, ₹1.24 Cr."""
    if x is None or pd.isna(x):
        return "—"
    a, sign = abs(x), "-" if x < 0 else ""
    if a >= 1e7:
        return f"{sign}₹{a / 1e7:,.2f} Cr"
    if a >= 1e5:
        return f"{sign}₹{a / 1e5:,.2f} L"
    return inr(x)


def pct(x: float | None, dec: int = 2) -> str:
    return "—" if x is None or pd.isna(x) else f"{x:.{dec}f}%"


def fdate(v) -> str:
    return "—" if v is None or (not isinstance(v, date) and pd.isna(v)) else f"{v:%d-%b-%Y}"


def _sign_color(v):
    if isinstance(v, (int, float)) and not pd.isna(v):
        return "color: #16a34a" if v > 0 else ("color: #dc2626" if v < 0 else "")
    return ""


def styled(df: pd.DataFrame, money=(), pcts=(), dates=(), num: dict | None = None, signed=()):
    """Format a table: ₹ amounts in Indian format, %, dates; green/red for signed columns."""
    fmt = {}
    fmt.update({c: (lambda v: inr(v)) for c in money if c in df.columns})
    fmt.update({c: (lambda v: pct(v)) for c in pcts if c in df.columns})
    fmt.update({c: fdate for c in dates if c in df.columns})
    fmt.update({k: v for k, v in (num or {}).items() if k in df.columns})
    sty = df.style.format(fmt)
    sc = [c for c in signed if c in df.columns]
    return sty.map(_sign_color, subset=sc) if sc else sty


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_nav(code: int):
    return get_nav(code)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(q: str):
    return search_funds(q)


def new_portfolio(name: str = "My Portfolio") -> dict:
    return {"name": name, "benchmark": dict(DEFAULT_BENCH), "stamp_duty": False,
            "as_of": None, "funds": []}


def new_fund(code: int, name: str) -> dict:
    return {"id": uuid.uuid4().hex[:8], "code": int(code), "name": name,
            "sips": [{"amount": 5000.0, "frequency": "Monthly",
                      "start": (TODAY.replace(day=1) - timedelta(days=3 * 365)).replace(day=5).isoformat(),
                      "end": None, "step_up_pct": 0.0}],
            "lumpsums": []}


def set_portfolio(pf: dict) -> None:
    pf.setdefault("benchmark", dict(DEFAULT_BENCH))
    pf.setdefault("funds", [])
    for f in pf["funds"]:
        f.setdefault("id", uuid.uuid4().hex[:8])
        f.setdefault("sips", [])
        f.setdefault("lumpsums", [])
    st.session_state.pf = pf
    st.session_state.ver = st.session_state.get("ver", 0) + 1


def _d(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, str):
        return date.fromisoformat(v[:10]) if v else None
    return v


def sip_df(sips: list[dict]) -> pd.DataFrame:
    cols = ["amount", "frequency", "start", "end", "step_up_pct"]
    rows = [{"amount": float(s.get("amount") or 0), "frequency": s.get("frequency") or "Monthly",
             "start": _d(s.get("start")), "end": _d(s.get("end")),
             "step_up_pct": float(s.get("step_up_pct") or 0)} for s in sips]
    df = pd.DataFrame(rows, columns=cols)
    df["frequency"] = df["frequency"].astype(object)
    df["start"] = df["start"].astype(object)
    df["end"] = df["end"].astype(object)
    return df


def ls_df(lumps: list[dict]) -> pd.DataFrame:
    rows = [{"amount": float(l.get("amount") or 0), "date": _d(l.get("date"))} for l in lumps]
    df = pd.DataFrame(rows, columns=["amount", "date"])
    df["date"] = df["date"].astype(object)
    return df


def _iso(v):
    v = _d(v)
    return v.isoformat() if v else None


def sips_from_df(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        amt = r.get("amount")
        if amt is None or pd.isna(amt):
            continue
        out.append({"amount": float(amt), "frequency": r.get("frequency") or "Monthly",
                    "start": _iso(r.get("start")), "end": _iso(r.get("end")),
                    "step_up_pct": 0.0 if pd.isna(r.get("step_up_pct")) else float(r.get("step_up_pct") or 0)})
    return out


def lumps_from_df(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df.to_dict("records"):
        amt = r.get("amount")
        if amt is None or pd.isna(amt):
            continue
        out.append({"amount": float(amt), "date": _iso(r.get("date"))})
    return out


if "pf" not in st.session_state:
    set_portfolio(new_portfolio())
pf: dict = st.session_state.pf
ver: int = st.session_state.ver


# ------------------------------------------------------------- sidebar -----
with st.sidebar:
    st.header("📁 Portfolio")
    pf["name"] = st.text_input("Portfolio name", value=pf["name"], key=f"pfname_{ver}")

    c1, c2 = st.columns(2)
    if c1.button("💾 Save", width="stretch"):
        saved = storage.save_portfolio(pf)
        st.toast(f"Saved: {saved}")
    if c2.button("➕ New", width="stretch"):
        set_portfolio(new_portfolio())
        st.rerun()

    saved_list = storage.list_portfolios()
    if saved_list:
        sel = st.selectbox("Saved portfolios", saved_list)
        c3, c4 = st.columns(2)
        if c3.button("📂 Load", width="stretch"):
            set_portfolio(storage.load_portfolio(sel))
            st.rerun()
        if c4.button("🗑️ Delete", width="stretch"):
            st.session_state.confirm_delete = sel
        if st.session_state.get("confirm_delete") == sel:
            st.warning(f"Delete '{sel}'? You cannot undo this.")
            d1, d2 = st.columns(2)
            if d1.button("Yes, delete", type="primary", width="stretch"):
                storage.delete_portfolio(sel)
                st.session_state.confirm_delete = None
                st.rerun()
            if d2.button("Cancel", width="stretch"):
                st.session_state.confirm_delete = None
                st.rerun()
    else:
        st.caption("No saved portfolios yet.")

    st.divider()
    st.header("⚙️ Settings")
    use_latest = st.checkbox("Value on latest NAV", value=pf.get("as_of") is None, key=f"latest_{ver}")
    if use_latest:
        pf["as_of"] = None
        as_of = TODAY
    else:
        as_of = st.date_input("Valuation date", value=_d(pf.get("as_of")) or TODAY,
                              max_value=TODAY, min_value=date(1995, 1, 1), key=f"asof_{ver}")
        pf["as_of"] = as_of.isoformat()

    pf["stamp_duty"] = st.checkbox("Deduct stamp duty (0.005%)", value=bool(pf.get("stamp_duty")),
                                   key=f"stamp_{ver}")

    st.subheader("Benchmark")
    st.caption(f"Now: **{pf['benchmark']['name']}**")
    bq = st.text_input("Find other benchmark fund", key=f"bq_{ver}", placeholder="e.g. Nifty 50 index direct")
    if bq:
        try:
            bres = cached_search(bq)
        except NavError as e:
            st.error(str(e))
            bres = []
        if bres:
            bopt = {f"{r['schemeName']} ({r['schemeCode']})": r for r in bres}
            bsel = st.selectbox("Result", list(bopt), key=f"bsel_{ver}")
            if st.button("Use as benchmark"):
                pf["benchmark"] = {"code": int(bopt[bsel]["schemeCode"]), "name": bopt[bsel]["schemeName"]}
                st.rerun()
        else:
            st.caption("No fund found.")

    st.divider()
    if st.button("🔄 Refresh NAV data", width="stretch"):
        cached_nav.clear()
        for f in pf["funds"] + [pf["benchmark"]]:
            try:
                get_nav(f["code"], force=True)
            except NavError:
                pass
        st.rerun()
    st.caption("NAV data: mfapi.in (AMFI). Past returns do not guarantee future returns.")


# ------------------------------------------------------------- main --------
st.title("📈 Mutual Fund Portfolio Simulator")
tab_build, tab_result, tab_relive, tab_tx, tab_cmp = st.tabs(
    ["🧱 Build portfolio", "📊 Results", "🎢 Relive the journey", "📜 Transactions", "⚖️ Compare"])

with tab_build:
    st.subheader("Add a fund")
    q = st.text_input("Search fund name", placeholder="e.g. parag parikh flexi cap direct growth",
                      key=f"q_{ver}")
    if q:
        try:
            res = cached_search(q)
        except NavError as e:
            st.error(str(e))
            res = []
        if res:
            opts = {f"{r['schemeName']} ({r['schemeCode']})": r for r in res}
            pick = st.selectbox(f"{len(res)} funds found", list(opts), key=f"pick_{ver}")
            if st.button("➕ Add this fund", type="primary"):
                r = opts[pick]
                pf["funds"].append(new_fund(r["schemeCode"], r["schemeName"]))
                st.rerun()
        else:
            st.info("No fund found. Try other words.")

    st.divider()
    if not pf["funds"]:
        st.info("The portfolio is empty. Search a fund above and add it.")

    freq_opts = list(engine.FREQUENCIES)
    for i, fund in enumerate(list(pf["funds"])):
        fid = fund["id"]
        with st.expander(f"**{fund['name']}**  ·  code {fund['code']}", expanded=True):
            st.markdown("**SIP plans** — add one row for each SIP. Keep *End* empty to continue to the valuation date.")
            base_key = f"sipbase_{fid}_{ver}"
            if base_key not in st.session_state:
                st.session_state[base_key] = sip_df(fund["sips"])
            sip_edit = st.data_editor(
                st.session_state[base_key], key=f"sip_{fid}_{ver}", num_rows="dynamic",
                width="stretch", hide_index=True,
                column_config={
                    "amount": st.column_config.NumberColumn("SIP amount (₹)", min_value=0, step=500,
                                                            default=5000.0, format="%.0f", required=True),
                    "frequency": st.column_config.SelectboxColumn("Frequency", options=freq_opts,
                                                                  default="Monthly", required=True),
                    "start": st.column_config.DateColumn("Start date", min_value=date(1995, 1, 1),
                                                         max_value=TODAY, format="DD-MMM-YYYY", required=True),
                    "end": st.column_config.DateColumn("End date (optional)", format="DD-MMM-YYYY"),
                    "step_up_pct": st.column_config.NumberColumn("Annual step-up %", min_value=0,
                                                                 max_value=100, step=1, default=0.0,
                                                                 format="%.1f"),
                },
            )
            fund["sips"] = sips_from_df(sip_edit)

            st.markdown("**Lumpsum investments** — add one row for each lumpsum.")
            lbase_key = f"lsbase_{fid}_{ver}"
            if lbase_key not in st.session_state:
                st.session_state[lbase_key] = ls_df(fund["lumpsums"])
            ls_edit = st.data_editor(
                st.session_state[lbase_key], key=f"ls_{fid}_{ver}", num_rows="dynamic",
                width="stretch", hide_index=True,
                column_config={
                    "amount": st.column_config.NumberColumn("Lumpsum amount (₹)", min_value=0, step=1000,
                                                            default=100000.0, format="%.0f", required=True),
                    "date": st.column_config.DateColumn("Date", min_value=date(1995, 1, 1), max_value=TODAY,
                                                        format="DD-MMM-YYYY", required=True),
                },
            )
            fund["lumpsums"] = lumps_from_df(ls_edit)

            if st.button("🗑️ Remove this fund", key=f"rm_{fid}"):
                pf["funds"] = [f for f in pf["funds"] if f["id"] != fid]
                st.rerun()


# ------------------------------------------------------------- compute -----
def compute(pf: dict, as_of: date) -> dict:
    """Simulate one portfolio. Returns all results the pages need."""
    results: list[engine.FundResult] = []
    errors: list[str] = []
    for fund in pf.get("funds", []):
        try:
            meta, nav = cached_nav(fund["code"])
        except NavError as e:
            errors.append(f"{fund['name']}: {e}")
            continue
        results.append(engine.simulate_fund(fund, meta, nav, as_of,
                                            stamp_duty_pct=0.005 if pf.get("stamp_duty") else 0.0))
    bench_nav = None
    bm = pf.get("benchmark") or DEFAULT_BENCH
    try:
        _, bench_nav = cached_nav(bm["code"])
    except NavError as e:
        errors.append(f"Benchmark: {e}")
    active = [r for r in results if not r.transactions.empty]
    c = {"results": results, "errors": errors, "active": active, "bench_nav": bench_nav,
         "bench_name": bm["name"], "total_inv": sum(r.invested for r in active),
         "total_val": sum(r.value for r in active),
         "flows": [fl for r in active for fl in r.flows]}
    c["val_date"] = max((r.valuation_date for r in active if r.valuation_date), default=None)
    c["xirr"] = engine.xirr(c["flows"] + [(c["val_date"], c["total_val"])]) if active and c["val_date"] else None
    c["bench"] = (engine.benchmark_compare(c["flows"], bench_nav, as_of)
                  if (bench_nav is not None and c["flows"]) else None)
    c["series"] = engine.value_series(active, as_of) if active else pd.DataFrame()
    c["risk"] = engine.risk_metrics(c["series"]) if active else {}
    c["pnl"] = engine.pnl_metrics(c["series"]["Value"], c["series"]["Invested"]) if active else {}
    c["first_buy"] = min((r.transactions["nav_date"].min() for r in active), default=None)
    return c


with st.spinner("Getting NAV data..."):
    C = compute(pf, as_of)
results, errors, active = C["results"], C["errors"], C["active"]
bench_nav, bench = C["bench_nav"], C["bench"]
total_inv, total_val, all_flows = C["total_inv"], C["total_val"], C["flows"]
val_date, port_xirr = C["val_date"], C["xirr"]


with tab_result:
    for e in errors:
        st.error(e)
    if not active:
        st.info("No transactions yet. Add a fund with a SIP or a lumpsum in the **Build portfolio** tab.")
    else:
        gain = total_val - total_inv
        st.caption(f"Valuation date: **{val_date:%d-%b-%Y}** (latest NAV on or before {as_of:%d-%b-%Y})")
        k = st.columns(6)
        k[0].metric("Total invested", inr_short(total_inv), help=inr(total_inv))
        k[1].metric("Current value", inr_short(total_val), help=inr(total_val))
        k[2].metric("Total gain", inr_short(gain), help=inr(gain),
                    delta=pct(gain / total_inv * 100) if total_inv else None)
        k[3].metric("Absolute return", pct(gain / total_inv * 100 if total_inv else None))
        k[4].metric("XIRR", pct(port_xirr * 100 if port_xirr is not None else None))
        if bench and bench["xirr"] is not None and port_xirr is not None:
            k[5].metric("Benchmark XIRR", pct(bench["xirr"] * 100),
                        delta=f"{(port_xirr - bench['xirr']) * 100:+.2f}% alpha", delta_color="normal")
        else:
            k[5].metric("Benchmark XIRR", "—")

        series, risk, first_buy = C["series"], C["risk"], C["first_buy"]
        hold_days = (val_date - first_buy).days
        k2 = st.columns(6)
        k2[0].metric("Holding period", f"{hold_days // 365}y {(hold_days % 365) // 30}m")
        k2[1].metric("Instalments", f"{sum(len(r.transactions) for r in active)}")
        k2[2].metric("TWR (annual)", pct(risk.get("twr_ann") * 100 if risk.get("twr_ann") is not None else None),
                     help="Time-weighted return. It removes the effect of cash flow timing. Shown for 1 year or more.")
        k2[3].metric("Max drawdown", pct(risk.get("max_drawdown", 0) * 100) if risk else "—",
                     help="Largest fall from a peak, on the time-weighted index.")
        k2[4].metric("Volatility (annual)", pct(risk["volatility"] * 100) if risk.get("volatility") else "—")
        if bench:
            k2[5].metric("Benchmark value", inr_short(bench["value"]), help=inr(bench["value"]),
                         delta=inr_short(total_val - bench["value"]) + " vs bench")

        # ---- fund table
        st.subheader("Fund summary")
        rows = [engine.fund_summary_row(r, total_val) for r in active]
        if bench_nav is not None:
            for row, r in zip(rows, active):
                b = engine.benchmark_compare(r.flows, bench_nav, as_of)
                row["Benchmark XIRR % (same flows)"] = b["xirr"] * 100 if b and b["xirr"] is not None else None
        tot = {"Fund": "TOTAL", "Category": "", "Invested (₹)": total_inv, "Current value (₹)": total_val,
               "Gain (₹)": gain, "Absolute return %": gain / total_inv * 100 if total_inv else None,
               "XIRR %": port_xirr * 100 if port_xirr is not None else None, "Weight %": 100.0,
               "Instalments": sum(len(r.transactions) for r in active), "First buy": first_buy,
               "Valuation date": val_date}
        if bench:
            tot["Benchmark XIRR % (same flows)"] = bench["xirr"] * 100 if bench["xirr"] is not None else None
        tbl = pd.DataFrame(rows + [tot])
        money = ["Invested (₹)", "Current value (₹)", "Gain (₹)"]
        pcts = [c for c in tbl.columns if c.endswith("%") or "%" in c]
        sty = (tbl.style
               .format({**{c: lambda v: inr(v) for c in money},
                        **{c: lambda v: pct(v) for c in pcts},
                        "Units": lambda v: "—" if pd.isna(v) else f"{v:,.3f}",
                        "Avg buy NAV": lambda v: "—" if pd.isna(v) else f"{v:,.4f}",
                        "Current NAV": lambda v: "—" if pd.isna(v) else f"{v:,.4f}",
                        "Instalments": lambda v: "—" if pd.isna(v) else f"{int(v)}",
                        "First buy": lambda v: "—" if pd.isna(v) else f"{v:%d-%b-%Y}",
                        "Valuation date": lambda v: "—" if pd.isna(v) else f"{v:%d-%b-%Y}"})
               .map(lambda v: "color: #16a34a" if isinstance(v, (int, float)) and v > 0
                    else ("color: #dc2626" if isinstance(v, (int, float)) and v < 0 else ""),
                    subset=["Gain (₹)", "Absolute return %", "XIRR %"])
               .apply(lambda r: ["font-weight: 700" if r["Fund"] == "TOTAL" else "" for _ in r], axis=1))
        st.dataframe(sty, width="stretch", hide_index=True)

        # ---- plan table
        st.subheader("Each SIP plan and lumpsum")
        st.caption("Plan names match the row numbers in the SIP and lumpsum tables of each fund. "
                   "Lowest P&L is the lowest point of (value − invested) during the plan.")
        plans = pd.DataFrame([row for r in active for row in engine.plan_summary(r)])
        st.dataframe(styled(plans,
                            money=["Invested (₹)", "Current value (₹)", "Gain (₹)", "Lowest P&L (₹)",
                                   "Biggest fall from peak gain (₹)"],
                            pcts=["Absolute return %", "XIRR %", "Lowest P&L %", "Days in loss %"],
                            dates=["From", "To", "Lowest P&L on"],
                            signed=["Gain (₹)", "Absolute return %", "XIRR %", "Lowest P&L (₹)", "Lowest P&L %"]),
                     width="stretch", hide_index=True)

        # ---- charts
        c1, c2 = st.columns([2, 1])
        with c1:
            st.subheader("Value and invested amount")
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=series.index, y=series["Invested"], name="Invested",
                                     line=dict(dash="dot", color="#64748b")))
            fig.add_trace(go.Scatter(x=series.index, y=series["Value"], name="Portfolio value",
                                     fill="tonexty", line=dict(color="#2563eb")))
            if bench_nav is not None:
                bs = engine.benchmark_series(all_flows, bench_nav, series.index)
                if not bs.empty:
                    fig.add_trace(go.Scatter(x=bs.index, y=bs.values, name=f"Benchmark: {pf['benchmark']['name'][:40]}",
                                             line=dict(color="#f59e0b")))
            fig.update_layout(hovermode="x unified", height=420, margin=dict(l=0, r=0, t=10, b=0),
                              yaxis_tickprefix="₹", yaxis_tickformat=",.0f",
                              legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, width="stretch")
        with c2:
            st.subheader("Allocation")
            alloc = pd.DataFrame({"Fund": [r.name for r in active], "Value": [r.value for r in active]})
            figp = px.pie(alloc, names="Fund", values="Value", hole=0.45)
            figp.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
            figp.update_traces(textinfo="percent", hovertemplate="%{label}<br>₹%{value:,.0f}<extra></extra>")
            st.plotly_chart(figp, width="stretch")

        c3, c4 = st.columns(2)
        with c3:
            st.subheader("Value by fund")
            fund_cols = [r.name for r in active]
            figa = px.area(series[fund_cols], labels={"value": "₹", "index": "", "variable": "Fund"})
            figa.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                               hovermode="x unified")
            st.plotly_chart(figa, width="stretch")
        with c4:
            st.subheader("XIRR by fund")
            bx = bench["xirr"] * 100 if bench and bench["xirr"] is not None else 0.0
            xr = pd.DataFrame({"Fund": [r.name[:45] for r in active],
                               "XIRR %": [(r.xirr or 0) * 100 for r in active]})
            xr["Result"] = ["Beats benchmark" if v >= bx else "Below benchmark" for v in xr["XIRR %"]]
            figx = px.bar(xr, x="XIRR %", y="Fund", orientation="h", text_auto=".2f", color="Result",
                          color_discrete_map={"Beats benchmark": "#16a34a", "Below benchmark": "#dc2626"})
            if bench and bench["xirr"] is not None:
                figx.add_vline(x=bench["xirr"] * 100, line_dash="dash",
                               annotation_text="Benchmark", line_color="#f59e0b")
            figx.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="",
                               legend=dict(orientation="h", y=-0.2, title=""))
            st.plotly_chart(figx, width="stretch")

        if risk:
            st.subheader("Drawdown (time-weighted)")
            figd = px.area(risk["drawdown"] * 100, labels={"value": "%", "index": ""})
            figd.update_traces(line_color="#dc2626")
            figd.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
            st.plotly_chart(figd, width="stretch")

        # ---- yearly table
        st.subheader("Year by year")
        yearly = series[["Invested", "Value", "Flow"]].copy()
        yearly["Year"] = yearly.index.year
        y = yearly.groupby("Year").agg(**{"Invested in year": ("Flow", "sum"),
                                          "Total invested (year end)": ("Invested", "last"),
                                          "Value (year end)": ("Value", "last")})
        y["Gain (year end)"] = y["Value (year end)"] - y["Total invested (year end)"]
        y["Absolute return % (year end)"] = y["Gain (year end)"] / y["Total invested (year end)"] * 100
        st.dataframe(y.style.format({c: (lambda v: pct(v)) if "%" in c else (lambda v: inr(v)) for c in y.columns}),
                     width="stretch")

        skipped = [f"{r.name}: {s}" for r in results for s in r.skipped]
        if skipped:
            with st.expander(f"⚠️ {len(skipped)} orders not done"):
                for s in skipped:
                    st.write("- " + s)
        if bench and bench["missed"]:
            st.caption(f"Benchmark: {bench['missed']} cash flows were not used (no benchmark NAV on those dates).")

# ------------------------------------------------- per-instalment data -----
def all_instalments(active: list[engine.FundResult]) -> pd.DataFrame:
    frames = []
    for r in active:
        t = engine.instalment_analysis(r)
        t.insert(0, "Fund", r.name)
        frames.append(t)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_values(["nav_date", "Fund"]).reset_index(drop=True)


INST_COLS = {"Fund": "Fund", "plan": "Plan", "kind": "Type", "order_date": "Order date",
             "nav_date": "NAV date", "amount": "Amount (₹)", "nav": "Buy NAV", "units": "Units",
             "current_value": "Value now (₹)", "gain": "Gain (₹)", "return_pct": "Return %",
             "cagr_pct": "CAGR %", "lowest_value": "Lowest value (₹)", "worst_fall_pct": "Worst fall %",
             "lowest_on": "Lowest on", "days_below_cost": "NAV days below cost",
             "below_cost_now": "Below cost now", "cum_units": "Total units (fund)",
             "cum_invested": "Total invested (fund)"}


def inst_table(df: pd.DataFrame, cols: list[str]):
    view = df.rename(columns=INST_COLS)[[INST_COLS[c] for c in cols]]
    return styled(view,
                  money=["Amount (₹)", "Value now (₹)", "Gain (₹)", "Lowest value (₹)", "Total invested (fund)"],
                  pcts=["Return %", "CAGR %", "Worst fall %"],
                  dates=["Order date", "NAV date", "Lowest on"],
                  num={"Buy NAV": lambda v: f"{v:,.4f}", "Units": lambda v: f"{v:,.4f}",
                       "Total units (fund)": lambda v: f"{v:,.4f}",
                       "Below cost now": lambda v: "Yes" if v else "No"},
                  signed=["Gain (₹)", "Return %", "CAGR %", "Worst fall %"]), view


INST = all_instalments(active)


# ------------------------------------------------------------- relive ------
with tab_relive:
    if not active:
        st.info("No transactions yet.")
    else:
        series = C["series"]
        st.markdown("See how your money moved after each purchase. "
                    "**P&L** is value − invested amount. A **fall from peak gain** is gain that you saw go away.")
        opts = {"Whole portfolio": ("all", None, None)}
        for r in active:
            opts[r.name] = ("fund", r, None)
            for plan in r.transactions["plan"].unique():
                opts[f"{r.name} › {plan}"] = ("plan", r, plan)
        sel = st.selectbox("What to relive", list(opts), key="relive_sel")
        kind, rsel, plan = opts[sel]
        if kind == "all":
            value, invested = series["Value"], series["Invested"]
            inst = INST
        elif kind == "fund":
            value, invested = series[rsel.name], series[rsel.name + engine.INVESTED_SUFFIX]
            inst = INST[INST["Fund"] == rsel.name]
        else:
            g = rsel.transactions[rsel.transactions["plan"] == plan]
            h = engine.holding_series(g, rsel.nav, series.index)
            value, invested = h["Value"], h["Invested"]
            inst = INST[(INST["Fund"] == rsel.name) & (INST["plan"] == plan)]
        m = engine.pnl_metrics(value, invested)
        if not m:
            st.info("No data for this selection.")
        else:
            pnl, pnl_pct, fall = m["pnl"], m["pnl_pct"], m["fall"]
            value, invested = value.loc[pnl.index], invested.loc[pnl.index]
            k = st.columns(6)
            k[0].metric("Lowest P&L", inr_short(m["worst_pnl"]), help=f"On {fdate(m['worst_pnl_date'])}")
            k[1].metric("Lowest P&L %", pct(m["worst_pnl_pct"]), help=f"On {fdate(m['worst_pnl_pct_date'])}")
            k[2].metric("Biggest fall from peak gain", inr_short(m["biggest_fall"]),
                        help=f"From {fdate(m['biggest_fall_peak'])} to {fdate(m['biggest_fall_trough'])}")
            k[3].metric("Best P&L", inr_short(m["best_pnl"]), help=f"On {fdate(m['best_pnl_date'])}")
            k[4].metric("Time in loss", pct(m["loss_days_pct"], 1), help="Part of NAV days with value below invested.")
            span = m["longest_loss_span"]
            k[5].metric("Longest loss period", f"{m['longest_loss_days']} days",
                        help=f"From {fdate(span[0])} to {fdate(span[1]) if span[1] else 'now'}")

            # Story in short sentences.
            story = []
            if m["worst_pnl"] < 0:
                story.append(f"On **{fdate(m['worst_pnl_date'])}**, your money was **{inr(-m['worst_pnl'])}** "
                             f"below the amount you invested "
                             f"({pct(pnl_pct.loc[pd.Timestamp(m['worst_pnl_date'])])}).")
            else:
                story.append("Your value was never below the amount you invested.")
            if m["biggest_fall"] < 0:
                story.append(f"The largest fall started on **{fdate(m['biggest_fall_peak'])}**. "
                             f"By **{fdate(m['biggest_fall_trough'])}**, **{inr(-m['biggest_fall'])}** "
                             f"of value went away, compared with that peak.")
            story.append(f"Now the P&L is **{inr(pnl.iloc[-1])}** ({pct(pnl_pct.iloc[-1])}).")
            st.info(" ".join(story))

            # Time travel.
            d0, d1 = pnl.index[0].date(), pnl.index[-1].date()
            when = st.slider("Go to a date", min_value=d0, max_value=d1, value=d1, format="DD-MMM-YYYY",
                             key=f"relive_date_{sel}") if d1 > d0 else d1
            ts = pnl.index[pnl.index <= pd.Timestamp(when)][-1]
            w = st.columns(5)
            w[0].metric(f"Invested on {ts:%d-%b-%Y}", inr_short(invested.loc[ts]), help=inr(invested.loc[ts]))
            w[1].metric("Value on that day", inr_short(value.loc[ts]), help=inr(value.loc[ts]))
            w[2].metric("P&L on that day", inr_short(pnl.loc[ts]), delta=pct(pnl_pct.loc[ts]))
            w[3].metric("Fall from peak gain", inr_short(fall.loc[ts]),
                        help="How much below the best P&L up to that day.")
            w[4].metric("P&L now", inr_short(pnl.iloc[-1]),
                        delta=inr_short(pnl.iloc[-1] - pnl.loc[ts]) + " since that day")

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=pnl.index, y=pnl.clip(lower=0), fill="tozeroy", name="Profit",
                                     line=dict(color="#16a34a", width=1)))
            fig.add_trace(go.Scatter(x=pnl.index, y=pnl.clip(upper=0), fill="tozeroy", name="Loss",
                                     line=dict(color="#dc2626", width=1)))
            fig.add_trace(go.Scatter(x=pnl.index, y=pnl_pct, name="P&L %", yaxis="y2",
                                     line=dict(color="#94a3b8", width=1, dash="dot")))
            fig.add_vline(x=ts, line_color="#f59e0b", line_dash="dash")
            fig.update_layout(title="P&L (value − invested)", hovermode="x unified", height=380,
                              margin=dict(l=0, r=0, t=40, b=0), yaxis_tickprefix="₹", yaxis_tickformat=",.0f",
                              yaxis2=dict(overlaying="y", side="right", ticksuffix="%", showgrid=False),
                              legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, width="stretch")

            # Value against a straight line at today's invested amount.
            st.subheader("Value against your investment today")
            mode = st.radio(
                "Value line", ["Actual value on each day", "Today's units at past NAV"], horizontal=True,
                key=f"line_mode_{sel}",
                help="Actual value: what the holding was worth on that day. "
                     "Today's units at past NAV: what your current holding would be worth on that day. "
                     "Use it to see the falls your full investment can see.")
            st.caption("The dashed line is the total amount you invested up to the last date. "
                       "Green: value is above this line. Red: value is below this line. "
                       + ("Early in a SIP, the value is low because you invested less money then."
                          if mode.startswith("Actual") else
                          "This line shows what all your units of today were worth on each past day."))
            if mode.startswith("Actual"):
                vline = value
            else:
                if kind == "all":
                    holdings = [(r.units, r.nav) for r in active]
                elif kind == "fund":
                    holdings = [(rsel.units, rsel.nav)]
                else:
                    holdings = [(float(g["units"].sum()), rsel.nav)]
                vline = engine.units_value_series(holdings, value.index)
            inv_now = float(invested.iloc[-1])
            base = pd.Series(inv_now, index=vline.index)
            figs = go.Figure()
            figs.add_trace(go.Scatter(x=base.index, y=base, line=dict(width=0), showlegend=False, hoverinfo="skip"))
            figs.add_trace(go.Scatter(x=vline.index, y=vline.clip(lower=inv_now), fill="tonexty", name="Above",
                                      fillcolor="rgba(22,163,74,0.30)", line=dict(width=0), hoverinfo="skip"))
            figs.add_trace(go.Scatter(x=base.index, y=base, line=dict(width=0), showlegend=False, hoverinfo="skip"))
            figs.add_trace(go.Scatter(x=vline.index, y=vline.clip(upper=inv_now), fill="tonexty", name="Below",
                                      fillcolor="rgba(220,38,38,0.35)", line=dict(width=0), hoverinfo="skip"))
            figs.add_trace(go.Scatter(x=base.index, y=base, name=f"Invested now: {inr(inv_now)}",
                                      line=dict(color="#a855f7", width=2, dash="dash"),
                                      hovertemplate="Invested now ₹%{y:,.0f}<extra></extra>"))
            figs.add_trace(go.Scatter(x=vline.index, y=vline, name="Value", line=dict(color="#3b82f6", width=2),
                                      customdata=((vline / inv_now - 1) * 100).to_numpy(),
                                      hovertemplate="Value ₹%{y:,.0f} (%{customdata:+.2f}% vs invested now)"
                                                    "<extra></extra>"))
            figs.add_vline(x=ts, line_color="#f59e0b", line_dash="dash")
            figs.update_layout(hovermode="x unified", height=400, margin=dict(l=0, r=0, t=10, b=0),
                               yaxis_tickprefix="₹", yaxis_tickformat=",.0f", legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(figs, width="stretch")
            gap = vline - inv_now
            s = st.columns(4)
            s[0].metric("Days above the line", pct(float((gap >= 0).mean() * 100), 1))
            s[1].metric("Most below the line", inr_short(float(gap.min())),
                        delta=pct(float(gap.min() / inv_now * 100)), help=f"On {fdate(gap.idxmin().date())}")
            s[2].metric("Most above the line", inr_short(float(gap.max())),
                        delta=pct(float(gap.max() / inv_now * 100)), help=f"On {fdate(gap.idxmax().date())}")
            s[3].metric(f"On {ts:%d-%b-%Y}", inr_short(float(vline.loc[ts])),
                        delta=pct(float(gap.loc[ts] / inv_now * 100)) + " vs invested now")

            c1, c2 = st.columns(2)
            with c1:
                figv = go.Figure()
                figv.add_trace(go.Scatter(x=invested.index, y=invested, name="Invested",
                                          line=dict(dash="dot", color="#64748b")))
                figv.add_trace(go.Scatter(x=value.index, y=value, name="Value", line=dict(color="#2563eb")))
                figv.add_vline(x=ts, line_color="#f59e0b", line_dash="dash")
                figv.update_layout(title="Value and invested", hovermode="x unified", height=320,
                                   margin=dict(l=0, r=0, t=40, b=0), yaxis_tickprefix="₹",
                                   yaxis_tickformat=",.0f", legend=dict(orientation="h", y=-0.2))
                st.plotly_chart(figv, width="stretch")
            with c2:
                figf = go.Figure(go.Scatter(x=fall.index, y=fall, fill="tozeroy", name="Fall from peak gain",
                                            line=dict(color="#dc2626", width=1)))
                figf.add_vline(x=ts, line_color="#f59e0b", line_dash="dash")
                figf.update_layout(title="Money lost from the best P&L so far", hovermode="x unified",
                                   height=320, margin=dict(l=0, r=0, t=40, b=0), yaxis_tickprefix="₹",
                                   yaxis_tickformat=",.0f")
                st.plotly_chart(figf, width="stretch")

            # Each instalment.
            st.subheader("Each instalment: value now and lowest point")
            st.caption("**Worst fall %** is the largest fall of the NAV below your buy NAV after that purchase. "
                       "**Lowest value** is what that instalment was worth on that day.")
            figi = go.Figure()
            figi.add_trace(go.Bar(x=pd.to_datetime(inst["nav_date"]), y=inst["return_pct"], name="Return % now",
                                  marker_color=["#16a34a" if v >= 0 else "#dc2626" for v in inst["return_pct"]],
                                  customdata=inst[["Fund", "amount", "current_value"]].to_numpy(),
                                  hovertemplate="%{x|%d-%b-%Y}<br>%{customdata[0]}<br>Buy ₹%{customdata[1]:,.0f}"
                                                " → now ₹%{customdata[2]:,.0f}<br>Return %{y:.2f}%<extra></extra>"))
            figi.add_trace(go.Scatter(x=pd.to_datetime(inst["nav_date"]), y=inst["worst_fall_pct"],
                                      mode="markers", name="Worst fall % after buy",
                                      marker=dict(color="#f59e0b", size=5, symbol="triangle-down"),
                                      hovertemplate="%{x|%d-%b-%Y}<br>Worst fall %{y:.2f}%<extra></extra>"))
            figi.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0), yaxis_ticksuffix="%",
                               hovermode="closest", legend=dict(orientation="h", y=-0.2), bargap=0.1)
            st.plotly_chart(figi, width="stretch")
            below = int(inst["below_cost_now"].sum())
            st.caption(f"{len(inst)} instalments. {below} are below their buy NAV now. "
                       f"{int((inst['worst_fall_pct'] < 0).sum())} went below their buy NAV at some time.")
            sty, _ = inst_table(inst, ["Fund", "plan", "nav_date", "amount", "nav", "current_value", "gain",
                                       "return_pct", "cagr_pct", "lowest_value", "worst_fall_pct", "lowest_on",
                                       "days_below_cost", "below_cost_now"])
            st.dataframe(sty, width="stretch", hide_index=True, height=420)


# ------------------------------------------------------- transactions ------
with tab_tx:
    if not active:
        st.info("No transactions yet.")
    else:
        fsel = st.multiselect("Filter by fund", sorted(INST["Fund"].unique()))
        sub = INST[INST["Fund"].isin(fsel)] if fsel else INST
        sty, view = inst_table(sub, ["Fund", "plan", "kind", "order_date", "nav_date", "amount", "nav", "units",
                                     "cum_units", "cum_invested", "current_value", "gain", "return_pct",
                                     "cagr_pct", "lowest_value", "worst_fall_pct", "lowest_on",
                                     "below_cost_now"])
        st.dataframe(sty, width="stretch", hide_index=True, height=560)
        st.download_button("⬇️ Download CSV", view.to_csv(index=False).encode("utf-8"),
                           file_name=f"{pf['name']}_transactions.csv", mime="text/csv")


# ------------------------------------------------------------ compare ------
with tab_cmp:
    st.markdown("Compare portfolios side by side. All use the valuation date in the sidebar. "
                "Save a portfolio first to see it here.")
    cur_label = "\x00open"  # fixed value: the name of the open portfolio can change
    choices = [cur_label] + storage.list_portfolios()
    names = {cur_label: "Open portfolio (now)"}
    picks = st.multiselect("Portfolios to compare", choices, default=choices[:2], key="cmp_picks",
                           format_func=lambda c: names.get(c, c))
    if not picks:
        st.info("Select one or more portfolios.")
    else:
        comp = {}
        with st.spinner("Calculating..."):
            for p in picks:
                try:
                    pfx = pf if p == cur_label else storage.load_portfolio(p)
                except (OSError, ValueError) as e:
                    st.error(f"{p}: cannot open file ({e}).")
                    continue
                comp[names.get(p, p)] = compute(pfx, as_of)
        rows = []
        for p, cx in comp.items():
            if not cx["active"]:
                rows.append({"Portfolio": p, "Funds": len(cx["results"])})
                continue
            rk, pm, b = cx["risk"], cx["pnl"], cx["bench"]
            inv, val = cx["total_inv"], cx["total_val"]
            rows.append({
                "Portfolio": p, "Funds": len(cx["active"]), "First buy": cx["first_buy"],
                "Invested (₹)": inv, "Value (₹)": val, "Gain (₹)": val - inv,
                "Absolute return %": (val / inv - 1) * 100 if inv else None,
                "XIRR %": cx["xirr"] * 100 if cx["xirr"] is not None else None,
                "Benchmark XIRR %": b["xirr"] * 100 if b and b["xirr"] is not None else None,
                "TWR (annual) %": rk["twr_ann"] * 100 if rk.get("twr_ann") is not None else None,
                "Max drawdown %": rk["max_drawdown"] * 100 if rk else None,
                "Volatility %": rk["volatility"] * 100 if rk.get("volatility") else None,
                "Lowest P&L (₹)": pm.get("worst_pnl"), "Lowest P&L %": pm.get("worst_pnl_pct"),
                "Biggest fall from peak gain (₹)": pm.get("biggest_fall"),
                "Time in loss %": pm.get("loss_days_pct"),
            })
        ctbl = pd.DataFrame(rows)
        st.dataframe(styled(ctbl,
                            money=["Invested (₹)", "Value (₹)", "Gain (₹)", "Lowest P&L (₹)",
                                   "Biggest fall from peak gain (₹)"],
                            pcts=[c for c in ctbl.columns if c.endswith("%")], dates=["First buy"],
                            signed=["Gain (₹)", "Absolute return %", "XIRR %", "Lowest P&L (₹)"]),
                     width="stretch", hide_index=True)

        what = st.radio("Chart", ["Value", "Invested", "P&L (₹)", "P&L %", "Drawdown % (time-weighted)"],
                        horizontal=True, key="cmp_chart")
        figc = go.Figure()
        for p, cx in comp.items():
            s = cx["series"]
            if s.empty:
                continue
            if what == "Value":
                y = s["Value"]
            elif what == "Invested":
                y = s["Invested"]
            elif what == "P&L (₹)":
                y = s["Value"] - s["Invested"]
            elif what == "P&L %":
                y = (s["Value"] / s["Invested"] - 1) * 100
            else:
                y = cx["risk"]["drawdown"] * 100 if cx["risk"] else None
            if y is not None:
                figc.add_trace(go.Scatter(x=y.index, y=y, name=p))
        money_chart = what in ("Value", "Invested", "P&L (₹)")
        figc.update_layout(hovermode="x unified", height=430, margin=dict(l=0, r=0, t=10, b=0),
                           yaxis_tickprefix="₹" if money_chart else "",
                           yaxis_ticksuffix="" if money_chart else "%",
                           yaxis_tickformat=",.0f" if money_chart else ",.1f",
                           legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(figc, width="stretch")

        bar_cols = [c for c in ["XIRR %", "Benchmark XIRR %", "TWR (annual) %"] if c in ctbl.columns]
        if bar_cols:
            bars = ctbl.melt(id_vars="Portfolio", value_vars=bar_cols, var_name="Measure", value_name="%")
            figb = px.bar(bars, x="Portfolio", y="%", color="Measure", barmode="group", text_auto=".2f")
            figb.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=-0.2))
            st.plotly_chart(figb, width="stretch")
