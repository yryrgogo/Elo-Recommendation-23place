import sys
import pandas as pd
outlier_thres = -3
fold=5
num_threads = 34

#========================================================================
# Args
#========================================================================
key = 'card_id'
target = 'target'
ignore_list = [key, target, 'first_active_month', 'merchant_id', 'column_0', 'index']

stack_name='en_route'
fname=''
xray=False
#  xray=True
submit = pd.read_csv('../input/sample_submission.csv')
#  submit = []


model_type='lgb'
#  try:
#      learning_rate = float(sys.argv[1])
#      win_path = f'../features/4_winner/*.gz'
#  except ValueError:
learning_rate = 0.01
win_path = sys.argv[1]
out_part = sys.argv[2]
win_path = f'../features/4_winner/*.gz'
#  learning_rate = 1
early_stopping_rounds = 150
num_boost_round = 20000

import numpy as np
import datetime
import glob
import gc
import os
from sklearn.metrics import mean_squared_error
HOME = os.path.expanduser('~')

sys.path.append(f'{HOME}/kaggle/data_analysis/model')
from params_lgbm import params_elo
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

params = params_elo()[1]
params['learning_rate'] = learning_rate

# Best outlier fit LB3.690
#  num_leaves = 4
num_leaves = 31
#  num_leaves = 16
#  num_leaves = 48
params['num_leaves'] = num_leaves
params['num_threads'] = num_threads
if num_leaves>40:
    params['num_leaves'] = num_leaves
    params['subsample'] = 0.8757099996397999
    #  params['colsample_bytree'] = 0.7401342964627846
    params['colsample_bytree'] = 0.3
    #  params['min_child_samples'] = 61
    params['min_child_samples'] = 40


start_time = "{0:%Y%m%d_%H%M%S}".format(datetime.datetime.now())

#========================================================================
# Data Load

tmp_path_list = glob.glob(f'../features/5_tmp/*.gz')

base = utils.read_df_pkl('../input/base_first*')
base_train = base[~base[target].isnull()].reset_index(drop=True)
base_test = base[base[target].isnull()].reset_index(drop=True)

win_path_list = glob.glob(win_path) + tmp_path_list
feature_list = utils.parallel_load_data(path_list=win_path_list)
df_feat = pd.concat(feature_list, axis=1)
train = pd.concat([base_train, df_feat.iloc[:len(base_train), :]], axis=1)
test = pd.concat([base_test, df_feat.iloc[len(base_train):, :].reset_index(drop=True)], axis=1)

self_predict = train.copy()

y = train[target].values


#========================================================================
# Outlier Setting
if out_part=='part':
    # Exclude Difficult Outlier
    #  clf_result = utils.read_pkl_gzip('../stack/0111_145_outlier_classify_9seed_lgb_binary_CV0-9045939277654236_188features.gz')[[key, 'prediction']]
    clf_result = utils.read_pkl_gzip('../stack/0130_214_outlier_classify_9seed_lgb_binary_CV0-9044513544501314_172features.gz')[[key, 'pred_mean']]
    train = train.merge(clf_result, how='inner', on=key)
    #  tmp1 = train[train.prediction>0.01]
    #  tmp2 = train[train.prediction<0.01][train.target>-30]
    tmp1 = train[train.pred_mean>0.01]
    tmp2 = train[train.pred_mean<0.01][train.target>-30]
    train = pd.concat([tmp1, tmp2], axis=0, ignore_index=True)
    del tmp1, tmp2
    gc.collect()
    #  train.drop('prediction', axis=1, inplace=True)
    train.drop('pred_mean', axis=1, inplace=True)
elif out_part=='all':
    #  Exclude Outlier
    train = train[train.target>-30]

#  train = train[train[target]<= 9]
#  train = train[train[target]> -9]
train.reset_index(drop=True, inplace=True)
#========================================================================


#========================================================================
# LGBM Setting
try:
    argv3 = int(sys.argv[3])
    seed_list = np.arange(argv3)
    if argv3<=10:
        seed_list = [1208, 605, 1212, 1222, 405, 1128, 1012, 328, 2005, 2019][:argv3]
