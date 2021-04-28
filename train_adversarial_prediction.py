import numpy as np
import torch
import time
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable
import glob
import os
from utils import *
from model_adversial import *
from layers_adversial import *
from sklearn.preprocessing import MinMaxScaler
import shutil
from numpy import inf

seed = 0x6a09e667f3bcc908
np.random.normal(seed & 0xFFFFFFFF)
torch.manual_seed(seed & 0xFFFFFFFF)

lmbda = 0.5
time_step = 120
batch_size = 42
# 66, 68, 70, 7, 71, 42, 43, 22, 24, 28
target_region = 42
target_cat = 3  # (starts from 0)
gen_gat_adj_file(target_region)  # generate the adj_matrix file for GAT layers

loaded_data = torch.from_numpy(np.loadtxt("data/com_crime/r_" + str(target_region) + ".txt", dtype=np.int)).T
loaded_data = loaded_data[:, target_cat:target_cat + 1]
tensor_ones = torch.from_numpy(np.ones((loaded_data.size(0), loaded_data.size(1)), dtype=np.int))
# loaded_data = torch.where(loaded_data > 1, tensor_ones, loaded_data)  # Needed for classification Problem
x, y, x_daily, x_weekly = create_inout_sequences(loaded_data, time_step)

# scale your data to [-1: 1]
scale = MinMaxScaler(feature_range=(-1, 1))
x = torch.from_numpy(scale.fit_transform(x))
x_daily = torch.from_numpy(scale.fit_transform(x_daily))
x_weekly = torch.from_numpy(scale.fit_transform(x_weekly))
y = torch.from_numpy(scale.fit_transform(y))

# Divide your data into train set & test set
train_x_size = int(x.shape[0] * .67)  # batch_size
train_x = x[: train_x_size, :]  # (batch_size, time-step) = (1386, 120)
train_x_daily = x_daily[: train_x_size, :]
train_x_weekly = x_weekly[: train_x_size, :]
train_y = y[: train_x_size, :]  # (batch_size, time-step) = (1386, 1)

test_x = x[train_x_size:, :]  # (batch_size, time-step) = (683, 120)
test_x_daily = x_daily[train_x_size:, :]
test_x_weekly = x_weekly[train_x_size:, :]
test_x = test_x[:test_x.shape[0] - 11, :]  # (batch_size, time-step) = (672, 120) -- to make it consistent with the
# batch size
test_x_daily = test_x_daily[:test_x_daily.shape[0] - 11, :]
test_x_weekly = test_x_weekly[:test_x_weekly.shape[0] - 11, :]
test_y = y[train_x_size:, :]  # (batch_size, time-step) = (683, 1)
test_y = test_y[:test_y.shape[0] - 11, :]

# Divide it into batches -----> (Num of Batches, batch size, time-step features)
train_x = train_x.view(int(train_x.shape[0] / batch_size), batch_size, time_step)
train_x_daily = train_x_daily.view(int(train_x_daily.shape[0] / batch_size), batch_size, train_x_daily.shape[1])
train_x_weekly = train_x_weekly.view(int(train_x_weekly.shape[0] / batch_size), batch_size, train_x_weekly.shape[1])
train_y = train_y.view(int(train_y.shape[0] / batch_size), batch_size, 1)

test_x = test_x.view(int(test_x.shape[0] / batch_size), batch_size, time_step)
test_x_daily = test_x_daily.view(int(test_x_daily.shape[0] / batch_size), batch_size, test_x_daily.shape[1])
test_x_weekly = test_x_weekly.view(int(test_x_weekly.shape[0] / batch_size), batch_size, test_x_weekly.shape[1])
test_y = test_y.view(int(test_y.shape[0] / batch_size), batch_size, 1)

# load data for spatial features
train_feat, test_feat = load_data_regions(target_cat, target_region)
train_feat_ext, test_feat_ext = load_data_regions_external_v2(target_region)
train_crime_side, test_crime_side = load_data_sides_crime(target_cat, target_region)

# Model and optimizer
nfeature = 1  # num of feature per time-step
nhid = 40  # num of features in hidden dimensions of rnn 64
nlayer = 1
nclasses = 2

model = Temporal_Module(nfeature, nhid, nlayer, nclasses, target_region, target_cat)
print(model)
n = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(n)

