fold=3
fold=5
#  params['num_threads'] = 34
import sys
import pandas as pd

#========================================================================
# Args
#========================================================================
key = 'card_id'
target = 'target'
ignore_list = [key, target, 'merchant_id']

win_path = f'../features/4_winner/*.gz'
stack_name='en_route'
fname=''
xray=False
#  xray=True
submit = pd.read_csv('../input/sample_submission.csv')
#  submit = []

#========================================================================
# argv[1] : model_type 
# argv[2] : learning_rate
# argv[3] : early_stopping_rounds
#========================================================================

try:
    model_type=sys.argv[1]
except IndexError:
    model_type='lgb'
try:
    learning_rate = float(sys.argv[2])
except IndexError:
    learning_rate = 0.1
try:
    early_stopping_rounds = int(sys.argv[3])
except IndexError:
    early_stopping_rounds = 150
num_boost_round = 10000

import numpy as np
import datetime
import glob
import gc
import os
HOME = os.path.expanduser('~')

sys.path.append(f'{HOME}/kaggle/data_analysis/model')
from params_lgbm import params_elo
from pdp import Xray_Cal
sys.path.append(f'{HOME}/kaggle/data_analysis')
from model.lightgbm_ex import lightgbm_ex as lgb_ex

sys.path.append(f"{HOME}/kaggle/data_analysis/library/")
import utils
from preprocessing import get_ordinal_mapping
from utils import logger_func
try:
    if not logger:
        logger=logger_func()
except NameError:
    logger=logger_func()

if model_type=='lgb':
    params = params_elo()[1]
    params['learning_rate'] = learning_rate

start_time = "{0:%Y%m%d_%H%M%S}".format(datetime.datetime.now())


#========================================================================
# Data Load
base = utils.read_df_pkl('../input/base*')
win_path_list = glob.glob(win_path)
win_path_list += glob.glob('../features/5_tmp/*.gz')
train_path_list = []
test_path_list = []
for path in win_path_list:
    if path.count('train'):
        train_path_list.append(path)
    elif path.count('test'):
        test_path_list.append(path)

base_train = base[~base[target].isnull()].reset_index(drop=True)
base_test = base[base[target].isnull()].reset_index(drop=True)
train_feature_list = utils.parallel_load_data(path_list=train_path_list)
test_feature_list = utils.parallel_load_data(path_list=test_path_list)
train = pd.concat(train_feature_list, axis=1)
train = pd.concat([base_train, train], axis=1)
test = pd.concat(test_feature_list, axis=1)
test = pd.concat([base_test, test], axis=1)

train_latest_id_list = np.load('../input/card_id_train_first_active_201712.npy')
test_latest_id_list = np.load('../input/card_id_test_first_active_201712.npy')


#========================================================================

#========================================================================
# LGBM Setting
seed = 1208
metric = 'rmse'
fold_type='self'
group_col_name=''
dummie=1
oof_flg=True
LGBM = lgb_ex(logger=logger, metric=metric, model_type=model_type, ignore_list=ignore_list)

train, test, drop_list = LGBM.data_check(train=train, test=test, target=target)
if len(drop_list):
    train.drop(drop_list, axis=1, inplace=True)
    test.drop(drop_list, axis=1, inplace=True)

# Valid Features
feat_list = glob.glob('../features/1_first_valid/*.gz')
feat_list = sorted(feat_list)
train_feat_list = ['']
test_feat_list = ['']

for path in feat_list:
    if path.count('train'):
        train_feat_list.append(path)
    elif path.count('test'):
        test_feat_list.append(path)

#========================================================================

from sklearn.model_selection import StratifiedKFold
train['outliers'] = train[target].map(lambda x: 1 if x<-30 else 0)
folds = StratifiedKFold(n_splits=fold, shuffle=True, random_state=seed)
kfold = list(folds.split(train,train['outliers'].values))
train.drop('outliers', axis=1, inplace=True)

valid_list = []
import shutil
used_path = []
#========================================================================
# outlierに対するスコアを出す
from sklearn.metrics import mean_squared_error
out_ids = train.loc[train.target<-30, key].values
out_val = train.loc[train.target<-30, target].values
#========================================================================

cv_score_list = []
df_pred = pd.DataFrame()

