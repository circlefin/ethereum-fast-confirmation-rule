# Fast Confirmation Rule Exploration

## Disclaimer

This repository is intended for educational and academic purposes only--not for production applications.

## Attribution

This reference implementation is based on [this implementation](https://gist.github.com/adiasg/4150de36181fd0f4b2351bef7b138893?ref=adiasg.me) and [code spec](https://github.com/ethereum/consensus-specs/pull/3339), which is the prototype of the paper: [A Confirmation Rule for the Ethereum Consensus Protocol](https://arxiv.org/pdf/2405.00549).

## Overview

This repository contains tooling to evaluate the [fast confirmation rule for Ethereum](https://arxiv.org/pdf/2405.00549). It implements the rule in Python, and contains scripts for gathering live network data and applying the rule to the collected data, under a variety of byzantine thresholds and configurations. The scripts also bubbles up certain interesting scenarios, like if the a confirmed block is ever reorged. 

Data is collected through the [Ethereum Beacon Client APIs](https://ethereum.github.io/beacon-APIs/).

## File structure

The project has the following file structure:
- README.md 
- `logs/`: Stores stdout and stderror when running ``analyze_data.py``.
- `results/`: Stores results from applying the confirmation rule through ``analyze_data.py``.
- `test_data/`: pre-collected data for test-running the ``analyze_data.py``.
- `confirmation_rule.py`: Contains the implementation of the confirmation rule
- `collect_data.py`: Periodically collects data from the Ethereum Beacon API and stores the data locally
- `analyze_data.py`: A script that reads data, computes the confirmation times, and stores it under ``/results``.

## Configuration 

To begin collecting data, set a `BEACON_API` value in a local `.env` file in the root of the repository. 

It's recommended to set up a virtual environment using Python 3.9, and the dependencies listed in ``requirements.txt``.

## Collecting data 

Run `collect_data.py` with various parameters:

```
python collect_data.py 
    --datadir datadirectory # where the collected data will be saved
    --period 6000 # length of time, in seconds, to collect data for
    --frequency 5 # polling frequency
    --waittime 2 # transient error backoff when querying the API
    --loglevel debug 
python collect_data.py -d sup -p 60 -f 10 -l info   
```

The value passed for `datadir` must be created beforehand. 

## Applying the confirmation rule 

Run `analyze_data.py` over the collected data:

```
python analyze_data.py
    --datadir /datadirectory # where the collected data was stored 
    --byzantinethreshold 0.1
    --slashingthreshold 0.05 
```

The confirmation times will be saved under ``/results``, and a detailed debug log will be saved under ``/logs``.

## Implementation Approximations:

The following 2 approximations are made in the `confirmation_rule.py` implementation.

#### Approximation 1:
All the validators has exactly 32 ETH as effective balance. 

#### Approximation 2:
The LMD weight of the checkpoint == FFG support for the checkpoint in the current epoch.
In Ethereum, the LMD-GHOST vote and FFG vote are bundled together. There is constraint that enforces the FFG checkpoint a validator votes for must be an ancestor of the LMD head they vote for. Therefore, whenever the descendant of the checkpoint receives an LMD vote in the current epoch, the checkpoint will also receive the corresponding FFG support. That's why the the LMD weight of the checkpoint in the current epoch is also the FFG support they receive.

