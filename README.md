# PETRA-experiments
This repossitory demonstrates the PETRA framework operation and includes launch scripts results and supplementary materials.

# Install requirements

pip3 install -r requirements

# Running the Experiment

You can run the experiment in any container by simply executing:

```bash
pip install git+https://github.com/v1docq/FedCore.git@experiments
```

Additionally, install `openpyxl` to enable saving results in `.xlsx` format instead of `.txt`:

```bash
pip install openpyxl
```

## PyTorch Versions Used

Two versions of PyTorch were used for the experiments:

1. **GPU Version**  
   ```bash
   pip install torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cu118
   ```

2. **CPU Version**  
   ```bash
   pip install torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cpu
   ```

## Execute experiment

To run particular experiment one could just execute corresponding script like 

- `experimental_scripts_imgnt/experiments_img.py` - for Imagenette dataset
- `experimental_scripts/experiments.py` - for CIFAR dataset
- `experimental_scripts_rgr/experiments_rgr.py` - for time series regression

# Analysis of results

Results are stored in `results` for GPU experiments and `results_cpu` for CPU experiments. 
Directory `analysis` contains Jupyter Notebooks for processing results with outcome as plots and tables located in corresponding directories. 