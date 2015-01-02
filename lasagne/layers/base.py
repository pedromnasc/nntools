import numpy as np

import theano
import theano.tensor as T
from theano.tensor.signal import downsample
from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams
# from theano.tensor.shared_randomstreams import RandomStreams

from .. import init
from .. import nonlinearities
from .. import utils
from ..theano_extensions import conv
from ..theano_extensions import padding


_srng = RandomStreams()


## Helper functions

def get_all_layers(layer):
    """
    This function gathers all layers below one or more given :class:`Layer`
    instances, including the given layer(s). Its main use is to collect all
    layers of a network just given the output layer(s).

    :usage:
        >>> l_in = InputLayer((100, 20))
        >>> l1 = DenseLayer(l_in, num_units=50)
        >>> all_layers = get_all_layers(l1)
        >>> all_layers == [l1, l_in]
        True
        >>> l2 = DenseLayer(l_in, num_units=10)
        >>> all_layers = get_all_layers([l2, l1])
        >>> all_layers == [l2, l1, l_in]
        True

    :parameters:
        - layer : Layer
            the :class:`Layer` instance for which to gather all layers feeding
            into it, or a list of :class:`Layer` instances.

    :returns:
        - layers : list
            a list of :class:`Layer` instances feeding into the given
            instance(s) either directly or indirectly, and the given
            instance(s) themselves.
    """
    if isinstance(layer, (list, tuple)):
        layers = list(layer)
    else:
        layers = [layer]
    layers_to_expand = list(layers)
    while len(layers_to_expand) > 0:
        current_layer = layers_to_expand.pop(0)
        children = []

        if hasattr(current_layer, 'input_layers'):
            children = current_layer.input_layers
        elif hasattr(current_layer, 'input_layer'):
            children = [current_layer.input_layer]

        # filter the layers that have already been visited.
        children = [child for child in children if child not in layers]
        layers_to_expand.extend(children)
        layers.extend(children)

    return layers


def get_all_params(layer):
    """
    This function gathers all learnable parameters of all layers below one
    or more given :class:`Layer` instances, including the layer(s) itself.
    Its main use is to collect all parameters of a network just given the
    output layer(s).

    :usage:
        >>> l_in = InputLayer((100, 20))
        >>> l1 = DenseLayer(l_in, num_units=50)
        >>> all_params = get_all_params(l1)
        >>> all_params == [l1.W, l1.b]
        True

    :parameters:
        - layer : Layer
            the :class:`Layer` instance for which to gather all parameters,
            or a list of :class:`Layer` instances.

    :returns:
        - params : list
            a list of Theano shared variables representing the parameters.
    """
    layers = get_all_layers(layer)
    params = sum([l.get_params() for l in layers], [])
    return utils.unique(params)


def get_all_bias_params(layer):
    """
    This function gathers all learnable bias parameters of all layers below one
    or more given :class`Layer` instances, including the layer(s) itself.

    This is useful for situations where the biases should be treated
    separately from other parameters, e.g. they are typically excluded from
    L2 regularization.

    :usage:
        >>> l_in = InputLayer((100, 20))
        >>> l1 = DenseLayer(l_in, num_units=50)
        >>> all_params = get_all_bias_params(l1)
        >>> all_params == [l1.b]
        True

    :parameters:
        - layer : Layer
            the :class:`Layer` instance for which to gather all bias parameters,
            or a list of :class:`Layer` instances.

    :returns:
        - params : list
            a list of Theano shared variables representing the bias parameters.

    """
    layers = get_all_layers(layer)
    params = sum([l.get_bias_params() for l in layers], [])
    return utils.unique(params)


def get_all_non_bias_params(layer):
    """
    This function gathers all learnable non-bias parameters of all layers below
    one or more given :class`Layer` instances, including the layer(s) itself.

    This is useful for situations where the biases should be treated
    separately from other parameters, e.g. they are typically excluded from
    L2 regularization.

    :usage:
        >>> l_in = InputLayer((100, 20))
        >>> l1 = DenseLayer(l_in, num_units=50)
        >>> all_params = get_all_non_bias_params(l1)
        >>> all_params == [l1.W]
        True

    :parameters:
        - layer : Layer
            the :class:`Layer` instance for which to gather all non-bias
            parameters, or a list of :class:`Layer` instances.

    :returns:
        - params : list
            a list of Theano shared variables representing the non-bias
            parameters.

    """
    all_params = get_all_params(layer)
    all_bias_params = get_all_bias_params(layer)
    return [p for p in all_params if p not in all_bias_params]


def count_params(layer):
    """
    This function counts all learnable parameters (i.e. the number of scalar
    values) of all layers below one or more given :class`Layer` instances,
    including the layer(s) itself.

    This is useful to compare the capacity of various network architectures.
    All parameters returned by the :class:`Layer`s' `get_params` methods are
    counted, including biases.

    :usage:
        >>> l_in = InputLayer((100, 20))
        >>> l1 = DenseLayer(l_in, num_units=50)
        >>> param_count = count_params(l1)
        >>> param_count
        1050
        >>> param_count == 20 * 50 + 50  # 20 input * 50 units + 50 biases
        True

    :parameters:
        - layer : Layer
            the :class:`Layer` instance for which to count the parameters,
            or a list of :class:`Layer` instances.
    :returns:
        - count : int
            the total number of learnable parameters.

    """
    params = get_all_params(layer)
    shapes = [p.get_value().shape for p in params]
    counts = [np.prod(shape) for shape in shapes]
    return sum(counts)


def get_all_param_values(layer):
    """
    This function returns the values of the parameters of all layers below one
    or more given :class:`Layer` instances, including the layer(s) itself.

    This function can be used in conjunction with set_all_param_values to save
    and restore model parameters.

    :usage:
        >>> l_in = InputLayer((100, 20))
        >>> l1 = DenseLayer(l_in, num_units=50)
        >>> all_param_values = get_all_param_values(l1)
        >>> (all_param_values[0] == l1.W.get_value()).all()
        True
        >>> (all_param_values[1] == l1.b.get_value()).all()
        True

    :parameters:
        - layer : Layer
            the :class:`Layer` instance for which to gather all parameter
            values, or a list of :class:`Layer` instances.

    :returns:
        - param_values : list of numpy.array
            a list of numpy arrays representing the parameter values.
    """
    params = get_all_params(layer)
    return [p.get_value() for p in params]


