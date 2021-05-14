import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F
from layers import *
from utils import *
import pickle


class AIST(nn.Module):
    def __init__(self, nfeat, nhid, nlayer, nclass, target_region, target_cat):
        """
        :param nfeat:
        :param nhid:
        :param nlayer:
        :param nclass:
        :param target_region: starts with 0
        """
        super(AIST, self).__init__()
        self.nfeat = nfeat
        self.nhid = nhid
        self.nlayer = nlayer
        self.nclass = nclass
        self.att_dim = 30
        self.target_cat = target_cat
        self.target_region = target_region

        # F = 6, 8, 10, 12
        self.sp_module1 = Spatial_Module(1, 8, 0.5, 0.6, 1, 20, target_region, target_cat)

        self.sab1 = self_LSTM_sparse_attn_predict(2*8, nhid, nlayer, nclass, truncate_length=5, top_k=4,
                                                  attn_every_k=5, predict_m=10)  # changed to 8 --> 16
        self.sab2 = self_LSTM_sparse_attn_predict(1, nhid, nlayer, nclass, truncate_length=5, top_k=4, attn_every_k=5,
                                                  predict_m=10)
        self.sab3 = self_LSTM_sparse_attn_predict(1, nhid, nlayer, nclass, truncate_length=1, top_k=3, attn_every_k=1,
                                                  predict_m=10)

        # single fully connected layer for prediction
        self.fc1 = nn.Linear(nhid, 1)  # nclass -> 1
        self.fc2 = nn.Linear(2 * nhid, nclass)
        self.fc3 = nn.Linear(3 * nhid, nclass)
        # print(self.fc1.weight.shape)

        # parameters for attention
        self.wv = nn.Linear(nhid, self.att_dim)  # (S, E) x (E, 1) = (S, 1)
        # self.wu = nn.Parameter(torch.zeros(self.att_dim))  # attention of the trends

        # For evaluation of interpretability - 3.3, 3.4
        self.wu = nn.Parameter(torch.zeros(size=(42, self.att_dim)))  # attention of the trends
        nn.init.xavier_uniform_(self.wu.data, gain=1.414)
        # self.wu.requires_grad = False

        """self.wu = torch.from_numpy(np.loadtxt("wu.txt"))
        self.wu = self.wu.type(torch.FloatTensor)
        self.wu.requires_grad = False"""

        self.dropout_layer = nn.Dropout(p=0.2)

    def forward(self, x_crime, x_crime_daily, x_crime_weekly, x_regions, x_sp_crime, x_ext, s_crime):

        x_crime = self.sp_module1(x_sp_crime, x_regions, x_ext, s_crime)
        # print(x_crime.shape)

        # x_crime = self.dropout_layer(x_crime)
        x_con, x_con_attn = self.sab1(x_crime)
        x_con = self.dropout_layer(x_con)

        """re_att = open("Heatmap/re_a_" + str(self.target_region) + "_" + str(self.target_cat) + ".txt", 'ab')
        re_att_arr = x_con_attn.view(42, -1).softmax(dim=1).mean(dim=0).view(1, -1).detach().numpy()
        np.savetxt(re_att, re_att_arr, fmt="%f")
        re_att.close()"""

        # x_daily = (B, 20)
        x_daily, x_daily_attn = self.sab2(x_crime_daily)
        x_daily = self.dropout_layer(x_daily)

        """d_att = open("Heatmap/d_a_" + str(self.target_region) + "_" + str(self.target_cat) + ".txt", 'ab')
        d_att_arr = x_daily_attn.view(42, -1).softmax(dim=1).mean(dim=0).view(1, -1).detach().numpy()
        np.savetxt(d_att, d_att_arr, fmt="%f")
        d_att.close()"""

        # x_weekly = (B, 3): Commented 17 March
        x_weekly, x_weekly_attn = self.sab3(x_crime_weekly)
        x_weekly = self.dropout_layer(x_weekly)

        """w_att = open("Heatmap/w_a_" + str(self.target_region) + "_" + str(self.target_cat) + ".txt", 'ab')
        w_att_arr = x_weekly_attn.view(42, -1).softmax(dim=1).mean(dim=0).view(1, -1).detach().numpy()
        np.savetxt(w_att, w_att_arr, fmt="%f")
        w_att.close()"""

        # incorporating attention
        # Commented 18 March
        x_con = x_con.unsqueeze(1)
        x_daily = x_daily.unsqueeze(1)
        x_weekly = x_weekly.unsqueeze(1)

        x = torch.cat((x_con, x_daily, x_weekly), 1)
        # x = torch.cat((x_con, x_weekly), 1)
        # x = torch.cat((x_con, x_daily), 1)

        um = torch.tanh(self.wv(x))  # (B, 3, A)
        um = um.transpose(2, 1)  # [B, A, 3]
        wu = self.wu.unsqueeze(1)
        alpha_m = torch.bmm(wu, um)  # [B, 1, 3]
        alpha_m = alpha_m.squeeze(1)  # [B, 3]
        alpha_m = torch.softmax(alpha_m, dim=1)
        attn_trend = alpha_m.detach()

        """t_att = open("Heatmap/t_a_" + str(self.target_region) + "_" + str(self.target_cat) + ".txt", 'ab')
        t_att_arr = alpha_m.view(42, -1).mean(dim=0).view(1, -1).detach().numpy()
        np.savetxt(t_att, t_att_arr, fmt="%f")
        t_att.close()"""

        alpha_m = alpha_m.unsqueeze(1)

        # for interpretability evaluation task
        """alpha_m = torch.ones((42, 3))
        alpha_m = torch.softmax(alpha_m, dim=1)
        alpha_m = alpha_m.unsqueeze(1)"""

        # Commented 18 March
        x = torch.bmm(alpha_m, x)
        x = x.squeeze(1)
        x = torch.tanh(self.fc1(x))

        return x, attn_trend


