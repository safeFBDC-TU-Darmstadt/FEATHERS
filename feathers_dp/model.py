import torch
import torch.nn as nn
from operations import *
from utils import drop_path
from opacus.grad_sample import register_grad_sampler
from typing import Dict
from operations import OPS, TABOPS

class Cell(nn.Module):

  def __init__(self, genotype, C_prev_prev, C_prev, C, reduction, reduction_prev, device):
    super(Cell, self).__init__()
    print(C_prev_prev, C_prev, C)

    self.device = device
    if reduction_prev:
      self.preprocess0 = FactorizedReduce(C_prev_prev, C)
    else:
      self.preprocess0 = ReLUConvBN(C_prev_prev, C, 1, 1, 0)
    self.preprocess1 = ReLUConvBN(C_prev, C, 1, 1, 0)
    
    if reduction:
      op_names, indices = zip(*genotype.reduce)
      concat = genotype.reduce_concat
    else:
      op_names, indices = zip(*genotype.normal)
      concat = genotype.normal_concat
    self._compile(C, op_names, indices, concat, reduction)

  def _compile(self, C, op_names, indices, concat, reduction):
    assert len(op_names) == len(indices)
    self._steps = len(op_names) // 2
    self._concat = concat
    self.multiplier = len(concat)

    self._ops = nn.ModuleList()
    for name, index in zip(op_names, indices):
      stride = 2 if reduction and index < 2 else 1
      op = OPS[name](C, stride, True)
      self._ops += [op]
    self._indices = indices

  def forward(self, s0, s1, drop_prob):
    s0 = self.preprocess0(s0)
    s1 = self.preprocess1(s1)

    states = [s0, s1]
    for i in range(self._steps):
      h1 = states[self._indices[2*i]]
      h2 = states[self._indices[2*i+1]]
      op1 = self._ops[2*i]
      op2 = self._ops[2*i+1]
      h1 = op1(h1)
      h2 = op2(h2)
      if self.training and drop_prob > 0.:
        if not isinstance(op1, Identity):
          h1 = drop_path(h1, drop_prob, self.device)
        if not isinstance(op2, Identity):
          h2 = drop_path(h2, drop_prob, self.device)
      s = h1 + h2
      states += [s]
    return torch.cat([states[i] for i in self._concat], dim=1)

class TabularCell(nn.Module):

  def __init__(self, genotype, out_prev_prev, out_prev, out_curr, reduction, reduction_prev, device):
    super(Cell, self).__init__()
    self.device = device
    self.reduction = reduction
    self.reduction_prev = reduction_prev

    if reduction_prev:
      self.preprocess = nn.Linear(out_prev_prev, out_prev)
    else:
      self.preprocess = Identity()
    if reduction:
      self.reduction = nn.Sequential(
        nn.Linear(out_prev, out_curr),
        nn.ReLU()
      )
    else:
      self.reduction = Identity()
    
    if reduction:
      op_names, indices = zip(*genotype.reduce)
      concat = genotype.reduce_concat
    else:
      op_names, indices = zip(*genotype.normal)
      concat = genotype.normal_concat
    self._compile(out_curr, op_names, indices, concat, reduction)

  def _compile(self, out_prev, out_curr, op_names, indices, concat, reduction):
    assert len(op_names) == len(indices)
    self._steps = len(op_names) // 2
    self.postprocess = nn.Linear((self._steps + 2)*out_curr, out_curr)

    self._ops = nn.ModuleList()
    for name, index in zip(op_names, indices):
      op = TABOPS[name](out_prev, out_curr)
      self._ops += [op]
    self._indices = indices

  def forward(self, s0, s1, drop_prob):
    s0 = self.preprocess(s0)

    states = [self.reduction(s0), self.reduction(s1)]
    for i in range(self._steps):
      h1 = states[self._indices[2*i]]
      h2 = states[self._indices[2*i+1]]
      op1 = self._ops[2*i]
      op2 = self._ops[2*i+1]
      h1 = op1(h1)
      h2 = op2(h2)
      if self.training and drop_prob > 0.:
        if not isinstance(op1, Identity):
          h1 = drop_path(h1, drop_prob, self.device)
        if not isinstance(op2, Identity):
          h2 = drop_path(h2, drop_prob, self.device)
      s = h1 + h2
      states += [s]
    return self.postprocess(torch.cat(states, dim=1))

