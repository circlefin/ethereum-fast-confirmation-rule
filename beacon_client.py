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

"""A simple helper for querying a Beacon node"""

from urllib.parse import urljoin, urlparse
import requests

class BeaconClientError(Exception):
    """Base error class for Beacon Client Errors"""

class SerializationError(BeaconClientError):
    """Raised for response serialization errors"""

class ServerError(BeaconClientError):
    """Raised in response to server errors"""

class BeaconClient:
    """
    A simple class for querying a Beacon node
    """

    def __init__(self, api_endpoint, logger):
        parsed = urlparse(api_endpoint)
        if not parsed.scheme or not parsed.netloc:
            raise BeaconClientError("Beacon API endpoint invalid")

        self.api_endpoint = api_endpoint
        self.logger = logger
    
    def get_genesis(self):
        """
        Retrieves the genesis time.
        """
        genesis = self._query_node('eth/v1/beacon/genesis')
        return int(genesis['data']['genesis_time'])

    def get_block_headers(self, params={}):
        """
        Retrieves the genesis time.
        """
        return self._query_node('eth/v1/beacon/headers/head', params=params)
    
    def get_fork_choice(self, params={}):
        """
        Retrieves the current fork-choice data, including all the potential heads.
        """
        return self._query_node('eth/v1/debug/fork_choice', params=params)
    
    def get_committees(self, params={}):
        """
        Retrieves validator committee information.
        """
        return self._query_node('eth/v1/beacon/states/head/committees', params=params)

    def _query_node(self, path, extra_headers={}, params={}):
        """
        Queries the configured BeaconAPI at a given path, with optional headers and parameters.
        """
        try:
            r = requests.get(urljoin(self.api_endpoint, path), headers={'accept': 'application/json',} | extra_headers, params=params, timeout=5)
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            error_msg = f"An error occurred while querying the Beacon API: {str(e)}"
            self.logger.error(error_msg)
            raise ServerError(error_msg) from e
        
        try:
            return r.json()
        except ValueError as e:
            error_msg = "Failed to decode the response from Beacon API"
            self.logger.error(error_msg)
            raise SerializationError(error_msg) from e
    
