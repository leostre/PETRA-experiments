import random
import numpy as np
import torch
import os


def set_all_seeds(seed=42, multi_gpu=False):
    """
    Set seeds for all major random number generators in Python libraries
    to ensure reproducible results in AI/ML experiments.
    
    Parameters:
        seed (int): Seed value to use (default: 42)
    """
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    if multi_gpu:
        torch.cuda.manual_seed_all(seed)  # if using multi-GPU
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    os.environ['PYTHONHASHSEED'] = str(seed)
    
    print(f"All seeds set to {seed} for random, numpy, torch")

set_all_seeds(42)

import gc
import traceback
import pandas as pd
import io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from itertools import permutations
from fedcore.api.config_factory import ConfigFactory
from fedcore.api.api_configs import (APIConfigTemplate, AutoMLConfigTemplate, FedotConfigTemplate,
                                     LearningConfigTemplate, ModelArchitectureConfigTemplate,
                                     NeuralModelConfigTemplate, QuantTemplate, PruningTemplate, 
                                     LowRankTemplate)
from fedcore.data.dataloader import load_data
from fedcore.api.main import FedCore
from fedcore.tools.example_utils import get_scenario_for_api
from fedcore.algorithm.quantization.utils import ParentalReassembler
from fedcore.architecture.utils.paths import PATH_TO_DATA
from fedcore.architecture.comptutaional.devices import default_device

RESULT_DIR = '../results'
PRETRAIN_MODELS_DIR = '../pretrain_models'
EPOCHS_PER_NODE = 1 #5
POP_SIZE = 1# 5
TIMEOUT = 0.5

RESIZE = (224, 224)

# TODO: delete for release
if default_device().type == "cuda":
    os.environ['PYTORCH_CUDA_ALLOC_CONF'] = ""
    os.environ['CUDA_VISIBLE_DEVICES'] = '2'


task_problems = {
    # 'img_cls_cifar': {'problem': 'classification', 'initial_model': 'ResNet18', 'dataset': 'CIFAR10'},
    'img_cls_imagenet': {'problem': 'classification', 'initial_model': 'ResNet18', 'dataset': 'Imagenette'},
    # 'ts_cls': {'problem':'classification', 'initial_model': 'ResNet18', 'dataset': 'CinCECGTorso'},
    # 'ts_reg': {'problem':'regression', 'initial_model': 'InceptionNet', 'dataset': 'AppliancesEnergy'}
}

peft_problems = {
    'low-rank': {'peft_problem': 'low_rank'},
    'pruning': {'peft_problem': 'pruning'},
    'quant-dynamic': {'peft_problem': 'quantization', 'quant_type': 'dynamic'},
    'quant-static': {'peft_problem': 'quantization', 'quant_type': 'static'},
    'quant-qat': {'peft_problem': 'quantization', 'quant_type': 'qat'}
}


