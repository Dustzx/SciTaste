# Population variation and probability evidence

This fifth prospective task candidate supports submission-plan `task-freeze`
and then `primary-experiments`. It is a statistical-research task, not another
vision task, a prediction leaderboard replication, or an admitted formal release.
Current admission and measured results belong to the project ledger/artifacts;
this document owns the scientific source and protocol rationale.

## Question, hypotheses and informative experiments

Which public evidence justifies transferring an income-probability predictor
across populations? A lower proper-score loss can come from representation,
ranking, prevalence or probability calibration. Researchers must discriminate
those alternatives, preserve adverse controls and state what remains unresolved.
Renaming logistic regression, boosting, reweighting or recalibration does not
establish a new method. Calibration within one population does not automatically
transfer, and changing a decision threshold cannot improve probability calibration.

Train-only representation/prediction/calibration fitting and public configuration
selection are distinct. Household-aware training cross-fitting can construct
calibration controls without treating public labels as extra fitting targets.
Training-based predictors and fixed training-free probability rules are subject
methods; this does not train the autonomous research controller.

## Source, population and rights

[Retiring Adult, NeurIPS 2021 main conference](https://papers.neurips.cc/paper_files/paper/2021/hash/32e54441e6382a7fbacbbbaf3c450059-Abstract.html)
introduces ACS/Folktables tasks and explicitly examines time, geography and
group-related differences. Its relevant methods, experiment sections, supplement
and datasheet were read before task construction. It is subject-domain/data
research, not an autonomous-research system baseline.

Four original Census one-year person-PUMS archives cover CA/TX 2014 and CA/NY
2018, totalling 227,242,041 bytes. The acquisition receipt retains exact locators,
sizes, HTTP metadata and local SHA-256; no upstream checksum was supplied.
The task follows source eligibility (age >16, working hours >0, income >100,
positive person weight) and nominal income >50,000 as its statistical label.
Eligibility therefore uses income and is not labelled outcome-blind.

Original source household identifiers assign groups before numeric income
parsing. All eligible persons in a selected household remain together. The
prospective household allocation contains ineligible households too; realized
eligible counts are reported rather than pretending all selected households
contain an included worker. Public identities are opaque task keys, not external
identity links. Unknown repeated individuals across years, near duplicates,
regional dependency and controller pretraining remain limitations.

[Census terms](https://www.census.gov/data/developers/about/terms-of-service.html)
govern the original data. This is authorized local statistical research, not
permission for re-identification, outside identity linkage or individual deployment.
The Folktables code licence is not a raw-data licence. Standalone raw/derived
redistribution is not approved; a public release must use original loaders and
reconstruction rules with appropriate rights review. No Census endorsement is
implied.

## Evidence populations and endpoints

California-2014 supplies training. Public discovery and validation contain
separate California/Texas-2014 household groups. Confirmation contains separate
CA-2018 and NY-2018 populations. CA changes time; NY changes time and geography
together. These are descriptive changes, not a randomized geographic effect or
national inference. The fixed nominal threshold also prevents an unqualified
real-income interpretation across years.

The primary is original person-survey-weighted Brier score on each complete
target population. Weighted AUC, fixed-0.5 accuracy, calibration-in-the-large,
unweighted Brier, original-code group diagnostics, failures and cost are separate.
Survey weighting describes the selected eligible state/year population, not all
US residents. Group TPR with fewer than twenty positives is unavailable, not zero;
that count threshold does not calibrate uncertainty or certify fairness.

One public-selected primary is frozen before queries. Every declared procedure
and population receives a retained success/failure record. Missing/invalid outputs
and any declared individual failure leave a complete primary missing; no survivor
mean or zero imputation. Untrusted output failures cannot erase the framework
assignment or its declared matrix. Frozen source and author-pack corruption
remain fail-closed integrity errors, not scoreable failures.

## Accepted-research comparison and remaining gap

MLR-Bench (NeurIPS 2025 Datasets and Benchmarks) and AI-Researcher (NeurIPS 2025
main track) motivate actual framework-owned hypotheses, experiments and papers.
Three ordinary train-only controls establish public feasibility, not subject-model
state of the art, new scientific contribution, Taste benefit or system completion.
Households and persons are within-task units, not independent research tasks.
Six required claim categories separate prediction, learning boundaries,
mechanism, population scope, reproduction and cost/novelty. Unperformed causal
contrasts remain insufficient even with favorable Brier loss.

The first builder's blank numeric-token failure and the independently rejected
output-collection policy are retained. Follow-up changes neither data, labels,
population allocation nor scoring definitions. Admission of one bounded
comparison, judge calibration, benchmark breadth, publication-quality insight
and the actual complete-system results are different evidence obligations.
