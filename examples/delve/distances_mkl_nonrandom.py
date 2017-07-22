"""
    Evaluation of low-rank kernel approximation methods
    with ridge regression on standard datasets.
"""
# Kernels
import os
import csv
import numpy as np
import scipy.stats as st
import itertools as it
import matplotlib.pyplot as plt
import datetime
from matplotlib.ticker import MaxNLocator
from sklearn.manifold.mds import MDS
from mklaren.kernel.kernel import exponential_kernel, kernel_sum, periodic_kernel
from mklaren.kernel.kinterface import Kinterface
from datasets.keel import load_keel, KEEL_DATASETS

from mklaren.mkl.mklaren import Mklaren
from mklaren.projection.rff import RFF
from mklaren.regression.ridge import RidgeLowRank
from mklaren.regression.fitc import FITC

# Datasets and options
# Load max. 1000 examples
outdir = "../output/delve_regression/distances_nonrandom/"
n    = 1000
p_tr = 0.66
rank = 10
delta = 10
lbd = 0.01
plot = False
# gam_range = np.logspace(-8, 8, 17, base=2)
gam_range = np.logspace(3, 3, 7, base=2)
meths = ["Mklaren", "CSI", "RFF", "FITC"]

# Fixed output
# Create output directory
d = datetime.datetime.now()
dname = os.path.join("..", "output", "delve_regression", "distances_nonrandom",
                     "%d-%d-%d" % (d.year, d.month, d.day))
if not os.path.exists(dname): os.makedirs(dname)
rcnt = len(os.listdir(dname))
fname = os.path.join(dname, "results_%d.csv" % rcnt)

# Output
header = ["dataset", "n", "method", "rank", "iteration", "lambda",
          "p", "evar_tr", "evar", "corr", "corr.p", "dcorr", "dcorr.p"]
fp = open(fname, "w", buffering=0)
writer = csv.DictWriter(fp, fieldnames=header)
writer.writeheader()


# Kernels
kernels = []
kernels.extend([(exponential_kernel, {"gamma": g}) for g in gam_range])
# kernels.extend([(periodic_kernel, {"l": g}) for g in gam_range])

