#!/bin/bash

python s002_lgb_feat_selection.py lgb 0.05 250
python s004_lgb_decrease.py
python s001_lgb_main.py lgb 0.01 200 10

wait
sudo shutdown -P