import flwr as fl
from hanf_strategy import HANFStrategy
import torch.nn as nn
from fedex_model import NetworkCIFAR
import argparse
import config
from genotypes import GENOTYPE
import torch
from helpers import prepare_log_dirs

def start_server(log_dir, rounds, dataset):
    device = torch.device("cuda:{}".format(config.SERVER_GPU))
    net = NetworkCIFAR(config.OUT_CHANNELS, config.CLASSES, config.CELL_NR, False, GENOTYPE, device, config.IN_CHANNELS)

    prepare_log_dirs()
    
    # Define strategy
    strategy = HANFStrategy(
        fraction_fit=0.5,
        fraction_eval=0.5,
        initial_net=net,
        log_dir=log_dir
    )

    # Start server
    fl.server.start_server(
        server_address="[::]:{}".format(config.PORT),
        config={"num_rounds": rounds},
        strategy=strategy,
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--rounds', type=int, default=60)
    parser.add_argument('--log-dir')
    parser.add_argument('--dataset', type=str, default='fmnist')

    args = parser.parse_args()

    start_server(args.log_dir, config.ROUNDS, args.dataset)
