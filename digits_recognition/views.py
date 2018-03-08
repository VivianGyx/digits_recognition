from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
import numpy as np
import tensorflow as tf
import json
import digits_recognition.model_attack as model
from attacks import fgm
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import os
import mpld3
from mpld3 import plugins

from io import BytesIO
from bottle import run, get, HTTPResponse
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg


x = tf.placeholder("float", [None, 784])


class Dummy:
    pass


env = Dummy()


img_size = 28
img_chan = 1
n_classes = 10

with tf.variable_scope('model'):
    env.x = tf.placeholder(tf.float32, (None, img_size, img_size, img_chan),
                           name='x')
    env.y = tf.placeholder(tf.float32, (None, n_classes), name='y')
    env.training = tf.placeholder_with_default(False, (), name='mode')

    env.ybar, logits = model.model(env.x, logits=True, training=env.training)

    with tf.variable_scope('acc'):
        count = tf.equal(tf.argmax(env.y, axis=1), tf.argmax(env.ybar, axis=1))
        env.acc = tf.reduce_mean(tf.cast(count, tf.float32), name='acc')

    with tf.variable_scope('loss'):
        xent = tf.nn.softmax_cross_entropy_with_logits(labels=env.y,
                                                       logits=logits)
        env.loss = tf.reduce_mean(xent, name='loss')

    with tf.variable_scope('train_op'):
        optimizer = tf.train.AdamOptimizer()
        env.train_op = optimizer.minimize(env.loss)

    env.saver = tf.train.Saver()

# fgsm攻击
with tf.variable_scope('model', reuse=True):
    env.fgsm_eps = tf.placeholder(tf.float32, (), name='fgsm_eps')
    env.fgsm_epochs = tf.placeholder(tf.int32, (), name='fgsm_epochs')
    env.x_fgsm = fgm(model, env.x, epochs=env.fgsm_epochs, eps=env.fgsm_eps)

print('\nInitializing graph')

sess = tf.InteractiveSession()
sess.run(tf.global_variables_initializer())


def train(sess, env, load=False, name='model'):
    """
    Train a TF model by running env.train_op.
    """
    if load:
        if not hasattr(env, 'saver'):
            return print('\nError: cannot find saver op')
        print('\nLoading saved model')
        return env.saver.restore(sess, 'digits_recognition/model/{}'.format(name))
        #Saver的作用是将我们训练好的模型的参数保存下来，以便下一次继续用于训练或测试；Restore的用法是将训练好的参数提取出来。


train(sess, env, load=True, name='mnist')


def predict(sess, env, X_data, batch_size=128):
    """
    Do inference by running env.ybar.
    过运行env.ybar进行推理。
    """
    print('\nPredicting')
    n_classes = env.ybar.get_shape().as_list()[1]

    n_sample = X_data.shape[0]
    n_batch = int((n_sample+batch_size-1) / batch_size)
    yval = np.empty((n_sample, n_classes))

    for batch in range(n_batch):
        print(' batch {0}/{1}'.format(batch + 1, n_batch), end='\r')
        start = batch * batch_size
        end = min(n_sample, start + batch_size)
        y_batch = sess.run(env.ybar, feed_dict={env.x: X_data[start:end]})
        yval[start:end] = y_batch
    print()
    return yval


def make_fgsm(sess, env, X_data, epochs=1, eps=0.01, batch_size=128):
    """
    Generate FGSM by running env.x_fgsm.
    """
    print('\nMaking adversarials via FGSM')

    n_sample = X_data.shape[0]
    n_batch = int((n_sample + batch_size - 1) / batch_size)
    X_adv = np.empty_like(X_data)

    for batch in range(n_batch):
        print(' batch {0}/{1}'.format(batch + 1, n_batch), end='\r')
        start = batch * batch_size
        end = min(n_sample, start + batch_size)
        adv = sess.run(env.x_fgsm, feed_dict={
            env.x: X_data[start:end],
            env.fgsm_eps: eps,
            env.fgsm_epochs: epochs})
        X_adv[start:end] = adv

    return X_adv


def index(request):
    return render(request, 'index.html')


@csrf_exempt
def process(request):
    #标准化数据
    input = ((255 - np.array(eval(request.POST.get('inputs')), dtype=np.float32)) / 255.0).reshape(1, 28, 28, 1)

    #一维数组，输出10个预测概率
    output_clean = predict(sess, env, input).tolist()
    print(output_clean)

    X_adv = make_fgsm(sess, env, input, epochs=12, eps=0.02)
    # print(X_adv)
    output_adv = predict(sess, env, X_adv).tolist()
    print(output_adv)

    return HttpResponse(json.dumps([output_clean[0], output_adv[0]]))     #json.dumps()用于将dict类型的数据转成str


@csrf_exempt
def fgsm_attack(request):
    #标准化数据
    input = ((255 - np.array(eval(request.POST.get('inputs')), dtype=np.float32)) / 255.0).reshape(1, 28, 28, 1)
    X_adv = make_fgsm(sess, env, input, epochs=12, eps=0.02).tolist()
    # print(X_adv[0])

    X_tmp = np.empty((10, 28, 28))
    X_tmp[0] = np.squeeze(X_adv[0])
    # print(X_tmp[0])

    fig = plt.figure(figsize=(1, 1.2))
    gs = gridspec.GridSpec(1, 1, wspace=0.05, hspace=0.05)
    ax = fig.add_subplot(gs[0, 0])  # 分别画子图
    ax.imshow(X_tmp[0], cmap='gray', interpolation='none')  # 展示预测错的对抗样本

    ax.set_xticks([])
    ax.set_yticks([])

    plugins.connect(fig, plugins.MousePosition(fontsize=14))
    # mpld3.show()

    os.makedirs('img', exist_ok=True)
    plt.savefig('img/fgsm_mnist.png')
    # return HttpResponse(json.dumps(X_adv))
    # print(mpld3.fig_to_html(fig))
    return HttpResponse(mpld3.fig_to_html(fig))
