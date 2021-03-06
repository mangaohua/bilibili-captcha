# Building a multilayer perceptron (MLP) model to learn to recognize captcha

import pickle
import time

import numpy
import theano
import theano.tensor as T
from sklearn.cross_validation import StratifiedShuffleSplit

import helper
import dataset_manager
import config as c
from captcha_provider import KuaiZhanCaptchaProvider

# The standard shape of one character, determined through experience
_std_height = 50
_std_width = 30

_captcha_provider = KuaiZhanCaptchaProvider()

_best_model_path = c.get('best_model.pkl')

# Reference:
# http://deeplearning.net/tutorial/logreg.html
# http://deeplearning.net/tutorial/mlp.html

# Some Interesting Pages
# http://yann.lecun.com/exdb/publis/pdf/lecun-98b.pdf
# http://yann.lecun.com/exdb/mnist/


class LogisticRegression(object):
    """Multi-class Logistic Regression Class

    The logistic regression is fully described by a weight matrix :math:`W`
    and bias vector :math:`b`. Classification is done by projecting data
    points onto a set of hyperplanes, the distance to which is used to
    determine a class membership probability.
    """

    def __init__(self, input_, n_in, n_out):
        """ Initialize the parameters of the logistic regression

        :type input_: theano.tensor.TensorType
        :param input_: symbolic variable that describes the input of the
                      architecture (one minibatch)

        :type n_in: int
        :param n_in: number of input units, the dimension of the space in
                     which the data points lie

        :type n_out: int
        :param n_out: number of output units, the dimension of the space in
                      which the labels lie

        """
        # initialize with 0 the weights W as a matrix of shape (n_in, n_out)
        self.W = theano.shared(
            value=numpy.zeros(
                (n_in, n_out),
                dtype=theano.config.floatX
            ),
            name='W',
            borrow=True
        )
        # initialize the biases b as a vector of n_out 0s
        self.b = theano.shared(
            value=numpy.zeros(
                (n_out,),
                dtype=theano.config.floatX
            ),
            name='b',
            borrow=True
        )

        # symbolic expression for computing the matrix of class-membership
        # probabilities
        # Where:
        # W is a matrix where column-k represent the separation hyperplane for
        # class-k
        # x is a matrix where row-j  represents input training sample-j
        # b is a vector where element-k represent the free parameter of
        # hyperplane-k
        self.p_y_given_x = T.nnet.softmax(T.dot(input_, self.W) + self.b)

        # symbolic description of how to compute prediction as class whose
        # probability is maximal
        self.y_pred = T.argmax(self.p_y_given_x, axis=1)

        # parameters of the model
        self.params = [self.W, self.b]

        # keep track of model input
        self.input = input_

    def negative_log_likelihood(self, y):
        """Return the mean of the negative log-likelihood of the prediction
        of this model under a given target distribution.

        :type y: theano.tensor.TensorType
        :param y: corresponds to a vector that gives for each example the
                  correct label

        Note: we use the mean instead of the sum so that
              the learning rate is less dependent on the batch size
        """
        # y.shape[0] is (symbolically) the number of rows in y, i.e.,
        # number of examples (call it n) in the minibatch
        # T.arange(y.shape[0]) is a symbolic vector which will contain
        # [0,1,2,... n-1] T.log(self.p_y_given_x) is a matrix of
        # Log-Probabilities (call it LP) with one row per example and
        # one column per class LP[T.arange(y.shape[0]),y] is a vector
        # v containing [LP[0,y[0]], LP[1,y[1]], LP[2,y[2]], ...,
        # LP[n-1,y[n-1]]] and T.mean(LP[T.arange(y.shape[0]),y]) is
        # the mean (across minibatch examples) of the elements in v,
        # i.e., the mean log-likelihood across the minibatch.
        return -T.mean(T.log(self.p_y_given_x)[T.arange(y.shape[0]), y])

    def errors(self, y):
        """Return a float representing the number of errors in the minibatch
        over the total number of examples of the minibatch ; zero one
        loss over the size of the minibatch

        :type y: theano.tensor.TensorType
        :param y: corresponds to a vector that gives for each example the
                  correct label
        """

        # check if y has same dimension of y_pred
        if y.ndim != self.y_pred.ndim:
            raise TypeError(
                'y should have the same shape as self.y_pred',
                ('y', y.type, 'y_pred', self.y_pred.type)
            )
        # check if y is of the correct datatype
        if y.dtype.startswith('int'):
            # the T.neq operator returns a vector of 0s and 1s, where 1
            # represents a mistake in prediction
            return T.mean(T.neq(self.y_pred, y))
        else:
            raise NotImplementedError()


