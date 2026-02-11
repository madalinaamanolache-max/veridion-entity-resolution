# Decision Log

This document tracks every design choice, observation, and iteration made during the project.

---

## Iteration 1: Initial Matching Algorithm

### Data Assessment

Before writing any code, I examined the input CSV structure:

- **592 unique input companies**, each with **5 candidate matches** from Veridion's engine (2,951 rows total).
- **Input fields available:** `input_company_name`, `input_main_country_code`, `input_main_country`, `input_main_region`, `input_main_city`, `input_main_postcode`, `input_main_street`, `input_main_street_number`.
- **Candidate fields available:** 76 columns including company name, legal/commercial name aliases, full address, phone, email, website, industry codes, descriptions, and more.


### Initial Weight Design

| Factor | Weight | Rationale |
|--------|--------|-----------|
| Company name similarity | 60% | Primary identifier — most reliable signal. Compared against `company_name`, `company_legal_names`, and `company_commercial_names`. |
| Country match | 15% | Strong structural signal. |
| City match | 10% | Narrows geography within a country. |
| Region match | 5% | Useful but cities are more specific. |
| Postcode match | 5% | Exact match only - when available, a strong confirming signal. |
| Street match | 5% | Rarely populated in input but helps when present. |

### Name Matching Strategy

- **Normalization:** Lowercase, strip ~40 legal suffixes (Inc, Ltd, GmbH, S.A., etc.), remove punctuation, collapse whitespace.
- **Comparison methods (best of 3):**
  - `fuzz.token_sort_ratio` — handles word reordering ("Smith & Jones" vs "Jones and Smith")
  - `fuzz.token_set_ratio` — handles extra/missing words ("Acme Corp Industries" vs "Acme Corp")
  - `fuzz.ratio` — straight Levenshtein for short, similar names
- **Multi-variant matching:** Each candidate can have up to 3 name fields (`company_name`, `company_legal_names`, `company_commercial_names`). The legal/commercial fields may contain multiple pipe-separated aliases. We compare against all variants and take the best score.

### Location Matching Strategy

- **Country:** Exact match on country code (case-insensitive). Binary — either it matches or it doesn't.
- **City/Region/Street:** Fuzzy comparison using `fuzz.ratio` with a cutoff at 0.80 to avoid spurious matches on short strings.
- **Postcode:** Exact match only - partial postcode matches are unreliable.

### Threshold

- **Minimum match score: 0.35** — below this, the input is marked as unmatched.
- Chosing 0.35 as a starting point because name similarity alone (60% weight) with a moderate fuzzy score (~0.60) yields 0.36, which should clear the bar when paired with at least one location match.

### Confidence Labels

- **High:** score >= 0.70
- **Medium:** score >= 0.50
- **Low:** score >= 0.35
- **Unmatched:** score < 0.35

---

## Iteration 1: Results

### Summary

| Metric | Value |
|--------|-------|
| Total input companies | 592 |
| Matched | 592 (100%) |
| Unmatched | 0 (0%) |
| High confidence (≥0.70) | 494 (83.4%) |
| Medium confidence (0.50–0.69) | 97 (16.4%) |
| Low confidence (0.35–0.49) | 1 (0.2%) |
| Mean score | 0.8359 |
| Median score | 0.8500 |

### What Went Well

1. **High match rate.** 100% of inputs found a candidate above threshold. 83% are High confidence.
2. **Multi-variant name matching paid off.** Comparing against `company_legal_names` and `company_commercial_names` in addition to `company_name` caught cases where the candidate's trading name differs from the legal name the client used. Example: "Google Cloud EMEA Limited" matched via the legal name alias "Google Cloud EMEA Ltd." on a candidate whose primary name was "ISP Cloud Services Inc."
3. **Location weighting kept most matches sensible.** Country match (15% weight) was enough to prefer a same country candidate over a slightly better name match in the wrong country for most cases.

### Problems Discovered

#### 1. `token_set_ratio` inflates scores for subset matches

When the input name is a **superset** of a candidate name's tokens, `token_set_ratio` returns 1.0 (100%) even when the candidate is shorter/more generic. Examples:

| Input | Candidate | token_set_ratio |
|-------|-----------|----------------|
| "google cloud emea" | "google cloud" | 1.00 |
| "accenture services" | "accenture" | 1.00 |

