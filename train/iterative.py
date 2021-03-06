import torch
import pickle
import shutil

import sys

sys.path.append("..")
from feature_extraction.stf_feats import generate_stf_feats
from feature_extraction.img_feats import generate_img_feats
from models import get_end2end_model, get_GR_model
from dataset import get_gr_datasets, get_end2end_datasets
from feature_extraction.gen_gr_dataset import generate_gloss_dataset
from train.end2end import train_end2end
from train.gloss_recog import train_gloss_recog
from vocab import Vocab
from config import *
from utils import check_stf_features

torch.backends.cudnn.enabled = False


def copy_iteration_model(iter_idx):
    dir = os.sep.join([ITER_WEIGHTS, STF_MODEL, str(IMG_FEAT_SIZE), str(iter_idx)])
    if not os.path.exists(dir):
        os.makedirs(dir)
    stf_path = os.path.join(dir, "STF.pt")
    seq2seq_path = os.path.join(dir, "SEQ2SEQ.pt")
    shutil.copy(STF_MODEL_PATH, stf_path)
    shutil.copy(SEQ2SEQ_MODEL_PATH, seq2seq_path)


def save_iters_info(iter_info_list, iters_info_path):
    dir = os.path.split(iters_info_path)[0]
    if not os.path.exists(dir):
        os.makedirs(dir)

    with open(iters_info_path, 'wb') as f:
        pickle.dump(iter_info_list, f)


def create_iter_info(iter_idx):
    return {"Iter_idx": iter_idx, "GR_DATA_DONE": False,
            "GR_ACC": None, "GR_TRAIN_DONE": False,
            "STF_FEATS_DONE": False, "STF_WER": None,
            "WER": None, "END2END_TRAIN_DONE": False}


def get_iters_info(iters_info_path):
    if not os.path.exists(iters_info_path):
        iter_info_list = [create_iter_info(0)]
        save_iters_info(iter_info_list, iters_info_path)
        return iter_info_list
    with open(iters_info_path, 'rb') as f:
        return pickle.load(f)


if __name__ == "__main__":
    iters_info_path = os.path.join(ITER_VARS_DIR, "iter_info.pkl")

    iter_info_list = get_iters_info(iters_info_path)
    vocab = Vocab()
    try:
        for iter_idx in range(N_ITER):
            if len(iter_info_list) <= iter_idx:
                iter_info_list.append(create_iter_info(iter_idx))

            print("Iteration", iter_idx, "Started")
            iter_info = iter_info_list[iter_idx]

            if iter_idx == 0:
                while not iter_info["END2END_TRAIN_DONE"]:
                    if USE_ST_FEAT:
                        if STF_TYPE == 0 and (not check_stf_features(img_feat=True)):
                            generate_img_feats()

                        if STF_TYPE == 1 and (not check_stf_features()):
                            generate_stf_feats()

                    model, _ = get_end2end_model(vocab, load_seq=False, stf_type=STF_TYPE, use_st_feat=USE_ST_FEAT)
                    datasets = get_end2end_datasets(model, vocab)
                    best_wer, finished = train_end2end(model, vocab, datasets, use_feat=USE_ST_FEAT)
                    iter_info["WER"] = best_wer
                    iter_info["END2END_TRAIN_DONE"] = finished
                    save_iters_info(iter_info_list, iters_info_path)
                    model = None
                    torch.cuda.empty_cache()
            else:
                while not iter_info["GR_DATA_DONE"]:
                    generate_gloss_dataset(vocab)
                    iter_info["GR_DATA_DONE"] = True
                    save_iters_info(iter_info_list, iters_info_path)
                    torch.cuda.empty_cache()

                while not iter_info["GR_TRAIN_DONE"]:
                    model = get_GR_model(vocab)
                    datasets = get_gr_datasets()
                    gr_acc, finished = train_gloss_recog(model, datasets)
                    iter_info["GR_ACC"] = gr_acc
                    iter_info["GR_TRAIN_DONE"] = finished
                    save_iters_info(iter_info_list, iters_info_path)
                    model = None
                    torch.cuda.empty_cache()

                while not iter_info["STF_FEATS_DONE"]:
                    generate_stf_feats()
                    iter_info["STF_FEATS_DONE"] = True
                    save_iters_info(iter_info_list, iters_info_path)
                    torch.cuda.empty_cache()

                while not iter_info["END2END_TRAIN_DONE"]:
                    model, _ = get_end2end_model(vocab, load_seq=False, stf_type=STF_TYPE, use_st_feat=USE_ST_FEAT)
                    datasets = get_end2end_datasets(model, vocab)
                    best_wer, finished = train_end2end(model, vocab, datasets, use_feat=USE_ST_FEAT)
                    iter_info["WER"] = best_wer
                    iter_info["END2END_TRAIN_DONE"] = finished
                    save_iters_info(iter_info_list, iters_info_path)
                    model = None
                    torch.cuda.empty_cache()

            copy_iteration_model(iter_idx)
            print("Iteration", iter_idx, "Finished")
            print()
            print()


    except KeyboardInterrupt:
        print()
        print(iter_info_list)
