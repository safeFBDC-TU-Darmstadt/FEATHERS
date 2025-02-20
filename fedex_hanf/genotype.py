from collections import namedtuple

Genotype = namedtuple('Genotype', 'normal normal_concat reduce reduce_concat')
# Fashion-MNIST
#GENOTYPE = Genotype(normal=[('max_pool_3x3', 0), ('sep_conv_3x3', 1), ('max_pool_3x3', 2), ('max_pool_3x3', 1), ('max_pool_3x3', 2), ('max_pool_3x3', 0), ('max_pool_3x3', 0), ('max_pool_3x3', 1)], normal_concat=range(2, 6), reduce=[('dil_conv_3x3', 0), ('skip_connect', 1), ('skip_connect', 0), ('dil_conv_5x5', 2), ('sep_conv_5x5', 1), ('sep_conv_5x5', 2), ('max_pool_3x3', 3), ('sep_conv_5x5', 0)], reduce_concat=range(2, 6))

# CIFAR-10
GENOTYPE = Genotype(normal=[('sep_conv_5x5', 1), ('dil_conv_5x5', 0), ('sep_conv_3x3', 2), ('dil_conv_5x5', 1), ('sep_conv_5x5', 3), ('sep_conv_3x3', 2), ('dil_conv_5x5', 2), ('dil_conv_5x5', 4)], normal_concat=range(2, 6), reduce=[('avg_pool_3x3', 1), ('dil_conv_3x3', 0), ('dil_conv_5x5', 2), ('sep_conv_5x5', 1), ('sep_conv_3x3', 3), ('skip_connect', 0), ('dil_conv_3x3', 3), ('dil_conv_3x3', 1)], reduce_concat=range(2, 6))