This means a generic "Accenture" in Mauritius scores name_sim=1.0 against "ACCENTURE SERVICES AS" (Norway), the same as "Accenture Norge" (Norway, name_sim=0.75). Combined with country weight, "Accenture Norge" should still win (0.60 + 0.15 = 0.75 vs 0.60 + 0 = 0.60), and it does. But there are edge cases where this inflation masks the real best match.

**Risk:** When 2 candidates both have name_sim=1.0 (via aliases or subset matching) and neither matches on location, the winner is arbitrary (first encountered).

#### 2. Country mismatches: 45 records (7.6%)

Many are **multinational companies** where the client's local subsidiary is in one country but the best Veridion match is the parent/sibling entity in another. Examples:

- ACCENTURE SERVICES AS: input=Norway → matched=Slovakia (legal alias match)
- Google Cloud EMEA Limited: input=Ireland → matched=United States
- ERNST & YOUNG LLP: input=Singapore → matched=United Kingdom
- Kahoot! Denmark ApS: input=Denmark → matched=Norway (parent HQ)

These aren't necessarily wrong. They may be the same corporate entity. But for a procurement use case, the client probably wants the local entity they actually contract with.

#### 3. Some inputs had NO good candidates in the pool

- **"Unit Trust Of Pakistan"** — 5 candidates are completely unrelated (Ministry of Commerce, a university, etc.). Best name_sim was 0.34. Matched anyway because total score (0.554) cleared the 0.35 threshold thanks to country match boosting a bad name match.
- **"TD SYNNEX Denmark ApS"** — 5 candidates are random Danish companies (a dog kennel, a restaurant, a wine shop).

#### 4. Duplicate matches: 12 cases

Same Veridion company matched to multiple input rows. Two categories:
- **Legitimate duplicates:** Client submitted the same company twice with different formatting (e.g., "Nets Denmark A/S" and "NETS DANMARK A/S"). These are correct: same company, different input strings.
- **Questionable duplicates:** "TELENOR ASA" and "TELENOR REAL ESTATE AS" both matched to the same Veridion entity. These are likely different subsidiaries that should resolve to different entities.

### Data Quality Findings (on matched records)

| Field | Completeness |
|-------|-------------|
| company_name | 100.0% |
| main_country | 99.1% |
| main_region | 97.4% |
| main_city | 95.7% |
| short_description | 90.3% |
| main_postcode | 89.8% |
| naics_2022_primary_label | 83.1% |
| main_street | 81.6% |
| primary_phone | 78.8% |
| website_url | 77.1% |
| primary_email | 62.8% |
| employee_count | 61.4% |
| revenue | 57.9% |
| year_founded | 49.3% |

**Other QC findings:**
- Phone format issues: 0 (all phones well-formatted)
- URL format issues: 0 (all URLs have http/https prefix)
- Year founded anomalies: 2 records outside 1800–2026 range

---

## Iteration 2: 3 Algorithm Fixes

Based on the problems discovered in iteration 1, I made 3 simultaneous changes and re-ran:

### Change 1: Length penalty on `token_set_ratio`

**Problem:** `token_set_ratio("accenture services", "accenture")` = 1.0 because "accenture" is a full subset of the input tokens. This inflates scores for short/generic candidate names.

**Fix:** Multiply `token_set_ratio` by a length penalty based on the word-count ratio between the two names:
```
penalty = 0.5 + 0.5 * (min_words / max_words)
```
- Same length → penalty = 1.0 (no change)
- 1 word vs 3 words → penalty = 0.67
- 1 word vs 2 words → penalty = 0.75

**Effect:** "accenture" vs "accenture services" now scores 0.75 instead of 1.0. This makes `token_sort_ratio` and `fuzz.ratio` more competitive, giving stricter matches a chance to win.

### Change 2: Minimum name similarity gate

**Problem:** "Unit Trust Of Pakistan" matched to "M.H. Ghanchi International" (name_sim=0.34) purely because country match boosted the total score above the threshold. The match is clearly wrong.

**Fix:** Added a second gate: `MIN_NAME_SIMILARITY = 0.45`. Even if the total weighted score clears the threshold, the name similarity alone must also be at least 0.45. Raised the overall threshold from 0.35 to 0.40 as well.

### Change 3: Tie-breaking by name similarity