class HiddenLayer(object):
    def __init__(self, rng, input_, n_in, n_out, W=None, b=None,
                 activation=T.tanh):
        """
        Typical hidden layer of a MLP: units are fully-connected and have
        sigmoidal activation function. Weight matrix W is of shape (n_in,n_out)
        and the bias vector b is of shape (n_out,).

        NOTE : The non-linearity used here is tanh

        Hidden unit activation is given by: tanh(dot(input,W) + b)

        :type rng: numpy.random.RandomState
        :param rng: a random number generator used to initialize weights

        :type input_: theano.tensor.dmatrix
        :param input_: a symbolic tensor of shape (n_examples, n_in)

        :type n_in: int
        :param n_in: dimensionality of input

        :type n_out: int
        :param n_out: number of hidden units

        :type activation: theano.Op or function
        :param activation: Non linearity to be applied in the hidden
                           layer
        """
        self.input = input_

        # `W` is initialized with `W_values` which is uniformly sampled
        # from sqrt(-6./(n_in+n_hidden)) and sqrt(6./(n_in+n_hidden))
        # for tanh activation function
        # the output of uniform if converted using asarray to dtype
        # theano.config.floatX so that the code is runable on GPU
        # Note : optimal initialization of weights is dependent on the
        #        activation function used (among other things).
        #        For example, results presented in [Xavier10] suggest that you
        #        should use 4 times larger initial weights for sigmoid
        #        compared to tanh
        #        We have no info for other function, so we use the same as
        #        tanh.

        if W is None:
            W_values = numpy.asarray(
                rng.uniform(
                    low=-numpy.sqrt(6. / (n_in + n_out)),
                    high=numpy.sqrt(6. / (n_in + n_out)),
                    size=(n_in, n_out)
                ),
                dtype=theano.config.floatX
            )
            if activation == theano.tensor.nnet.sigmoid:
                W_values *= 4

            W = theano.shared(value=W_values, name='W', borrow=True)

        if b is None:
            b_values = numpy.zeros((n_out,), dtype=theano.config.floatX)
            b = theano.shared(value=b_values, name='b', borrow=True)

        self.W = W
        self.b = b

        lin_output = T.dot(input_, self.W) + self.b
        self.output = (
            lin_output if activation is None
            else activation(lin_output)
        )
        # parameters of the model
        self.params = [self.W, self.b]