def set_all_param_values(layer, values):
    """
    Given a list of numpy arrays, this function sets the parameters of all
    layers below one or more given :class:`Layer` instances (including the
    layer(s) itself) to the given values.

    This function can be used in conjunction with get_all_param_values to save
    and restore model parameters.

    :usage:
        >>> l_in = InputLayer((100, 20))
        >>> l1 = DenseLayer(l_in, num_units=50)
        >>> all_param_values = get_all_param_values(l1)
        >>> # all_param_values is now [l1.W.get_value(), l1.b.get_value()]
        >>> # ...
        >>> set_all_param_values(l1, all_param_values)
        >>> # the parameter values are restored.

    :parameters:
        - layer : Layer
            the :class:`Layer` instance for which to set all parameter
            values, or a list of :class:`Layer` instances.
        - values : list of numpy.array
    """
    params = get_all_params(layer)
    for p,v in zip(params, values):
        p.set_value(v)


## Layer base class

class Layer(object):
    def __init__(self, input_layer):
        self.input_layer = input_layer

    def get_params(self):
        """
        Get all Theano variables that parameterize the layer.
        """
        return []

    def get_bias_params(self):
        """
        Get all Theano variables that are bias parameters for the layer.
        """
        return []

    def get_output_shape(self):
        input_shape = self.input_layer.get_output_shape()
        return self.get_output_shape_for(input_shape)

    def get_output(self, input=None, *args, **kwargs):
        """
        Computes the output of the network at this layer. Optionally, you can
        define an input to propagate through the network instead of using the
        input variables associated with the network's input layers.

        :parameters:
            - input : None, Theano expression, numpy array, or dict
                If None, uses the inputs of the :class:`InputLayer` instances.
                If a Theano expression, this will replace the inputs of all
                :class:`InputLayer` instances (useful if your network has a
                single input layer).
                If a numpy array, this will be wrapped as a Theano constant
                and used just like a Theano expression.
                If a dictionary, any :class:`Layer` instance (including the
                input layers) can be mapped to a Theano expression or numpy
                array to use instead of its regular output.

        :returns:
            - output : Theano expression
                the output of this layer given the input to the network

        :note:
            When implementing a new :class:`Layer` class, you will usually
            keep this unchanged and just override `get_output_for()`.
        """
        if isinstance(input, dict) and (self in input):
            # this layer is mapped to an expression or numpy array
            return utils.as_theano_expression(input[self])
        else: # in all other cases, just pass the network input on to the next layer.
            layer_input = self.input_layer.get_output(input, *args, **kwargs)
            return self.get_output_for(layer_input, *args, **kwargs)

    def get_output_shape_for(self, input_shape):
        return input_shape # By default, the shape is assumed to be preserved.
        # This means that layers performing elementwise operations, or other
        # shape-preserving operations (such as normalization), only need to
        # implement a single method, i.e. get_output_for(). 

    def get_output_for(self, input, *args, **kwargs):
        """
        Propagates the given input through this layer (and only this layer).

        :parameters:
            - input : Theano expression
                the expression to propagate through this layer

        :returns:
            - output : Theano expression
                the output of this layer given the input to this layer

        :note:
            This is called by the base :class:`Layer` implementation to
            propagate data through a network in `get_output()`. While
            `get_output()` asks the underlying layers for input and thus
            returns an expression for a layer's output in terms of the
            network's input, `get_output_for()` just performs a single step
            and returns an expression for a layer's output in terms of
            that layer's input.
        """
        raise NotImplementedError

    @staticmethod
    def create_param(param, shape):
        """
        Helper method to create Theano shared variables for
        Layer parameters and to initialize them.

        param: one of three things:
            - a numpy array with the initial parameter values
            - a Theano shared variable
            - a function or callable that takes the desired
              shape of the parameter array as its single
              argument.

        shape: the desired shape of the parameter array.
        """
        if isinstance(param, np.ndarray):
            if param.shape != shape:
                raise RuntimeError("parameter array has shape %s, should be %s" % (param.shape, shape))
            return theano.shared(param)

        elif isinstance(param, theano.compile.SharedVariable):
            # cannot check shape here, the shared variable might not be initialized correctly yet.
            return param

        elif hasattr(param, '__call__'):
            arr = param(shape)
            if not isinstance(arr, np.ndarray):
                raise RuntimeError("cannot initialize parameters: the provided callable did not return a numpy array")

            return theano.shared(utils.floatX(arr))

        else:
            raise RuntimeError("cannot initialize parameters: 'param' is not a numpy array, a Theano shared variable, or a callable")


class MultipleInputsLayer(Layer):
    def __init__(self, input_layers):
        self.input_layers = input_layers

    def get_output_shape(self):
        input_shapes = [input_layer.get_output_shape() for input_layer in self.input_layers]
        return self.get_output_shape_for(input_shapes)

    def get_output(self, input=None, *args, **kwargs):
        if isinstance(input, dict) and (self in input):
            # this layer is mapped to an expression or numpy array
            return utils.as_theano_expression(input[self])
        else: # in all other cases, just pass the network input on to the next layers.
            layer_inputs = [input_layer.get_output(input, *args, **kwargs) for input_layer in self.input_layers]
            return self.get_output_for(layer_inputs, *args, **kwargs)

    def get_output_shape_for(self, input_shapes):
        raise NotImplementedError

    def get_output_for(self, inputs, *args, **kwargs):
        raise NotImplementedError


class InputLayer(Layer):
    def __init__(self, shape, input_var=None):
        self.shape = shape
        ndim = len(shape)
        if input_var is None:
            # create the right TensorType for the given number of dimensions
            input_var_type = T.TensorType(theano.config.floatX, [False] * ndim)
            input_var = input_var_type("input")
        else:
            # ensure the given variable has the correct dimensionality
            if input_var.ndim != ndim:
                raise ValueError("shape has %d dimensions, "
                    "but variable has %d" % (ndim, input_var.ndim))
        self.input_var = input_var

    def get_output_shape(self):
        return self.shape

    def get_output(self, input=None, *args, **kwargs):
        if isinstance(input, dict):
            input = input.get(self, None)
        if input is None:
            input = self.input_var
        return utils.as_theano_expression(input)
            