lr = 0.001  # initial learning rate 0.004
weight_decay = 5e-4  # Weight decay = (L2 loss on parameters)
optimizer = optim.Adam(model.parameters(), lr=lr)
# optimizer = optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=lr)
# criterion = nn.KLDivLoss(size_average=None, reduce=None, reduction='sum')
# criterion = nn.MSELoss()
criterion = nn.L1Loss()


epochs = 300
best = epochs + 1
best_epoch = 0
t_total = time.time()
loss_values = []
bad_counter = 0
patience = 100

train_batch = train_x.shape[0]
test_batch = test_x.shape[0]
print(train_batch, test_batch)
"""r_att = np.loadtxt("Adversial/r_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
f_att = np.loadtxt("Adversial/f_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
re_att = np.loadtxt("Adversial/re_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
d_att = np.loadtxt("Adversial/d_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
w_att = np.loadtxt("Adversial/w_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
t_att = np.loadtxt("Adversial/t_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
o = np.loadtxt("Adversial/o_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)"""

"""def compute_train():
    loss = 0
    for i in range(train_batch):
        model.eval()

        x_crime_train = Variable(train_x[i]).float()
        x_crime_daily_train = Variable(train_x_daily[i]).float()
        x_crime_weekly_train = Variable(train_x_weekly[i]).float()
        y_train = Variable(train_y[i]).float()
        # y_test = y_test.view(y_test.shape[0]).long()  # cross entropy

        # test_feat = region_daily_crime; test_feat_ext = external features
        output_train, list_att = model(x_crime_train, x_crime_daily_train, x_crime_weekly_train, train_feat[i],
                                           train_x[i], train_feat_ext[i], train_crime_side[i])
        y_train = y_train.view(-1, 1)

        # Do not scale
        # y_train = torch.from_numpy(scale.inverse_transform(y_train))
        # output_train = torch.from_numpy(scale.inverse_transform(output_train.detach()))

        r_att = open("Adversial/r_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        r_att_arr = list_att[0].detach().numpy()
        np.savetxt(r_att, r_att_arr, fmt="%f")
        r_att.close()

        f_att = open("Adversial/f_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        f_att_arr = list_att[1].detach().numpy()
        np.savetxt(f_att, f_att_arr, fmt="%f")
        f_att.close()

        re_att = open("Adversial/re_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        re_att_arr = list_att[2].detach().numpy()
        np.savetxt(re_att, re_att_arr, fmt="%f")
        re_att.close()

        d_att = open("Adversial/d_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        d_att_arr = list_att[3].detach().numpy()
        np.savetxt(d_att, d_att_arr, fmt="%f")
        d_att.close()

        w_att = open("Adversial/w_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        w_att_arr = list_att[4].detach().numpy()
        np.savetxt(w_att, w_att_arr, fmt="%f")
        w_att.close()

        t_att = open("Adversial/t_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        t_att_arr = list_att[5].detach().numpy()
        np.savetxt(t_att, t_att_arr, fmt="%f")
        t_att.close()

        o = open("Adversial/o_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        o_arr = output_train.detach().numpy()
        np.savetxt(o, o_arr, fmt="%f")
        o.close()

        loss_test = criterion(output_train, y_train)

        # for j in range(42):
        #   print(y_test[j, :].data.item(), output_test[j, :].data.item())

        loss += loss_test.data.item()
        print("Test set results:",
              "loss= {:.4f}".format(loss_test.data.item()))

    print(loss / i)
    print(target_region, " ", target_cat, " ", loss / i, file=f)


compute_train()"""

