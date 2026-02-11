import pandas as pd
import re
import os
from fuzzywuzzy import fuzz

# Configuration

INPUT_FILE = os.path.join("input_data", "presales_data_sample.csv")
OUTPUT_DIR = "output_data"
MATCHED_OUTPUT = os.path.join(OUTPUT_DIR, "matched_companies.csv")
QC_OUTPUT = os.path.join(OUTPUT_DIR, "qc_report.txt")

# Weights — tuned after iteration 1 analysis
WEIGHT_NAME = 0.60
WEIGHT_COUNTRY = 0.15
WEIGHT_REGION = 0.05
WEIGHT_CITY = 0.10
WEIGHT_POSTCODE = 0.05
WEIGHT_STREET = 0.05

# Minimum score to accept a match
MIN_MATCH_THRESHOLD = 0.40

# Minimum name similarity required
MIN_NAME_SIMILARITY = 0.45

# Helpers

LEGAL_SUFFIXES = re.compile(
    r'\b(inc|incorporated|ltd|limited|llc|llp|plc|corp|corporation|co|company'
    r'|gmbh|ag|sa|srl|sas|pty|pvt|private|public|group|holding|holdings'
    r'|s\.?a\.?|s\.?r\.?l\.?|s\.?p\.?a\.?|e\.?v\.?|b\.?v\.?|n\.?v\.?'
    r'|oy|ab|as|a/s|aps|hf|ehf|kft|zrt|nyrt|d\.?o\.?o\.?|s\.?r\.?o\.?'
    r'|sp\.?\s*z\.?\s*o\.?\s*o\.?)\b\.?',
    re.IGNORECASE
)

def normalize_name(name):
    if not isinstance(name, str) or not name.strip():
        return ""
    name = name.lower().strip()
    name = LEGAL_SUFFIXES.sub("", name)
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _length_penalty(a, b):
    len_a, len_b = len(a.split()), len(b.split())
    if max(len_a, len_b) == 0:
        return 1.0
    ratio = min(len_a, len_b) / max(len_a, len_b)
    return 0.5 + 0.5 * ratio


def name_score(input_name, candidate_name, candidate_legal=None, candidate_commercial=None):
    inp = normalize_name(input_name)
    if not inp:
        return 0.0

    variants = [candidate_name]
    if isinstance(candidate_legal, str) and candidate_legal.strip():
        variants.extend([n.strip() for n in candidate_legal.split("|")])
    if isinstance(candidate_commercial, str) and candidate_commercial.strip():
        variants.extend([n.strip() for n in candidate_commercial.split("|")])

    best = 0.0
    for v in variants:
        nv = normalize_name(v)
        if not nv:
            continue
        s1 = fuzz.token_sort_ratio(inp, nv) / 100
        s2 = fuzz.token_set_ratio(inp, nv) / 100
        s3 = fuzz.ratio(inp, nv) / 100
        
        penalty = _length_penalty(inp, nv)
        s2 = s2 * penalty

        best = max(best, s1, s2, s3)
    return best


def exact_or_empty(a, b):
    if not isinstance(a, str) or not isinstance(b, str):
        return 0.0
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return 0.0
    return 1.0 if a == b else 0.0


def fuzzy_location_score(a, b):
    if not isinstance(a, str) or not isinstance(b, str):
        return 0.0
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = fuzz.ratio(a, b) / 100
    return ratio if ratio > 0.80 else 0.0


def score_candidate(input_row, candidate_row):
    ns = name_score(
        input_row["input_company_name"],
        candidate_row["company_name"],
        candidate_row.get("company_legal_names"),
        candidate_row.get("company_commercial_names"),
    )

    country_s = exact_or_empty(
        str(input_row.get("input_main_country_code", "")),
        str(candidate_row.get("main_country_code", "")),
    )
    region_s = fuzzy_location_score(
        str(input_row.get("input_main_region", "")),
        str(candidate_row.get("main_region", "")),
    )
    city_s = fuzzy_location_score(
        str(input_row.get("input_main_city", "")),
        str(candidate_row.get("main_city", "")),
    )
    postcode_s = exact_or_empty(
        str(input_row.get("input_main_postcode", "")),
        str(candidate_row.get("main_postcode", "")),
    )
    street_s = fuzzy_location_score(
        str(input_row.get("input_main_street", "")),
        str(candidate_row.get("main_street", "")),
    )

    total = (
        WEIGHT_NAME * ns
        + WEIGHT_COUNTRY * country_s
        + WEIGHT_REGION * region_s
        + WEIGHT_CITY * city_s
        + WEIGHT_POSTCODE * postcode_s
        + WEIGHT_STREET * street_s
    )
    return total, ns, country_s, region_s, city_s