## Layer implementations

class DenseLayer(Layer):
    def __init__(self, input_layer, num_units, W=init.Uniform(), b=init.Constant(0.), nonlinearity=nonlinearities.rectify):
        super(DenseLayer, self).__init__(input_layer)
        if nonlinearity is None:
            self.nonlinearity = nonlinearities.identity
        else:
            self.nonlinearity = nonlinearity

        self.num_units = num_units

        output_shape = self.input_layer.get_output_shape()
        num_inputs = int(np.prod(output_shape[1:]))

        self.W = self.create_param(W, (num_inputs, num_units))
        self.b = self.create_param(b, (num_units,)) if b is not None else None

    def get_params(self):
        return [self.W] + self.get_bias_params()

    def get_bias_params(self):
        return [self.b] if self.b is not None else []

    def get_output_shape_for(self, input_shape):
        return (input_shape[0], self.num_units)

    def get_output_for(self, input, *args, **kwargs):
        if input.ndim > 2:
            # if the input has more than two dimensions, flatten it into a
            # batch of feature vectors.
            input = input.flatten(2)

        activation = T.dot(input, self.W)
        if self.b is not None:
            activation = activation + self.b.dimshuffle('x', 0)
        return self.nonlinearity(activation)

class DropoutLayer(Layer):
    def __init__(self, input_layer, p=0.5, rescale=True):
        super(DropoutLayer, self).__init__(input_layer)
        self.p = p
        self.rescale = rescale

    def get_output_for(self, input, deterministic=False, *args, **kwargs):
        if deterministic or self.p == 0:
            return input
        else:
            retain_prob = 1 - self.p
            if self.rescale:
                input /= retain_prob

            return input * _srng.binomial(input.shape, p=retain_prob,
                                          dtype=theano.config.floatX)

dropout = DropoutLayer # shortcut


class GaussianNoiseLayer(Layer):
    def __init__(self, input_layer, sigma=0.1):
        super(GaussianNoiseLayer, self).__init__(input_layer)
        self.sigma = sigma

    def get_output_for(self, input, deterministic=False, *args, **kwargs):
        if deterministic or self.sigma == 0:
            return input
        else:
            return input + _srng.normal(input.shape, avg=0.0, std=self.sigma)


class RecurrentLayer(Layer):
    '''
    A layer which implements a recurrent connection.

    Expects inputs of shape
        (n_batch, n_time_steps, n_features_1, n_features_2, ...)
    '''
    def __init__(self, input_layer, input_to_hidden, hidden_to_hidden,
                 nonlinearity=nonlinearities.rectify,
                 h_init=init.Constant(0.)):
        '''
        Create a recurrent layer.

        :parameters:
            - input_layer : nntools.layers.Layer
                Input to the recurrent layer
            - input_to_hidden : nntools.layers.Layer
                Layer which connects input to thie hidden state
            - hidden_to_hidden : nntools.layers.Layer
                Layer which connects the previous hidden state to the new state
            - nonlinearity : function or theano.tensor.elemwise.Elemwise
                Nonlinearity to apply when computing new state
            - h_init : function or np.ndarray or theano.shared
                Initial hidden state
        '''
        super(RecurrentLayer, self).__init__(input_layer)

        self.input_to_hidden = input_to_hidden
        self.hidden_to_hidden = hidden_to_hidden
        if nonlinearity is None:
            self.nonlinearity = nonlinearities.identity
        else:
            self.nonlinearity = nonlinearity

        # Get the batch size and number of units based on the expected output
        # of the input-to-hidden layer
        (n_batch, self.num_units) = self.input_to_hidden.get_output_shape()

        # Initialize hidden state
        self.h_init = self.create_param(h_init, (n_batch, self.num_units))

    def get_params(self):
        return (get_all_params(self.input_to_hidden) +
                get_all_params(self.hidden_to_hidden) +
                [self.h_init])

    def get_bias_params(self):
        return (get_all_bias_params(self.input_to_hidden) +
                get_all_bias_params(self.hidden_to_hidden))

    def get_output_shape_for(self, input_shape):
        return (input_shape[0], input_shape[1], self.num_units)

    def get_output_for(self, input, *args, **kwargs):
        if input.ndim > 3:
            input = input.reshape((input.shape[0], input.shape[1],
                                   T.prod(input.shape[2:])))

        # Input should be provided as (n_batch, n_time_steps, n_features)
        # but scan requires the iterable dimension to be first
        # So, we need to dimshuffle to (n_time_steps, n_batch, n_features)
        input = input.dimshuffle(1, 0, 2)

        # Create single recurrent computation step function
        def step(layer_input, previous_output):
            return self.nonlinearity(
                self.input_to_hidden.get_output(layer_input) +
                self.hidden_to_hidden.get_output(previous_output))

        output = theano.scan(step, sequences=input,
                             outputs_info=[self.h_init])[0]
        # Now, dimshuffle back to (n_batch, n_time_steps, n_features))
        output = output.dimshuffle(1, 0, 2)

        return output


class ReshapeLayer(Layer):
    def __init__(self, input_layer, shape):
        super(ReshapeLayer, self).__init__(input_layer)
        self.shape = shape

    def get_output_shape_for(self, input_shape):
        return self.shape

    def get_output_for(self, input, *args, **kwargs):
        return input.reshape(self.shape)