class MLP(object):
    """Multi-Layer Perceptron Class

    A multilayer perceptron is a feed-forward artificial neural network model
    that has one layer or more of hidden units and nonlinear activations.
    Intermediate layers usually have as activation function tanh or the
    sigmoid function (defined here by a ``HiddenLayer`` class)  while the
    top layer is a softmax layer (defined here by a ``LogisticRegression``
    class).
    """

    def __init__(self, rng, input_, n_in, n_hidden, n_out):
        """Initialize the parameters for the multilayer perceptron

        :type rng: numpy.random.RandomState
        :param rng: a random number generator used to initialize weights

        :type input_: theano.tensor.TensorType
        :param input_: symbolic variable that describes the input of the
        architecture (one minibatch)

        :type n_in: int
        :param n_in: number of input units, the dimension of the space in
        which the data points lie

        :type n_hidden: int
        :param n_hidden: number of hidden units

        :type n_out: int
        :param n_out: number of output units, the dimension of the space in
        which the labels lie

        """
        # Since we are dealing with a one hidden layer MLP, this will translate
        # into a HiddenLayer with a tanh activation function connected to the
        # LogisticRegression layer; the activation function can be replaced by
        # sigmoid or any other nonlinear function
        self.hiddenLayer = HiddenLayer(
            rng=rng,
            input_=input_,
            n_in=n_in,
            n_out=n_hidden,
            activation=T.tanh  # could be T.nnet.sigmoid or T.tanh
        )

        # The logistic regression layer gets as input the hidden units
        # of the hidden layer
        self.logRegressionLayer = LogisticRegression(
            input_=self.hiddenLayer.output,
            n_in=n_hidden,
            n_out=n_out
        )

        # L1 norm ; one regularization option is to enforce L1 norm to
        # be small
        self.L1 = (
            abs(self.hiddenLayer.W).sum()
            + abs(self.logRegressionLayer.W).sum()
        )

        # square of L2 norm ; one regularization option is to enforce
        # square of L2 norm to be small
        self.L2_sqr = (
            T.sum(self.hiddenLayer.W ** 2)
            + T.sum(self.logRegressionLayer.W ** 2)
        )

        # negative log likelihood of the MLP is given by the negative
        # log likelihood of the output of the model, computed in the
        # logistic regression layer
        self.negative_log_likelihood = (
            self.logRegressionLayer.negative_log_likelihood
        )
        # same holds for the function computing the number of errors
        self.errors = self.logRegressionLayer.errors

        # the parameters of the model are the parameters of the two layer it is
        # made out of
        self.params = self.hiddenLayer.params + self.logRegressionLayer.params

        # keep track of model input
        self.input = input_