"""for epoch in range(epochs):
    i = 0
    loss_values_batch = []
    r_att = np.loadtxt("Adversial/r_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
    f_att = np.loadtxt("Adversial/f_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
    re_att = np.loadtxt("Adversial/re_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
    d_att = np.loadtxt("Adversial/d_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
    w_att = np.loadtxt("Adversial/w_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
    t_att = np.loadtxt("Adversial/t_a_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
    o = np.loadtxt("Adversial/o_" + str(target_region) + "_" + str(target_cat) + ".txt", dtype=np.float)
    for i in range(train_batch):
        t = time.time()

        x_crime = Variable(train_x[i]).float()
        x_crime_daily = Variable(train_x_daily[i]).float()
        x_crime_weekly = Variable(train_x_weekly[i]).float()
        y = Variable(train_y[i]).float()
        # y = y.view(y.shape[0]).long()  # cross entropy, MAE loss works fine, does not work for MSE loss

        model.train()
        optimizer.zero_grad()
        output, list_att = model(x_crime, x_crime_daily, x_crime_weekly, train_feat[i], train_x[i], train_feat_ext[i],
                                 train_crime_side[i])
        y = y.view(-1, 1)

        r_att = open("Adversial/r_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        r_att_arr = list_att[0].detach().numpy()
        np.savetxt(r_att, r_att_arr, fmt="%f")
        r_att.close()

        f_att = open("Adversial/f_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        f_att_arr = list_att[1].detach().numpy()
        np.savetxt(f_att, f_att_arr, fmt="%f")
        f_att.close()

        re_att = open("Adversial/re_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        re_att_arr = list_att[2].detach().numpy()
        np.savetxt(re_att, re_att_arr, fmt="%f")
        re_att.close()

        d_att = open("Adversial/d_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        d_att_arr = list_att[3].detach().numpy()
        np.savetxt(d_att, d_att_arr, fmt="%f")
        d_att.close()

        w_att = open("Adversial/w_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        w_att_arr = list_att[4].detach().numpy()
        np.savetxt(w_att, w_att_arr, fmt="%f")
        w_att.close()

        t_att = open("Adversial/t_a_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        t_att_arr = list_att[5].detach().numpy()
        np.savetxt(t_att, t_att_arr, fmt="%f")
        t_att.close()

        o = open("Adversial/o_" + str(target_region) + "_" + str(target_cat) + ".txt", 'ab')
        o_arr = output.detach().numpy()
        np.savetxt(o, o_arr, fmt="%f")
        o.close()

        # For advarsarial exp
        idx = i * batch_size
        r_att_gold = torch.from_numpy(r_att[idx:idx + batch_size]).float()
        f_att_gold = torch.from_numpy(f_att[idx:idx + batch_size]).float()
        re_att_gold = torch.from_numpy(re_att[idx:idx + batch_size]).float()
        d_att_gold = torch.from_numpy(d_att[idx:idx + batch_size]).float()
        w_att_gold = torch.from_numpy(w_att[idx:idx + batch_size]).float()
        t_att_gold = torch.from_numpy(t_att[idx:idx + batch_size]).float()
        o_gold = torch.from_numpy(o[idx:idx + batch_size])

        total_loss_train = 0
        total_jsd = 0
        total_tvd = 0
        for _ in range(batch_size):
            kl_loss_r = criterion(r_att_gold[_].log(), list_att[0][_]).float()
            kl_loss_r[kl_loss_r == float('inf')] = 0
            kl_loss_f = criterion(f_att_gold[_].log(), list_att[1][_]).float()
            kl_loss_re = criterion(re_att_gold[_].log(), list_att[2][_]).float()
            kl_loss_d = criterion(d_att_gold[_].log(), list_att[3][_]).float()
            kl_loss_w = criterion(w_att_gold[_].log(), list_att[4][_]).float()
            kl_loss_t = criterion(t_att_gold[_].log(), list_att[5][_]).float()

            jsd_loss_r = instance_jsd(r_att_gold[_], list_att[0][_]).float()
            jsd_loss_r[kl_loss_r == float('inf')] = 0
            jsd_loss_f = instance_jsd(f_att_gold[_], list_att[1][_]).float()
            jsd_loss_re = instance_jsd(re_att_gold[_], list_att[2][_]).float()
            jsd_loss_d = instance_jsd(d_att_gold[_], list_att[3][_]).float()
            jsd_loss_w = instance_jsd(w_att_gold[_], list_att[4][_]).float()
            jsd_loss_t = instance_jsd(t_att_gold[_], list_att[5][_]).float()

            losses = [kl_loss_r, kl_loss_f, kl_loss_re, kl_loss_d, kl_loss_w, kl_loss_t]
            # print("KLD = ", kl_loss_r.data.item(), kl_loss_f.data.item(), kl_loss_re.data.item(),
            # kl_loss_d.data.item(), kl_loss_w.data.item(), kl_loss_t.data.item())

            jsd_losses = [jsd_loss_r, jsd_loss_f, jsd_loss_re, jsd_loss_d, jsd_loss_w, jsd_loss_t]
            total_jsd_losses = sum(jsd_losses).float()
            # print("JSD = ", jsd_loss_r.data.item(), jsd_loss_f.data.item(), jsd_loss_re.data.item(),
            # jsd_loss_d.data.item(), jsd_loss_w.data.item(), jsd_loss_t.data.item())

            tvd_loss = batch_tvd(output[_], o_gold[_])
            # print("TVD = ", tvd_loss.data.item())

            loss_train = tvd_loss - lmbda * sum(losses).float()
            total_loss_train += loss_train
            total_tvd += tvd_loss
            total_jsd += total_jsd_losses

        # print("TVD = ", total_tvd.data.item() / batch_size)
        # print("JSD = ", total_jsd.data.item() / batch_size)
        # print("LOSS = ", total_loss_train.data.item())
        # print("---------------------------------------------------------------------------")
        total_loss_train.backward()
        optimizer.step()

        # loss_train = criterion(output, y)
        # loss_train.backward()
        # optimizer.step()

        print('Epoch: {:04d}'.format(epoch * train_batch + i + 1),
              'loss_train: {:.4f}'.format(total_loss_train.data.item()),
              'tvd: {:.4f}'.format(total_tvd.data.item() / batch_size),
              'jsd: {:.4f}'.format(total_jsd.data.item() / batch_size),
              'time: {:.4f}s'.format(time.time() - t))

        loss_values.append(loss_train)
        torch.save(model.state_dict(), '{}.pkl'.format(epoch * train_batch + i + 1))
        if loss_values[-1] < best:
            best = loss_values[-1]
            best_epoch = epoch * train_batch + i + 1
            bad_counter = 0
        else:
            bad_counter += 1

        if bad_counter == patience:
            break

        files = glob.glob('*.pkl')
        for file in files:
            epoch_nb = int(file.split('.')[0])
            if epoch_nb < best_epoch:
                os.remove(file)

    files = glob.glob('*.pkl')
    for file in files:
        epoch_nb = int(file.split('.')[0])
        if epoch_nb > best_epoch:
            os.remove(file)

    if epoch * train_batch + i + 1 >= 800:
        break
print("Optimization Finished!")
print("Total time elapsed: {:.4f}s".format(time.time() - t_total))"""