class BidirectionalLayer(Layer):
    '''
    Takes two layers and runs one forward and one backword on input sequences.
    '''
    def __init__(self, input_layer, forward_layer, backward_layer):
        '''
        Initialize the bidirectional layer with a forward and backward layer

        :parameters:
            - input_layer : nntools.layers.Layer
                Input to the bidirectional layer
            - forward_layer : nntools.layers.Layer
                Layer to run the sequence forward on
            - backward_layer : nntools.layers.Layer
                Layer to run the sequence backward on
        '''
        # In order to sum the outputs of the layers, they must have the same
        # number of units
        assert forward_layer.num_units == backward_layer.num_units
        self.input_layer = input_layer
        self.forward_layer = forward_layer
        self.backward_layer = backward_layer

    def get_params(self):
        '''
        Get all parameters of the forward and backward layers.

        :returns:
            - params : list of theano.shared
                List of all parameters
        '''
        return (self.forward_layer.get_params()
                + self.backward_layer.get_params())

    def get_bias_params(self):
        '''
        Get all bias parameters of the forward and backward layers

        :returns:
            - bias_params : list of theano.shared
                List of all bias parameters
        '''
        return (self.forward_layer.get_bias_params()
                + self.backward_layer.get_bias_params())

    def get_output_shape_for(self, input_shape):
        '''
        Compute the expected output shape given the input.

        :parameters:
            - input_shape : tuple
                Dimensionality of expected input

        :returns:
            - output_shape : tuple
                Dimensionality of expected outputs given input_shape
        '''
        # In order to sum the outputs of the layers, they must have the same
        # number of units
        assert self.forward_layer.num_units == self.backward_layer.num_units
        return (input_shape[0], input_shape[1], self.forward_layer.num_units)

    def get_output_for(self, input, *args, **kwargs):
        '''
        Compute the output by running the sequence forwards through
        self.forward_layer and backwards through self.backward_layer

        :parameters:
            - input : theano.TensorType
                Symbolic input variable

        :returns:
            - layer_output : theano.TensorType
                Symbolic output variable
        '''
        forward_output = self.forward_layer.get_output_for(input)
        backward_output = self.backward_layer.get_output_for(
            input[:, ::-1, :])
        return forward_output + backward_output


