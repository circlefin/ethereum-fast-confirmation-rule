# Copyright 2024 Circle Internet Group, Inc. All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import logging
import argparse
import re
import sys
from confirmation_rule import ConfRule
from common import LOG_LEVELS

SLOT_DATA_FILE_FORMAT = re.compile(r"""\d+_\d+\.json""")

def get_logger(log_file, loglevel):
    """
    return a configured logger object
    """
    # Create a logger object
    logger = logging.getLogger('ConfRuleLogger')
    logger.setLevel(logging.DEBUG)  # Set the logging level for the logger

    # Create a file handler for logging to a file
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)  # Log all levels to the file

    # Create a console handler for logging to stdout
    console_handler = logging.StreamHandler()
    console_handler.setLevel(loglevel)  # Log INFO and higher levels to the console

    # Create a logging format
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)  # Set the format for the file handler
    console_handler.setFormatter(formatter)  # Set the format for the console handler

    # Add the handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

def read_json(file_name):
    """
    read the json file and return the dictionary
    """
    with open(file_name, 'r', encoding="UTF-8") as file:
        return json.load(file)

def sort_file_names(data_folder):
    """
    sort the files in a folder by slot and then by time_in_slot
    the file names is in the form of "{slot}_{time_in_slot}.json"
    """
    file_names = os.listdir(data_folder)  # get all the file names in the folder
    file_names = [item for item in file_names if SLOT_DATA_FILE_FORMAT.fullmatch(item) ]

    # split the file names
    file_name_arithmetic = []
    for file_name in file_names:
        split = file_name.split("_")
        slot = int(split[0])
        time_in_slot = int(split[1].split(".")[0])
        file_name_arithmetic.append((slot, time_in_slot))

    # sort the file names by slot and then by time_in_slot
    file_name_arithmetic.sort(key=lambda x: (x[0], x[1]))
    # reconstruct the file names
    sorted_file_names = list(map(lambda x: f"{x[0]}_{x[1]}.json", file_name_arithmetic))
    return sorted_file_names

def log_data_collection_time_period(num_of_processed_slots, logger):
    """
    Logs the data collection time period.
    """
    data_collection_time = 12 * num_of_processed_slots
    data_collection_days = data_collection_time // (60*60*24)
    data_collection_hours = data_collection_time % (60*60*24) // (60*60)
    data_collection_mins = data_collection_time % (60*60) // 60
    logger.info("""The total number of processed slots is: %s, the data collection period is: %s days %s hours %s minutes""",
        num_of_processed_slots,
        data_collection_days,
        data_collection_hours,
        data_collection_mins
    )

def execute_rule(rule, data_directory, logger):
    """
    Executes the confirmation rule, using the data found in the data directory
    """
    logger.info("""Executing confirmation rule with confirmation byzantine threshold: %s and the confirmation slashing threshold is: %s""",
        rule.confirmation_byzantine_threshold,
        rule.confirmation_slashing_threshold
    )

    # First, ensure that the entires in the data_directory are sorted
    sorted_files = sort_file_names(data_directory)
    for file_name in sorted_files:  # process the datasets
        logger.debug(f"Processing {file_name}")

        # read conf info from file
        conf_info = read_json(os.path.join(data_directory, file_name))

        # update current confirmed with the next dataset
        rule.update_confirmed_head(conf_info)
    
    return rule

if __name__ == '__main__':
    # Collect parameters from the command line
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--datadir", help="Path to directory holding collected data", required=True)
    parser.add_argument("-b", "--byzantinethreshold", help="The byzantine threshold to apply. Must be less than or equal to 1/3.", required=True)
    parser.add_argument("-s", "--slashingthreshold", help="The slashing threshold to apply. Must be less than the byzantine threshold.", required=True)
    parser.add_argument('-l', "--loglevel", type=str, default="INFO", help="Log level for stdout. Defaults to INFO.", choices=LOG_LEVELS,)
    args = parser.parse_args()
    
    data_folder = args.datadir
    byzantine_threshold = float(args.byzantinethreshold)
    slashing_threshold = float(args.slashingthreshold)

    # Validate parameters
    if not 0 <= slashing_threshold <= byzantine_threshold <= 1/3:
        print("Invalid input. Please ensure that 0 <= slashing_threshold <= byzantine_threshold <= 1/3.")
        sys.exit(1)

    log_file = f'logs/conf_rule_{byzantine_threshold}_{slashing_threshold}.log'
    result_file = f'results/conf_time_{byzantine_threshold}_{slashing_threshold}.json'
    empty_or_forked_slots_file = f"logs/forked_or_empty_slots_urls_{byzantine_threshold}_{slashing_threshold}.txt"

    if not os.path.exists('logs'):
        os.makedirs('logs')

    if not os.path.exists('results'):
        os.makedirs('results')

    # Initialize logger
    logger = get_logger(log_file, args.loglevel.upper())

    # Initialize ConfRule with the byzantine / slashing threshold and logger
    conf_rule = ConfRule(
        byzantine_threshold,
        slashing_threshold,
        logger
    )

    # Execute rule against the data 
    execute_rule(conf_rule, data_folder, logger)

    # get the total number of slots processed and log the total data collection time
    log_data_collection_time_period(conf_rule.get_num_of_processed_slots(), logger)

    # get the confirmation times
    conf_times = conf_rule.get_conf_times()
    logger.info('The average confirmation time: %ss. Maximum confirmation time is: %ss.', sum(conf_times)/len(conf_times), max(conf_times))
    logger.info('The debug info is saved in %s', log_file)

    # save the info of the empty or forked slots
    empty_or_forked_slots = conf_rule.get_empty_or_forked_slots()
    with open(empty_or_forked_slots_file, 'w', encoding="UTF-8") as f:
        for slot in empty_or_forked_slots:
            f.write(f"https://beaconscan.com/slot/{slot}\n")

    logger.info('The info about the empty or forked slots is saved to %s', empty_or_forked_slots_file)

    # save conf times to file
    with open(result_file, 'w', encoding="UTF-8") as f:
        json.dump(conf_times, f)

    logger.info('The confirmation time data is saved to %s', result_file)
