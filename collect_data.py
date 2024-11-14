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
"""
A script to periodically query a Beacon node for fork-choice data
and persist it for further analysis
"""

import json
import time
import argparse
import configparser
import logging
import eth2spec.capella.mainnet as spec
from common import LOG_LEVELS
from beacon_client import BeaconClient, BeaconClientError

logger = logging.getLogger('ConfRuleCollectData')

# Much of this code is forked and adapted from the prototype of the paper: A Confirmation Rule for the Ethereum Consensus Protocol
# Original code is available at: https://gist.github.com/adiasg/4150de36181fd0f4b2351bef7b138893?ref=adiasg.me

# Errors
class CollectDataError(Exception):
    """Base error class errors occurred while collecting data"""

class NodeError(CollectDataError):
    """Errors occurring while interacting with a node"""

class ForkChoiceDataNotUpdatedError(CollectDataError):
    """Error occurring when the fork choice data is not updating as expected"""


def calculate_current_slot(genesis_time_seconds):
    """
    Calculates the current slot, based off of the genesis time and the system time.

    :param genesis_time: The genesis time. This is used to calculate the current slot, which is written into each 
    data snapshot.
    :returns a tuple containing the current slot (int) and current time in the slot (int)
    """
    current_time = time.time()
    current_slot = int(current_time - genesis_time_seconds) // spec.config.SECONDS_PER_SLOT
    current_time_in_slot = int(current_time - genesis_time_seconds) % spec.config.SECONDS_PER_SLOT
    return int(current_slot), int(current_time_in_slot)


def get_confirmation_context(beacon_client, current_slot):
    """
    Retrieves fork-choice data required for the confirmation rule. 

    Forked from and modified: https://gist.github.com/adiasg/4150de36181fd0f4b2351bef7b138893
    
    :param beacon_client: An instance of BeaconClient
    :param data_directory: The directory under which the collected fork-choice data will be stored.
    :param genesis_time: The genesis time. This is used to calculate the current slot, which is written into each 
    data snapshot.
    :raises NodeError: Raised if there was an issue querying the Beacon node
    :raises ForkChoiceDataNotUpdatedError: Raised if the data to need to be re-queried 
    """
    try:
        head_block_header = beacon_client.get_block_headers()
        fork_choice_context = beacon_client.get_fork_choice()
        head_committee = beacon_client.get_committees(params={'slot': current_slot})
    except BeaconClientError as e:
        raise NodeError() from e

    # If the head_committee is missing data, retry
    # This can occur if querying at the beginning of an epoch
    committee_size = 0
    try:
        for comm in head_committee['data']:
            committee_size += len(comm['validators'])
    except Exception as e:
        raise ForkChoiceDataNotUpdatedError() from e

    # Prepare a dict of fork choice blocks, keyed by their root
    nodes = {}
    for node in fork_choice_context['fork_choice_nodes']:
        block_root = node['block_root']
        nodes[block_root] = node

    return {
        'current_slot': current_slot,
        'justified_checkpoint': fork_choice_context['justified_checkpoint'],
        'finalized_checkpoint': fork_choice_context['finalized_checkpoint'],
        'nodes': nodes,
        'head_root': head_block_header['data']['root'],
        'committee_size': committee_size,
    }  


def store_data(data_directory, data, current_slot, current_time_in_slot):
    """
    Prepares a JSON file under the data directory with the fork choice data. 

    Each file is formatted as: <slot>_<current seconds in slot>.json.
    """
    json_string = json.dumps(data)
    file_name = f'{data_directory}/{current_slot}_{current_time_in_slot}.json'
    with open(file_name, 'a', encoding='UTF-8') as f:
        f.write(json_string)
    logger.debug('Saved fork choice data to: %s', file_name)


def run(
    beacon_client,
    data_directory,
    genesis_time_seconds
):
    """
    Retrieves fork-choice data, and persists it to a JSON file under the data_directory
    with the file format <slot>_<time in slot>.json.
    
    :param beacon_client: An instance of BeaconClient
    :param data_directory: The directory under which the collected fork-choice data will be stored.
    :param genesis_time: The genesis time. This is used to calculate the current slot, which is written into each 
    data snapshot.
    """
    query_time = time.time()
    logger.debug('------ START querying data at: %s -------', query_time)

    current_slot, time_in_current_slot = calculate_current_slot(genesis_time_seconds)

    # Query for data
    try:
        confirmation_info = get_confirmation_context(beacon_client, current_slot)
    except NodeError as e:
        logger.exception(e)
        raise e
    except ForkChoiceDataNotUpdatedError as e:
        logger.exception(e)
        raise e

    logger.info('Successfully queried data at %s', query_time)
    logger.debug('Current slot number: %s, time since start of slot %s', current_slot, time_in_current_slot)

    # Persist current time in the slot
    confirmation_info['current_time_in_slot'] = time_in_current_slot

    # Store data 
    store_data(data_directory, confirmation_info, current_slot, time_in_current_slot)


if __name__ == '__main__':
    # Read Beacon API configured in the .env
    config = configparser.ConfigParser()
    config.read('.env')
    try:
        beacon_api = config['collectdata.config']['BEACON_API'].replace('"', '')
    except KeyError as e:
        raise CollectDataError("Must set BEACON_API in .env") from e

    # Parse remaining arguments from command line
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--datadir", help="Path to directory where data will be written", required=True)
    parser.add_argument("-p", "--period", type=int, help="The period over which to collect data (seconds).", required=True)
    parser.add_argument("-f", "--frequency", type=int, default=10, help="The frequency with which to poll the Beacon API (seconds). Defaults to 10.")
    parser.add_argument("-a", "--adjusttime", type=int, default=2, help="How long to wait within an interval for the block to appear, if not seen yet (seconds). Defaults to 2.")
    parser.add_argument("-w", "--waittime", type=int, default=2, help="How long to wait if the BEACON API reports a transient error (seconds). Defaults to 2.")
    parser.add_argument('-l', "--loglevel", type=str, default="INFO", help="Log level. Defaults to INFO.", choices=LOG_LEVELS,)
    args = parser.parse_args()

    # Configure logger
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(args.loglevel)

    # Configure BeaconClient
    client = BeaconClient(
        beacon_api,
        logger
    )

    # Since genesis time doesn't change, we can fetch it 1x, and reference later to calculate 
    # the current time within a slot
    genesis_time = client.get_genesis()

    # Run query
    query_start_time = interval_start_time = time.monotonic()
    while interval_start_time < query_start_time + args.period:
        try:
            run(
                client,
                args.datadir,
                genesis_time
            )
            cur_time = time.monotonic()
            time.sleep(max(args.frequency - (cur_time - interval_start_time), 0))

        except NodeError:
            time.sleep(args.waittime)

        except ForkChoiceDataNotUpdatedError:
            time.sleep(args.adjusttime)

        interval_start_time = time.monotonic()