class LSTMLayer(Layer):
    '''
    A long short-term memory (LSTM) layer.  Includes "peephole connections" and
    forget gate.  Based on the definition in [#graves2014generating]_, which is
    the current common definition.

    :references:
        .. [#graves2014generating] Alex Graves, "Generating Sequences With
            Recurrent Neural Networks".
    '''
    def __init__(self, input_layer, num_units,
                 W_input_to_input_gate=init.Normal(0.1),
                 W_hidden_to_input_gate=init.Normal(0.1),
                 W_cell_to_input_gate=init.Normal(0.1),
                 b_input_gate=init.Normal(0.1),
                 nonlinearity_input_gate=nonlinearities.sigmoid,
                 W_input_to_forget_gate=init.Normal(0.1),
                 W_hidden_to_forget_gate=init.Normal(0.1),
                 W_cell_to_forget_gate=init.Normal(0.1),
                 b_forget_gate=init.Normal(0.1),
                 nonlinearity_forget_gate=nonlinearities.sigmoid,
                 W_input_to_cell=init.Normal(0.1),
                 W_hidden_to_cell=init.Normal(0.1),
                 b_cell=init.Normal(0.1),
                 nonlinearity_cell=nonlinearities.tanh,
                 W_input_to_output_gate=init.Normal(0.1),
                 W_hidden_to_output_gate=init.Normal(0.1),
                 W_cell_to_output_gate=init.Normal(0.1),
                 b_output_gate=init.Normal(0.1),
                 nonlinearity_output_gate=nonlinearities.sigmoid,
                 nonlinearity_output=nonlinearities.tanh,
                 c_init=init.Constant(0.),
                 h_init=init.Constant(0.)):
        '''
        Initialize an LSTM layer.  For details on what the parameters mean, see
        (7-11) from [#graves2014generating]_.

        :parameters:
            - input_layer : layers.Layer
                Input to this recurrent layer
            - num_units : int
                Number of hidden units
            - W_input_to_input_gate : function or np.ndarray or theano.shared
                :math:`W_{xi}`
            - W_hidden_to_input_gate : function or np.ndarray or theano.shared
                :math:`W_{hi}`
            - W_cell_to_input_gate : function or np.ndarray or theano.shared
                :math:`W_{ci}`
            - b_input_gate : function or np.ndarray or theano.shared
                :math:`b_i`
            - nonlinearity_input_gate : function
                :math:`\sigma`
            - W_input_to_forget_gate : function or np.ndarray or theano.shared
                :math:`W_{xf}`
            - W_hidden_to_forget_gate : function or np.ndarray or theano.shared
                :math:`W_{hf}`
            - W_cell_to_forget_gate : function or np.ndarray or theano.shared
                :math:`W_{cf}`
            - b_forget_gate : function or np.ndarray or theano.shared
                :math:`b_f`
            - nonlinearity_forget_gate : function
                :math:`\sigma`
            - W_input_to_cell : function or np.ndarray or theano.shared
                :math:`W_{ic}`
            - W_hidden_to_cell : function or np.ndarray or theano.shared
                :math:`W_{hc}`
            - b_cell : function or np.ndarray or theano.shared
                :math:`b_c`
            - nonlinearity_cell : function or np.ndarray or theano.shared
                :math:`\tanh`
            - W_input_to_output_gate : function or np.ndarray or theano.shared
                :math:`W_{io}`
            - W_hidden_to_output_gate : function or np.ndarray or theano.shared
                :math:`W_{ho}`
            - W_cell_to_output_gate : function or np.ndarray or theano.shared
                :math:`W_{co}`
            - b_output_gate : function or np.ndarray or theano.shared
                :math:`b_o`
            - nonlinearity_output_gate : function
                :math:`\sigma`
            - nonlinearity_output : function or np.ndarray or theano.shared
                :math:`\tanh`
            - c_init : function or np.ndarray or theano.shared
                :math:`c_0`
            - h_init : function or np.ndarray or theano.shared
                :math:`h_0`
        '''
        # Initialize parent layer
        super(LSTMLayer, self).__init__(input_layer)

        # For any of the nonlinearities, if None is supplied, use identity
        if nonlinearity_input_gate is None:
            self.nonlinearity_input_gate = nonlinearities.identity
        else:
            self.nonlinearity_input_gate = nonlinearity_input_gate

        if nonlinearity_forget_gate is None:
            self.nonlinearity_forget_gate = nonlinearities.identity
        else:
            self.nonlinearity_forget_gate = nonlinearity_forget_gate

        if nonlinearity_cell is None:
            self.nonlinearity_cell = nonlinearities.identity
        else:
            self.nonlinearity_cell = nonlinearity_cell

        if nonlinearity_output_gate is None:
            self.nonlinearity_output_gate = nonlinearities.identity
        else:
            self.nonlinearity_output_gate = nonlinearity_output_gate

        if nonlinearity_output is None:
            self.nonlinearity_output = nonlinearities.identity
        else:
            self.nonlinearity_output = nonlinearity_output

        self.num_units = num_units

        # Input dimensionality is the output dimensionality of the input layer
        (num_batch, _, num_inputs) = self.input_layer.get_output_shape()

        # Initialize parameters using the supplied args
        self.W_input_to_input_gate = self.create_param(
            W_input_to_input_gate, (num_inputs, num_units))

        self.W_hidden_to_input_gate = self.create_param(
            W_hidden_to_input_gate, (num_units, num_units))

        self.W_cell_to_input_gate = self.create_param(
            W_cell_to_input_gate, (num_units))

        self.b_input_gate = self.create_param(b_input_gate, (num_units))

        self.W_input_to_forget_gate = self.create_param(
            W_input_to_forget_gate, (num_inputs, num_units))

        self.W_hidden_to_forget_gate = self.create_param(
            W_hidden_to_forget_gate, (num_units, num_units))

        self.W_cell_to_forget_gate = self.create_param(
            W_cell_to_forget_gate, (num_units))

        self.b_forget_gate = self.create_param(b_forget_gate, (num_units,))

        self.W_input_to_cell = self.create_param(
            W_input_to_cell, (num_inputs, num_units))

        self.W_hidden_to_cell = self.create_param(
            W_hidden_to_cell, (num_units, num_units))

        self.b_cell = self.create_param(b_cell, (num_units,))

        self.W_input_to_output_gate = self.create_param(
            W_input_to_output_gate, (num_inputs, num_units))

        self.W_hidden_to_output_gate = self.create_param(
            W_hidden_to_output_gate, (num_units, num_units))

        self.W_cell_to_output_gate = self.create_param(
            W_cell_to_output_gate, (num_units))

        self.b_output_gate = self.create_param(b_output_gate, (num_units,))

        self.c_init = self.create_param(c_init, (num_batch, num_units))
        self.h_init = self.create_param(h_init, (num_batch, num_units))

    def get_params(self):
        '''
        Get all parameters of this layer.

        :returns:
            - params : list of theano.shared
                List of all parameters
        '''
        return [self.W_input_to_input_gate,
                self.W_hidden_to_input_gate,
                self.W_cell_to_input_gate,
                self.b_input_gate,
                self.W_input_to_forget_gate,
                self.W_hidden_to_forget_gate,
                self.W_cell_to_forget_gate,
                self.b_forget_gate,
                self.W_input_to_cell,
                self.W_hidden_to_cell,
                self.b_cell,
                self.W_input_to_output_gate,
                self.W_hidden_to_output_gate,
                self.W_cell_to_output_gate,
                self.b_output_gate]

    def get_bias_params(self):
        '''
        Get all bias parameters of this layer.

        :returns:
            - bias_params : list of theano.shared
                List of all bias parameters
        '''
        return [self.b_input_gate, self.b_forget_gate,
                self.b_cell, self.b_output_gate]

    def get_output_shape_for(self, input_shape):
        '''
        Compute the expected output shape given the input.

        :parameters:
            - input_shape : tuple
                Dimensionality of expected input

        :returns:
            - output_shape : tuple
                Dimensionality of expected outputs given input_shape
        '''
        return (input_shape[0], input_shape[1], self.num_units)

    def get_output_for(self, input, *args, **kwargs):
        '''
        Compute this layer's output function given a symbolic input variable

        :parameters:
            - input : theano.TensorType
                Symbolic input variable

        :returns:
            - layer_output : theano.TensorType
                Symbolic output variable
        '''
        # Treat all layers after the first as flattened feature dimensions
        if input.ndim > 3:
            input = input.reshape((input.shape[0], input.shape[1],
                                   T.prod(input.shape[2:])))

        # Input should be provided as (n_batch, n_time_steps, n_features)
        # but scan requires the iterable dimension to be first
        # So, we need to dimshuffle to (n_time_steps, n_batch, n_features)
        input = input.dimshuffle(1, 0, 2)

        # Create single recurrent computation step function
        def step(layer_input, previous_cell, previous_output,
                 W_input_to_input_gate, W_hidden_to_input_gate,
                 W_cell_to_input_gate, b_input_gate, W_input_to_forget_gate,
                 W_hidden_to_forget_gate, W_cell_to_forget_gate, b_forget_gate,
                 W_input_to_cell, W_hidden_to_cell, b_cell,
                 W_input_to_output_gate, W_hidden_to_output_gate,
                 W_cell_to_output_gate, b_output_gate):
            # i_t = \sigma(W_{xi}x_t + W_{hi}h_{t-1} + W_{ci}c_{t-1} + b_i)
            input_gate = self.nonlinearity_input_gate(
                T.dot(layer_input, W_input_to_input_gate) +
                T.dot(previous_output, W_hidden_to_input_gate) +
                previous_cell*W_cell_to_input_gate +
                b_input_gate)
            # f_t = \sigma(W_{xf}x_t + W_{hf}h_{t-1} + W_{cf}c_{t-1} + b_f)
            forget_gate = self.nonlinearity_forget_gate(
                T.dot(layer_input, W_input_to_forget_gate) +
                T.dot(previous_output, W_hidden_to_forget_gate) +
                previous_cell*W_cell_to_forget_gate +
                b_forget_gate)
            # c_t = f_tc_{t - 1} + i_t\tanh(W_{xc}x_t + W_{hc}h_{t-1} + b_c)
            cell = (forget_gate*previous_cell +
                    input_gate*self.nonlinearity_cell(
                        T.dot(layer_input, W_input_to_cell) +
                        T.dot(previous_output, W_hidden_to_cell) +
                        b_cell))
            # o_t = \sigma(W_{xo}x_t + W_{ho}h_{t-1} + W_{co}c_t + b_o)
            output_gate = self.nonlinearity_output_gate(
                T.dot(layer_input, W_input_to_output_gate) +
                T.dot(previous_output, W_hidden_to_output_gate) +
                cell*W_cell_to_output_gate +
                b_output_gate)
            # h_t = o_t \tanh(c_t)
            output = output_gate*self.nonlinearity_output(cell)
            return [cell, output]

        # Scan op iterates over first dimension of input and repeatedly
        # applied the step function
        output = theano.scan(step, sequences=input,
                             outputs_info=[self.c_init, self.h_init],
                             non_sequences=[self.W_input_to_input_gate,
                                            self.W_hidden_to_input_gate,
                                            self.W_cell_to_input_gate,
                                            self.b_input_gate,
                                            self.W_input_to_forget_gate,
                                            self.W_hidden_to_forget_gate,
                                            self.W_cell_to_forget_gate,
                                            self.b_forget_gate,
                                            self.W_input_to_cell,
                                            self.W_hidden_to_cell, self.b_cell,
                                            self.W_input_to_output_gate,
                                            self.W_hidden_to_output_gate,
                                            self.W_cell_to_output_gate,
                                            self.b_output_gate])[0][1]
        # Now, dimshuffle back to (n_batch, n_time_steps, n_features))
        output = output.dimshuffle(1, 0, 2)

        return output


