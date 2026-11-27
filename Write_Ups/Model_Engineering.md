# Model engineering — Queensland road crash analysis

*Covers the models in `Traffic_Incidents_V6.ipynb` (27 November 2026): what each answers, which algorithm was chosen and why, the alternatives considered, how each is validated, and what limits it. The model register uses the headings of [`ML Model Cheat Sheet.xlsx`](../ML%20Model%20Cheat%20Sheet.xlsx): family, task, algorithm, metrics, advantages and disadvantages. The models sit in CRISP-ML(Q) **Phase 3 · Modelling** and **Phase 4 · Evaluation**. The data preparation behind them is in [`Data_Engineering.md`](Data_Engineering.md).*

---

## Contents

1. [Model register](#1-model-register)
2. [Framing constraints that shape every choice](#2-framing-constraints-that-shape-every-choice)
3. [Severity classifiers](#3-severity-classifiers)
4. [Adjusted-odds model](#4-adjusted-odds-model)
5. [Road-site screening model](#5-road-site-screening-model)
6. [Association rules](#6-association-rules)
7. [Statistical comparison methods](#7-statistical-comparison-methods)
8. [Models considered and not used](#8-models-considered-and-not-used)
9. [Quality gates before any operational use](#9-quality-gates-before-any-operational-use)
10. [Reproducibility](#10-reproducibility)
11. [Experimental design](#11-experimental-design)
12. [References](#12-references)

> **Coverage of the methodology brief.** Method details and formulas: §3.4, §3.6, §4, §5.3, §6. Selection criteria: §2.1 and the "why" in each model section. Supporting material: §1.1 (cheat sheet), §12 (references), and the notebook's figures and exports. Experimental design: §11 (the R1–R7 programme, with results). Evaluation metrics, why chosen and how implemented: §3.6 and §11.3. Descriptive analytics methods and the full experiment log are in [`Analytics_Methods.md`](Analytics_Methods.md).

---

## 1. Model register

| Model | Family | Task | Algorithm | Question it answers | Main metrics | Status |
|---|---|---|---|---|---|---|
| Severity classifier (serious) | Supervised · tree-based and linear | Binary classification | `HistGradientBoostingClassifier`; `LogisticRegression` (L2) | How likely is a serious outcome, given the crash that occurred? | ROC AUC, average precision, Brier skill, reliability | Exploratory. Calibrated, but not ready for operational use. |
| Severity classifier (fatal) | Same | Binary classification, rare class (1.9%) | Same, with a threshold set on the validation year | Which crashes are most likely fatal? | Average precision, precision and recall at threshold, false alerts | Exploratory. About 9 false alerts per correct one. |
| Adjusted odds | Supervised · linear (inferential) | Binary regression | Unpenalised logistic regression with Wald 95% intervals | How is each road user or setting associated with a serious outcome, holding the others constant? | Odds ratios with intervals | In use for description |
| Road-site screening | Probabilistic · empirical Bayes | Ranking and estimation | Beta-binomial excess over stratum expectation, with shrinkage | Which junctions and road links have more serious crashes than their setting predicts? | Two-period persistence, decile calibration | In use for shortlisting. Calibration offset noted (§5). |
| Association rules | Unsupervised · association rule learning | Pattern mining | Apriori (`mlxtend`) | Which pairs of conditions often come with a serious outcome? | Support, confidence, lift | Descriptive. Redundancy filter still to do. |

### 1.1 Cheat-sheet profile of the chosen algorithms

The profile columns are taken from `ML Model Cheat Sheet.xlsx` (sheet *ML Cheat Sheet*). The last column shows how this project's use compares.

| Algorithm | Cheat-sheet metrics | Interpretability | Data size suitability | Training / inference cost | Cheat-sheet disadvantages | How this project fits |
|---|---|---|---|---|---|---|
| Logistic Regression | Accuracy; AUC-ROC; F1 | High | Small / Medium | Low / Low | Poor with non-linear boundaries | About 39k training rows suit it. Non-linearity is tested by benchmarking against gradient boosting, which gains nothing here (§3.7). Accuracy and F1 are replaced by average precision and Brier score because the fatal class is rare (§3.6). |
| Gradient Boosting (scikit-learn histogram variant) | RMSE; MAE; LogLoss | Medium | Medium / Large | Medium / Medium | Slow training; sensitive to outliers | Histogram binning removes the training-time concern (seconds). Targets are binary and the inputs mostly categorical, so outliers are not an issue. Judged on log-loss-family measures (Brier score) and ranking. |
| Apriori (`mlxtend`) | Lift; Confidence | Medium | Medium | Medium / Medium | Slow; many uninteresting rules | Seven fields keep it fast. The "many uninteresting rules" problem is visible, and a redundancy filter is pending (§6). |
| Random Forest (V5, replaced) | OOB Error; AUC-ROC | Medium | Medium / Large | Medium / Medium | Less interpretable; larger models | Replaced. It gave no better ranking than boosting and was used with resampling that hurt it (§3.1). |
| K-Means, DBSCAN (V3–V5, replaced) | Silhouette score; inertia | Medium | Medium | Medium / Medium | Requires K / struggles with varying density | Crash density varies hugely between the city and the bush, which is the stated weakness of both. Replaced by the site-screening model (§5). |
| Empirical-Bayes excess (not on the cheat sheet) | Persistence and calibration across periods | High | Any | Low / Low | Needs a good reference expectation | A road-safety statistical model rather than machine learning. It is included because it ranks sites better than the clustering methods the cheat sheet lists. |

---

## 2. Framing constraints that shape every choice

1. **No operational user or decision is defined yet.** Phase 1 leaves open who would use a prediction, when it would be made and what it would trigger. So every model is chosen for explanation and honest evaluation, not for best-possible accuracy.
2. **The inputs describe the crash after it happened.** Crash nature, movement code (DCA) and unit counts are known only once a crash has occurred. The classifiers therefore estimate severity *given the crash*. They cannot forecast where or when crashes will happen.
3. **No exposure data.** There are no traffic volumes, travel or population, so models compare outcomes among recorded crashes, not risk per trip or per person.
4. **The outcome label drifts.** The hospitalisation share of injury crashes rose from 30.5% to 49.1% over 2001–2024 while the fatal share stayed level ([`Data_Engineering.md`](Data_Engineering.md) §5). Any model that pools years learns that drift. All models are fitted inside the stable window (2020–2024) or use year-specific expectations.
5. **The fatal class is rare.** Fatal crashes are about 1.9% of injury crashes, so accuracy is meaningless for them. Ranking quality (average precision) and the false-alert count are the relevant measures.
6. **Grouped files cannot link to crashes.** Drink-driving, speed, fatigue and driver flags exist only per year × region, so no crash-level model can use them.
7. **The environment is pinned.** Package versions are fixed in the release manifest. Alternatives that need new packages (XGBoost, LightGBM, CatBoost, statsmodels, SHAP) were weighed against that cost.

### 2.1 Selection criteria

Every candidate method was judged against the same seven criteria, which follow from the constraints above.

| # | Criterion | Meaning for this project |
|---|---|---|
| C1 | **Data fit** | Handles about 40–130k rows, mostly categorical inputs (up to 89 levels), a binary rare outcome, and spatial point data |
| C2 | **Effectiveness** | Expected to discriminate or rank well on held-out years; beats a naive baseline |
| C3 | **Interpretability** | Results can be explained to road-safety analysts (coefficients, rules, site lists) |
| C4 | **Calibration** | Produces probabilities or expected counts that mean what they say |
| C5 | **Robustness** | Copes with the rare class, the severity drift and small groups, without fragile tuning |
| C6 | **Cost** | Trains in seconds to minutes on a laptop; reruns cheaply at each data refresh |
| C7 | **Dependency fit** | Available in the pinned environment, or worth adding |

Scoring of the severity-classifier candidates (● strong, ◐ partial, ○ weak):

| Candidate | C1 | C2 | C3 | C4 | C5 | C6 | C7 | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Logistic regression** | ● | ◐ | ● | ● | ● | ● | ● | **Selected**: transparent baseline, equal to boosting in R1 |
| **Histogram gradient boosting** | ● | ● | ◐ | ● | ● | ● | ● | **Selected**: non-linear benchmark |
| Random Forest + SMOTENC (V5) | ◐ | ◐ | ◐ | ○ | ○ | ◐ | ● | Replaced (§3.1) |
| XGBoost / LightGBM / CatBoost | ● | ● | ◐ | ● | ● | ● | ○ | Not needed: same family, new dependency |
| SVM | ○ | ◐ | ○ | ○ | ◐ | ○ | ● | Rejected: one-hot blow-up, no native probabilities, slow at this size |
| KNN | ○ | ○ | ◐ | ○ | ○ | ○ | ● | Rejected: distance is poorly defined on categorical inputs |
| MLP | ◐ | ◐ | ○ | ◐ | ○ | ◐ | ● | Rejected: no expected gain on tabular data; hard to explain |
| Ordinal logistic | ● | ◐ | ● | ● | ◐ | ● | ○ | Deferred: needs statsmodels; two binary models are simpler |

The site-screening and association-rule choices apply the same criteria (§5.1, §6). The descriptive statistical techniques are assessed in [`Analytics_Methods.md`](Analytics_Methods.md) §3.1.

---

## 3. Severity classifiers

### 3.1 What V5 did and why it changed

V5 fitted three four-class Random Forests (80 trees, depth 15, minimum leaf 5) on a stratified sample of 60,000 injury crashes from 2001–2022. Two used SMOTENC oversampling. They were tested on 2023–2025.

| V5 model | Accuracy | Macro F1 | Fatal recall | Fatal precision | Fatal average precision |
|---|---|---|---|---|---|
| Training majority class | 0.318 | 0.121 | 0.000 | — | — |
| Random Forest | 0.499 | 0.274 | 0.000 | — | 0.088 |
| Random Forest + SMOTENC | 0.335 | 0.284 | 0.495 | 0.050 | 0.081 |
| Random Forest + SMOTENC + road context | 0.381 | 0.309 | 0.441 | 0.065 | 0.091 |

V6 replaced them for five reasons:

1. **SMOTENC didn't help.** It moved the default prediction towards the fatal class but lowered fatal average precision (0.081 against 0.088). Synthetic minority rows changed the operating point, not the ranking, and they distort predicted probabilities.
2. **Wrong target.** Four unordered classes ignore that severity is ordered, and the rest of the notebook works with serious-or-not. Macro F1 across four classes was also hard to act on.
3. **Mismatched years.** Training spanned the severity drift, so the training class mix (about 41% hospitalisation) did not match the test years (about 49%).
4. **Unused data.** Only 60,000 of about 260,000 available training rows were used, to keep training time down.
5. **Unused fields.** Unit counts and month, which are available on every crash, were left out.

### 3.2 Target

Two binary targets, each with its own models:

- **Fatal or hospitalisation (serious).** Balanced (about 51%) and matches the severity measure used throughout the notebook. This is a probability model, judged on discrimination and calibration.
- **Fatal.** Rare (about 1.9%) and closest to what a road-safety intervention cares about. This is a ranking-and-alert model, judged on average precision and false alerts.

An ordinal model (proportional-odds logistic regression) was considered. Two binary models are simpler to evaluate, give each outcome its own threshold, and need no extra package.

### 3.3 Data window and split

| Set | Years | Injury crashes | Purpose |
|---|---|---|---|
| Training | 2020–2022 | 38,644 | Fit |
| Validation | 2023 | 13,622 | Set the fatal threshold; check stability |
| Test | 2024 | 14,358 | One independent evaluation |
| Partial year | 2025 | 7,029 | Reported separately (incomplete reporting) |

- **Follows the cheat sheet's *Data splitting* rule.** Training fits the model. Validation tunes the one setting that matters here, the fatal threshold (early stopping uses an internal 15% split of the training years). The test year is used **once**, for the final evaluation.
- **Split by time, not at random.** That's how any operational model would be used, and it prevents near-duplicate crashes from the same period leaking between training and test.
- **Inside the stable severity window.** So the label means the same thing in training and testing.
- **All rows used.** The data is small enough for histogram gradient boosting to train in seconds.
- **The cost:** fewer training years (three). A rolling-origin evaluation is listed as the next step as more stable-window years arrive.

### 3.4 Algorithms

**Gradient boosting: `HistGradientBoostingClassifier` (scikit-learn).**
- **Why:** the strongest general-purpose learner for tabular data with mixed categorical and numeric inputs and non-linear interactions (speed × remoteness × crash type). Its histogram method matches LightGBM's, but it ships with scikit-learn, so it adds no dependency. It handles **categorical features natively** (no one-hot expansion of 16 fields), has built-in early stopping, and gives calibrated probabilities when no resampling is used.
- **Settings:** learning rate 0.05, up to 800 iterations, 31 leaf nodes, minimum leaf 40, L2 regularisation 1.0, early stopping on an internal 15% split with patience 40. The serious model stopped after 136 iterations and the fatal model after 154. Moderate leaves and regularisation suit about 39,000 rows. No grid search was run, because three training years are too few to tune on without overfitting the validation year.
- **Why not XGBoost, LightGBM or CatBoost:** similar accuracy is expected on this size and type of data. They need new packages, and CatBoost's categorical handling is the main advantage this model already has natively.

**Logistic regression: `LogisticRegression`, L2, C = 1.0.**
- **Why:** the transparent baseline from the cheat sheet. It is interpretable, fast and well calibrated by construction. If it matches boosting, the simpler model wins.
- **Encoding:** one-hot with levels under 30 grouped as "infrequent", hour treated as a category (severity varies non-linearly by hour), unit counts standardised.

**Majority / training-share baseline.** Every metric is reported against a model that predicts the training share for every crash.

#### Algorithm details

**Logistic regression.**
- **Model:** the probability of the outcome for crash *i* with encoded inputs **x**ᵢ is

  p̂ᵢ = σ(β₀ + **β**ᵀ**x**ᵢ), with σ(z) = 1 / (1 + e⁻ᶻ).
- **Fitting:** coefficients minimise the L2-penalised log-loss with L-BFGS:

  L(β) = −Σᵢ [yᵢ log p̂ᵢ + (1 − yᵢ) log(1 − p̂ᵢ)] + (1/2C)‖**β**‖².

  C = 1 gives mild shrinkage that stabilises rare one-hot levels.
- **Meaning:** each coefficient is a log odds ratio relative to the dropped or infrequent level. The adjusted-odds model (§4) uses the same form unpenalised (C = ∞).

**Histogram gradient boosting** (Friedman 2001; the histogram method follows LightGBM, Ke et al. 2017).
- **Model:** an additive model of *M* regression trees on the log-odds scale:

  F_M(**x**) = F₀ + η Σₘ fₘ(**x**), with p̂ = σ(F_M).

  F₀ is the log-odds of the training share, and η = 0.05 is the learning rate.
- **One boosting step** *m*:
  1. Compute each crash's gradient gᵢ = p̂ᵢ − yᵢ and hessian hᵢ = p̂ᵢ(1 − p̂ᵢ) of the log-loss.
  2. Bin each numeric input into ≤255 histogram bins. Categorical inputs keep one bin per category, and their splits partition the categories into two groups ordered by gradient statistics.
  3. Grow a tree best-first, up to 31 leaves and at least 40 crashes per leaf. Each split is chosen to maximise

     Gain = ½ [G_L²/(H_L + λ) + G_R²/(H_R + λ) − (G_L + G_R)²/(H_L + H_R + λ)],

     where G and H are summed gradients and hessians in the left and right children, and λ = 1 (L2).
  4. Each leaf's value is −G/(H + λ).
- **Early stopping:** training stops when the log-loss on an internal 15% split hasn't improved for 40 iterations. The serious model stopped at 136 iterations and the fatal model at 154.

**Permutation importance** (Breiman 2001).
- For each input field *j*, shuffle its values across 12,000 test crashes and re-score average precision.
- Importance = mean drop over 8 shuffles: Iⱼ = AP − (1/8) Σᵣ AP(shuffled j, repeat r).
- Fields whose drop is within about two standard deviations of zero carry no detectable signal.

**Fixed category sets.** Every categorical field uses one category list built from all injury crashes, so a label has the same code in every split. Without this, gradient boosting would silently mis-read categories between years.

### 3.5 Imbalance and the alert threshold

| Option | Decision | Reason |
|---|---|---|
| SMOTENC oversampling (V5) | Dropped | Lowered fatal average precision; distorts probabilities |
| Class weights | Not used | Shift the probabilities just as a threshold would, but lose calibration |
| **Threshold chosen on the validation year** | **Used** | Keeps calibrated probabilities. The trade-off is set once on held-out data and then tested unchanged. |

**Threshold rule:** the highest-precision threshold on the 2023 validation year that still finds at least **50% of fatal crashes**, which matches V5's recall for comparison. This gives 0.044 for gradient boosting and 0.056 for logistic regression. Any real use would replace the 50% target with an agreed cost of missed cases against false alerts.

### 3.6 Evaluation metrics and why

| Metric | Used for | Why |
|---|---|---|
| ROC AUC | Both outcomes | Threshold-free ranking quality |
| Average precision | Both, mainly fatal | Ranking quality that reflects rarity. Its random baseline equals the outcome share (0.019 for fatal). |
| Brier score and skill against the training-share baseline | Both | Probability accuracy |
| Reliability curve (deciles) | Serious | Checks that predicted 30% means about 30% |
| Precision, recall, misses, false alerts at the threshold, per year | Fatal | What an operator would see |
| Permutation importance (average-precision drop, 8 repeats, 12,000 test crashes) | Gradient boosting | Measured on held-out data. Unlike impurity importance, it doesn't favour fields with many levels. |
| Accuracy, macro F1 | Not used | Uninformative with a rare class. The cheat sheet's *Evaluation Metrics* sheet makes the same point: always predicting the majority class gives 98% accuracy on the fatal target and finds no fatal crashes. |

#### Metric definitions and implementation

Notation: TP, FP, FN and TN are true and false positives and negatives at a threshold *t*. p̂ is the predicted probability and *y* the 0/1 outcome.

| Metric | Formula | Implementation (scikit-learn 1.9.1) |
|---|---|---|
| Precision | TP / (TP + FP) | Computed from alerts at the validation threshold, per evaluation year |
| Recall | TP / (TP + FN) | Same |
| ROC AUC | P(p̂ of a random positive > p̂ of a random negative), the area under the true-positive vs false-positive rate curve | `roc_auc_score` |
| Average precision | AP = Σₙ (Rₙ − Rₙ₋₁) Pₙ over decreasing thresholds; random baseline = outcome share | `average_precision_score`, `precision_recall_curve` |
| Brier score | (1/N) Σᵢ (p̂ᵢ − yᵢ)² | `brier_score_loss` |
| Brier skill | 1 − Brier(model) / Brier(training share). Above 0 means better than always predicting the training share. | Computed per evaluation set |
| Reliability | Observed share against mean p̂ in 10 equal-count bins | `calibration_curve(strategy='quantile')` |
| False alerts per correct alert | FP / TP | Threshold-sensitivity experiment (R4) |
| Bootstrap 95% interval | 2.5th–97.5th percentile of the metric over 500 crash-level resamples, paired across models | R1 (§11) |

### 3.7 Results (test year 2024 unless stated)

| Outcome | Model | ROC AUC | Average precision | Outcome share | Brier skill |
|---|---|---|---|---|---|
| Serious | Logistic regression | 0.714 | 0.699 | 0.510 | 0.138 |
| Serious | Gradient boosting | 0.718 | 0.703 | 0.510 | 0.147 |
| Fatal | Logistic regression | 0.838 | 0.115 | 0.019 | 0.045 |
| Fatal | Gradient boosting | 0.831 | 0.118 | 0.019 | 0.037 |

- **Against V5 on its own test years (2023–2025 pooled):** fatal average precision is 0.130 for logistic regression and 0.128 for gradient boosting, against V5's best of 0.091. That is about 40% better at ranking fatal crashes.
- **Fatal alerts on 2024 at the validation threshold:**
  - Gradient boosting found 137 of 273 fatal crashes (recall 50.2%) with 1,411 false alerts (precision 8.9%).
  - Logistic regression found 124 (45.4%) with 1,127 false alerts (precision 9.9%).
  - V5's best achieved a precision of 5.0–6.5% at similar recall. Precision held on partial 2025 (8.8–9.6%).
- **Calibration:** the serious-outcome reliability curves sit within about 0.04 of the diagonal, and mean predictions (0.49–0.50) match the observed share (0.51).
- **What drives the predictions:**
  - **Fatal model:** movement group, speed zone, motorcycle count, truck count and remoteness.
  - **Serious model:** motorcycle count, crash nature, movement group and speed zone. The new unit counts are among the strongest inputs.

**Uncertainty and robustness** (§11, R1–R4):
- **Serious outcome:** the 2024 metrics are precise (ROC AUC 0.71–0.72).
- **Fatal outcome:** the metrics are wide (average precision 0.09–0.15), and the two models are statistically indistinguishable (paired differences include 0).
- **Seeds:** the results don't depend on the seed (fatal average precision 0.121–0.135 over five seeds).
- **Inputs available before a crash:** with only road, time and environment inputs, fatal average precision falls to 0.051 and ROC AUC to 0.74.

### 3.8 Decision

- **Logistic regression is sufficient.** It matches gradient boosting on every measure, and the paired bootstrap (R1) confirms the difference isn't significant. That suggests the signal is mostly additive. It is the recommended model for any explanatory use.
- **Gradient boosting stays as the benchmark.** If it ever pulls ahead (for example with more years or new inputs), it shows the gap.
- **Neither is ready to drive operations.** At useful recall, about nine of every ten fatal alerts are false. The models describe severity given a crash and cannot target prevention before one.

---

## 4. Adjusted-odds model

*Notebook: Phase 3 "Adjusted odds of a serious outcome at crash level".*

| | |
|---|---|
| **Question** | The association of each road user, vehicle type and setting with a serious outcome, each holding the others constant |
| **Algorithm** | Logistic regression, unpenalised (`C = inf`, Newton–Cholesky), fitted to all 66,624 stable-window injury crashes |
| **Intervals** | Wald 95% intervals from the inverse of the observed information matrix |

**Why logistic regression.**
- Its coefficients are log odds ratios, the standard effect measure for a binary outcome in road-safety work.
- It adjusts for many factors at once, which the V5 matched method (Mantel–Haenszel within year × region) cannot do on grouped tables.
- It is unpenalised so that the estimates and intervals keep their usual meaning; regularisation would shrink them towards 1.

**Why the intervals are computed by hand.** `statsmodels` isn't in the pinned environment. The information matrix X′WX is computed in about ten lines and gives the same Wald intervals.

**Design choices.**
- Six involvement flags from the crash-level unit counts.
- Ten categorical fields with the most common level as reference.
- **Year as a category,** to absorb any drift left inside the window.
- **Rare levels:** under 100 crashes are pooled, and folded into the reference if the pool is still under 100. This avoids unstable one-crash terms.
- **Crash nature and movement code are left out,** because "hit pedestrian" would absorb the pedestrian effect.

**Result and why it mattered.**

| Flag | Adjusted (crash level) | V5 matched (grouped table) |
|---|---|---|
| Motorcycle | 3.35 (3.17–3.54) | 3.06 (2.90–3.22) |
| Pedestrian | 2.97 (2.75–3.21) | — |
| Single vehicle, no pedestrian | 2.14 (2.04–2.24) | — |
| Bicycle | 2.13 (1.98–2.29) | — |
| Truck | 1.31 (1.23–1.40) | 1.10 (1.04–1.18) |
| Bus | 1.01 (0.88–1.15) | 0.84 (0.74–0.96) |

The apparent "protective" bus association in V5 disappears once road setting is held constant. The truck association is stronger. Both suggest the grouped-table estimates were confounded by where these vehicles crash.

**Limits.**
- These are associations among recorded injury crashes, not causal effects.
- There are no interaction terms yet.
- The speed, drink-driving and fatigue flags are unavailable at crash level.

---

## 5. Road-site screening model

*Code: `traffic_road_sites.py` for the geometry. Notebook: Phase 3 "Screen road sites for excess serious crashes".*

### 5.1 How the approach evolved

| Version | Method | Problem found |
|---|---|---|
| V3–V4 | K-Means on longitude, latitude, hour and year | Clusters mainly separated the early recording period (with property-damage-only crashes) from the later one. It found recording changes, not places. |
| V5 | DBSCAN on serious crashes (50 m radius, 10 crashes minimum), 2011–2024 | Ranks by count, so busy sites lead. The top 100 grid cells fell to 0.61× in the next period while all cells rose 1.19×, which is regression to the mean. Clusters can also chain along one road. |
| **V6** | **Excess serious crashes over expectation on junctions and road links, with empirical-Bayes shrinkage** | — |

### 5.2 Why this model

- **A road-safety standard.** It follows the Highway Safety Manual's network-screening idea of the *excess proportion of specific crash types*. That works without traffic volumes, which we don't have.
- **Excess, not count.** Busy sites are only flagged if they are severe for their setting, not just busy.
- **A fair comparison.** Each crash's expected serious share comes from the statewide share for its **year × site type (junction or link) × speed zone × remoteness**. Including the year cancels the severity drift.
- **Real road units.** Sites are junctions (crash-coded intersections snapped within 40 m) and same-named links between junctions (snapped within 30 m), not arbitrary clusters or grid cells.

### 5.3 Estimation

For site *i* with *n* injury crashes, observed serious crashes *O* and expected serious crashes *E* = Σ stratum shares:

- **Overdispersion.** ρ, the intra-site correlation of serious outcomes beyond binomial, is estimated by method of moments across sites with two or more crashes: ρ = Σ[(O − E)² − V] / Σ[V(n − 1)], where V = Σp(1 − p). The estimate is ρ = 0.0446.
- **Shrinkage constant.** k = (1 − ρ)/ρ = 21.4 crashes. This is the beta-binomial prior strength.
- **Shrunk excess** = (O − E) × n/(n + k). A site with 21 crashes keeps about half its raw excess, and one with 5 keeps about a fifth.
- **Ranking:** by shrunk excess, sites with five or more injury crashes (5,645 of 55,943).

**The model behind the formulas.**
- Each site's true serious-outcome probability is treated as a draw from a beta distribution: πᵢ ~ Beta(k·mᵢ, k·(1 − mᵢ)).
  - mᵢ = Eᵢ/nᵢ is the site's expected share from its strata.
  - k is the prior strength, the number of "pseudo-crashes" the expectation is worth.
- Observed serious crashes are binomial given πᵢ: Oᵢ | πᵢ ~ Binomial(nᵢ, πᵢ).
- The posterior mean is (Oᵢ + k·mᵢ)/(nᵢ + k). This is the **shrunk serious share** in the site table.
- The posterior mean excess in crashes is nᵢ·[(Oᵢ + k·mᵢ)/(nᵢ + k) − mᵢ] = (Oᵢ − Eᵢ)·nᵢ/(nᵢ + k). This is the **shrunk excess**.
- Under the beta-binomial, Var(Oᵢ) = Vᵢ·[1 + (nᵢ − 1)ρ] with ρ = 1/(k + 1), where Vᵢ = Σ p(1 − p). That gives the moment estimator for ρ above. Each site also gets a z-score, zᵢ = (Oᵢ − Eᵢ)/√(Vᵢ[1 + (nᵢ − 1)ρ]).

**Why empirical Bayes rather than a full safety performance function:** a negative binomial safety performance function needs traffic volumes. Beta-binomial shrinkage toward the stratum expectation is the volume-free equivalent and needs no extra package.

### 5.4 Validation and what it showed

A two-period test ranked sites on 2015–2019 and measured them in 2020–2024:

- **Count ranking.** The top 100 by serious-crash count kept **no** excess next period (−3 serious crashes), which confirms the V5 problem.
- **Excess ranking.** The top 100 by raw or shrunk excess kept **45–50** serious crashes above expected, about 15% of their earlier raw excess. These are persistent severity problems.
- **Calibration.** Pooled by decile, shrunk estimates track the later period with a slope close to 1. Raw estimates span −34 to +32 points but the later period only −9 to +6.
- **Shrinkage did not improve the ranking order** over raw excess. Its benefit is the size of the estimates, not which sites are listed.
- **Known offset.** Shrunk estimates run about 3–4 points high because busy sites sit below their stratum's expected share, from +3.2 points at one-crash sites to −7.4 at sites with 20 or more. The shrinkage strength is about right; the reference it shrinks towards is off. **Next step:** add site crash frequency (or traffic volume) to the strata.
- **Robustness (R6).** The top 100 keep 98–100 sites under tighter (30/20 m) or looser (50/40 m) snapping and minimum crash counts of 3 or 10. They keep 95 when the year is dropped from the strata. Dropping remoteness changes the list to 61 shared sites and k falls from 21 to 8, so remoteness must stay in the reference.
- **Interpretation note.** The top-ranked links are largely recreational motorcycle routes: 33% of their crashes involve a motorcycle, against 12% statewide. The expectation allows for road setting but not road users, so a road-user-adjusted variant is listed as a follow-up.

---

## 6. Association rules

*Notebook: Phase 3 "Find combinations associated with serious outcomes".*

| | |
|---|---|
| **Algorithm** | Apriori (`mlxtend`) |
| **Items** | Seven recorded conditions, one-hot encoded, plus a serious-outcome item |
| **Settings** | Itemsets up to three items (two conditions plus the outcome), minimum support 0.5%, minimum confidence 60%, ranked by lift |
| **Data** | Stable-window injury crashes (66,624; serious share 49.9%). V5 pooled 2001–2025, mixing grading periods. |

**Algorithm** (Agrawal and Srikant 1994).
- **Each crash is a transaction:** a set of items such as `Crash_Nature = Head-on` and `Outcome = Fatal or hospitalisation`.
- **Frequent itemsets:** Apriori finds every itemset whose support is at least the minimum, building size-*k* candidates only from frequent size-(*k* − 1) sets (the *Apriori property*: every subset of a frequent set is frequent).
- **Rules:** each frequent itemset yields rules A → B.
- **Measures:**
  - Support(A → B) = P(A ∩ B)
  - Confidence = P(B | A) = Support(A ∪ B)/Support(A)
  - Lift = Confidence / P(B)
- **Selection:** only rules with B = {serious outcome} are kept. Lift > 1 means the conditions co-occur with a serious outcome more often than the window's baseline of 49.9%.

**Why Apriori.** It produces intuitive "if A and B, then often serious" statements for non-specialists, and the item space is small, so its speed disadvantage doesn't matter. FP-Growth would give the same rules faster but isn't needed at this size.

**Result.** 136 rules. The leading rule is still head-on crashes in 100–110 km/h zones (84.9% serious, lift 1.70). Remote and very remote settings dominate the rest.

**Stability (R7).** Mined separately on 2020–2022 and 2023–2024, 125 rules appear in both periods (133 and 137 found), 11 of the 12 strongest early rules recur, and lift correlates at 0.88 (median change 0.07).

**Limits.**
- Many rules repeat the same high-risk setting with a second condition that adds little, which is the "many uninteresting rules" disadvantage on the cheat sheet. A redundancy filter that keeps a two-condition rule only if it beats both single-condition rules is still to do.
- Rules are co-occurrence, not adjusted effects. The adjusted-odds model (§4) is the check on them.

---

## 7. Statistical comparison methods

These are not machine-learning models, but they are model-based comparisons that the findings depend on.

| Method | Where | Why chosen |
|---|---|---|
| Wilson 95% interval | Every share | Accurate for small counts and shares near 0 or 1, unlike the normal approximation |
| Exact Poisson interval | Weather fatality rates | Rates based on few events (for example 3 fatalities in smoke or dust) |
| Indirect standardisation (recorded ÷ expected) | Police regions, council areas, districts, electorates | Separates "where crashes happen" (remoteness × speed zone) from "how severe they are there" |
| Funnel plots (95% and 99.8% limits) | Area comparisons | Prevent small areas reaching the top of a list through noise. Limits narrow with size. |
| Direct standardisation | Wet against dry roads by lighting | Compares conditions under one common region × speed-zone mix |
| Mantel–Haenszel odds ratio, Robins–Breslow–Greenland variance | Grouped flags (speed, drink driving, fatigue, driver) | The only adjustment possible on year × region tables. Superseded by §4 where crash-level data exist. |
| Fixed-effects residual correlation | Speed against severity across region-years | Shows the pooled correlation (0.81) mostly reflects region and year differences (0.12 within) |

---

## 8. Models considered and not used

| Model (cheat-sheet family) | Considered for | Why not |
|---|---|---|
| Random Forest + SMOTENC (tree-based) | Severity | V5 incumbent. Resampling lowered fatal ranking quality and distorted probabilities (§3.1). |
| XGBoost / LightGBM / CatBoost (tree-based) | Severity | Little expected gain over histogram boosting at this size. Each adds a dependency to a pinned environment. |
| Ordinal logistic regression (linear) | Four-level severity | Needs `statsmodels`. Two binary models are easier to evaluate and threshold. |
| SVM, KNN, MLP (kernel, instance-based, neural) | Severity | Poor fit for high-cardinality categorical data, slow or hard to calibrate and explain, and no expected gain over boosting |
| K-Means (clustering) | Hotspots | Needs K, and in V3–V4 it separated recording periods rather than places |
| DBSCAN (clustering) | Hotspots | V5 incumbent. Count-based, so it favours busy sites, and it chains along roads. |
| Negative binomial safety performance function | Site screening | Needs traffic volumes |
| Kernel density or Getis–Ord hot-spot statistics | Hotspots | Areal rather than road units, and still count-driven without exposure |
| FP-Growth (association) | Rules | Same rules as Apriori, and speed isn't a constraint here |
| Time-series forecasting (for example ARIMA, Prophet) | Trends | No operational forecasting need is defined, and the severity series has a grading break. Breakpoint or interrupted time-series analysis is listed for later. |

---

## 9. Quality gates before any operational use

From the notebook's Phase 4 and Phase 6 tables:

1. **Use case agreed.** User, decision, prediction timing, the inputs available at that moment, and acceptable fatal precision and recall, with the cost of a missed case against a false alert.
2. **Severity drift explained.** The data custodian confirms why the hospitalisation share rose, so the stable window can be justified or extended.
3. **Rolling-origin evaluation** as more stable-window years arrive, with performance by region and condition and intervals for precision and recall.
4. **Site screening refined.** Site frequency (or traffic volume) in the strata, and a road-user-adjusted variant. Refresh annually and check whether treated sites fall back by more than the expected period-to-period fall.
5. **Monitoring.** Re-run the severity-mix check on every refresh. If the window moves, refit the models, rules and odds on the new window.
6. **Packaging,** only if a model goes into use: a versioned pipeline bundle, release and rollback procedure, and monitoring ownership.

**Deployment strategy, if needed** (from the cheat sheet's *Model Deployment* sheet):

| Strategy | Fit for these models | Reason |
|---|---|---|
| **Batch deployment** | **Recommended** | Crash data is released periodically and the outputs (site shortlists, severity profiles, adjusted odds) feed planning, not instant decisions. Scheduled scoring at each data refresh is cheaper and simpler. |
| **Shadow deployment** | **Recommended for model updates** | Run a refitted model next to the current one on the same refresh and compare before switching. This suits the annual refit the severity-mix check may force. |
| Real-time, streaming | Not justified | No decision needs an immediate prediction, and the models need inputs known only after a crash is coded |
| Canary, blue-green, A/B, multi-armed bandit | Not applicable | These assume live user traffic to route between versions |

---

## 10. Reproducibility

- **Seed:** `SEED = 42` for every split, sample, model and permutation.
- **Versions:** scikit-learn 1.9.1, mlxtend 0.25.0, pandas 3.1.1, NumPy 2.5.5 (full list in `Traffic release manifest V6.json`).
- **Recorded in the manifest:** model years, fatal thresholds (gradient boosting 0.0437, logistic regression 0.0563), site-screening ρ and k, and snap distances.
- **Results exported to `Tableau data V6/`:**
  - **Model results:** `result_model_summary`, `result_model_by_year`, `result_model_confusion`, `result_model_precision_recall`, `result_model_permutation_importance`.
  - **Other model outputs:** `result_adjusted_odds`, `result_site_screening`, `result_site_persistence`, `result_hotspots`, `result_association_rules`.
  - **Reliability experiments:** `result_model_bootstrap`, `result_model_seed_stability`, `result_model_feature_ablation`, `result_model_threshold_sensitivity`, `result_window_tolerance`, `result_site_sensitivity`, `result_rule_recurrence`.

---

## 11. Experimental design

### 11.1 Objectives and principles

The experiments answer two questions for each method:
- **Feasibility:** can it work with these data?
- **Reliability:** would the result hold up with different data, settings or random draws?

Design principles:

| Principle | How it is applied |
|---|---|
| **Baselines and controls** | Every model is compared with a training-share baseline. Every ranking is compared with the V5 count ranking. Every standardised comparison is compared with its unadjusted version. |
| **Time-ordered hold-out** | Train on earlier years, tune on the next, test once on the latest. Random splits are never used for evaluation. |
| **One test, used once** | 2024 is scored only after the threshold is fixed on 2023 (the cheat sheet's *Data splitting* rule) |
| **Paired comparisons** | Model differences are bootstrapped on the same resampled crashes, so shared noise cancels |
| **Change one thing at a time** | Ablation and sensitivity runs vary a single choice against the baseline |
| **Negative results are kept** | Rejected methods (K-Means, DBSCAN, SMOTENC, the car flag, date reconstruction) are documented with their evidence |
| **Reproducibility** | Fixed seed 42, pinned versions, and every experiment's table exported |

### 11.2 Experiment programme

The development experiments (E-series, the full log in [`Analytics_Methods.md`](Analytics_Methods.md) §4) chose the methods. The reliability experiments (R-series, notebook Phase 4 "Reliability and sensitivity experiments") test the chosen methods.

| # | Hypothesis | Design | Metric | Result | Conclusion |
|---|---|---|---|---|---|
| E19 | Resampling improves fatal detection | Random Forest with and without SMOTENC (V5) | Fatal average precision | 0.088 → 0.081 | Rejected; no resampling |
| E20 | Binary models in the stable window beat V5 | Both models on V5's test years 2023–2025 | Fatal average precision; precision at about 50% recall | 0.13 vs 0.091; 9–10% vs 5–6.5% | Supported |
| E15 | Excess ranking persists better than count ranking | Rank sites in 2015–19, measure in 2020–24 | Later excess of the top 100 | Count −3; raw +50; shrunk +45 | Supported for excess; shrinkage helps magnitudes, not order |
| E16 | Shrunk estimates are calibrated | Decile calibration and size bands | Slope, offset | Slope ≈ 1, offset 3–4 points | Reference needs site frequency |
| **R1** | Test metrics are precise enough to compare models | 500 paired bootstrap resamples of 2024 | 95% intervals; paired difference | Serious tight; fatal wide (average precision 0.09–0.15); difference ≈ 0 | The models are equivalent; report intervals |
| **R2** | Results don't depend on the seed | Five boosting seeds | Spread of ROC AUC and average precision | Fatal average precision 0.121–0.135 | Stable |
| **R3** | Unit counts and crash description carry signal; inputs known before a crash have weak power | Feature-group ablation | Fatal average precision, ROC AUC | 0.118 → 0.089 (no units), 0.082 (no description), 0.051 (road, time and environment only) | Supported; prediction before a crash is only weakly feasible |
| **R4** | The alert trade-off is smooth | Recall targets 0.3–0.7 on 2023, applied to 2024 | Precision, recall, false alerts per correct alert | 14–16% precision at 30% recall down to about 6% at 70% | Smooth; no good operating point |
| **R5** | The stable window isn't an artefact of the tolerance | Tolerances 2–5 points | Window years | 3–5 points → 2020–2024; 2 points → 2023–2024 | Robust at ≥3 points |
| **R6** | The site list is robust to analyst choices | Vary snapping, minimum crashes and strata | Top-100 overlap; k | 95–100 shared; remoteness removed → 61 | Robust; remoteness essential |
| **R7** | The association rules recur | Apriori on 2020–22 against 2023–24 | Shared rules; lift correlation | 125 shared; 11 of the top 12; r = 0.88 | Stable |

### 11.3 How the metrics enter the experiments

- **Model comparisons** use threshold-free metrics (ROC AUC, average precision, Brier skill) on the test year, with paired bootstrap intervals. Threshold metrics (precision, recall, false alerts) are reported only at thresholds fixed on the validation year.
- **Ranking experiments** use **later-period outcomes** of the earlier top 100 (serious crashes, excess) and **overlap counts**, because the purpose of a site list is to find sites that stay problematic.
- **Calibration experiments** compare predicted with observed shares by decile, pooled crash-weighted on both sides, so that small sites don't dominate.
- **Stability experiments** use overlap counts (sites, rules) and correlation of effect sizes (lift) between periods or settings.
- **Every experiment table is exported**, so the results can be re-plotted or audited without rerunning.

### 11.4 Planned experiments

| Experiment | Purpose | Trigger |
|---|---|---|
| Rolling-origin evaluation | Stability across several test years | When a further complete stable-window year is released |
| Site frequency in the screening strata | Fix the calibration offset (E16) | Next screening revision |
| Road-user-adjusted screening | Separate motorcycle-route sites from road-design sites (E18) | Next screening revision |
| Rule redundancy filter | Reduce near-duplicate rules | Next rules revision |
| Rainfall join and its sensitivity to month vs candidate-day matching | Test whether wetter-than-usual months change counts or severity | When rainfall data is obtained |
| Exposure-adjusted rates | Risk per person or vehicle-kilometre | When ABS population or traffic volumes are added |

---

## 12. References

- Agrawal, R. & Srikant, R. (1994). Fast algorithms for mining association rules. *Proc. 20th VLDB Conference*, 487–499.
- American Association of State Highway and Transportation Officials (2010). *Highway Safety Manual*, 1st ed., Part B, Chapter 4: Network screening. AASHTO.
- Breiman, L. (2001). Random forests. *Machine Learning*, 45(1), 5–32. (Permutation importance.)
- Brier, G. W. (1950). Verification of forecasts expressed in terms of probability. *Monthly Weather Review*, 78(1), 1–3.
- Chawla, N. V., Bowyer, K. W., Hall, L. O. & Kegelmeyer, W. P. (2002). SMOTE: synthetic minority over-sampling technique. *Journal of Artificial Intelligence Research*, 16, 321–357.
- Ester, M., Kriegel, H.-P., Sander, J. & Xu, X. (1996). A density-based algorithm for discovering clusters in large spatial databases with noise. *Proc. KDD-96*, 226–231.
- Friedman, J. H. (2001). Greedy function approximation: a gradient boosting machine. *Annals of Statistics*, 29(5), 1189–1232.
- Hauer, E. (1997). *Observational Before–After Studies in Road Safety*. Pergamon. (Empirical Bayes and regression to the mean.)
- Ke, G. et al. (2017). LightGBM: a highly efficient gradient boosting decision tree. *Advances in Neural Information Processing Systems*, 30.
- Pedregosa, F. et al. (2011). Scikit-learn: machine learning in Python. *Journal of Machine Learning Research*, 12, 2825–2830.
- Saito, T. & Rehmsmeier, M. (2015). The precision-recall plot is more informative than the ROC plot when evaluating binary classifiers on imbalanced datasets. *PLOS ONE*, 10(3), e0118432.
- Studer, S. et al. (2021). Towards CRISP-ML(Q): a machine learning process model with quality assurance methodology. *Machine Learning and Knowledge Extraction*, 3(2), 392–413.
- Supporting material in this project: `ML Model Cheat Sheet.xlsx` (model families, metrics, deployment strategies, definitions); notebook figures (precision–recall, reliability, importance, persistence, reliability experiments); `Tableau data V6/result_*` tables.

---

<!-- project-docs-nav -->
**Project documentation:** [Index](Documentation_Index.md) · [Goals and tasks](Analytical_Goals_and_Tasks.md) · [Data and resources](Data_and_Resources.md) · [Data engineering](Data_Engineering.md) · [Analytics methods](Analytics_Methods.md) · **Model engineering** · [Implementation design](Implementation_Design.md) · [System architecture](Analytical_System_Architecture.md) · [Timeline and milestones](Timeline_and_Milestones.md) · [Risk management](Risk_Management.md)
