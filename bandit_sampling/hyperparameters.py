import numpy as np

class Hyperparameters:

    _instance = None

    def __init__(self, nr_configs) -> None:
        if Hyperparameters._instance is not None:
            raise RuntimeError("Hyperparameters is a singleton, use instance()")
        self.sample_hyperparams = lambda: {
            'learning_rate': 10 ** (np.random.uniform(-4, -2))
        }
        self.hyperparams = [self.sample_hyperparams() for _ in range(nr_configs)]
        
    @classmethod
    def instance(cls, nr_configs):
        if Hyperparameters._instance is None:
            Hyperparameters._instance = Hyperparameters(nr_configs)
        return Hyperparameters._instance

    def __getitem__(self, idx):
        return self.hyperparams[idx]

    def __len__(self):
        return len(self.hyperparams)

    def to_dict(self):
        hyperparam_dict = {}
        for config in self.hyperparams:
            for key, val in config.items():
                if key in hyperparam_dict.keys():
                    hyperparam_dict[key].append(val)
                else:
                    hyperparam_dict[key] = [val]
        return hyperparam_dict