def _construct_mlp(datasets, learning_rate=0.01, L1_reg=0.00, L2_reg=0.0001,
                   n_epochs=1000,
                   batch_size=20, n_hidden=200):
    """
    Demonstrate stochastic gradient descent optimization for a multilayer
    perceptron

    Note: Parameters need tuning.

    :type datasets: tuple
    :param datasets: (inputs, targets)

    :type learning_rate: float
    :param learning_rate: learning rate used (factor for the stochastic
    gradient

    :type L1_reg: float
    :param L1_reg: L1-norm's weight when added to the cost (see regularization)

    :type L2_reg: float
    :param L2_reg: L2-norm's weight when added to the cost (see regularization)

    :type n_epochs: int
    :param n_epochs: maximal number of epochs to run the optimizer

    :type batch_size: int
    :param batch_size: number of examples in one batch

    :type n_hidden: int
    :param n_hidden: number of hidden units to be used in class HiddenLayer

     """
    inputs, targets = datasets
    temp_train_set_x = []
    temp_train_set_y = []
    train_set_x = []
    train_set_y = []
    valid_set_x = []
    valid_set_y = []
    test_set_x = []
    test_set_y = []

    # stratified k-fold to split test and temporary train, which contains
    # validation and train
    skf = StratifiedShuffleSplit(targets, 1, 0.2)
    for temp_train_index, test_index in skf:
        # print("TEMP_TRAIN:", temp_train_index, "TEST:", test_index)
        temp_train_set_x.append(inputs[temp_train_index])
        temp_train_set_y.append(targets[temp_train_index])
        test_set_x.append(inputs[test_index])
        test_set_y.append(targets[test_index])

    # convert from list-wrapping array to array
    test_set_x = test_set_x[0]
    test_set_y = test_set_y[0]
    temp_train_set_x = temp_train_set_x[0]
    temp_train_set_y = temp_train_set_y[0]

    # stratified k-fold to split valid and train
    skf = StratifiedShuffleSplit(temp_train_set_y, 1, 0.25)
    for train_index, valid_index in skf:
        # print("TRAIN: ", train_index, ", VALID: ", valid_index)
        train_set_x.append(temp_train_set_x[train_index])
        train_set_y.append(temp_train_set_y[train_index])
        valid_set_x.append(temp_train_set_x[valid_index])
        valid_set_y.append(temp_train_set_y[valid_index])

    # convert from list-wrapping array to array
    train_set_x = train_set_x[0]
    train_set_y = train_set_y[0]
    valid_set_x = valid_set_x[0]
    valid_set_y = valid_set_y[0]

    # check shape
    # print("train_set_x shape: " + str(train_set_x.shape))
    # print("train_set_y shape: " + str(train_set_y.shape))
    # print("valid_set_x shape: " + str(valid_set_x.shape))
    # print("valid_set_y shape: " + str(valid_set_y.shape))
    # print("test_set_x shape: " + str(test_set_x.shape))
    # print("test_set_y shape: " + str(test_set_y.shape))

    # convert to theano.shared variable
    train_set_x = theano.shared(value=train_set_x, name='train_set_x')
    train_set_y = theano.shared(value=train_set_y, name='train_set_y')
    valid_set_x = theano.shared(value=valid_set_x, name='valid_set_x')
    valid_set_y = theano.shared(value=valid_set_y, name='valid_set_y')
    test_set_x = theano.shared(value=test_set_x, name='test_set_x')
    test_set_y = theano.shared(value=test_set_y, name='test_set_y')

    # compute number of minibatches for training, validation and testing
    n_train_batches = int(train_set_x.get_value().shape[0] / batch_size)
    n_valid_batches = int(valid_set_x.get_value().shape[0] / batch_size)
    n_test_batches = int(test_set_x.get_value().shape[0] / batch_size)

    # check batch
    # print("n_train_batches:" + str(n_train_batches))
    # print("n_valid_batches:" + str(n_valid_batches))
    # print("n_test_batches:" + str(n_test_batches))

    print('... building the model')

    # allocate symbolic variables for the data
    index = T.lscalar()  # index to a [mini]batch
    x = T.matrix('x')  # the data is presented as rasterized images
    y = T.lvector('y')  # the labels are presented as 1D vector of [int] labels

    # set a random state that is related to the time
    # noinspection PyUnresolvedReferences
    rng = numpy.random.RandomState(int((time.time())))

    # construct the MLP class
    classifier = MLP(
        rng=rng,
        input_=x,
        n_in=_std_height * _std_width,
        n_hidden=n_hidden,
        n_out=len(_captcha_provider.chars)
    )

    # the cost we minimize during training is the negative log likelihood of
    # the model plus the regularization terms (L1 and L2); cost is expressed
    # here symbolically
    cost = (
        classifier.negative_log_likelihood(y)
        + L1_reg * classifier.L1
        + L2_reg * classifier.L2_sqr
    )

    # compiling a Theano function that computes the mistakes that are made
    # by the model on a minibatch
    test_model = theano.function(
        inputs=[index],
        outputs=classifier.errors(y),
        givens={
            x: test_set_x[index * batch_size:(index + 1) * batch_size],
            y: test_set_y[index * batch_size:(index + 1) * batch_size]
        },
        mode='FAST_RUN'
    )

    validate_model = theano.function(
        inputs=[index],
        outputs=classifier.errors(y),
        givens={
            x: valid_set_x[index * batch_size:(index + 1) * batch_size],
            y: valid_set_y[index * batch_size:(index + 1) * batch_size]
        },
        mode='FAST_RUN'
    )

    # compute the gradient of cost with respect to theta (sorted in params)
    # the resulting gradients will be stored in a list gparams
    gparams = [T.grad(cost, param) for param in classifier.params]

    # specify how to update the parameters of the model as a list of
    # (variable, update expression) pairs

    # given two lists of the same length, A = [a1, a2, a3, a4] and
    # B = [b1, b2, b3, b4], zip generates a list C of same size, where each
    # element is a pair formed from the two lists :
    #    C = [(a1, b1), (a2, b2), (a3, b3), (a4, b4)]
    updates = [
        (param, param - learning_rate * gparam)
        for param, gparam in zip(classifier.params, gparams)
        ]

    # compiling a Theano function `train_model` that returns the cost, but
    # in the same time updates the parameter of the model based on the rules
    # defined in `updates`
    train_model = theano.function(
        inputs=[index],
        outputs=cost,
        updates=updates,
        givens={
            x: train_set_x[index * batch_size: (index + 1) * batch_size],
            y: train_set_y[index * batch_size: (index + 1) * batch_size]
        },
        mode='FAST_RUN'
    )

    print('... training')

    # early-stopping parameters
    patience = 10000  # look as this many examples regardless
    patience_increase = 2  # wait this much longer when a new best is found
    improvement_threshold = 0.995  # a relative improvement of this much is
    # considered significant

    if T.lt(n_train_batches, patience / 2):
        validation_frequency = n_train_batches
    else:
        validation_frequency = patience / 2
    # go through this many minibatches before checking the network
    # on the validation set; in this case we check every epoch

    best_validation_loss = numpy.inf
    best_iter = 0
    test_score = 0.
    start_time = time.time()

    epoch = 0
    done_looping = False

    while (epoch < n_epochs) and (not done_looping):
        epoch += 1
        for minibatch_index in range(n_train_batches):
            # noinspection PyUnusedLocal
            minibatch_avg_cost = train_model(minibatch_index)
            iteration = (epoch - 1) * n_train_batches + minibatch_index

            if (iteration + 1) % validation_frequency == 0:
                # compute zero-one loss on validation set
                validation_losses = [validate_model(i) for i
                                     in range(n_valid_batches)]
                this_validation_loss = numpy.mean(validation_losses)

                print(
                    'epoch {0}, minibatch {1}/{2}, validation error {3}'.format(
                        epoch,
                        minibatch_index + 1,
                        n_train_batches,
                        this_validation_loss * 100.
                    )
                )
                # if we got the best validation score until now
                if this_validation_loss < best_validation_loss:
                    # improve patience if loss improvement is good enough
                    if (this_validation_loss
                            < best_validation_loss * improvement_threshold):
                        patience = max(patience, iteration * patience_increase)

                    best_validation_loss = this_validation_loss
                    best_iter = iteration

                    # test it on the test set
                    test_losses = [test_model(i) for i
                                   in range(n_test_batches)]
                    test_score = numpy.mean(test_losses)

                    print(
                        '    epoch {0}, minibatch {1}/{2}, test error of best '
                        'model {3}'.format(epoch, minibatch_index + 1,
                                           n_train_batches, test_score * 100))

            if patience <= iteration:
                done_looping = True
                break

    end_time = time.time()
    print(
        'Optimization complete. Best validation score of {0} obtained at '
        'iteration {1}, with test performance {2}'.format
        (best_validation_loss * 100, best_iter + 1, test_score * 100))
    print('Time used for testing the mlp is', end_time - start_time)
    return classifier