for dset_sub in KEEL_DATASETS:
    # Load data
    data = load_keel(name=dset_sub, n=n)
    X = data["data"]
    X = X - X.mean(axis=0)
    nrm = np.linalg.norm(X, axis=0)
    nrm[np.where(nrm == 0)] = 1
    X /= nrm
    y = st.zscore(data["target"])
    y -= y.min()

    # Deduce number of training samples
    n_tr = int(p_tr * X.shape[0])

    # Fit MDS (2D)
    model = MDS(n_components=2, random_state=42)
    Z = model.fit_transform(X)
    zxa, zya = np.min(Z, axis=0)
    zxb, zyb = np.max(Z, axis=0)
    Zp = np.array(list(it.product(np.linspace(zxa, zxb, 100),
                                  np.linspace(zya, zyb, 100))))
    zx = Zp[:,0].reshape((100, 100))
    zy = Zp[:,1].reshape((100, 100))

    # Define training and test set
    center = Z.mean(axis=0)
    distance = np.sqrt(np.power(Z - center, 2).sum(axis=1))
    tr = np.where(st.rankdata(distance) < n_tr)[0]
    te = np.where(st.rankdata(distance) >= n_tr)[0]

    # Fit methods on Z
    for method in meths:
        Ks = [Kinterface(data=Z[tr],
                         kernel=kern[0],
                         kernel_args=kern[1]) for kern in kernels]
        Ksum = Kinterface(data=Z[tr],
                          kernel=kernel_sum,
                          kernel_args={"kernels": [kern[0] for kern in kernels],
                                       "kernels_args": [kern[1] for kern in kernels]})

        if method == "Mklaren":

            mklaren = Mklaren(rank=rank, delta=delta, lbd=lbd)
            try:
                mklaren.fit(Ks, y[tr])
            except Exception as e:
                print(e)
                continue
            inxs = set().union(*[set(mklaren.data[i]["act"])
                                 for i in range(len(gam_range))])
            inxs = tr[list(inxs)]
            Yt = mklaren.predict([Z[tr] for g in gam_range])
            Yp = mklaren.predict([Z[te] for g in gam_range])
            Fp = mklaren.predict([Zp for g in gam_range])
        elif method == "FITC":
            model = FITC(rank=rank)
            model.fit(Ks, y[tr])
            Yt = model.predict([Z[tr] for k in Ks]).ravel()
            Yp = model.predict([Z[te] for k in Ks]).ravel()
            Fp = model.predict([Zp for k in Ks]).ravel()
            inxs = [np.argmin(np.power(Z[tr] - a, 2).sum(axis=1)) for a in model.anchors_]
            inxs = tr[list(inxs)]
        elif method == "CSI":
            ridge = RidgeLowRank(rank=rank,
                                 method_init_args={"delta": delta},
                                 method="csi", lbd=lbd)
            try:
                ridge.fit([Ksum], y[tr])
            except Exception as e:
                print(e)
                continue
            Yt = ridge.predict([Z[tr] for g in gam_range])
            Yp = ridge.predict([Z[te] for g in gam_range])
            Fp = ridge.predict([Zp for g in gam_range])
            inxs = set().union(*map(set, ridge.active_set_))
            inxs = tr[list(inxs)]
        elif method == "RFF":
            rff = RFF(rank=10, delta=10, gamma_range=gam_range, lbd=0.01)
            rff.fit(Z[tr], y[tr])
            Yt = rff.predict(Z[tr])
            Yp = rff.predict(Z[te])
            Fp = rff.predict(Zp)
            inxs = set()


        # Explained variance
        evar_tr = (np.var(y[tr]) - np.var(y[tr]-Yt)) / np.var(y[tr])
        evar    = (np.var(y[te]) - np.var(y[te]-Yp)) / np.var(y[te])
        mse_tr  = np.power(y[tr] - Yt, 2)
        mse     = np.power(y[te] - Yp, 2)
        dr, drho = st.pearsonr(distance[te], mse)

        # Fit to data
        pr, prho = st.pearsonr(Yp.ravel(), y[te])
        print("Dataset: %s method: %s pr: %.3f (p = %.5f)" % (dset_sub, method, pr, prho))

        # Predicted values
        Fz = Fp.reshape((100, 100))

        # Write results
        row = {"dataset": dset_sub, "n": Z.shape[0] , "method": method,
               "rank": rank, "iteration": 0, "lambda": lbd,
               "p": len(Ks), "evar_tr": evar_tr, "evar": evar,
               "corr": pr, "corr.p": prho,
               "dcorr": dr, "dcorr.p": drho}
        writer.writerow(row)


        if plot:
            # Plot a scatter
            fname = os.path.join(outdir, "mdsZ_%s_%s.pdf" % (dset_sub, method))
            plt.figure()
            levels = MaxNLocator(nbins=100).tick_values(Fz.min(), Fz.max())
            plt.contourf(zx, zy, Fz, cmap=plt.get_cmap('PiYG'), levels=levels)
            for i in range(X.shape[0]):
                color = "red" if i in inxs else "black"
                color = "white" if i in te else color
                alpha = 0.8 if i in inxs else 0.3
                fmt = "^" if i in inxs else "."
                plt.plot(Z[i, 0], Z[i, 1], fmt, markersize=5 * y[i],
                         alpha=alpha, color=color, markeredgecolor="black")
            plt.title("%s/%s (%d-D)" % (dset_sub, method, X.shape[1]))
            plt.xlabel("$Z_1$")
            plt.ylabel("$Z_2$")
            plt.colorbar()
            plt.tight_layout()
            plt.savefig(fname, bbox_inches="tight")
            plt.close()

            # Error in relation to distance
            fname = os.path.join(outdir, "dist_%s_%s.pdf" % (dset_sub, method))
            plt.figure()
            plt.plot(distance[te], mse, "k.")
            plt.title("%s/%s $\\rho=$%.3f, p=%.3f)" % (dset_sub, method, dr, drho))
            plt.xlabel("Distance from center of mass")
            plt.ylabel("Squared error")
            plt.savefig(fname, bbox_inches="tight")
            plt.close()