## Convolutions

class Conv1DLayer(Layer):
    def __init__(self, input_layer, num_filters, filter_length, stride=1, border_mode="valid", untie_biases=False,
                 W=init.Uniform(), b=init.Constant(0.), nonlinearity=nonlinearities.rectify,
                 convolution=conv.conv1d_mc0):
        super(Conv1DLayer, self).__init__(input_layer)
        if nonlinearity is None:
            self.nonlinearity = nonlinearities.identity
        else:
            self.nonlinearity = nonlinearity

        self.num_filters = num_filters
        self.filter_length = filter_length
        self.stride = stride
        self.border_mode = border_mode
        self.untie_biases = untie_biases
        self.convolution = convolution

        self.W = self.create_param(W, self.get_W_shape())
        if b is None:
            self.b = None
        elif self.untie_biases:
            output_shape = self.get_output_shape()
            self.b = self.create_param(b, (num_filters, output_shape[2]))
        else:
            self.b = self.create_param(b, (num_filters,))

    def get_W_shape(self):
        num_input_channels = self.input_layer.get_output_shape()[1]
        return (self.num_filters, num_input_channels, self.filter_length)

    def get_params(self):
        return [self.W] + self.get_bias_params()

    def get_bias_params(self):
        return [self.b] if self.b is not None else []

    def get_output_shape_for(self, input_shape):
        if self.border_mode == 'valid':
            output_length = (input_shape[2] - self.filter_length) // self.stride + 1
        elif self.border_mode == 'full':
            output_length = (input_shape[2] + self.filter_length) // self.stride - 1
        elif self.border_mode == 'same':
            output_length = input_shape[2] // self.stride
        else:
            raise RuntimeError("Invalid border mode: '%s'" % self.border_mode)

        return (input_shape[0], self.num_filters, output_length)

    def get_output_for(self, input, input_shape=None, *args, **kwargs):
        # the optional input_shape argument is for when get_output_for is called
        # directly with a different shape than the output_shape of self.input_layer.
        if input_shape is None:
            input_shape = self.input_layer.get_output_shape()

        filter_shape = self.get_W_shape()

        if self.border_mode in ['valid', 'full']:
            conved = self.convolution(input, self.W, subsample=(self.stride,), image_shape=input_shape,
                                      filter_shape=filter_shape, border_mode=self.border_mode)
        elif self.border_mode == 'same':
            conved = self.convolution(input, self.W, subsample=(self.stride,), image_shape=input_shape,
                                      filter_shape=filter_shape, border_mode='full')
            shift = (self.filter_length - 1) // 2
            conved = conved[:, :, shift:input_shape[2] + shift]
        else:
            raise RuntimeError("Invalid border mode: '%s'" % self.border_mode)

        if self.b is None:
            activation = conved
        elif self.untie_biases:
            activation = conved + self.b.dimshuffle('x', 0, 1)
        else:
            activation = conved + self.b.dimshuffle('x', 0, 'x')

        return self.nonlinearity(activation)