def _load_data():
    input_list = []
    target_list = []
    for cat in range(len(_captcha_provider.chars)):
        char = _captcha_provider.chars[cat]
        char_images = dataset_manager.get_training_char_images(char)
        for image in char_images:
            target_list.append(cat)
            input_list.append(helper.resize_image(
                image, _std_height, _std_width
            ).flatten())
    inputs = numpy.array(input_list, dtype=theano.config.floatX)
    targets = numpy.array(target_list, dtype=numpy.int64)
    return inputs, targets
    # Loading the dataset
    # Output format: tuple(input, target)
    # input is an numpy.ndarray of 2 dimensions (a matrix)
    # witch row's correspond to an example. target is a
    # numpy.ndarray of 1 dimensions (vector)) that have the same length as
    # the number of rows in the input. It should give the target
    # target to the example with the same index in the input.


def predict(img):
    # data should be a numpy array that has not been resized
    data = helper.resize_image(img, _std_height, _std_width).flatten()
    predicted_values = _get_predict_model()([data])
    return _captcha_provider.chars[predicted_values]


def reconstruct_model(dry_run=False):
    dataset = _load_data()
    classifier = _construct_mlp(dataset)
    if not dry_run:
        _update_classifier(classifier)


def _load_classifier():
    try:
        return pickle.load(open(_best_model_path, 'rb'))
    except Exception as e:
        print(e)
        reconstruct_model()
        return pickle.load(open(_best_model_path, 'rb'))


def _update_classifier(classifier):
    global _classifier
    _classifier = classifier
    with open(_best_model_path, 'wb') as f:
        pickle.dump(classifier, f)


_classifier = None
_predict_model = None


def _get_classifier():
    global _classifier
    if not _classifier:
        _classifier = _load_classifier()
    return _classifier


def _get_predict_model():
    global _predict_model
    if not _predict_model:
        classifier = _get_classifier()
        _predict_model = theano.function(
            inputs=[classifier.input],
            outputs=classifier.logRegressionLayer.y_pred,
            mode='FAST_RUN'
        )
    return _predict_model