except IndexError:
    seed_list = [1208]
metric = 'rmse'
#  metric = 'mse'
params['metric'] = metric
fold_type='self'
#  fold_type='stratified'
group_col_name=''
dummie=1
oof_flg=True
LGBM = lgb_ex(logger=logger, metric=metric, model_type=model_type, ignore_list=ignore_list)

#  train, test, drop_list = LGBM.data_check(train=train, test=test, target=target)
train, test, drop_list = LGBM.data_check(train=train, test=test, target=target, encode='label')
if len(drop_list):
    train.drop(drop_list, axis=1, inplace=True)
    test.drop(drop_list, axis=1, inplace=True)


from sklearn.model_selection import StratifiedKFold
from s018_make_first_month_distribution import make_fam_dist
# seed_avg
seed_pred = np.zeros(len(test))
cv_list = []
iter_list = []
model_list = []
for i, seed in enumerate(seed_list):


    if i>0:
        train.reset_index(inplace=True)

    LGBM = lgb_ex(logger=logger, metric=metric, model_type=model_type, ignore_list=ignore_list)
    LGBM.seed = seed

    #  if i>=5:
    #      params['num_leaves'] = 48
    #      params['subsample'] = 0.8757099996397999
    #      params['colsample_bytree'] = 0.7401342964627846
    #      params['min_child_samples'] = 61

    #========================================================================
    # Validation Setting vvv
    # Validation Set はFitさせたいFirst month のグループに絞る

    # 1. マイナスでOutlierの閾値を切って、それらの分布が揃う様にKFoldを作る
    if sys.argv[4]=='minus':
        train['outliers'] = train[target].map(lambda x: 1 if x < outlier_thres else 0)
        folds = StratifiedKFold(n_splits=fold, shuffle=True, random_state=seed)
        kfold = folds.split(train,train['outliers'].values)
        train.drop('outliers', axis=1, inplace=True)

    # 2. プラスマイナスでOutlierの閾値を切って、プラス、マイナス別に分布が揃う様にKFoldを作る
    elif sys.argv[4]=='pmo':
        if train[target].min()>-30:
            print(f"Max Target: {train[target].max()}. Don't Use Option: pmo")
            sys.exit()

        plus  = train[train[target] >= 0]
        tmp_minus = train[train[target] <  0]
        minus = tmp_minus[tmp_minus[target] >  -30]
        out = tmp_minus[tmp_minus[target] <  -30]

        plus['outliers'] = plus[target].map(lambda x: 1 if x>=outlier_thres*-1 else 0)
        minus['outliers'] = minus[target].map(lambda x: 1 if x<=outlier_thres else 0)
        out['outliers'] = out[target].map(lambda x: 1 if x<=outlier_thres else 0)

        folds = StratifiedKFold(n_splits=fold, shuffle=True, random_state=seed)
        kfold_plus = folds.split(plus, plus['outliers'].values)
        kfold_minus = folds.split(minus, minus['outliers'].values)
        kfold_out = folds.split(out, out['outliers'].values)

        trn_idx_list = []
        val_idx_list = []
        for (p_trn_idx, p_val_idx), (m_trn_idx, m_val_idx), (o_trn_idx, o_val_idx) in zip(kfold_plus, kfold_minus, kfold_out):

            def get_ids(df, idx):
                ids = list(df.iloc[idx, :][key].values)
                return ids

            trn_ids = get_ids(plus, p_trn_idx) + get_ids(minus, m_trn_idx) + get_ids(out, o_trn_idx)
            val_ids = get_ids(plus, p_val_idx) + get_ids(minus, m_val_idx) + get_ids(out, o_val_idx)

            # idをindexの番号にする
            trn_ids = list(train[train[key].isin(trn_ids)].index)
            val_ids = list(train[train[key].isin(val_ids)].index)

            trn_idx_list.append(trn_ids)
            val_idx_list.append(val_ids)
        kfold = zip(trn_idx_list, val_idx_list)

    elif sys.argv[4]=='pm':
        plus  = train[train[target] >= 0]
        minus = train[train[target] <  0]

        plus['outliers'] = plus[target].map(lambda x: 1 if x>=outlier_thres*-1 else 0)
        minus['outliers'] = minus[target].map(lambda x: 1 if x<=outlier_thres else 0)

        folds = StratifiedKFold(n_splits=fold, shuffle=True, random_state=seed)
        kfold_plus = folds.split(plus, plus['outliers'].values)
        kfold_minus = folds.split(minus, minus['outliers'].values)

        trn_idx_list = []
        val_idx_list = []
        for (p_trn_idx, p_val_idx), (m_trn_idx, m_val_idx) in zip(kfold_plus, kfold_minus):

            def get_ids(df, idx):
                ids = list(df.iloc[idx, :][key].values)
                return ids

            trn_ids = get_ids(plus, p_trn_idx) + get_ids(minus, m_trn_idx)
            val_ids = get_ids(plus, p_val_idx) + get_ids(minus, m_val_idx)

            # idをindexの番号にする
            trn_ids = list(train[train[key].isin(trn_ids)].index)
            val_ids = list(train[train[key].isin(val_ids)].index)

            trn_idx_list.append(trn_ids)
            val_idx_list.append(val_ids)
        kfold = zip(trn_idx_list, val_idx_list)


    elif sys.argv[4]=='out':
        train['outliers'] = train[target].map(lambda x: 1 if x<-30 else 0)
        folds = StratifiedKFold(n_splits=fold, shuffle=True, random_state=seed)
        kfold = list(folds.split(train,train['outliers'].values))
        train.drop('outliers', axis=1, inplace=True)

    elif sys.argv[4]=='ods':

        #========================================================================
        # ods.ai 3rd kernel
        # https://www.kaggle.com/c/elo-merchant-category-recommendation/discussion/78903
        # KFold: n_splits=6(or 7)!, shuffle=False!
        #========================================================================
        train['rounded_target'] = train['target'].round(0)
        train = train.sort_values('rounded_target').reset_index(drop=True)
        vc = train['rounded_target'].value_counts()
        vc = dict(sorted(vc.items()))
        df = pd.DataFrame()
        train['indexcol'],idx = 0,1
        for k,v in vc.items():
            step = train.shape[0]/v
            indent = train.shape[0]/(v+1)
            df2 = train[train['rounded_target'] == k].sample(v, random_state=120).reset_index(drop=True)
            for j in range(0, v):
                df2.at[j, 'indexcol'] = indent + j*step + 0.000001*idx
            df = pd.concat([df2,df])
            idx+=1
        train = df.sort_values('indexcol', ascending=True).reset_index(drop=True)
        del train['indexcol'], train['rounded_target']
        kfold = False
        fold_type = 'kfold'
        fold = 6

    # 3. Default KFold
    else:
        kfold = False
        fold_type = 'kfold'
    #========================================================================

    train.sort_index(axis=1, inplace=True)
    test.sort_index(axis=1, inplace=True)

    #========================================================================
    # Train & Prediction Start
    #========================================================================
    #  LGBM = LGBM.cross_prediction(
    LGBM = LGBM.dist_prediction(
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
        ,self_predict=self_predict
    )

    seed_pred += LGBM.prediction

    if i==0:
        cv_list.append(LGBM.cv_score)
        iter_list.append(LGBM.iter_avg)
        cv_feim = LGBM.cv_feim
        feature_num = len(LGBM.use_cols)
        df_pred = LGBM.result_stack.copy()[[key, 'prediction']]
        df_pred = base[[key, target]].merge(df_pred, how='left', on=key)
    else:
        cv_score = LGBM.cv_score
        cv_list.append(cv_score)
        iter_list.append(LGBM.iter_avg)
        LGBM.cv_feim.columns = [col if col.count('feature') else f"{col}_{seed}" for col in LGBM.cv_feim.columns]
        cv_feim = cv_feim.merge(LGBM.cv_feim, how='inner', on='feature')
        df_pred = df_pred.merge(LGBM.result_stack[[key, 'prediction']].rename(columns={'prediction':f'prediction_{i}'}), how='left', on=key)

