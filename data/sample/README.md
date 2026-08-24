# Sample data

A 1,500-account stratified slice of the full 29,376-account run, committed so
the repo is browsable and the API can start without generating anything.

Stratified by risk band, so the portfolio KPIs computed from this sample match
the shape of the full dataset rather than over-representing at-risk accounts.

Regenerate the full dataset with:

```bash
python ml/generate_data.py --customers 50000 --out data/
python ml/build_features.py --data data/ --out data/
python ml/train_model.py --data data/ --artifacts ml/artifacts/
```