class TemplateLoader:
    def __init__(self, task_params: dict, model=None):
        self.problem = task_params['problem']
        self.dataset = task_params['dataset']
        self.model = model or task_params['initial_model']
        self.loss = 'cross_entropy' if self.problem == 'classification' else 'rmse'
        self.metrics = ['accuracy', 'latency'] if self.problem == 'classification' else ['rmse', 'latency']

    def load_dataset(self):
        if self.problem == 'classification':
            try:
                train_loader = {'resize': RESIZE, "batch_size": 32, "shuffle": True, "is_train": True, "data_type": "image", "split_ratio": [0.8, 0.2], "num_workers": 0}
                test_loader = {'resize': RESIZE, "batch_size": 32, "shuffle": False, "is_train": False, "data_type": "image", "num_workers": 0}
                return load_data(self.dataset, train_loader), load_data(self.dataset, test_loader)
            except:
                train_path = os.path.join(PATH_TO_DATA, 'time_series_classification', 'one_dim', f'{self.dataset}', f'{self.dataset}_TRAIN.tsv')
                test_path = os.path.join(PATH_TO_DATA, 'time_series_classification', 'one_dim', f'{self.dataset}', f'{self.dataset}_TEST.tsv')
                train_loader = {'resize': RESIZE, "batch_size": 8, "shuffle": True, "data_type": "time_series", "split_ratio": [0.8, 0.2], "num_workers": 0}
                test_loader = {'resize': RESIZE, "batch_size": 8, "shuffle": False, "data_type": "time_series", "num_workers": 0}
                return load_data(train_path, train_loader), load_data(test_path, test_loader)
        elif self.problem == 'regression':
            train_path = os.path.join(PATH_TO_DATA, 'time_series_regression', 'multi_dim', f'{self.dataset}', f'{self.dataset}_TRAIN.ts')
            test_path = os.path.join(PATH_TO_DATA, 'time_series_regression', 'multi_dim', f'{self.dataset}', f'{self.dataset}_TEST.ts')
            train_loader = {'resize': RESIZE, "batch_size": 8, "shuffle": True, "data_type": "time_series", "split_ratio": [0.8, 0.2], "num_workers": 0}
            test_loader = {'resize': RESIZE, "batch_size": 8, "shuffle": False, "data_type": "time_series", "num_workers": 0}
            return load_data(train_path, train_loader), load_data(test_path, test_loader)


    def get_peft_config(self, peft_dict):
        ptype = peft_dict['peft_problem']
        qtype = peft_dict.get('quant_type')
        epochs_per_stage = EPOCHS_PER_NODE
        base_config = NeuralModelConfigTemplate(epochs=epochs_per_stage, log_each=1,
                                                #  eval_each=1,
                                                   criterion=self.loss)
        if ptype == 'low_rank':
            return ptype, LowRankTemplate(epochs=epochs_per_stage,
                                          log_each=1, 
                                        #   eval_each=1,
                                            criterion=self.loss,
                                          custom_criterions={'hoer': 5,}, 
                                          compose_mode='two_layers',
                                          strategy='explained_variance',
                                          rank_prune_each=max(1, int(0.3 * epochs_per_stage)),
                                          non_adaptive_threshold=0.8, )
        if ptype == 'pruning':
            return ptype, PruningTemplate(importance='magnitude', pruning_ratio=0.5, finetune_params=base_config)
        if ptype == 'quantization':
            return ptype, QuantTemplate(quant_type=qtype, allow_emb=False, allow_conv=True, qat_params=base_config)
        raise ValueError("Unsupported PEFT type")

    def build_config(self, peft_dict, current_model):
        initial, strategy = get_scenario_for_api('from_checkpoint', current_model)
        peft_type, peft_config = self.get_peft_config(peft_dict)
        pop_size = POP_SIZE
        # model_cfg = ModelArchitectureConfigTemplate(input_dim=None, output_dim=None, depth=1)
        pretrain_cfg = NeuralModelConfigTemplate(epochs=0, log_each=1,
                                                #   eval_each=1,
                                                 criterion=self.loss, 
                                                #  model_architecture=model_cfg
                                                 )
        fedot = FedotConfigTemplate(problem=self.problem, metric=self.metrics, pop_size=pop_size,
                                    timeout=TIMEOUT, initial_assumption=initial, n_jobs=1)
        automl = AutoMLConfigTemplate(fedot_config=fedot)
        learning = LearningConfigTemplate(criterion=self.loss, learning_strategy=strategy,
                                          learning_strategy_params=pretrain_cfg,
                                          peft_strategy=peft_type, peft_strategy_params=peft_config)
        return APIConfigTemplate(automl_config=automl, learning_config=learning)


def save_results(model, metrics, model_name, dataset_name, combo, step, hist=None):
    combo_list = list(combo)
    combo_name = "_".join(str(x) for x in combo_list)
    result_dir = Path(RESULT_DIR, model_name, dataset_name, combo_name)
    os.makedirs(result_dir, exist_ok=True)
    model_path = Path(result_dir, f"{step}_{combo_list[step]}.pt")
    hist_path = Path(result_dir, f"{step}_{combo_list[step]}_history.json")

    try:
        torch.save(model, model_path)
    except:
        lambda model: torch.save(model, model_path)
    if hist is not None:
        hist.save(hist_path)
    try:
        metrics_path = Path(result_dir, f"{step}_{combo_list[step]}_metrics.xlsx")
        quality_df = pd.DataFrame(metrics['quality_comparison'])
        compute_df = pd.DataFrame(metrics['computational_comparison'])
        with pd.ExcelWriter(metrics_path) as writer:
            quality_df.to_excel(writer, sheet_name='quality_comparison')
            compute_df.to_excel(writer, sheet_name='computational_comparison')
    except:
        pass
    try:
        metrics_path = Path(result_dir, f"{step}_{combo_list[step]}_metrics.txt")
        torch.save(metrics, Path(result_dir, f"{step}_{combo_list[step]}_metrics.pth"))
        with open(metrics_path, 'w') as f:
            f.write(str(metrics))
    except:
        pass