#========================================================================
# STACKING
if len(stack_name)>0:
    logger.info(f'result_stack shape: {df_pred.shape}')
    if len(seed_list)>1:
        pred_cols = [col for col in df_pred.columns if col.count('predict')]
        df_pred['pred_mean'] = df_pred[pred_cols].mean(axis=1)
        df_pred['pred_std'] = df_pred[pred_cols].std(axis=1)
        df_pred.drop(pred_cols, axis=1, inplace=True)
#========================================================================


#========================================================================
# Result
cv_score = np.mean(cv_list)
iter_avg = np.int(np.mean(iter_list))
#========================================================================

logger.info(f'''
#========================================================================
# {len(seed_list)}SEED CV SCORE AVG: {cv_score}
#========================================================================''')

#========================================================================
# Part of card_id Score
part_score_list = []
part_N_list = []
fam_list = []
#  for i in range(201101, 201713, 1):
for i in range(201601, 201713, 1):
    fam = str(i)[:4] + '-' + str(i)[-2:]
    df_part = base_train[base_train['first_active_month']==fam]
    if len(df_part)<1:
        continue
    part_id_list = df_part[key].values

    part_train = df_pred.loc[df_pred[key].isin(part_id_list), :]
    y_train = part_train[target].values
    if 'pred_mean' in list(part_train.columns):
        y_pred = part_train['pred_mean'].values
    else:
        y_pred = part_train['prediction'].values

    y_pred = np.where(y_pred != y_pred, 0, y_pred)
    # RMSE
    part_score = np.sqrt(mean_squared_error(y_train, y_pred))

    fam_list.append(fam)
    part_score_list.append(part_score)
    part_N_list.append(len(part_id_list))