class AuxiliaryHeadCIFAR(nn.Module):

  def __init__(self, C, num_classes):
    """assuming input size 8x8"""
    super(AuxiliaryHeadCIFAR, self).__init__()
    self.features = nn.Sequential(
      nn.ReLU(inplace=True),
      nn.AvgPool2d(5, stride=3, padding=0, count_include_pad=False), # image size = 2 x 2
      nn.Conv2d(C, 128, 1, bias=False),
      nn.GroupNorm(num_groups=1, num_channels=128),
      nn.ReLU(inplace=True),
      nn.Conv2d(128, 768, 2, bias=False),
      nn.GroupNorm(num_groups=1, num_channels=768),
      nn.ReLU(inplace=True)
    )
    self.classifier = nn.Linear(768, num_classes)

  def forward(self, x):
    x = self.features(x)
    x = self.classifier(x.view(x.size(0),-1))
    return x


class AuxiliaryHeadImageNet(nn.Module):

  def __init__(self, C, num_classes):
    """assuming input size 14x14"""
    super(AuxiliaryHeadImageNet, self).__init__()
    self.features = nn.Sequential(
      nn.ReLU(inplace=True),
      nn.AvgPool2d(5, stride=2, padding=0, count_include_pad=False),
      nn.Conv2d(C, 128, 1, bias=False),
      nn.GroupNorm(num_groups=1, num_channels=128),
      nn.ReLU(inplace=True),
      nn.Conv2d(128, 768, 2, bias=False),
      # NOTE: This batchnorm was omitted in my earlier implementation due to a typo.
      # Commenting it out for consistency with the experiments in the paper.
      # nn.BatchNorm2d(768),
      nn.ReLU(inplace=True)
    )
    self.classifier = nn.Linear(768, num_classes)

  def forward(self, x):
    x = self.features(x)
    x = self.classifier(x.view(x.size(0),-1))
    return x