def confidence_label(score):
    if score >= 0.70:
        return "High"
    elif score >= 0.50:
        return "Medium"
    else:
        return "Low"


# Main matching logic

def run_matching(df):
    grouped = df.groupby("input_row_key")
    results = []

    for key, group in grouped:
        input_info = group.iloc[0]

        scored = []
        for _, cand in group.iterrows():
            total, ns, cs, rs, cis = score_candidate(input_info, cand)
            scored.append((total, ns, cand))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

        best_score, best_ns, best_row = None, 0.0, None
        matched = False
        for total, ns, cand in scored:
            if total >= MIN_MATCH_THRESHOLD and ns >= MIN_NAME_SIMILARITY:
                best_score, best_ns, best_row = total, ns, cand
                matched = True
                break

        if not matched:
            best_score, best_ns, best_row = scored[0]

        note_parts = []
        if matched:
            if best_ns >= 0.90:
                note_parts.append("Strong name match")
            elif best_ns >= 0.70:
                note_parts.append("Good fuzzy name match")
            else:
                note_parts.append("Moderate name match")
        else:
            if scored[0][1] < MIN_NAME_SIMILARITY:
                note_parts.append(f"Name similarity too low ({scored[0][1]:.2f})")
            else:
                note_parts.append("Below score threshold")

        results.append({
            "input_row_key": key,
            "input_company_name": input_info["input_company_name"],
            "input_country": input_info.get("input_main_country", ""),
            "input_city": input_info.get("input_main_city", ""),
            "matched_company_name": best_row["company_name"] if matched else "",
            "matched_veridion_id": best_row["veridion_id"] if matched else "",
            "matched_country": best_row.get("main_country", "") if matched else "",
            "matched_city": best_row.get("main_city", "") if matched else "",
            "matched_website": best_row.get("website_url", "") if matched else "",
            "match_score": round(best_score, 4),
            "name_similarity": round(best_ns, 4),
            "match_confidence": confidence_label(best_score) if matched else "Unmatched",
            "notes": " | ".join(note_parts),
        })

    return pd.DataFrame(results)


# QC Checks