# best_epoch = 699 print('Loading {}th epoch'.format(best_epoch)) shutil.copy('{}.pkl'.format(best_epoch),
# 'E:/AIST_ADV/' + str(target_region) + '_' + str(target_cat) + '_' + str(lmbda) + '_F.pkl')
# model.load_state_dict(torch.load('{}.pkl'.format(best_epoch)))
# 22, 24, 28, 31
model.load_state_dict(torch.load('E:/AIST_ADV/' + str(target_region) + '_' + str(target_cat) + '_1_F.pkl'))
# model.load_state_dict(torch.load("Heatmap/" + str(target_region) + "_" + str(target_cat) + ".pkl"))

"""print("Model's state_dict:")
for param_tensor in model.state_dict():
    print(param_tensor, "\t", model.state_dict()[param_tensor].size())
    np.savetxt("wu.txt", model.state_dict()[param_tensor])"""

f = open('C:/Users/Yeasir Rayhan/PycharmProjects/AIST/aist_eval_adv_mae.txt', 'a')


def compute_test():
    loss = 0
    for i in range(test_batch):
        model.eval()

        x_crime_test = Variable(test_x[i]).float()
        x_crime_daily_test = Variable(test_x_daily[i]).float()
        x_crime_weekly_test = Variable(test_x_weekly[i]).float()
        y_test = Variable(test_y[i]).float()
        # y_test = y_test.view(y_test.shape[0]).long()  # cross entropy

        # test_feat = region_daily_crime; test_feat_ext = external features
        output_test, list_att_test = model(x_crime_test, x_crime_daily_test, x_crime_weekly_test, test_feat[i],
                                           test_x[i], test_feat_ext[i], test_crime_side[i])
        y_test = y_test.view(-1, 1)

        y_test = torch.from_numpy(scale.inverse_transform(y_test))
        output_test = torch.from_numpy(scale.inverse_transform(output_test.detach()))
        # print(output_test.detach().numpy().reshape(1, -1))
        # print(y_test.detach().numpy().reshape(1, -1))

        loss_test = criterion(output_test, y_test)
        loss += loss_test.data.item()
        print("Test set results:",
              "loss= {:.4f}".format(loss_test.data.item()))

    print(loss / i)
    print(target_region, " ", target_cat, " ", loss / i, file=f)


compute_test()