class NetworkCIFAR(nn.Module):

  def __init__(self, C, num_classes, layers, auxiliary, genotype, device, in_channels=3):
    super(NetworkCIFAR, self).__init__()
    self._layers = layers
    self._auxiliary = auxiliary
    self.drop_path_prob = 0.2

    stem_multiplier = 3
    C_curr = stem_multiplier*C
    self.stem = nn.Sequential(
      nn.Conv2d(in_channels, C_curr, 3, padding=1, bias=False),
      nn.GroupNorm(num_groups=1, num_channels=C_curr),
    )
    
    C_prev_prev, C_prev, C_curr = C_curr, C_curr, C
    self.cells = nn.ModuleList()
    reduction_prev = False
    for i in range(layers):
      if i in [layers//3, 2*layers//3]:
        C_curr *= 2
        reduction = True
      else:
        reduction = False
      cell = Cell(genotype, C_prev_prev, C_prev, C_curr, reduction, reduction_prev, device)
      reduction_prev = reduction
      self.cells += [cell]
      C_prev_prev, C_prev = C_prev, cell.multiplier*C_curr
      if i == 2*layers//3:
        C_to_auxiliary = C_prev

    if auxiliary:
      self.auxiliary_head = AuxiliaryHeadCIFAR(C_to_auxiliary, num_classes)
    self.global_pooling = nn.AdaptiveAvgPool2d(1)
    self.classifier = nn.Linear(C_prev, num_classes)

  def forward(self, input):
    logits_aux = None
    s0 = s1 = self.stem(input)
    for i, cell in enumerate(self.cells):
      s0, s1 = s1, cell(s0, s1, self.drop_path_prob)
      if i == 2*self._layers//3:
        if self._auxiliary and self.training:
          logits_aux = self.auxiliary_head(s1)
    out = self.global_pooling(s1)
    logits = self.classifier(out.view(out.size(0),-1))
    return logits, logits_aux


class NetworkImageNet(nn.Module):

  def __init__(self, C, num_classes, layers, auxiliary, genotype, device):
    super(NetworkImageNet, self).__init__()
    self._layers = layers
    self._auxiliary = auxiliary
    self.drop_path_prob = 0.2

    self.stem0 = nn.Sequential(
      nn.Conv2d(3, C // 2, kernel_size=3, stride=2, padding=1, bias=False),
      nn.GroupNorm(num_groups=1, num_channels=C // 2),
      nn.ReLU(inplace=True),
      nn.Conv2d(C // 2, C, 3, stride=2, padding=1, bias=False),
      nn.GroupNorm(num_groups=1, num_channels=C),
    )

    self.stem1 = nn.Sequential(
      nn.ReLU(inplace=True),
      nn.Conv2d(C, C, 3, stride=2, padding=1, bias=False),
      nn.GroupNorm(num_groups=1, num_channels=C),
    )

    C_prev_prev, C_prev, C_curr = C, C, C

    self.cells = nn.ModuleList()
    reduction_prev = True
    for i in range(layers):
      if i in [layers // 3, 2 * layers // 3]:
        C_curr *= 2
        reduction = True
      else:
        reduction = False
      cell = Cell(genotype, C_prev_prev, C_prev, C_curr, reduction, reduction_prev, device)
      reduction_prev = reduction
      self.cells += [cell]
      C_prev_prev, C_prev = C_prev, cell.multiplier * C_curr
      if i == 2 * layers // 3:
        C_to_auxiliary = C_prev

    if auxiliary:
      self.auxiliary_head = AuxiliaryHeadImageNet(C_to_auxiliary, num_classes)
    self.global_pooling = nn.AvgPool2d(7)
    self.classifier = nn.Linear(C_prev, num_classes)

  def forward(self, input):
    logits_aux = None
    s0 = self.stem0(input)
    s1 = self.stem1(s0)
    for i, cell in enumerate(self.cells):
      s0, s1 = s1, cell(s0, s1, self.drop_path_prob)
      if i == 2 * self._layers // 3:
        if self._auxiliary and self.training:
          logits_aux = self.auxiliary_head(s1)
    out = self.global_pooling(s1)
    logits = self.classifier(out.view(out.size(0), -1))
    return logits, logits_aux

class NetworkTabular(nn.Module):
  def __init__(self, in_dim, num_classes, layers, genotype, device):
    super(NetworkTabular, self).__init__()
    self.in_dime = in_dim
    self._num_classes = num_classes
    self._layers = layers
    self.device = device
    self.drop_path_prob = 0.2
 
    dim_prev_prev, dim_prev, dim_curr = in_dim, in_dim, in_dim
    self.cells = nn.ModuleList()
    reduction_prev = False
    for i in range(layers):
      if i in [layers//3, 2*layers//3]:
        dim_curr = int(dim_curr * 0.8)
        reduction = True
      else:
        reduction = False
      cell = TabularCell(genotype, dim_prev_prev, dim_prev, dim_curr, 
                      reduction=reduction, reduction_prev=reduction_prev, device=device)
      reduction_prev = reduction
      self.cells += [cell]
      dim_prev_prev, dim_prev = dim_prev, dim_curr

    self.classifier = nn.Linear(dim_prev, num_classes)

  def forward(self, input):
    s0 = s1 = input
    for i, cell in enumerate(self.cells):
      s0, s1 = s1, cell(s0, s1, self.drop_path_prob)
    logits = self.classifier(s1)
    return logits, None

#@register_grad_sampler(NetworkCIFAR)
#def compute_linear_grad_sample(
#    layer: nn.Linear, activations: torch.Tensor, backprops: torch.Tensor
#) -> Dict[nn.Parameter, torch.Tensor]:
#    """
#    Computes per sample gradients for ``nn.Linear`` layer
#    Args:
#        layer: Layer
#        activations: Activations
#        backprops: Backpropagations
#    """
#    gs = torch.einsum("n...i,n...j->nij", backprops, activations)
#    ret = {layer.weight: gs}
#    if layer.bias is not None:
#        ret[layer.bias] = torch.einsum("n...k->nk", backprops)
#
#    return ret
#
#@register_grad_sampler(NetworkImageNet)
#def compute_linear_grad_sample(
#    layer: nn.Linear, activations: torch.Tensor, backprops: torch.Tensor
#) -> Dict[nn.Parameter, torch.Tensor]:
#    """
#    Computes per sample gradients for ``nn.Linear`` layer
#    Args:
#        layer: Layer
#        activations: Activations
#        backprops: Backpropagations
#    """
#    gs = torch.einsum("n...i,n...j->nij", backprops, activations)
#    ret = {layer.weight: gs}
#    if layer.bias is not None:
#        ret[layer.bias] = torch.einsum("n...k->nk", backprops)
#
#    return ret