class Spatial_Module(nn.Module):
    def __init__(self, nfeat, nhid, dropout, alpha, nheads, ts, target_region, target_cat):
        """

        :param nfeat:
        :param nhid:
        :param dropout:
        :param alpha:
        :param nheads:
        :param ts:
        :param target_region: starts with 0
        """
        super(Spatial_Module, self).__init__()
        self.nhid = nhid
        self.target_region = target_region
        self.target_cat = target_cat
        # self.gat = GraphAttentionLayer(nfeat, nhid, dropout=dropout, alpha=alpha)
        self.gat = [GraphAttentionLayer(nfeat, nhid, target_region, target_cat, dropout=dropout, alpha=alpha) for _ in range(ts)]
        for i, g in enumerate(self.gat):
            self.add_module('gat{}'.format(i), g)

    def forward(self, x_crime, x_regions, x_ext, s_crime):
        B = x_crime.shape[0]
        T = x_crime.shape[1]
        tem_x_regions = x_regions.copy()

        # label = torch.tensor([6, 23, 27, 31, 7]) ----- Added new
        reg = gen_neighbor_index_zero_with_target(self.target_region)
        label = torch.tensor(reg)

        label = label.repeat(T*B, 1)  # (T*B, 5)
        label = label.view(label.shape[0] * label.shape[1], 1).long()  # label-shape = (T * B * N, 1)

        x_crime = x_crime.transpose(1, 0)  # shape = (T, B)
        tem_x_regions.append(x_crime)

        N = len(tem_x_regions)  # Num of actual nodes

        feat = torch.stack(tem_x_regions, 2)  # (T, B, N)
        feat = feat.view(feat.shape[0]*feat.shape[1]*feat.shape[2], 1).long()  # (T*B*N, 1)
        feat = torch.cat([label, feat], dim=1)  # (T*B*N, 2) --> (Node Label, features)
        feat = feat.view(T, B*N, 2)
        # feat = feat.view(T, B, N, 2)

        nfeat = 12
        feat_ext = torch.stack(x_ext, 2)
        feat_ext = feat_ext.view(feat_ext.shape[0] * feat_ext.shape[1] * feat_ext.shape[2], -1).long()  # (T*B*N, nfeat)
        feat_ext = torch.cat([label, feat_ext], dim=1)  # (T*B*N, 2)
        feat_ext = feat_ext.view(T, B * N, nfeat+1)
        # feat_ext = feat_ext.view(T, B, N, nfeat + 1)

        crime_side = torch.stack(s_crime, 2)
        crime_side = crime_side.view(crime_side.shape[0]*crime_side.shape[1]*crime_side.shape[2], -1).long()  # (T*B*N, 1)
        crime_side = torch.cat([label, crime_side], dim=1)  # (T*B*N, 2)
        crime_side = crime_side.view(T, B * N, 2)  # (T, B*N, 2)
        # crime_side = crime_side.view(T, B, N, 2)  # (T, B*N, 2)

        spatial_output = []
        j = 0
        for i in range(100, 120):
            np.savetxt("gat_feat.txt", feat[i], fmt='%d')
            np.savetxt("gat_feat_ext.txt", feat_ext[i], fmt='%d')
            np.savetxt("gat_crime_side.txt", crime_side[i], fmt='%d')
            adj, features, features_ext, crime_side_features = load_data_GAT()

            out, ext = self.gat[j](features, adj, features_ext, crime_side_features)  # (N, F')(N, N, dv)
            # out = self.gat[j](features, adj, features_ext, crime_side_features)  # (N, F')(N, N, dv)

            # out = out.view(B, N, out.shape[1])
            out = out[:, -1, :]
            # ext = ext.view(B, N, ext.shape[1])

            # print(out.shape, ext.shape)

            # Commented this for Feature 5:19 AM
            ext = ext[:, -1, :]
            out = torch.stack((out, ext), dim=2)

            spatial_output.append(out)
            j = j + 1

        spatial_output = torch.stack(spatial_output, 1)
        return spatial_output
