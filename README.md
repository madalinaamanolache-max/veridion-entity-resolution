# Veridion POC Simulation: Entity Resolution & Data Quality


## Data Overview

**Input:** 592 unique supplier companies from the client, each with up to 5 candidate matches (2,951 rows total, 76 columns).

- **Client-provided fields:** Company name, country, region, city, postcode, street
- **No website or phone** in the client data; matching relies entirely on name + location
- **Candidate fields:** Full Veridion company profiles: name, legal/commercial aliases, address, phone, email, website, industry codes, revenue, employee count, descriptions, social media, and more

## Approach

### Matching Algorithm

Weighted scoring system across 2 dimensions (since only name and location are available in the input):

| Factor | Weight | Method |
|--------|--------|--------|
| Company name similarity | 60% | Fuzzy matching (token_sort_ratio, token_set_ratio with length penalty, Levenshtein ratio) across primary name + legal + commercial aliases |
| Country | 15% | Exact match on country code |
| City | 10% | Fuzzy match (>80% threshold) |
| Region | 5% | Fuzzy match (>80% threshold) |
| Postcode | 5% | Exact match |
| Street | 5% | Fuzzy match (>80% threshold) |

**Additional safeguards:**
- **Name gate:** Minimum name similarity of 0.45 required regardless of total score — prevents location-only matches from accepting poor name matches
- **Fall-through selection:** If the highest scoring candidate fails the name gate, the algorithm tries the next candidate until one passes both gates
- **Tie-breaking:** When candidates tie on total score, the one with higher name similarity wins

### Name Normalization

Before comparing, company names are cleaned:
- Lowercased
- ~40 legal suffixes stripped (Inc, Ltd, GmbH, S.A., Pty, AS, ApS, etc.)
- Punctuation removed
- Whitespace collapsed

Names are compared against all available variants: `company_name`, `company_legal_names` (pipe-separated), and `company_commercial_names` (pipe-separated).

## Results

### Final Numbers (Iteration 3)

| Metric | Value |
|--------|-------|
| **Matched** | **583 / 592 (98.5%)** |
| High confidence (score ≥ 0.70) | 450 (76.0%) |
| Medium confidence (0.50–0.69) | 114 (19.3%) |
| Low confidence (0.40–0.49) | 19 (3.2%) |
| Unmatched | 9 (1.5%) |
| Mean score | 0.7987 |

### Unmatched Records

9 inputs could not be matched. Root causes:

- **No viable candidates in pool (4):** Veridion's engine returned unrelated companies. Examples: HEWLETT-PACKARD NORGE AS got candidates like "ThinkEV" and "Tiny Elephant"; TD SYNNEX Denmark ApS got a dog kennel and a wine shop.
- **Complex input names (3):** Names with "filial af" (branch of) suffixes or ".com" fragments that dilute fuzzy matching scores.
- **Weak name overlap (2):** Vertiv variants where candidates scored just below thresholds.

### Data Quality Summary (on matched records)

| Field | Completeness |
|-------|-------------|
| company_name | 100.0% |
| main_country | 98.6% |
| main_region | 96.8% |
| main_city | 95.4% |
| short_description | 88.9% |
| naics_2022_primary_label | 83.1% |
| primary_phone | 78.8% |
| website_url | 77.2% |
| primary_email | 62.1% |
| employee_count | 60.7% |
| revenue | 58.4% |
| year_founded | 50.6% |

**Other QC findings:**
- 45 country mismatches between input and match (mostly multinational subsidiaries)
- 16 duplicate matches (same Veridion entity matched to multiple inputs, some legitimate, some flagged)
- 0 phone format issues, 0 URL format issues
- 2 year_founded anomalies (outside 1800–2026)

## Iterations

The algorithm went through 4 iterations. Full details are in [DECISIONS_LOG.md](DECISIONS_LOG.md). Summary:

| Iter | Change | Match Rate | High Conf | Outcome |
|------|--------|-----------|-----------|---------|
| 1 | Initial algorithm | 100% | 83.4% | Inflated - accepted bad matches (dog kennels, unrelated companies) |
| 2 | Length penalty + name gate + tie breaking | 96.3% | 76.0% | Rejected poor matches, but also blocked some legitimate matches (Pelatro bug) |
| 3 | Fall-through fix | **98.5%** | **76.0%** | Recovered legitimate matches while keeping poor matches rejected |
| 4 | Filial/TLD normalization | 99.0% | 76.4% | **Reverted** - recovered matches were false positives (TCS→shoe company, AmEx→steakhouse) |

**Key takeaway:** Iteration 1's 100% match rate looked better on paper but included false positives. Iteration 3's 98.5% is more trustworthy and the 9 gaps are honest "we couldn't find this" rather than silent errors.

## Observations & Recommendations

### For the Client
- **Phone and website data are well-populated** (79% and 77%) — usable for supplier outreach and verification
- **Industry classification (NAICS) covers 83%** of matched records — sufficient for spend categorization
- **Revenue and employee data** are sparser (58% and 61%) — supplemental sources may be needed for complete supplier profiling
- **45 country mismatches** should be manually reviewed — many are multinational parents vs. local subsidiaries, which matters for procurement contracts

### For Veridion
- **Legal name alias contamination:** Some candidates have legal names that belong to entirely different entities (e.g., "P o STER ART" has legal name "WIX Amazon Web Services Inc."). This causes false positive matches for well-known brands. Validating legal aliases against the primary company identity would improve matching accuracy.
- **Candidate pool gaps:** For 4 of the 9 unmatched inputs, all 5 candidates were completely unrelated. The entity resolution engine may need broader coverage or fallback strategies for less common company names.
