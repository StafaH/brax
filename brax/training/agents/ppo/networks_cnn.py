"""
Network implementations
"""

from functools import partial
from typing import Any, Callable, Sequence, Tuple

from flax import linen
import jax
import jax.numpy as jp

from brax.training import networks

ModuleDef = Any
ActivationFn = Callable[[jp.ndarray], jp.ndarray]
Initializer = Callable[..., Any]


class CNN(linen.Module):
  """CNN module.
  Warning: this expects the images to be 3D; convention NHWC
  num_filters: the number of filters per layer
  kernel_sizes: also per layer
  """
  num_filters: Sequence[int]
  kernel_sizes: Sequence[Tuple]
  strides: Sequence[Tuple]
  activation: ActivationFn = linen.relu
  use_bias: bool = True

  @linen.compact
  def __call__(self, data: jp.ndarray):
    hidden = data
    for i, (num_filter, kernel_size, stride) in enumerate(
      zip(self.num_filters, self.kernel_sizes, self.strides)):
      
      hidden = linen.Conv(
          num_filter,
          kernel_size=kernel_size,
          strides=stride,
          use_bias=self.use_bias)(
              hidden)
      
      hidden = self.activation(hidden)
    return hidden


class VisionMLP(linen.Module):
  # Apply a CNN backbone then an MLP.
  layer_sizes: Sequence[int]
  activation: ActivationFn = linen.relu
  kernel_init: Initializer = jax.nn.initializers.lecun_uniform()
  activate_final: bool = False
  layer_norm: bool = False
  normalise_channels: bool = False

  @linen.compact
  def __call__(self, data: dict):
    if self.normalise_channels:
      # Calculates shared statistics over an entire 2D image.
      image_layernorm = partial(linen.LayerNorm, use_bias=False, use_scale=False,
                   reduction_axes=(-1, -2))
    
      def ln_per_chan(v: jax.Array):
        normalised = [image_layernorm()(v[..., chan]) for chan in range(v.shape[-1])]
        return jp.stack(normalised, axis=-1)

      pixels_hidden = {
        key: ln_per_chan(v) for key, v in data.items() 
        if key.startswith('pixels/')}
    else:
      pixels_hidden = {
        k: v for k, v in data.items() if k.startswith('pixels/')}

    natureCNN = partial(CNN,
                        num_filters=[32, 64, 64],
                        kernel_sizes=[(8, 8), (4, 4), (3, 3)],
                        strides=[(4, 4), (2, 2), (1, 1)],
                        activation=linen.relu,
                        use_bias=False)
    cnn_outs = [natureCNN()(pixels_hidden[key]) for key in pixels_hidden.keys()]
    cnn_outs = [jp.mean(cnn_out, axis=(-2, -3)) for cnn_out in cnn_outs]
    if 'state' in data:
      cnn_outs.append(data['state']) # TODO: Try with dedicated state network

    hidden = jp.concatenate(cnn_outs, axis=-1)
    return networks.MLP(layer_sizes=self.layer_sizes,
                        activation=self.activation,
                        kernel_init=self.kernel_init,
                        activate_final=self.activate_final,
                        layer_norm=self.layer_norm)(hidden)