def save_log(log, model_name, dataset_name, combo, step):
    combo_list = list(combo)
    combo_name = "_".join(str(x) for x in combo_list)
    result_dir = Path(RESULT_DIR, model_name, dataset_name, combo_name)
    os.makedirs(result_dir, exist_ok=True)
    log_path = Path(result_dir, f"{step}_{combo_list[step]}_log")
    with open(log_path.with_suffix('.txt'), 'w') as f:
        f.write(str(log))


def valid_combo(combo):
    peft_types = [peft_problems[c]['peft_problem'] for c in combo]
    return all(peft_types[i] != peft_types[i+1] for i in range(len(peft_types) - 1))


def is_combo_completed(model_name, dataset_name, combo):
    combo_list = list(combo)
    combo_name = "_".join(str(x) for x in combo_list)
    result_dir = Path(RESULT_DIR, model_name, dataset_name, combo_name)
    if not result_dir.exists():
        return False
    # for step in range(4):
    #     model_file = Path(result_dir, f"{step}_{combo_list[step]}.pt")
    #     if not model_file.exists():
    #         return False
    return True


def filter_completed_combos(all_combos, model_name, dataset_name):
    return [combo for combo in all_combos if not is_combo_completed(model_name, dataset_name, combo)]


if __name__ == "__main__":
    for task_name, task in task_problems.items():
        print(f"\n=== Starting task: {task_name} ===")
        loader = TemplateLoader(task)
        train_data, test_data = loader.load_dataset()
        all_peft_keys = list(peft_problems.keys())
        combos = [combo for combo in permutations(all_peft_keys, 4) if valid_combo(combo)]
        all_valid_combos = filter_completed_combos(combos, loader.model, loader.dataset)
        for combo_id, combo in enumerate(all_valid_combos):
            print(f"\n-- PEFT combo #{combo_id}: {combo} --")
            tp = 'base'
            if loader.dataset == 'Imagenette':
                tp = 'imagenet'
            path_to_model = f'{PRETRAIN_MODELS_DIR}/{loader.model}_{tp}.pth'
            current_model = {'path_to_model': path_to_model, 'model_type': loader.model}
            model = None
            for step, peft_key in enumerate(combo):
                buffer = io.StringIO()
                try:
                    with redirect_stdout(buffer), redirect_stderr(buffer):
                    # with open('/ptls-experiments/TMP.txt', 'at') as file:
                        print(f"\n>>> PEFT step {step+1}: {peft_key}")
                        if peft_problems[peft_key]['peft_problem'] in ('pruning',) and not isinstance(current_model, dict):
                                print("Reassembling pruned model")
                                ParentalReassembler.reassemble(current_model)
                                from fedcore.models.network_impl.decomposed_layers import IDecomposed
                                assert not any(
                                    isinstance(m, IDecomposed) for m in current_model.modules()
                            )
                        api_template = loader.build_config(peft_problems[peft_key], current_model)
                        config = ConfigFactory.from_template(api_template)()
                        compressor = FedCore(config)
                        compressor.fit(train_data)
                        
                        metrics = compressor.get_report(test_data)
                        hist = compressor.manager.solver.history
                        model = compressor.fedcore_model.operator.root_node.fitted_operation.model_after
                        save_results(model, metrics, loader.model, loader.dataset, combo, step, hist)
                        current_model = model
                except Exception as e:
                    print(f"Failed step {combo[step]} for {loader.model} on {loader.dataset}")
                    traceback.print_exc()
                    save_log(buffer.getvalue(), loader.model, loader.dataset, combo, step)
                finally:
                    buffer.close()
            del model
        del loader, train_data, test_data
        torch.cuda.empty_cache()
        gc.collect()
