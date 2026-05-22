# Delivery: stable-opponent-prediction-inference

## Summary

- Added unified opponent hidden-hand inference with particle sampling, Monte Carlo budget config, and Bayesian evidence adjustment.
- Connected stable hard analysis to structured opponent prediction while preserving existing text fields.
- Added top-bar controls for opponent prediction, particle count, MC count, Bayesian toggle, and manual rerun.
- Rendered a dedicated opponent prediction panel in the strategy area.
- Ensured simulation hidden opponent hand does not affect displayed prediction.

## Verification

- `python -m py_compile game\opponent_inference.py game\stable_hard_analysis.py ui\stable_battle_panel.py ui\main_window.py tests\test_stable_hard_analysis.py`
- `python -m unittest tests.test_stable_hard_analysis`
- `python -m unittest tests.test_stable_hard_analysis tests.test_stable_simulator`
- `gitnexus detect-changes --scope all -r mahjong-learning`

## Notes

- `python -m pytest tests/test_stable_hard_analysis.py` could not run because this Python environment does not have `pytest` installed.
- `gitnexus detect-changes` returned critical because `analyze_snapshot` is a critical shared entry and the workspace already contains unrelated dirty files outside this change.

## Follow-up UI Adjustment

- Clarified the prediction is a public-information posterior estimate, not a true known probability.
- Moved "对我方危险牌" to the top of the prediction area.
- Changed probability sections to compact table-style rows sorted from high to low.
- Changed non-zero probabilities under 1% to display as `<1%` instead of `0%`.
- Removed representative-hand sample display from the UI and stopped populating it.
- Reduced the top control row font size and narrowed controls.
- Added dynamic analysis gating. When enabled, low-value early states skip particle/MC/Bayesian computation and show the evidence score/reasons.
- Increased the compressed top control row font from 7px to 9px.