for i, path in enumerate(zip(train_feat_list, test_feat_list)):

    LGBM = lgb_ex(logger=logger, metric=metric, model_type=model_type, ignore_list=ignore_list)
    LGBM.seed = seed

    if len(path[0])>0:
        train_path = path[0]
        test_path = path[1]
        if train_path[-7:] != test_path[-7:]:
            print('Feature Sort is different.')
            print(train_path, test_path)
            sys.exit()
        used_path += list(path).copy()
        train_feat = utils.get_filename(path=train_path, delimiter='gz')
        train_feat = train_feat[15:]
        test_feat = utils.get_filename(path=test_path, delimiter='gz')
        test_feat = test_feat[14:]

        try:
            train[train_feat] = utils.read_pkl_gzip(train_path)
            test[train_feat] = utils.read_pkl_gzip(test_path)
        except FileNotFoundError:
            continue
        except ValueError:
            continue
    else:
        train_feat = 'base'

    # idを絞る
    try:
        tmp_train = train.loc[train[key].isin(train_latest_id_list), :]
        tmp_test = test.loc[test[key].isin(test_latest_id_list), :]
        fold_type='kfold'
        kfold = False
        all_id = False
    except AttributeError:
        all_id = True
        pass

    logger.info(f'''
    #========================================================================
    # No: {i}/{len(train_feat_list)}
    # Valid Feature: {train_feat}
    #========================================================================''')

    train.sort_index(axis=1, inplace=True)
    test.sort_index(axis=1, inplace=True)

    try:
        seed_list = [1208, 605, 328, 1222, 405][:int(sys.argv[4])]
    except IndexError:
        seed_list = [1208]
    for seed in seed_list:
        LGBM.seed = seed

#========================================================================
# Train & Prediction Start
#========================================================================
        if all_id:
            LGBM = LGBM.cross_prediction(
                train=train
                ,test=test
                ,key=key
                ,target=target
                ,fold_type=fold_type
                ,fold=fold
                ,group_col_name=group_col_name
                ,params=params
                ,num_boost_round=num_boost_round
                ,early_stopping_rounds=early_stopping_rounds
                ,oof_flg=oof_flg
                ,self_kfold=kfold
            )
        else:
            LGBM = LGBM.cross_prediction(
                train=tmp_train
                ,test=tmp_test
                ,key=key
                ,target=target
                ,fold_type=fold_type
                ,fold=fold
                ,group_col_name=group_col_name
                ,params=params
                ,num_boost_round=num_boost_round
                ,early_stopping_rounds=early_stopping_rounds
                ,oof_flg=oof_flg
            )

        cv_score = LGBM.cv_score
        cv_feim = LGBM.cv_feim
        feature_num = len(LGBM.use_cols)

        cv_score_list.append(cv_score)

        if len(df_pred):
            df_pred['prediction'] += LGBM.result_stack['prediction'].values
        else:
            df_pred = LGBM.result_stack


    if len(path[0])>0:
        train.drop(train_feat, axis=1, inplace=True)
        test.drop(train_feat, axis=1, inplace=True)

    df_pred['prediction'] /= len(seed_list)
    cv_score_mean = np.mean(cv_score_list)
    logger.info(f'''
#************************************************************************
#========================================================================
# CV SCORE AVG: {cv_score_mean}
#========================================================================
#************************************************************************ ''')

    # Result Summarize

    if len(target)>150000:
        #========================================================================
        # outlierに対するスコアを出す
        out_pred = df_pred[df_pred[key].isin(out_ids)]['prediction'].values
        out_score = np.sqrt(mean_squared_error(out_val, out_pred))
        LGBM.val_score_list.append(out_score)
        #========================================================================

    LGBM.val_score_list.append(cv_score_mean)
    tmp = pd.Series(LGBM.val_score_list, name=f"{i}_{train_feat}")
    valid_list.append(tmp.copy())
    if i==0:
        base_valid = tmp.copy()

    if i%10==1 and i>9:
        df_valid = pd.concat(valid_list, axis=1)
        print("Enroute Saving...")
        df_valid.to_csv(f'../output/{start_time[4:12]}_elo_multi_feat_valid_lr{learning_rate}.csv', index=True)
        print("Enroute Saving Complete.")
        for p in used_path:
            shutil.move(p, '../features/2_second_valid/')
        used_path = []
else:
    for p in used_path:
        shutil.move(p, '../features/2_second_valid/')
    used_path = []


df_valid = pd.concat(valid_list, axis=1)

for col in df_valid.columns:
    if col.count('base'):continue
    df_valid[f"val_{col}"] = (df_valid[col].values < base_valid.values) * 1

df_valid.to_csv(f'../output/{start_time[4:12]}_elo_multi_feat_valid_lr{learning_rate}.csv', index=True)
