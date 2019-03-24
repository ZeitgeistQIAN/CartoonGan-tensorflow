import tensorflow as tf


__initializer__ = tf.keras.initializers.glorot_normal()


def triplet_conv(x, in_chs, out_chs, k_size, stride, dilate,
                 mcnt, init_param):
    assert len(init_param) == 6, len(init_param)
    with tf.variable_scope(f"triplet_conv_{mcnt}"):
        pad = (k_size - 1) // 2
        x = conv(x, in_chs, in_chs, 1, 1, 0, 1, 0, True, *init_param[0:2])
        x = tf.nn.leaky_relu(x)
        x = dconv(x, in_chs, k_size, stride, pad, dilate, 1, True, 1, *init_param[2:4])
        x = conv(x, in_chs, out_chs, 1, 1, 0, 1, 2, True, *init_param[4:])
        x = tf.nn.leaky_relu(tf.nn.lrn(x, bias=5e-5))
        return x


def coupled_conv(x, in_chs, out_chs, k_size, stride, act,
                 mcnt, init_param):
    with tf.variable_scope(f"coupled_conv_{mcnt}"):
        pad = (k_size - 1) // 2
        x = dconv(x, in_chs, k_size, stride, pad, 1, 0, False, 1, init_param[0])
        x = instance_norm(x, in_chs, 1, 1e-6, *init_param[1:3])
        x = conv(x, in_chs, out_chs, 1, 1, 0, 1, 2, False, init_param[3])
        x = instance_norm(x, out_chs, 3, 1e-6, *init_param[4:6])
        return tf.nn.relu(x) if act else x


def conv_with_in(x, in_chs, out_chs, k_size, stride, act,
                 mcnt, init_param):
    with tf.variable_scope(f"conv_with_in_{mcnt}"):
        pad = (k_size - 1) // 2
        x = conv(x, in_chs, out_chs, k_size, 1, pad, 1, 0, False, init_param[0])
        x = instance_norm(x, out_chs, 1, 1e-6, *init_param[1:3])
        return tf.nn.relu(x) if act else x


# WARNING: The behavior of batchnorm in GAN is different from normal NN!
# WARNING: batchnorm should be always in train mode!
# def batch_norm(
#         x, chs, is_training, mcnt, inf_only, eps=1e-5, momentum=.9,
#         init_g=None, init_b=None, init_rm=None, init_rv=None):  # load from numpy
def batch_norm(
        x, chs, mcnt, eps=1e-5,
        init_g=None, init_b=None):  # load from numpy
    with tf.variable_scope("bn_%02d" % mcnt):
        gamma = tf.get_variable(
            "gamma", dtype=tf.float32,
            initializer=init_g if init_g is not None else tf.ones([chs]))
        beta = tf.get_variable(
            "beta", dtype=tf.float32,
            initializer=init_b if init_b is not None else tf.zeros([chs]))
        mean, variance = tf.nn.moments(x, [0, 1, 2], name="moments")
        x = tf.nn.batch_normalization(x, mean, variance, beta, gamma, eps)
        # No running mean / var since bn always in training mode
        # r_mean = tf.get_variable(
        #     "r_mean", dtype=tf.float32,
        #     initializer=init_rm if init_rm is not None else tf.zeros([chs]),
        #     trainable=False)
        # r_var = tf.get_variable(
        #     "r_var", dtype=tf.float32,
        #     initializer=init_rv if init_rv is not None else tf.ones([chs]),
        #     trainable=False)
        # Avoid producing dirty graph
        # if inf_only:
        #     x = tf.nn.batch_normalization(x, r_mean, r_var, beta, gamma, eps)
        # else:
        #     def _train():
        #         mean, variance = tf.nn.moments(x, [0, 1, 2], name="moments")
        #         # not using tf.train.ExponentialMovingAverage for better variable control
        #         # so we can load trained variables into inf_only graph
        #         update_mean_op = tf.assign(
        #             r_mean, r_mean * momentum + mean * (1 - momentum))
        #         update_var_op = tf.assign(
        #             r_var, r_var * momentum + variance * (1 - momentum))
        #         with tf.control_dependencies([update_mean_op, update_var_op]):
        #             return tf.nn.batch_normalization(x, mean, variance, beta, gamma, eps)
        #     x = tf.cond(
        #         is_training,
        #         _train,
        #         lambda: tf.nn.batch_normalization(x, r_mean, r_var, beta, gamma, eps))
        return x


def instance_norm(x, chs, mcnt, eps=1e-6, init_g=None, init_b=None):
    with tf.variable_scope(f"in_{mcnt}"):
        gamma = tf.get_variable(
            "gamma", dtype=tf.float32,
            initializer=init_g if init_g is not None else tf.ones([chs]))
        beta = tf.get_variable(
            "beta", dtype=tf.float32,
            initializer=init_b if init_b is not None else tf.zeros([chs]))
        mean, variance = tf.nn.moments(x, [1, 2], name="moments", keep_dims=True)
        x = tf.nn.batch_normalization(
            x, mean, variance, beta, gamma, eps, name='instancenorm')

        return x


def conv(
        x, in_chs, out_chs, k_size, stride, pad, dilate, mcnt, bias,
        init_w=None, init_b=None):  # load from numpy
    with tf.variable_scope("conv_%02d" % mcnt):
        w_shape = [k_size, k_size, in_chs, out_chs]
        weight = tf.get_variable(
            "kernel",
            None,
            tf.float32,
            init_w if init_w is not None else __initializer__(w_shape))
        # "SAME" pad in tf.nn.conv2d does not do the same as pytorch
        # would do when k_size=3, stride=2, pad=1
        if pad > 0:
            x = tf.pad(x, [[0, 0], [pad, pad], [pad, pad], [0, 0]])
        x = tf.nn.conv2d(x, weight, [1, stride, stride, 1], "VALID",
                         dilations=[1, dilate, dilate, 1])
        if bias:
            b = tf.get_variable(
                "bias", None, tf.float32,
                init_b if init_b is not None else tf.zeros([out_chs]))
            x = tf.nn.bias_add(x, b)
        return x


def dconv(
        x, in_chs, k_size, stride, pad, dilate, mcnt, bias, chs_mult=1,
        init_w=None, init_b=None):
    with tf.variable_scope("dwise_conv_%02d" % mcnt):
        w_shape = [k_size, k_size, in_chs, chs_mult]
        weight = tf.get_variable(
            "kernel",
            None,
            tf.float32,
            init_w if init_w is not None else __initializer__(w_shape))
        if pad > 0:
            x = tf.pad(x, [[0, 0], [pad, pad], [pad, pad], [0, 0]])
        x = tf.nn.depthwise_conv2d(x, weight, [1, stride, stride, 1], "VALID",
                                   rate=[dilate, dilate])
        if bias:
            b = tf.get_variable(
                "bias", None, tf.float32,
                init_b if init_b else tf.zeros([int(in_chs * chs_mult)]))
            x = tf.nn.bias_add(x, b)
        return x


def _test():
    import numpy as np
    x = tf.placeholder(tf.float32, [2, 35, 35, 3])
    is_training = tf.placeholder(tf.bool)
    nx = np.random.rand(2, 35, 35, 3).astype(np.float32)
    out_op = coupled_conv(x, 3, 30, 5, 2, True, 0, [None]*4)
    out_op = tf.image.resize_bilinear(out_op, [35, 35])
    with tf.Session() as sess:
        sess.run(tf.global_variables_initializer())
        out = sess.run(out_op, {x: nx, is_training: False})
    print(out.shape)


if __name__ == '__main__':
    _test()
