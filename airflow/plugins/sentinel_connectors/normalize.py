"""Normalisation of heterogeneous feeds into the canonical daily-signal schema.

Canonical record: observed_on, region_id (FIPS), disease_code, and one or more of
cases, ed_visits, admissions, deaths, positivity, otc_sales, wastewater.

Quality rules are applied here; failing rows are returned separately and
written to the quarantine zone with the reason, never silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

CANONICAL = ["observed_on", "region_id", "disease_code", "cases", "ed_visits", "admissions", "deaths",
             "positivity", "otc_sales", "wastewater"]

# NNDSS condition labels -> SentinelHealth disease codes.
NNDSS_CONDITIONS = {
    "Measles, Indigenous": "MEASLES",
    "Measles, Imported": "MEASLES",
    "Dengue": "DENGUE",
    "Dengue virus infections, Dengue": "DENGUE",
    "Salmonellosis (excluding Salmonella Typhi infection and Salmonella Paratyphi infection)": "FOODBORNE",
    "Shiga toxin-producing Escherichia coli": "FOODBORNE",
    "Influenza-associated pediatric mortality": "INFLUENZA",
}

STATE_FIPS_PREFIX = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11",
    "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30",
    "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}


@dataclass
class NormalizeResult:
    valid: pd.DataFrame
    rejected: pd.DataFrame
    stats: dict = field(default_factory=dict)


def validate(df: pd.DataFrame, known_regions: set[str] | None = None,
             known_diseases: set[str] | None = None) -> NormalizeResult:
    df = df.copy()
    for col in CANONICAL:
        if col not in df:
            df[col] = None
    parsed = pd.to_datetime(df["observed_on"], errors="coerce")
    df["observed_on"] = parsed.dt.date
    reasons = pd.Series("", index=df.index)
    reasons[parsed.isna()] += "bad_date;"
    reasons[parsed > pd.Timestamp.today().normalize() + pd.Timedelta(days=1)] += "future_date;"
    if known_regions is not None:
        reasons[~df["region_id"].isin(known_regions)] += "unknown_region;"
    if known_diseases is not None:
        reasons[~df["disease_code"].isin(known_diseases)] += "unknown_disease;"
    for col in ["cases", "ed_visits", "admissions", "deaths", "otc_sales", "wastewater"]:
        vals = pd.to_numeric(df[col], errors="coerce")
        reasons[vals < 0] += f"negative_{col};"
        df[col] = vals
    pos = pd.to_numeric(df["positivity"], errors="coerce")
    pos = pos.where(pos <= 1, pos / 100)  # some feeds send percentages
    reasons[(pos < 0) | (pos > 1)] += "bad_positivity;"
    df["positivity"] = pos
    metric_cols = ["cases", "ed_visits", "admissions", "deaths", "positivity", "otc_sales", "wastewater"]
    reasons[df[metric_cols].isna().all(axis=1)] += "no_metrics;"
    dup = df.duplicated(subset=["observed_on", "region_id", "disease_code"], keep="last")
    reasons[dup] += "duplicate;"
    bad = reasons != ""
    rejected = df[bad].assign(reject_reason=reasons[bad])
    valid = df[~bad][CANONICAL]
    return NormalizeResult(valid, rejected, {"input": len(df), "valid": len(valid), "rejected": int(bad.sum())})


def normalize_nwss(records: list[dict], county_fips_by_sewershed: dict[str, str] | None = None) -> pd.DataFrame:
    """NWSS: percentile/concentration per sewershed -> CLI wastewater index per county."""
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=CANONICAL)
    df["region_id"] = df.get("county_fips", pd.Series(dtype=str)).astype(str).str.split(",").str[0].str.zfill(5)
    if county_fips_by_sewershed:
        df["region_id"] = df["wwtp_id"].map(county_fips_by_sewershed).fillna(df["region_id"])
    df["wastewater"] = pd.to_numeric(df.get("percentile"), errors="coerce")
    out = df.assign(observed_on=df["date_end"], disease_code="CLI")
    return out.groupby(["observed_on", "region_id", "disease_code"], as_index=False)["wastewater"].mean()


def normalize_healthdata_hospital(records: list[dict], state_to_region: dict[str, str]) -> pd.DataFrame:
    """HealthData.gov state hospital timeseries -> admissions for INFLUENZA and CLI at a representative region."""
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=CANONICAL)
    df["region_id"] = df["state"].map(state_to_region)
    flu = df.assign(disease_code="INFLUENZA",
                    admissions=pd.to_numeric(df.get("previous_day_admission_influenza_confirmed"), errors="coerce"))
    cli = df.assign(disease_code="CLI", admissions=pd.to_numeric(
        df.get("previous_day_admission_adult_covid_confirmed"), errors="coerce").fillna(0) + pd.to_numeric(
        df.get("previous_day_admission_pediatric_covid_confirmed"), errors="coerce").fillna(0))
    out = pd.concat([flu, cli]).rename(columns={"date": "observed_on"})
    return out[["observed_on", "region_id", "disease_code", "admissions"]].dropna(subset=["region_id"])


def normalize_nndss(records: list[dict], state_to_region: dict[str, str]) -> pd.DataFrame:
    """NNDSS weekly counts -> daily signal on the MMWR week's end date (counts attributed to the Saturday)."""
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=CANONICAL)
    label = df.get("label", df.get("disease"))
    df["disease_code"] = label.map(NNDSS_CONDITIONS)
    df = df.dropna(subset=["disease_code"])
    state = df.get("states", df.get("reporting_area")).str.upper().map(_state_code)
    df["region_id"] = state.map(state_to_region)
    year = pd.to_numeric(df["year"], errors="coerce")
    week = pd.to_numeric(df["week"], errors="coerce")
    df["observed_on"] = [_mmwr_week_end(int(y), int(w)) if pd.notna(y) and pd.notna(w) else None
                         for y, w in zip(year, week)]
    df["cases"] = pd.to_numeric(df.get("m1", df.get("current_week")), errors="coerce")
    return df[["observed_on", "region_id", "disease_code", "cases"]].dropna(subset=["region_id"])


def _state_code(name: str | None) -> str | None:
    if not isinstance(name, str):
        return None
    if len(name) == 2:
        return name
    from_name = {"TEXAS": "TX", "NEW YORK": "NY", "CALIFORNIA": "CA", "FLORIDA": "FL", "ILLINOIS": "IL",
                 "PUERTO RICO": "PR", "GEORGIA": "GA", "ARIZONA": "AZ", "WASHINGTON": "WA"}
    return from_name.get(name)


def _mmwr_week_end(year: int, week: int):
    jan4 = pd.Timestamp(year=year, month=1, day=4)
    week1_start = jan4 - pd.Timedelta(days=(jan4.dayofweek + 1) % 7)  # Sunday on/before Jan 4
    return (week1_start + pd.Timedelta(weeks=week - 1, days=6)).date()