class Conv2DLayer(Layer):
    def __init__(self, input_layer, num_filters, filter_size, strides=(1, 1), border_mode="valid", untie_biases=False,
                 W=init.Uniform(), b=init.Constant(0.), nonlinearity=nonlinearities.rectify,
                 convolution=T.nnet.conv2d):
        super(Conv2DLayer, self).__init__(input_layer)
        if nonlinearity is None:
            self.nonlinearity = nonlinearities.identity
        else:
            self.nonlinearity = nonlinearity

        self.num_filters = num_filters
        self.filter_size = filter_size
        self.strides = strides
        self.border_mode = border_mode
        self.untie_biases = untie_biases
        self.convolution = convolution

        self.W = self.create_param(W, self.get_W_shape())
        if b is None:
            self.b = None
        elif self.untie_biases:
            output_shape = self.get_output_shape()
            self.b = self.create_param(b, (num_filters, output_shape[2], output_shape[3]))
        else:
            self.b = self.create_param(b, (num_filters,))

    def get_W_shape(self):
        num_input_channels = self.input_layer.get_output_shape()[1]
        return (self.num_filters, num_input_channels, self.filter_size[0], self.filter_size[1])

    def get_params(self):
        return [self.W] + self.get_bias_params()

    def get_bias_params(self):
        return [self.b] if self.b is not None else []

    def get_output_shape_for(self, input_shape):
        if self.border_mode == 'valid':
            output_width = (input_shape[2] - self.filter_size[0]) // self.strides[0] + 1
            output_height = (input_shape[3] - self.filter_size[1]) // self.strides[1] + 1
        elif self.border_mode == 'full':
            output_width = (input_shape[2] + self.filter_size[0]) // self.strides[0] - 1
            output_height = (input_shape[3] + self.filter_size[1]) // self.strides[1] - 1
        elif self.border_mode == 'same':
            output_width = input_shape[2] // self.strides[0]
            output_height = input_shape[3] // self.strides[1]
        else:
            raise RuntimeError("Invalid border mode: '%s'" % self.border_mode)

        return (input_shape[0], self.num_filters, output_width, output_height)

    def get_output_for(self, input, input_shape=None, *args, **kwargs):
        # the optional input_shape argument is for when get_output_for is called
        # directly with a different shape than the output_shape of self.input_layer.
        if input_shape is None:
            input_shape = self.input_layer.get_output_shape()

        filter_shape = self.get_W_shape()

        if self.border_mode in ['valid', 'full']:
            conved = self.convolution(input, self.W, subsample=self.strides, image_shape=input_shape,
                                      filter_shape=filter_shape, border_mode=self.border_mode)
        elif self.border_mode == 'same':
            conved = self.convolution(input, self.W, subsample=self.strides, image_shape=input_shape,
                                      filter_shape=filter_shape, border_mode='full')
            shift_x = (self.filter_size[0] - 1) // 2
            shift_y = (self.filter_size[1] - 1) // 2
            conved = conved[:, :, shift_x:input_shape[2] + shift_x, shift_y:input_shape[3] + shift_y]
        else:
            raise RuntimeError("Invalid border mode: '%s'" % self.border_mode)

        if self.b is None:
            activation = conved
        elif self.untie_biases:
            activation = conved + self.b.dimshuffle('x', 0, 1, 2)
        else:
            activation = conved + self.b.dimshuffle('x', 0, 'x', 'x')

        return self.nonlinearity(activation)

# TODO: add Conv3DLayer


## Pooling

class MaxPool2DLayer(Layer):
    def __init__(self, input_layer, ds, ignore_border=False):
        super(MaxPool2DLayer, self).__init__(input_layer)
        self.ds = ds # a tuple
        self.ignore_border = ignore_border

    def get_output_shape_for(self, input_shape):
        output_shape = list(input_shape) # copy / convert to mutable list
        
        if self.ignore_border:
            output_shape[2] = int(np.floor(float(output_shape[2]) / self.ds[0]))
            output_shape[3] = int(np.floor(float(output_shape[3]) / self.ds[1]))
        else:
            output_shape[2] = int(np.ceil(float(output_shape[2]) / self.ds[0]))
            output_shape[3] = int(np.ceil(float(output_shape[3]) / self.ds[1]))

        return tuple(output_shape)

    def get_output_for(self, input, *args, **kwargs):
        return downsample.max_pool_2d(input, self.ds, self.ignore_border)

# TODO: add reshape-based implementation to MaxPool2DLayer
# TODO: add MaxPool1DLayer
# TODO: add MaxPool3DLayer


class FeaturePoolLayer(Layer):
    """
    Pooling across feature maps. This can be used to implement maxout.
    IMPORTANT: this layer requires that the number of feature maps is
    a multiple of the pool size.
    """
    def __init__(self, input_layer, ds, axis=1, pool_function=T.max):
        """
        ds: the number of feature maps to be pooled together
        axis: the axis along which to pool. The default value of 1 works
        for DenseLayer and Conv*DLayers
        pool_function: the pooling function to use
        """
        super(FeaturePoolLayer, self).__init__(input_layer)
        self.ds = ds
        self.axis = axis
        self.pool_function = pool_function

        num_feature_maps = self.input_layer.get_output_shape()[self.axis]
        if num_feature_maps % self.ds != 0:
            raise RuntimeError("Number of input feature maps (%d) is not a multiple of the pool size (ds=%d)" %
                    (num_feature_maps, self.ds))

    def get_output_shape_for(self, input_shape):
        output_shape = list(input_shape) # make a mutable copy
        output_shape[self.axis] = output_shape[self.axis] // self.ds
        return tuple(output_shape)

    def get_output_for(self, input, *args, **kwargs):
        num_feature_maps = input.shape[self.axis]
        num_feature_maps_out = num_feature_maps // self.ds

        pool_shape = ()
        for k in range(self.axis):
            pool_shape += (input.shape[k],)
        pool_shape += (num_feature_maps_out, self.ds)
        for k in range(self.axis + 1, input.ndim):
            pool_shape += (input.shape[k],)

        input_reshaped = input.reshape(pool_shape)
        return self.pool_function(input_reshaped, axis=self.axis + 1)


class FeatureWTALayer(Layer):
    """
    Perform 'Winner Take All' across feature maps: zero out all but
    the maximal activation value within a group of features.
    IMPORTANT: this layer requires that the number of feature maps is
    a multiple of the pool size.
    """
    def __init__(self, input_layer, ds, axis=1):
        """
        ds: the number of feature maps per group. This is called 'ds'
        for consistency with the pooling layers, even though this
        layer does not actually perform a downsampling operation.
        axis: the axis along which the groups are formed.
        """
        super(FeatureWTALayer, self).__init__(input_layer)
        self.ds = ds
        self.axis = axis

        num_feature_maps = self.input_layer.get_output_shape()[self.axis]
        if num_feature_maps % self.ds != 0:
            raise RuntimeError("Number of input feature maps (%d) is not a multiple of the group size (ds=%d)" %
                    (num_feature_maps, self.ds))

    def get_output_for(self, input, *args, **kwargs):
        num_feature_maps = input.shape[self.axis]
        num_pools = num_feature_maps // self.ds

        pool_shape = ()
        arange_shuffle_pattern = ()
        for k in range(self.axis):
            pool_shape += (input.shape[k],)
            arange_shuffle_pattern += ('x',)

        pool_shape += (num_pools, self.ds)
        arange_shuffle_pattern += ('x', 0)

        for k in range(self.axis + 1, input.ndim):
            pool_shape += (input.shape[k],)
            arange_shuffle_pattern += ('x',)

        input_reshaped = input.reshape(pool_shape)
        max_indices = T.argmax(input_reshaped, axis=self.axis + 1, keepdims=True)

        arange = T.arange(self.ds).dimshuffle(*arange_shuffle_pattern)
        mask = T.eq(max_indices, arange).reshape(input.shape)

        return input * mask


