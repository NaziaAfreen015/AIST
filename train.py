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
from model import *
from layers import *
from sklearn.preprocessing import MinMaxScaler
import shutil
import sys
import argparse as Ap

seed = 0x6a09e667f3bcc908
np.random.normal(seed & 0xFFFFFFFF)
torch.manual_seed(seed & 0xFFFFFFFF)

argp = Ap.ArgumentParser()
argp.add_argument("--tr", default=66, type=int, help="Target region")
argp.add_argument("--tc", default=3, type=int, help="Target category")
d = argp.parse_args(sys.argv[1:])

time_step = 120
batch_size = 42
target_region = 7  # 66 68 70 7 71 42 43 22 24 28
target_cat = 1  # 3(starts from 0)
gen_gat_adj_file(target_region)   # generate the adj_matrix file for GAT layers

loaded_data = torch.from_numpy(np.loadtxt("data/com_crime/r_" + str(target_region) + ".txt", dtype=np.int)).T
loaded_data = loaded_data[:, target_cat:target_cat+1]
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
# model = Temporal_Module_LSTM(nfeature, nhid, nlayer, nclasses, target_region, target_cat)
# print(model)
n = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(n)

lr = 0.001 # initial learning rate 0.004
weight_decay = 5e-4  # Weight decay = (L2 loss on parameters)
optimizer = optim.Adam(model.parameters(), lr=lr)
# optimizer = optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=lr)
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

for epoch in range(epochs):
    i = 0
    loss_values_batch = []
    for i in range(train_batch):  # 10
        t = time.time()

        x_crime = Variable(train_x[i]).float()
        x_crime_daily = Variable(train_x_daily[i]).float()
        x_crime_weekly = Variable(train_x_weekly[i]).float()
        y = Variable(train_y[i]).float()
        # y = y.view(y.shape[0]).long()  # cross entropy, MAE loss works fine, does not work for MSE loss

        model.train()
        optimizer.zero_grad()
        output, attn = model(x_crime, x_crime_daily, x_crime_weekly, train_feat[i], train_x[i], train_feat_ext[i], train_crime_side[i])
        y = y.view(-1, 1)

        loss_train = criterion(output, y)
        loss_train.backward()
        optimizer.step()

        """print('Epoch: {:04d}'.format(epoch*train_batch + i + 1),
              'loss_train: {:.4f}'.format(loss_train.data.item()),
              'time: {:.4f}s'.format(time.time() - t))"""

        loss_values.append(loss_train)
        torch.save(model.state_dict(), '{}.pkl'.format(epoch*train_batch + i + 1))
        if loss_values[-1] < best:
            best = loss_values[-1]
            best_epoch = epoch*train_batch + i + 1
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

    if epoch*train_batch + i + 1 >= 800:
        break
print("Optimization Finished!")
print("Total time elapsed: {:.4f}s".format(time.time() - t_total))

# best_epoch = 666
print('Loading {}th epoch'.format(best_epoch))
# shutil.copy('{}.pkl'.format(best_epoch), 'E:/sab_r/' + str(target_region) + '_' + str(target_cat) + '_mae.pkl')
# shutil.copy('{}.pkl'.format(best_epoch), 'E:/param/Q_' + str(Q) + '_' + str(target_region) + '_' + str(target_cat) + '_mae.pkl')
# shutil.copy('{}.pkl'.format(best_epoch), 'E:/gat+fgat' + str(target_region) + '_' + str(target_cat) + '_mae.pkl')
model.load_state_dict(torch.load('{}.pkl'.format(best_epoch)))
# model.load_state_dict(torch.load("Heatmap/" + str(target_region) + "_" + str(target_cat) + ".pkl"))

"""print("Model's state_dict:")
for param_tensor in model.state_dict():
    print(param_tensor, "\t", model.state_dict()[param_tensor].size())
    np.savetxt("wu.txt", model.state_dict()[param_tensor])"""

f = open('C:/Users/BD/PycharmProjects/AIST/aist_param_Q_mae.txt','a')


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
        output_test, attn_test = model(x_crime_test, x_crime_daily_test, x_crime_weekly_test, test_feat[i], test_x[i], test_feat_ext[i], test_crime_side[i])
        y_test = y_test.view(-1, 1)
        # print(attn_test.shape)

        """with open('E:/aist_datasets/base_prediction_trend/test_'+str(i)+'.pkl', 'wb') as f1:
            pickle.dump(output_test, f1)
        with open('E:/aist_datasets/base_attn_trend/test_' + str(i) + '.pkl', 'wb') as f2:
            pickle.dump(attn_test, f2)"""

        y_test = torch.from_numpy(scale.inverse_transform(y_test))
        output_test = torch.from_numpy(scale.inverse_transform(output_test.detach()))

        loss_test = criterion(output_test, y_test)

        """for j in range(42):
            print(y_test[j, :].data.item(), output_test[j, :].data.item())"""

        loss += loss_test.data.item()
        print("Test set results:",
              "loss= {:.4f}".format(loss_test.data.item()))

    print(target_region, " ", target_cat, " ", loss/i)
    print(target_region, " ", target_cat, " ", loss/i, file=f)


compute_test()