def run_qc(matched_df, full_df):
    lines = []
    lines.append("=" * 60)
    lines.append("DATA QUALITY REPORT")
    lines.append("=" * 60)

    total = len(matched_df)
    matched = matched_df[matched_df["match_confidence"] != "Unmatched"]
    unmatched = matched_df[matched_df["match_confidence"] == "Unmatched"]
    lines.append(f"\nTotal input companies:   {total}")
    lines.append(f"Matched:                 {len(matched)} ({len(matched)/total*100:.1f}%)")
    lines.append(f"Unmatched:               {len(unmatched)} ({len(unmatched)/total*100:.1f}%)")

    # Confidence breakdown
    lines.append("\nMatch Confidence Breakdown:")
    for level in ["High", "Medium", "Low", "Unmatched"]:
        count = len(matched_df[matched_df["match_confidence"] == level])
        lines.append(f"  {level:12s}: {count:4d} ({count/total*100:.1f}%)")

    # Score distribution
    scores = matched_df["match_score"]
    lines.append(f"\nScore Statistics:")
    lines.append(f"  Mean:   {scores.mean():.4f}")
    lines.append(f"  Median: {scores.median():.4f}")
    lines.append(f"  Min:    {scores.min():.4f}")
    lines.append(f"  Max:    {scores.max():.4f}")

    matched_ids = set(matched["matched_veridion_id"])
    matched_rows = full_df[full_df["veridion_id"].isin(matched_ids)].drop_duplicates(subset="veridion_id")

    lines.append(f"\n{'=' * 60}")
    lines.append("DATA ATTRIBUTE QUALITY (on matched records)")
    lines.append(f"{'=' * 60}")
    n_matched = len(matched_rows)

    key_fields = [
        "company_name", "website_url", "primary_phone", "primary_email",
        "main_country", "main_city", "main_region", "main_postcode",
        "main_street", "year_founded", "revenue", "employee_count",
        "naics_2022_primary_label", "short_description",
    ]

    lines.append(f"\nField Completeness ({n_matched} matched records):")
    for field in key_fields:
        if field in matched_rows.columns:
            non_null = matched_rows[field].notna().sum()
            non_empty = matched_rows[field].apply(
                lambda x: bool(str(x).strip()) if pd.notna(x) else False
            ).sum()
            pct = non_empty / n_matched * 100 if n_matched else 0
            lines.append(f"  {field:30s}: {non_empty:4d}/{n_matched} ({pct:5.1f}%)")

    dup_matches = matched.groupby("matched_veridion_id").filter(lambda g: len(g) > 1)
    if len(dup_matches) > 0:
        dup_ids = dup_matches["matched_veridion_id"].unique()
        lines.append(f"\nDuplicate Matches (same Veridion company matched to multiple inputs): {len(dup_ids)} cases")
        for did in dup_ids[:10]:
            rows = dup_matches[dup_matches["matched_veridion_id"] == did]
            inputs = ", ".join(rows["input_company_name"].tolist())
            lines.append(f"  Veridion ID {did}: matched to [{inputs}]")
        if len(dup_ids) > 10:
            lines.append(f"  ... and {len(dup_ids) - 10} more")
    else:
        lines.append("\nDuplicate Matches: None detected")

    country_mismatch = matched[
        (matched["input_country"].str.strip() != "") &
        (matched["matched_country"].str.strip() != "") &
        (matched["input_country"].str.lower() != matched["matched_country"].str.lower())
    ]
    lines.append(f"\nCountry Mismatch (input vs matched): {len(country_mismatch)} records")
    if len(country_mismatch) > 0:
        for _, row in country_mismatch.head(10).iterrows():
            lines.append(
                f"  {row['input_company_name']}: "
                f"input={row['input_country']} → matched={row['matched_country']}"
            )
            
    if "primary_phone" in matched_rows.columns:
        phone_vals = matched_rows["primary_phone"].dropna().astype(str)
        phone_vals = phone_vals[phone_vals.str.strip() != ""]
        bad_phones = phone_vals[~phone_vals.str.match(r'^\+?[\d\s\-\(\)\.]+$')]
        lines.append(f"\nPhone Format Issues: {len(bad_phones)} of {len(phone_vals)} phones look malformed")

    if "website_url" in matched_rows.columns:
        url_vals = matched_rows["website_url"].dropna().astype(str)
        url_vals = url_vals[url_vals.str.strip() != ""]
        bad_urls = url_vals[~url_vals.str.match(r'^https?://')]
        lines.append(f"URL Format Issues: {len(bad_urls)} of {len(url_vals)} URLs missing http(s) prefix")

    if "year_founded" in matched_rows.columns:
        years = pd.to_numeric(matched_rows["year_founded"], errors="coerce").dropna()
        weird_years = years[(years < 1800) | (years > 2026)]
        lines.append(f"Year Founded Anomalies: {len(weird_years)} records outside 1800-2026 range")

    return "\n".join(lines)


# Entry point

def main():
    print("Loading data...")
    df = pd.read_csv(INPUT_FILE, dtype=str, keep_default_na=False)
    print(f"  Rows: {len(df)}  |  Unique inputs: {df['input_row_key'].nunique()}")

    print("\nRunning entity matching...")
    matched_df = run_matching(df)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    matched_df.to_csv(MATCHED_OUTPUT, index=False)
    print(f"  Matched results written to {MATCHED_OUTPUT}")

    print("\nRunning QC checks...")
    qc_report = run_qc(matched_df, df)
    with open(QC_OUTPUT, "w") as f:
        f.write(qc_report)
    print(f"  QC report written to {QC_OUTPUT}")

    print("\n" + qc_report)


if __name__ == "__main__":
    main()
