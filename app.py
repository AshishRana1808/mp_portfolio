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
tab_build, tab_result, tab_tx = st.tabs(["🧱 Build portfolio", "📊 Results", "📜 Transactions"])

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
results: list[engine.FundResult] = []
errors: list[str] = []
with st.spinner("Getting NAV data..."):
    for fund in pf["funds"]:
        try:
            meta, nav = cached_nav(fund["code"])
        except NavError as e:
            errors.append(f"{fund['name']}: {e}")
            continue
        results.append(engine.simulate_fund(fund, meta, nav, as_of,
                                            stamp_duty_pct=0.005 if pf.get("stamp_duty") else 0.0))
    bench_nav = None
    try:
        _, bench_nav = cached_nav(pf["benchmark"]["code"])
    except NavError as e:
        errors.append(f"Benchmark: {e}")

active = [r for r in results if not r.transactions.empty]
total_inv = sum(r.invested for r in active)
total_val = sum(r.value for r in active)
all_flows = [fl for r in active for fl in r.flows]
val_date = max((r.valuation_date for r in active if r.valuation_date), default=None)
port_xirr = engine.xirr(all_flows + [(val_date, total_val)]) if active and val_date else None
bench = engine.benchmark_compare(all_flows, bench_nav, as_of) if (bench_nav is not None and all_flows) else None


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

        series = engine.value_series(active, as_of)
        risk = engine.risk_metrics(series)
        first_buy = min(r.transactions["nav_date"].min() for r in active)
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

with tab_tx:
    if not active:
        st.info("No transactions yet.")
    else:
        frames = []
        for r in active:
            t = r.transactions.copy()
            t.insert(0, "Fund", r.name)
            frames.append(t)
        tx = pd.concat(frames).sort_values(["nav_date", "Fund"]).reset_index(drop=True)
        tx = tx.rename(columns={"order_date": "Order date", "nav_date": "NAV date", "kind": "Type",
                                "amount": "Amount (₹)", "nav": "NAV", "units": "Units",
                                "cum_units": "Total units (fund)", "cum_invested": "Total invested (fund)"})
        fsel = st.multiselect("Filter by fund", sorted(tx["Fund"].unique()))
        view = tx[tx["Fund"].isin(fsel)] if fsel else tx
        st.dataframe(view, width="stretch", hide_index=True,
                     column_config={"Amount (₹)": st.column_config.NumberColumn(format="%.2f"),
                                    "NAV": st.column_config.NumberColumn(format="%.4f"),
                                    "Units": st.column_config.NumberColumn(format="%.4f"),
                                    "Total units (fund)": st.column_config.NumberColumn(format="%.4f"),
                                    "Order date": st.column_config.DateColumn(format="DD-MMM-YYYY"),
                                    "NAV date": st.column_config.DateColumn(format="DD-MMM-YYYY")})
        st.download_button("⬇️ Download CSV", view.to_csv(index=False).encode("utf-8"),
                           file_name=f"{pf['name']}_transactions.csv", mime="text/csv")