**Problem:** When two candidates had the same total score (e.g., both with name_sim=1.0 in wrong countries), the winner was arbitrary (first row encountered in the CSV).

**Fix:** Sort candidates by `(total_score, name_similarity)` descending. When totals tie, the candidate with the higher name similarity wins.

### Iteration 2 Results

| Metric | Iter 1 | Iter 2 | Change |
|--------|--------|--------|--------|
| Matched | 592 (100%) | 570 (96.3%) | -22 |
| High confidence | 494 (83.4%) | 450 (76.0%) | -44 |
| Medium confidence | 97 (16.4%) | 106 (17.9%) | +9 |
| Low confidence | 1 (0.2%) | 14 (2.4%) | +13 |
| Unmatched | 0 (0.0%) | 22 (3.7%) | +22 |
| Mean score | 0.8359 | 0.8003 | -0.036 |

The stricter algorithm correctly rejected 22 bad matches (including "Unit Trust Of Pakistan" and "TD SYNNEX Denmark ApS"). But it also rejected some that should have matched, like "PELATRO LIMITED" whose best Pelatro candidate (India, name_sim=1.0) lost to "Aspects of History" (UK, name_sim=0.40) on total score, then failed the name gate.

### Bug Discovered: Name gate blocking fall-through

The name gate checked only the TOP candidate by total score. When that candidate had a high location score but low name similarity, the algorithm rejected it, but never looked at the next candidate down, which might have had a perfect name match.

Example: PELATRO LIMITED (input country=UK)
- Candidate "Aspects of History" (UK): total=0.64 (country match), name_sim=0.40 → **wins on total but fails name gate**
- Candidate "Pelatro" (India): total=0.60 (no country match), name_sim=1.0 → **would pass both gates but never reached**

---

## Iteration 3: Fall-Through Fix

**Change:** Instead of only evaluating the top candidate, walk down the sorted list and pick the **first candidate that passes BOTH gates** (total ≥ 0.40 AND name_sim ≥ 0.45). Only mark as unmatched if no candidate passes both.

### Iteration 3 Results

| Metric | Iter 1 | Iter 2 | Iter 3 | Change (2→3) |
|--------|--------|--------|--------|---------------|
| Matched | 592 (100%) | 570 (96.3%) | 583 (98.5%) | +13 |
| High confidence | 494 (83.4%) | 450 (76.0%) | 450 (76.0%) | — |
| Medium confidence | 97 (16.4%) | 106 (17.9%) | 114 (19.3%) | +8 |
| Low confidence | 1 (0.2%) | 14 (2.4%) | 19 (3.2%) | +5 |
| Unmatched | 0 (0.0%) | 22 (3.7%) | 9 (1.5%) | -13 |
| Mean score | 0.8359 | 0.8003 | 0.7987 | — |
| Country mismatches | 45 | 46 | 45 | -1 |
| Duplicate matches | 12 | 15 | 16 | +1 |

**Recovered matches:** 13 companies that were wrongly unmatched in iteration 2 are now correctly matched via fall-through. Examples:
- PELATRO LIMITED → Pelatro (India, name_sim=1.0)
- AMAZON WEB SERVICES EMEA SARL, NORWEGIAN BRANCH → Amazon Web Services EMEA (name_sim=0.79)
- DK HOSTMASTER A/S → Hostmaster (Greece, name_sim=0.67)

**Remaining 9 unmatched:** These are genuinely hard cases where either (a) Veridion's engine returned no relevant candidates at all, or (b) the input name is too complex/different to match:
- HEWLETT-PACKARD NORGE AS — 0 relevant candidates (ThinkEV, Tiny Elephant, etc.)
- TD SYNNEX Denmark ApS — 0 relevant candidates (dog kennel, restaurant, etc.)
- SALESFORCE.COM SINGAPORE PTE. LTD. — ".com" in name hurts fuzzy matching
- TATA CONSULTANCY SERVICES LIMITED, FILIAL AF... — extremely long name dilutes scores
- American Express Europe Denmark, filial af... — same issue with "filial af" suffix
- DRAKA NORSK KABEL AS, Aon Assessment Denmark A/S, Vertiv variants — weak candidates

---

## Observations on Veridion Data Quality

During manual spot-checks of candidates, I discovered issues with legal name aliases in Veridion's data:

### Legal name alias contamination

Some candidate companies have legal names that belong to completely different entities:

