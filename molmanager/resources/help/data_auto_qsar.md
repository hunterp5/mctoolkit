# Quick QSAR

Quick QSAR builds a pool of models for one activity column, keeps the best of them, and predicts with their consensus.

## Goal

Get a model without choosing fingerprints, latent factors, or a descriptor checklist. **Generate Model** remains the manual tool.

## When to use

Open it from **Data → QSAR → Quick QSAR**. Use it when labeled rows are available and the goal is a first model. Use **Generate Model** when the columns and algorithm should stay under manual control.

## Inputs / scope

- **Visible Rows Only** / **Selected Rows Only** / **Refresh columns**. The learning set is this scope.
- **Activity (Y)** column. **Task**: Auto, Regression, or Classification.
- **Structure** source. Structures are not standardized or deduplicated.
- **Table columns**. Checked numeric columns are added to the calculated descriptors. Nothing in that list is included until it is checked. The activity column is skipped.
- **Prediction column**, default `Quick QSAR_<activity>`.
- **Consensus of retained models**, on by default. Uncheck it to predict with the selected leaderboard row. Selecting a row does not turn consensus off.

At least 8 learning rows are required. A learning row needs a numeric activity and, when any structure is available, a structure. **Add predictions** scores the visible table and ignores **Selected Rows Only**, so a selected learning set can be applied to the other visible rows.

## What the search tries

One descriptor pool, filtered once before the splits:

- RDKit 2D descriptors, including 2D autocorrelation and MQN. 3D descriptors and ionization scores are not calculated.
- Ipc, qed, the three Morgan fingerprint densities, and the unspecified-stereocenter count are left out. Ro5 and ESOL are not calculated.
- Checked numeric columns from the table. The activity, the prediction column, and fingerprint on-bit counts stay out. A column whose name matches a calculated descriptor uses the calculated value.

The filter drops a column when 90% of the learning rows share one value or the variance is negligible, then keeps one descriptor from each cluster of columns whose absolute correlation is at least 0.8. That filter does not look at the activity.

Four unfolded fingerprints are scored on their own, never concatenated with descriptors. Each keeps the 10,000 highest-variance bits:

- Radial (Morgan, radius 2)
- Linear (RDKit path)
- Dendritic (atom pair)
- MOLPRINT2D, represented here by unfolded feature-Morgan (FCFP), radius 2

Regression on descriptors uses best-subsets MLR, PLS, PCR, and kernel PLS. Regression on a fingerprint uses kernel PLS only. Classification on descriptors uses naive Bayes and an ensemble of 100 trees. Classification on a fingerprint uses naive Bayes only. PLS, PCR, and kernel PLS stop adding latent factors before the training R² passes 0.9.

## How models are scored

Each split is a random 75/25 cut. Classification splits are stratified when that is possible. The search repeats the cut 50 times and keeps the 10 best models.

The score is test accuracy times one minus the absolute gap between train and test accuracy. A negative test accuracy is used as the score, so a very poor test cannot become a large positive score. Continuous test accuracy divides the residual variance by the variance of the learning-set activity, not by the variance of the test rows alone. Categorical accuracy is the unweighted mean of per-class recall. That ranking, the descriptor filter, and the model search follow Dixon et al. (see References).

The leaderboard lists Score, Test accuracy, Train accuracy, Method, Features, and Split. Features is the number of descriptors or fingerprint bits in that model. Click a row to show that model in the results box, including every feature it uses.

**Save model** writes the selected row to an `.mmqsar` file. **Load model** reads that file back. **Add predictions** then scores the current table with the loaded model. The file keeps the estimator, the features, and the training rows used for the applicability domain and for kernel PLS.

## Predictions, interval, and domain

The default prediction is the unweighted consensus: the mean for regression, and a majority vote for classification. A tied vote uses the average class probability.

Regression writes the prediction, a separate interval column, and a domain column. The interval is a 90% half-width, so the range is prediction ± interval. It comes from the absolute residuals on that model's own 25% test rows. The consensus interval is the mean of those half-widths. Classification writes the class, a probability column, and a domain column instead of an interval.

A row is out of domain when its distance to the model's training rows is greater than the 95th percentile of nearest-neighbor distances inside that training set. Descriptor models use Euclidean distance. Fingerprint models use Tanimoto distance. The consensus calls a row in domain when at least half of the models do.

Rows in the learning set were used to train some of the retained models, so those predictions overlap the models. Rows outside the learning scope are the external set. Duplicate structures are kept and only mentioned in the report.

Predictions add the prediction column, an interval or class probability, and a domain flag. Calculated descriptors and fingerprint bits are not written to the table.

## References

Dixon, S. L.; Duan, J.; Smith, E.; Von Bargen, C. D.; Sherman, W.; Repasky, M. P. AutoQSAR: An Automated Machine Learning Tool for Best-Practice Quantitative Structure–Activity Relationship Modeling. Future Med. Chem. 2016, 8, 1825–1839. https://doi.org/10.4155/fmc-2016-0093
