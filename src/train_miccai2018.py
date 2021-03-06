"""
train atlas-based alignment with MICCAI2018 version of VoxelMorph, 
specifically adding uncertainty estimation and diffeomorphic transforms.
"""

# python imports
import os
import glob
import sys
import random
from argparse import ArgumentParser

# third-party imports
import tensorflow as tf
import numpy as np
from keras.backend.tensorflow_backend import set_session
from keras.optimizers import Adam
from keras.callbacks import ModelCheckpoint

# project imports
import datagenerators
import networks
import losses


def train(data_dir,
          atlas_file,
          model_dir,
          gpu_id,
          lr,
          nb_epochs,
          prior_lambda,
          image_sigma,
          steps_per_epoch,
          batch_size,
          load_model_file,
          initial_epoch=0):
    """
    model training function
    :param data_dir: folder with npz files for each subject.
    :param atlas_file: atlas filename. So far we support npz file with a 'vol' variable
    :param model_dir: model folder to save to
    :param gpu_id: integer specifying the gpu to use
    :param lr: learning rate
    :param nb_epochs: number of training iterations
    :param prior_lambda: the prior_lambda, the scalar in front of the smoothing laplacian, in MICCAI paper
    :param image_sigma: the image sigma in MICCAI paper
    :param steps_per_epoch: frequency with which to save models
    :param batch_size: Optional, default of 1. can be larger, depends on GPU memory and volume size
    :param load_model_file: optional h5 model file to initialize with
    """
    
    # load atlas from provided files. The atlas we used is 160x192x224.
    atlas_vol = np.load(atlas_file)['vol'][np.newaxis, ..., np.newaxis]
    vol_size = atlas_vol.shape[1:-1] 
    # prepare data files
    # for the CVPR and MICCAI papers, we have data arranged in train/validate/test folders
    # inside each folder is a /vols/ and a /asegs/ folder with the volumes
    # and segmentations. All of our papers use npz formated data.
    train_vol_names = glob.glob(os.path.join(data_dir, '*.npz'))
    random.shuffle(train_vol_names)  # shuffle volume list
    assert len(train_vol_names) > 0, "Could not find any training data"

    # Diffeomorphic network architecture used in MICCAI 2018 paper
    nf_enc = [16,32,32,32]
    nf_dec = [32,32,32,32,16,3] 

    # prepare model folder
    if not os.path.isdir(model_dir):
        os.mkdir(model_dir)

    # gpu handling
    gpu = '/gpu:' + str(gpu_id)
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    config.allow_soft_placement = True
    set_session(tf.Session(config=config))

    # prepare the model
    with tf.device(gpu):
        # the MICCAI201 model takes in [image_1, image_2] and outputs [warped_image_1, velocity_stats]
        # in these experiments, we use image_2 as atlas
        model = networks.miccai2018_net(vol_size, nf_enc, nf_dec)

        # load initial weights
        if load_model_file is not None:
            model.load_weights(load_model_file)

        # save first iteration
        model.save(os.path.join(model_dir, '%02d.h5' % initial_epoch))

        # compile
        loss_class = losses.Miccai2018(image_sigma, prior_lambda)
        model_losses = [loss_class.recon_loss, loss_class.kl_loss]
        model.compile(optimizer=Adam(lr=lr), loss=model_losses)
    
    # data generator
    train_example_gen = datagenerators.example_gen(train_vol_names, batch_size=batch_size)
    atlas_vol_bs = np.repeat(atlas_vol, batch_size, axis=0)
    miccai2018_gen = datagenerators.miccai2018_gen(train_example_gen, atlas_vol_bs, batch_size=batch_size)

    # prepare callbacks
    save_file_name = os.path.join(model_dir, '{epoch:02d}.h5')
    save_callback = ModelCheckpoint(save_file_name)

    # fit generator
    with tf.device(gpu):
        model.fit_generator(miccai2018_gen, 
                            initial_epoch=initial_epoch,
                            epochs=nb_epochs,
                            callbacks=[save_callback],
                            steps_per_epoch=steps_per_epoch,
                            verbose=1)


if __name__ == "__main__":
    parser = ArgumentParser()

    parser.add_argument("data_dir", type=str,
                        help="data folder")

    parser.add_argument("--atlas_file", type=str,
                        dest="atlas_file", default='../data/atlas_norm.npz',
                        help="gpu id number")
    parser.add_argument("--model_dir", type=str,
                        dest="model_dir", default='../models/',
                        help="models folder")
    parser.add_argument("--gpu", type=int, default=0,
                        dest="gpu_id", help="gpu id number")
    parser.add_argument("--lr", type=float,
                        dest="lr", default=1e-4, help="learning rate")
    parser.add_argument("--epochs", type=int,
                        dest="nb_epochs", default=1500,
                        help="number of iterations")
    parser.add_argument("--prior_lambda", type=float,
                        dest="prior_lambda", default=10,
                        help="prior_lambda regularization parameter")
    parser.add_argument("--image_sigma", type=float,
                        dest="image_sigma", default=0.02,
                        help="image noise parameter")
    parser.add_argument("--steps_per_epoch", type=int,
                        dest="steps_per_epoch", default=100,
                        help="frequency of model saves")
    parser.add_argument("--batch_size", type=int,
                        dest="batch_size", default=1,
                        help="batch_size")
    parser.add_argument("--load_model_file", type=str,
                        dest="load_model_file", default='../models/miccai2018_10_02_init1.h5',
                        help="optional h5 model file to initialize with")

    args = parser.parse_args()
    train(**vars(args))
