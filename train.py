import time
import torch
import ctcdecode
import torch.nn as nn
import numpy as np
import Levenshtein as Lev
from torch.optim import RMSprop, Adam, SGD
from torch.optim.lr_scheduler import ReduceLROnPlateau
from numpy import random
from models import SLR, weights_init
from data import read_pheonix, split_batches

from utils import Vocab, print_progress
from config import *

random.seed(0)

torch.backends.cudnn.deterministic = True


# TODO
# googlenet train
# hand features

# evaluate and try training samples,
# if they are ok, try fix lstm weights and re-train temporal fusion with predicted glosses


# debug from CRNN => padded outputs, maybe inputs
# permutations
# try tensorflow


def predict_glosses(preds, vocab, decoder):
    out_gloss = []
    out_idx = []
    if decoder:
        beam_result, beam_scores, timesteps, out_seq_len = decoder.decode(preds)
        for i in range(preds.size(0)):
            hypo = list(beam_result[i][0][:out_seq_len[i][0]])
            out_idx += hypo
            out_gloss.append(" ".join([vocab.idx2gloss[x] for x in hypo]))
    else:
        preds = preds.argmax(dim=2).cpu().numpy()
        # glosses_batch = vocab.decode_batch(preds)
        for pred in preds:
            hypo = []
            for i in range(len(pred)):
                if pred[i] == 0 or (i > 0 and pred[i] == pred[i - 1]):
                    continue
                hypo.append(pred[i])

            out_idx += hypo
            out_gloss.append(" ".join([vocab.idx2gloss[x] for x in hypo]))

    return out_gloss, out_idx


def get_split_wer(model, device, X, y, vocab, batch_size=16, beam_search=False):
    hypes = []
    gts = []
    model.eval()

    decoder = None
    if beam_search:
        decoder = ctcdecode.CTCBeamDecoder(vocab.idx2gloss, beam_width=20,
                                           blank_id=0, log_probs_input=True)

    with torch.no_grad():
        X_batches, y_batches = split_batches(X, y, batch_size, shuffle=False, target_format=2)

        for idx in range(len(X_batches)):
            X_batch, y_batch = X_batches[idx], y_batches[idx]
            inp = torch.Tensor(X_batch).unsqueeze(1).to(device)
            preds = model(inp).permute(1, 0, 2)
            out, out_idx = predict_glosses(preds, vocab, decoder)

            gt_batch = [" ".join(gt) for gt in vocab.decode_batch(y_batch)]

            if idx == 10:
                print("EXAMPLE: [" + gt_batch[0] + "]", "[" + out[0] + "]")

            for gt in y_batch:
                gts += gt

            hypes += out_idx

    hypes = "".join([chr(x) for x in hypes])
    gts = "".join([chr(x) for x in gts])
    return Lev.distance(hypes, gts) / len(gts) * 100


def train(model, device, vocab, X_tr, y_tr, X_dev, y_dev, X_test, y_test, optimizer, n_epochs, batch_size):
    scheduler = ReduceLROnPlateau(optimizer, verbose=True, patience=5)

    loss_fn = nn.CTCLoss(zero_infinity=True)

    best_dev_wer = get_split_wer(model, device, X_dev, y_dev, vocab)
    print("DEV WER:", best_dev_wer)
    for epoch in range(1, n_epochs + 1):
        print("Epoch", epoch)
        start_time = time.time()
        tr_losses = []
        model.train()
        X_batches, y_batches = split_batches(X_tr, y_tr, batch_size, target_format=1)
        for idx in range(len(X_batches)):
            optimizer.zero_grad()

            X_batch, y_batch = X_batches[idx], y_batches[idx]

            inp = torch.Tensor(X_batch).unsqueeze(1).to(device)
            pred = model(inp)

            T, N, V = pred.shape

            gt = torch.IntTensor(y_batch[0])
            inp_lens = torch.full(size=(N,), fill_value=T, dtype=torch.int32)
            gt_lens = torch.IntTensor(y_batch[1])

            loss = loss_fn(pred, gt, inp_lens, gt_lens)

            if torch.isnan(loss):
                print("NAN!!")

            # loss_batch = loss.detach().cpu().numpy()
            # tr_losses += [x for x in loss_batch]

            tr_losses.append(loss.item())

            loss.backward()
            optimizer.step()

            if idx % 10 == 0:
                print_progress(idx + 1, len(y_batches), start_time)

        print()
        train_wer = get_split_wer(model, device, X_tr, y_tr, vocab)
        if epoch % 5 == 0:
            print("Train Loss:", np.mean(tr_losses), "Train WER:", train_wer)
        else:
            print("Train Loss:", np.mean(tr_losses))

        print("Train Loss:", np.mean(tr_losses))

        dev_wer = get_split_wer(model, device, X_dev, y_dev, vocab)
        print("DEV WER:", dev_wer)
        if dev_wer < best_dev_wer:
            test_wer = get_split_wer(model, device, X_test, y_test, vocab)
            # test_wer = dev_wer
            best_dev_wer = dev_wer
            torch.save(model.state_dict(), os.sep.join([WEIGHTS_DIR, "slr.pt"]))
            print("Model Saved", "TEST WER:", test_wer)

        if scheduler:
            scheduler.step(dev_wer)

        print()
        print()


if __name__ == "__main__":
    vocab = Vocab(source="pheonix")
    X_tr, y_tr = read_pheonix("train", vocab, save=True)
    X_test, y_test = read_pheonix("test", vocab, save=True)
    X_dev, y_dev = read_pheonix("dev", vocab, save=True)
    print()

    device = torch.device("cuda:0")
    model = SLR(rnn_hidden=512, vocab_size=vocab.size).to(device)

    if os.path.exists(os.sep.join([WEIGHTS_DIR, "slr.pt"])):
        model.load_state_dict(torch.load(os.sep.join([WEIGHTS_DIR, "slr.pt"])))
        print("Model Loaded")
    else:
        model.apply(weights_init)

    lr = 0.0001
    # optimizer = SGD(model.parameters(), lr=lr, nesterov=True)
    # optimizer = RMSprop(model.parameters(), lr=lr)
    optimizer = Adam(model.parameters(), lr=lr)
    train(model, device, vocab, X_tr, y_tr, X_dev, y_dev, X_test, y_test, optimizer, n_epochs=200, batch_size=8)

    # y_tr