| Candidate (primary name) | Legal name alias | Likely explanation |
|--------------------------|-----------------|-------------------|
| P o STER ART | WIX Amazon Web Services Inc. | Poster art business registered with AWS/WIX infrastructure as part of legal name |
| TKBEL | Amazon Web Service EMEA SARL | Unrelated company with AWS-derived legal registration |
| Bon Plan Sur Mesure | Google Cloud EMEA Limited | Similar — legal name leaking from infrastructure provider |

This causes the algorithm to match "AMAZON WEB SERVICES, INC." to "P o STER ART" (a poster shop) via its misleading legal alias. These false positives are particularly dangerous because the legal name match looks perfect.

---

## Iteration 4 (Reverted): Filial/TLD Normalization

### Hypothesis

Several unmatched inputs contained Scandinavian legal patterns that bloated the name and tanked fuzzy scores:
- "TATA CONSULTANCY SERVICES LIMITED, **filial af** TATA CONSULTANCY SERVICES NEDERLAND B.V." — "filial af" means "branch of" in Danish/Norwegian; everything after it is the parent company name, essentially doubling the string.
- "SALESFORCE**.COM** SINGAPORE PTE. LTD." — ".com" becomes the word "com" after punctuation removal, adding noise.

### Changes

1. Strip "filial af" + everything after it from names before comparison
2. Strip common TLD fragments (com, io, net, org, ai) as noise words

### Results: Worse than #3

| Metric | Iter 3 | Iter 4 |
|--------|--------|--------|
| Matched | 583 (98.5%) | 586 (99.0%) |
| Unmatched | 9 | 6 |

Looked like an improvement (+3 matches). But all 3 recovered matches were **false positives**:

| Input | Matched to | Why it's wrong |
|-------|-----------|----------------|
| TATA CONSULTANCY SERVICES...filial af... | TATA SKO | "Tata Sko" is a shoe company. "tata" is a common word; stripping the filial suffix made the input short enough to fuzzy-match a shoe shop. |
| American Express...filial af... | American Steakhouse | A restaurant in Denmark. The word "american" + country match was enough to clear the gates. |
| SALESFORCE.COM SINGAPORE | DancingMind | Completely unrelated. Barely cleared the 0.45 name gate at 0.46. |

### Why It Failed

The normalization was correct in principle, as "filial af" is noise that should be stripped. But the underlying problem was that **the candidate pools for these inputs didn't contain the right companies**. Stripping the noise made the input names shorter and more generic, which lowered the bar for bad candidates to clear the name gate.

Being honestly **unmatched** is better than being **falsely matched** to a shoe company. A client spotting "Tata Sko" in their TCS supplier record would immediately lose trust in the entire dataset.

### Decision: Reverted

Rolled back to iteration 3. The 9 unmatched records remain unmatched, but this is the correct outcome given the candidate pools available.

---

## Accuracy vs. Match Rate — A Note on Metrics

It's worth noting the tension between **match rate** (how many inputs got a match) and **match accuracy** (how many matches are actually correct).

- **Iteration 1** had the best looking headline number: 100% match rate, 83.4% High confidence. But it included matches like "Unit Trust of Pakistan" → "M.H. Ghanchi International" and "TD SYNNEX" → a dog kennel. These are false positives masquerading as successful matches.
- **Iteration 3 (final)** has a lower match rate (98.5%) and fewer High confidence matches (76.0%). But the matches it does produce are more trustworthy, and the 9 unmatched records are genuinely hard cases where the candidate pool lacked a viable match.

**The iteration 3 results represent the best balance of coverage and accuracy that could be achieved with the available data.**

---

## Final Algorithm Summary

The final algorithm uses:
- **Name similarity (60%):** Fuzzy matching across company name + legal + commercial aliases, with length penalty on `token_set_ratio`
- **Country (15%):** Exact match on country code
- **City (10%):** Fuzzy match with 0.80 cutoff
- **Region (5%):** Fuzzy match with 0.80 cutoff
- **Postcode (5%):** Exact match
- **Street (5%):** Fuzzy match with 0.80 cutoff
- **Name gate:** Minimum name similarity of 0.45 required regardless of total score
- **Fall-through:** If top candidate by total score fails name gate, try next until one passes both gates
- **Tie-breaking:** When total scores tie, prefer higher name similarity

---