## Network in network

class NINLayer(Layer):
    """
    Like DenseLayer, but broadcasting across all trailing dimensions beyond the 2nd.
    This results in a convolution operation with filter size 1 on all trailing dimensions.
    Any number of trailing dimensions is supported, so NINLayer can be used to implement
    1D, 2D, 3D, ... convolutions.
    """
    def __init__(self, input_layer, num_units, untie_biases=False,
        W=init.Uniform(), b=init.Constant(0.), nonlinearity=nonlinearities.rectify):
        super(NINLayer, self).__init__(input_layer)
        if nonlinearity is None:
            self.nonlinearity = nonlinearities.identity
        else:
            self.nonlinearity = nonlinearity

        self.num_units = num_units
        self.untie_biases = untie_biases

        output_shape = self.input_layer.get_output_shape()
        num_input_channels = output_shape[1]

        self.W = self.create_param(W, (num_input_channels, num_units))
        if b is None:
            self.b = None
        elif self.untie_biases:
            output_shape = self.get_output_shape()
            self.b = self.create_param(b, (num_units,) + output_shape[2:])
        else:
            self.b = self.create_param(b, (num_units,))

    def get_params(self):
        return [self.W] + self.get_bias_params()

    def get_bias_params(self):
        return [self.b] if self.b is not None else []

    def get_output_shape_for(self, input_shape):
        return (input_shape[0], self.num_units) + input_shape[2:]

    def get_output_for(self, input, *args, **kwargs):
        out_r = T.tensordot(self.W, input, axes=[[0], [1]]) # cf * bc01... = fb01...
        remaining_dims = range(2, input.ndim) # input dims to broadcast over
        out = out_r.dimshuffle(1, 0, *remaining_dims) # bf01...

        if self.b is None:
            activation = out
        else:
            if self.untie_biases:
                remaining_dims_biases = range(1, input.ndim - 1) # no broadcast
            else:
                remaining_dims_biases = ['x'] * (input.ndim - 2) # broadcast
            b_shuffled = self.b.dimshuffle('x', 0, *remaining_dims_biases)
            activation = out + b_shuffled

        return self.nonlinearity(activation)


class GlobalPoolLayer(Layer):
    """
    Layer that pools globally across all trailing dimensions beyond the 2nd.
    """
    def __init__(self, input_layer, pool_function=T.mean):
        super(GlobalPoolLayer, self).__init__(input_layer)
        self.pool_function = pool_function

    def get_output_shape_for(self, input_shape):
        return input_shape[:2]

    def get_output_for(self, input, *args, **kwargs):
        return self.pool_function(input.flatten(3), axis=2)


## Shape modification

class FlattenLayer(Layer):
    def get_output_shape_for(self, input_shape):
        return (input_shape[0], int(np.prod(input_shape[1:])))

    def get_output_for(self, input, *args, **kwargs):
        return input.flatten(2)

flatten = FlattenLayer # shortcut


class PadLayer(Layer):
    def __init__(self, input_layer, width, val=0, batch_ndim=2):
        super(PadLayer, self).__init__(input_layer)
        self.width = width
        self.val = val
        self.batch_ndim = batch_ndim

    def get_output_shape_for(self, input_shape):
        output_shape = ()
        for k, s in enumerate(input_shape):
            if k < self.batch_ndim:
                output_shape += (s,)
            else:
                output_shape += (s + 2 * self.width,)

        return output_shape

    def get_output_for(self, input, *args, **kwargs):
        return padding.pad(input, self.width, self.val, self.batch_ndim)

pad = PadLayer # shortcut


## Merging multiple layers

class ConcatLayer(MultipleInputsLayer):
    def __init__(self, input_layers, axis=1):
        super(ConcatLayer, self).__init__(input_layers)
        self.axis = axis

    def get_output_shape_for(self, input_shapes):
        sizes = [input_shape[self.axis] for input_shape in input_shapes]
        output_shape = list(input_shapes[0]) # make a mutable copy
        output_shape[self.axis] = sum(sizes)
        return tuple(output_shape)

    def get_output_for(self, inputs, *args, **kwargs):
        # unfortunately the gradient of T.concatenate has no GPU
        # implementation, so we have to do this differently.
        return utils.concatenate(inputs, axis=self.axis)

concat = ConcatLayer # shortcut


class ElemwiseSumLayer(MultipleInputsLayer):
    """
    This layer performs an elementwise sum of its input layers.
    It requires all input layers to have the same output shape.

    Hint: Depending on your architecture, this can be used to avoid the more
    costly :class:`ConcatLayer`. For example, instead of concatenating layers
    before a :class:`DenseLayer`, insert separate :class:`DenseLayer` instances
    of the same number of output units and add them up afterwards. (This avoids
    the copy operations in concatenation, but splits up the dot product.)
    """

    def __init__(self, input_layers, coeffs=1):
        """
        Creates a layer perfoming an elementwise sum of its input layers.

        :parameters:
            - input_layers: list
                A list of :class:`Layer` instances of same output shape to sum
            - coeffs: list or scalar
                A same-sized list of coefficients, or a single coefficient that
                is to be applied to all instances. By default, these will not
                be included in the learnable parameters of this layer.
        """
        super(ElemwiseSumLayer, self).__init__(input_layers)
        if isinstance(coeffs, list):
            if len(coeffs) != len(input_layers):
                raise ValueError("Mismatch: got %d coeffs for %d input_layers" %
                                 (len(coeffs), len(input_layers)))
        else:
            coeffs = [coeffs] * len(input_layers)
        self.coeffs = coeffs

    def get_output_shape_for(self, input_shapes):
        if any(shape != input_shapes[0] for shape in input_shapes):
            raise ValueError("Mismatch: not all input shapes are the same")
        return input_shapes[0]

    def get_output_for(self, inputs, *args, **kwargs):
        output = None
        for coeff, input in zip(self.coeffs, inputs):
            if coeff != 1:
                input *= coeff
            if output is not None:
                output += input
            else:
                output = input
        return output