#  for i, part_score, N in zip(fam_list, part_score_list, part_N_list):
df = pd.DataFrame(np.asarray([fam_list, part_score_list, part_N_list]).T)
df.columns = ['FAM', 'CV', 'N']

# FAM: {i} | CV: {part_score} | N: {len(part_id_list)}
pd.set_option('max_rows', 200)
logger.info(f'''
#========================================================================
# {df}
#========================================================================''')
#========================================================================


if len(train)>150000:
    if len(train[train[target]<-30])>0:
        # outlierに対するスコアを出す
        train.reset_index(inplace=True)
        out_ids = train.loc[train.target<-30, key].values
        out_val = train.loc[train.target<-30, target].values
        if len(seed_list)==1:
            out_pred = df_pred[df_pred[key].isin(out_ids)]['prediction'].values
        else:
            out_pred = df_pred[df_pred[key].isin(out_ids)]['pred_mean'].values
        out_score = np.sqrt(mean_squared_error(out_val, out_pred))
    else:
        out_score = 0
else:
    out_score = 0

# Save
utils.to_pkl_gzip(path=f"../stack/{start_time[4:12]}_stack_{model_type}_lr{learning_rate}_{feature_num}feats_val{sys.argv[4]}_{len(seed_list)}seed_{num_leaves}leaves_iter{iter_avg}_CV{str(cv_score).replace('.', '-')}_LB", obj=df_pred)

# 不要なカラムを削除
drop_feim_cols = [col for col in cv_feim.columns if col.count('importance_') or col.count('rank_')]
cv_feim.drop(drop_feim_cols, axis=1, inplace=True)
drop_feim_cols = [col for col in cv_feim.columns if col.count('importance') and not(col.count('avg'))]
cv_feim.drop(drop_feim_cols, axis=1, inplace=True)
cv_feim.to_csv( f'../valid/{start_time[4:12]}_valid_{model_type}_lr{learning_rate}_{feature_num}feats_val{sys.argv[4]}_{len(seed_list)}seed_{num_leaves}leaves_iter{iter_avg}_CV{cv_score}_LB.csv' , index=False)
