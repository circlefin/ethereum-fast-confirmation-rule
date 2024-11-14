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

import eth2spec.capella.mainnet as spec

# This code is adapted from the prototype of the paper: A Confirmation Rule for the Ethereum Consensus Protocol
# The original code is available at: https://gist.github.com/adiasg/4150de36181fd0f4b2351bef7b138893?ref=adiasg.me,
# as well as at: https://github.com/ethereum/consensus-specs/blob/687fd5cb3288e9e4708b719d278bf567b70ff2cd/specs/bellatrix/confirmation-rule.md

VALIDATOR_BALANCE = 32 * (10**9) # we assume that all the validators have exactly 32 ETH 
PROPOSER_SCORE_BOOST = 40 # proposer boost is 40% of the full attestation weight
SLOTS_PER_EPOCH = int(spec.SLOTS_PER_EPOCH)
SLOT_LEN = int(spec.config.SECONDS_PER_SLOT)
COMMITTEE_WEIGHT_ESTIMATION_ADJUSTMENT_FACTOR = int(5)

class ConfRule:
    """
    Implementation of the confirmation rule. 
    """

    def __init__(self, confirmation_byzantine_threshold, confirmation_slashing_threshold, logger):
        self.confirmation_byzantine_threshold = confirmation_byzantine_threshold
        self.confirmation_slashing_threshold = confirmation_slashing_threshold
        self.logger = logger

        self.empty_or_forked_slots = []
        self.confirmed_head_root = None
        self.confirmed_head_slot = 0
        self.ffg_confirmed_checkpoint = None
        self.current_slot = 0
        self.time_in_current_slot = 0
        self.times_from_confirmed_head = []
        self.conf_times = []
        self.processed_slots = set()

    def update_confirmed_head(self, conf_info):
        """
        Updates the confirmed head given the conf_info provided.
        """
        current_slot = int(conf_info["current_slot"])
        assert self.current_slot <= int(conf_info["current_slot"])  # check that the slots are processed in chronological order
        if self.current_slot + 1 < current_slot:  # if the gap between the current slot and the slot from previous dataset is greater than 1 slot,
            record_conf_time = False  #  do not record conf time.
        else:
            record_conf_time = True
        self.current_slot = current_slot  # update current slot
        self.time_in_current_slot = int(conf_info["current_time_in_slot"])

        # add current slot to the set of processed slots
        self.processed_slots.add(self.current_slot)

        head_root = self.__find_head_root(conf_info)
        self.logger.debug("---- Looking for confirmed head ----")
        self.logger.debug(f"current slot is: {self.current_slot}, current epoch is: {self.current_slot // SLOTS_PER_EPOCH}, " +
                          f"current slot in epoch is: {self.current_slot % SLOTS_PER_EPOCH}, current time in slot is: {self.time_in_current_slot}.")
        confirmed_head_root = self.__find_confirmed_block_head(conf_info, head_root)
        confirmed_head_slot = int(conf_info["nodes"][confirmed_head_root]["slot"])
        self.logger.debug("---- Done with looking for confirmed head \u2705 ----")
        self.logger.debug(f"Current confirmed slot is: {confirmed_head_slot}")
       
        if confirmed_head_slot > self.confirmed_head_slot:  # progress is made
            self.logger.debug(f"Progress is made: confirmed head slot is now {confirmed_head_slot}")
            if record_conf_time:
                self.conf_times += self.__compute_conf_times(confirmed_head_root, conf_info)
            self.confirmed_head_root = confirmed_head_root
            self.confirmed_head_slot = confirmed_head_slot
        elif confirmed_head_slot == self.confirmed_head_slot:  # no action, progress hasn't been made
            self.logger.debug(f"Progress is not made; confirmed head slot is still {confirmed_head_slot}")
        else:  # record that the confirmation head goes backward (which should not happen in normal cases)
            self.logger.warning(f"Confirmation head goes backwards. Old confirmed head slot: {self.confirmed_head_slot}; new confirmed head slot: {confirmed_head_slot}.")

        # add the time from latest confirmed block to the list
        self.times_from_confirmed_head.append(self.__get_time_from_last_confirmed_block())
        return 
    
    def get_conf_times(self):
        """
        Returns the confirmation times.
        """
        return self.conf_times
    
    def get_num_of_processed_slots(self):
        """
        Returns the number of processed slots.
        """
        return len(self.processed_slots)
    
    def get_empty_or_forked_slots(self):
        """
        Return the empty or forked slot.
        """
        return self.empty_or_forked_slots
    
    def __find_head_root(self, conf_info):
        """
        Return the block head with highest block slot
        """
        nodes = conf_info["nodes"]
        sorted_nodes = sorted(nodes.items(), key=lambda item: item[1]['slot'])
        head_root = sorted_nodes[-1][0]
        return head_root

    # Forked from: https://github.com/ethereum/consensus-specs/blob/687fd5cb3288e9e4708b719d278bf567b70ff2cd/specs/bellatrix/confirmation-rule.md#is_full_validator_set_covered
    def __is_full_validator_set_covered(self, start_slot, end_slot) -> bool:
        """
        Return whether the range from ``start_slot`` to ``end_slot`` (inclusive of both) includes an entire epoch
        """
        start_epoch = spec.compute_epoch_at_slot(start_slot)
        end_epoch = spec.compute_epoch_at_slot(end_slot)
        at_boundary = (start_slot % SLOTS_PER_EPOCH == 0  # the start slot is the first slot at epoch
                       or (end_slot + 1) % SLOTS_PER_EPOCH == 0)  # the end slot is the last slot at epoch

        return (
            end_epoch > start_epoch + 1
            or (at_boundary and start_slot + SLOTS_PER_EPOCH - 1 <= end_slot))  # (Different from the original code spec) include boundary cases

    # Forked from: https://github.com/ethereum/consensus-specs/blob/687fd5cb3288e9e4708b719d278bf567b70ff2cd/specs/bellatrix/confirmation-rule.md#ceil_div
    def __ceil_div(self, numerator: int, denominator: int) -> int:
        """
        Return ``ceil(numerator / denominator)`` using only integer arithmetic
        """
        if numerator % denominator == 0:
            return numerator // denominator
        else:
            return (numerator // denominator) + 1

    # Forked from: https://github.com/ethereum/consensus-specs/blob/687fd5cb3288e9e4708b719d278bf567b70ff2cd/specs/bellatrix/confirmation-rule.md#adjust_committee_weight_estimate_to_ensure_safety  
    def __adjust_committee_weight_estimate_to_ensure_safety(self, estimate: int) -> int:
        """
        Adjusts the ``estimate`` of the weight of a committee for a sequence of slots not covering a full epoch to
        ensure the safety of the confirmation rule with high probability.

        See https://gist.github.com/saltiniroberto/9ee53d29c33878d79417abb2b4468c20 for an explanation of why this is
        required.
        """
        return self.__ceil_div(int(estimate * (1000 + COMMITTEE_WEIGHT_ESTIMATION_ADJUSTMENT_FACTOR)), 1000)

    # Forked from: https://github.com/ethereum/consensus-specs/blob/687fd5cb3288e9e4708b719d278bf567b70ff2cd/specs/bellatrix/confirmation-rule.md#adjust_committee_weight_estimate_to_ensure_safety
    def __get_committee_weight_between_slots(self, conf_info, start_slot, end_slot):
        """
        Returns the total weight of committees between ``start_slot`` and ``end_slot`` (inclusive of both).
        """
        total_active_balance = self.__get_total_active_balance(conf_info) 

        start_epoch = spec.compute_epoch_at_slot(start_slot)
        end_epoch = spec.compute_epoch_at_slot(end_slot)

        if start_slot > end_slot:
            return 0

        # If an entire epoch is covered by the range, return the total active balance
        if self.__is_full_validator_set_covered(start_slot, end_slot):
            return total_active_balance

        if start_epoch == end_epoch:
            return self.__ceil_div((end_slot - start_slot + 1) * int(total_active_balance), SLOTS_PER_EPOCH)
        else:
            # A range that spans an epoch boundary, but does not span any full epoch
            # needs pro-rata calculation

            # First, calculate the number of committees in the end epoch
            num_slots_in_end_epoch = int((end_slot % SLOTS_PER_EPOCH) + 1)
            # Next, calculate the number of slots remaining in the end epoch
            remaining_slots_in_end_epoch = int(SLOTS_PER_EPOCH - num_slots_in_end_epoch)
            # Then, calculate the number of slots in the start epoch
            num_slots_in_start_epoch = int(SLOTS_PER_EPOCH - (start_slot % SLOTS_PER_EPOCH))

            # Simplification steps for start_epoch_weight_mul_by_slots_per_epoch:
            # start_epoch_weight = [num_slots_in_start_epoch  - 
            #                      (num_slots_in_start_epoch * num_slots_in_end_epoch) / SLOTS_PER_EPOCH] 
            #                      * (total_active_balance) / SLOTS_PER_EPOCH
            #                    = [(num_slots_in_start_epoch * remaining_slots_in_end_epoch) / SLOTS_PER_EPOCH]
            #                      * (total_active_balance) / SLOTS_PER_EPOCH
            # ==>
            # start_epoch_weight_mul_by_slots_per_epoch = num_slots_in_start_epoch * remaining_slots_in_end_epoch 
            #                                             * total_active_balance / SLOTS_PER_EPOCH

            end_epoch_weight_mul_by_slots_per_epoch = num_slots_in_end_epoch * int(total_active_balance)
            start_epoch_weight_mul_by_slots_per_epoch = self.__ceil_div(
                num_slots_in_start_epoch * remaining_slots_in_end_epoch * int(total_active_balance),
                SLOTS_PER_EPOCH
            )

            # Each committee from the end epoch only contributes a pro-rated weight
            return self.__adjust_committee_weight_estimate_to_ensure_safety(
                self.__ceil_div(
                    start_epoch_weight_mul_by_slots_per_epoch + end_epoch_weight_mul_by_slots_per_epoch,
                    SLOTS_PER_EPOCH
                )
            )

    # Forked from: https://github.com/ethereum/consensus-specs/blob/687fd5cb3288e9e4708b719d278bf567b70ff2cd/specs/bellatrix/confirmation-rule.md#is_one_confirmed
    def __is_one_lmd_confirmed(self, conf_info, block_root) -> bool:
        """
        Return whether the requested block is one-lmd-confirmed.
        A block is one lmd confirmed if it gets enough lmd support.
        A block is lmd confirmed if it is one-lmd-confirmed and all its ancestors are one-lmd-confirmed.
        """
        nodes = conf_info['nodes']
        node = nodes[block_root]
        support = int(node['weight'])

        parent_root = nodes[block_root]['parent_root']
        parent_slot = int(nodes[parent_root]['slot'])

        # We start to count the maximum_support from parent_slot + 1
        # When parent_slot + 1 != slot_of_block, 
        # we need to count from parent_slot + 1, since there may be a competing branch starting at parent_slot + 1
        # Different from original code spec: we count current_slot when calculating maximum_support, 
        # since we may run the conf rule after the block is proposed in the slot.
        maximum_support = int(
            self.__get_committee_weight_between_slots(conf_info, parent_slot + 1, self.current_slot)
        )
        proposer_score = ((PROPOSER_SCORE_BOOST / 100) 
                          * self.__ceil_div(self.__get_total_active_balance(conf_info), SLOTS_PER_EPOCH))
        support_without_proposer_boost = support - proposer_score  # In the paper, the support does not include proposer boost.

        # Returns whether the one-lmd safety condition is true using only integer arithmetic
        # support / maximum_support >
        # 0.5 * (1 + proposer_score / maximum_support) + CONFIRMATION_BYZANTINE_THRESHOLD / 100
        # note that: CONFIRMATION_BYZANTINE_THRESHOLD = confirmation_byzantine_threshold * 100

        is_one_lmd_confirmed = (
            100 * support_without_proposer_boost >
            50 * maximum_support + 50 * proposer_score + self.confirmation_byzantine_threshold * 100 * maximum_support
        )

        self.logger.debug("---- Checking one-LMD safety ----")
        self.logger.debug(f"Block slot: {node['slot']}, block epoch: {int(node['slot']) // SLOTS_PER_EPOCH}; , " +
                          f"is one lmd confirmed: {is_one_lmd_confirmed}.")

        return is_one_lmd_confirmed

    # Forked from: https://github.com/ethereum/consensus-specs/blob/687fd5cb3288e9e4708b719d278bf567b70ff2cd/specs/bellatrix/confirmation-rule.md#is_lmd_confirmed
    def __is_lmd_confirmed(self, conf_info, block_root):
        """
        Return whether the a block is LMD-confirmed
        """
        # log the slot of the epoch and the current slot.
        nodes = conf_info['nodes']
        node = nodes[block_root]
        self.logger.debug("---- Checking whether a block is LMD-confirmed \U0001F47B ----")
        self.logger.debug(f"Block slot: {node['slot']}, block epoch: {int(node['slot']) // SLOTS_PER_EPOCH}")
        
        if conf_info["finalized_checkpoint"]["root"] == block_root or self.confirmed_head_root == block_root:
            self.logger.debug("The block is finalized or already confirmed, so it is LMD-confirmed \U0001F680")
            return True
        else:
            parent_root = conf_info["nodes"][block_root]["parent_root"]
            return (self.__is_one_lmd_confirmed(conf_info, block_root) 
                    and self.__is_lmd_confirmed(conf_info, parent_root))
        
    def __get_ancestor(self, block_root, slot, conf_info):
        """
        Return the root of the highest ancestor of a block at or below the requested slot
        """
        nodes = conf_info['nodes']
        node = nodes[block_root]
        while int(node['slot']) > slot:
            parent_root = node['parent_root']
            node = nodes[parent_root]
        return node['block_root']

    def __get_checkpoint_block(self, block_root, conf_info, block_epoch):
        """
        Return the root of the highest checkpoint block in the chain of a block
        """
        checkpoint_slot = block_epoch * SLOTS_PER_EPOCH
        checkpoint_root = self.__get_ancestor(block_root, checkpoint_slot, conf_info)
        return checkpoint_root

    def __get_checkpoint_ffg_support(self, block_root, conf_info, block_epoch):
        """
        Return the highest checkpoint block in the block's chain
        and the FFG support for it
        """
        nodes = conf_info['nodes']
        checkpoint_root = self.__get_checkpoint_block(block_root, conf_info, block_epoch)
        node = nodes[checkpoint_root]
        proposer_boost_weight = ((PROPOSER_SCORE_BOOST / 100) 
                          * self.__ceil_div(self.__get_total_active_balance(conf_info), SLOTS_PER_EPOCH))
        ffg_support = int(node['weight']) - proposer_boost_weight  # ffg support is the lmd weight without proposer boost
        return checkpoint_root, ffg_support

    def __get_total_active_balance(self, conf_info):
        """
        Return the total active balance of an epoch
        assuming no validator set changes, and all the validators have same effective balances (32ETH)
        """
        committee_size = int(conf_info['committee_size'])
        total_active_balance = SLOTS_PER_EPOCH * committee_size * VALIDATOR_BALANCE
        return total_active_balance

    def __get_remaining_weight_in_epoch(self, conf_info):
        """
        Return the weight of validators yet to vote in the current epoch
        """
        committee_size = int(conf_info['committee_size'])
        # (Different from the original code spec) we do not count the current slot in remaining slots.
        remaining_slots_in_epoch = SLOTS_PER_EPOCH - (self.current_slot % SLOTS_PER_EPOCH) - 1
        return remaining_slots_in_epoch * committee_size * VALIDATOR_BALANCE

    # Forked from: https://github.com/ethereum/consensus-specs/blob/687fd5cb3288e9e4708b719d278bf567b70ff2cd/specs/bellatrix/confirmation-rule.md#is_ffg_confirmed
    def __is_ffg_confirmed(self, conf_info, block_root) -> bool:
        """
        Return whether the requested block is ffg confirmed
        """
        nodes = conf_info['nodes']
        node = nodes[block_root]
        block_slot = int(node['slot'])
        block_epoch = spec.compute_epoch_at_slot(block_slot)
        current_epoch = spec.compute_epoch_at_slot(self.current_slot)
       
        assert block_epoch == current_epoch   # This function is only applicable to blocks in the current epoch

        self.logger.debug("---- Checking whether a block is FFG-confirmed \u2B50 ----")

        checkpoint_root, checkpoint_ffg_support = self.__get_checkpoint_ffg_support(block_root, conf_info, block_epoch)
        total_validators_weight = self.__get_total_active_balance(conf_info)
        remaining_weight_in_epoch = self.__get_remaining_weight_in_epoch(conf_info)
        max_adversarial_ffg_support = min(
            self.confirmation_byzantine_threshold * (total_validators_weight - remaining_weight_in_epoch), 
            self.confirmation_slashing_threshold * total_validators_weight,  
            checkpoint_ffg_support
        )
        
        is_confirmed = ((2 / 3) * total_validators_weight 
                        <= checkpoint_ffg_support - max_adversarial_ffg_support + 
                        (1 - self.confirmation_byzantine_threshold) * remaining_weight_in_epoch)
        
        # update the highest confirmed checkpoint at the last slot of epoch
        if is_confirmed and (self.current_slot + 1) % SLOTS_PER_EPOCH == 0:
            self.ffg_confirmed_checkpoint = checkpoint_root

        self.logger.debug(f"Block slot: {node['slot']}, block epoch: {block_epoch}. is FFG confirmed: {is_confirmed}")

        return is_confirmed
        
    ## Combine lmd and ffg safety
    # Forked from: https://github.com/ethereum/consensus-specs/blob/687fd5cb3288e9e4708b719d278bf567b70ff2cd/specs/bellatrix/confirmation-rule.md#is_confirmed_no_caching
    def __is_confirmed(self, conf_info, block_root) -> bool:
        """
        Returns whether a block is confirmed.
        """
        current_epoch = spec.compute_epoch_at_slot(self.current_slot)

        block = conf_info["nodes"][block_root]
        block_slot = int(block["slot"])
        block_epoch = spec.compute_epoch_at_slot(block_slot)

        # if conf_info["finalized_checkpoint"]["root"] == block_root:
        if conf_info["finalized_checkpoint"]["root"] == block_root or self.confirmed_head_root == block_root:
            self.logger.debug("The block is finalized or already confirmed, so it is confirmed! \U0001F685")
            return True

        self.logger.debug(">>> checking whether a block is confirmed <<<")
        self.logger.debug(f"Block slot: {block_slot}, block epoch: {block_epoch}, block slot in epoch: {block_slot % SLOTS_PER_EPOCH}")
        second_highest_checkpoint_root = self.__get_checkpoint_block(block_root, conf_info, (current_epoch - 1)) 
         
        if block_epoch == current_epoch:  # for block from current epoch
            is_lmd_confirmed = self.__is_lmd_confirmed(conf_info, block_root)
            is_confirmed = (
                (second_highest_checkpoint_root == conf_info["justified_checkpoint"]["root"]  # check whether the last checkpoint is justified or finalized
                 or second_highest_checkpoint_root == conf_info["finalized_checkpoint"]["root"])  # the last checkpoint may be finalized at the last slot of the epoch
                and is_lmd_confirmed
                and self.__is_ffg_confirmed(conf_info, block_root)
            )
            if is_lmd_confirmed and not is_confirmed:
                self.logger.debug("This block is lmd confirmed but not ffg confirmed.")

            return is_confirmed

        elif block_epoch == current_epoch - 1: # for block from last epoch
            if second_highest_checkpoint_root == conf_info["finalized_checkpoint"]["root"]:  # may happen at the last slot of the epoch
                is_lmd_confirmed = self.__is_lmd_confirmed(conf_info, block_root)
                return is_lmd_confirmed # if the second highest checkpoint is finalized, only need to check the lmd safety
            else:
                third_highest_checkpoint_root = self.__get_checkpoint_block(block_root, conf_info, (current_epoch - 2)) 
                is_lmd_confirmed = self.__is_lmd_confirmed(conf_info, block_root)
                is_confirmed = (
                    second_highest_checkpoint_root == self.ffg_confirmed_checkpoint  # check whether the checkpoint was ffg-confirmed in the last epoch
                    and second_highest_checkpoint_root == conf_info["justified_checkpoint"]["root"] # check whether the second highest checkpoint is justified
                    and is_lmd_confirmed
                    and third_highest_checkpoint_root == conf_info["finalized_checkpoint"]["root"]  # check whether the third highest checkpoint is finalized
                )
                return is_confirmed
            
        else:
            self.logger.debug(" \u26A0 This block is not in current or previous epoch and has not been confirmed yet.")
            return False

    def __find_confirmed_block_head(self, conf_info, block_root):
        """
        Returns the root of the first confirmed ancestor of a block
        """
        if self.__is_confirmed(conf_info, block_root):
            return block_root
        else:
            return self.__find_confirmed_block_head(conf_info, conf_info["nodes"][block_root]["parent_root"])
        
    def __deal_with_empty_or_forked_slot(self, slot):
        """
        Prints out info about the empty or forked slot and records it.
        """
        self.logger.debug(f"Slot {slot} is empty or forked")
        self.empty_or_forked_slots.append(slot)
    
    def __compute_conf_times(self, new_head_root, conf_info):
        """
        Return the list of the confirmation times for the newly confirmed blocks.
        Record error if a confirmed block is reorged.
        """
        old_head_slot = self.confirmed_head_slot
        old_head_root = self.confirmed_head_root
        nodes = conf_info["nodes"]

        conf_times = []
        cur_root = new_head_root
        pre_slot = int(nodes[cur_root]["slot"])
        while cur_root != old_head_root:
            cur_slot = int(nodes[cur_root]["slot"])
            if cur_slot <= old_head_slot:  # The while loop should have ended when reaching the slot of old confirmed head
                self.logger.error("\U0001F6A8 \U0001F6A8 \U0001F6A8 Confirmed block is forked!! \U0001F6A8 \U0001F6A8 \U0001F6A8 ")
                break
            if pre_slot - cur_slot > 1:  # If there is a gap in the confirmed chain
                for slot in range(cur_slot + 1, pre_slot):
                    self.__deal_with_empty_or_forked_slot(slot)
            time = (self.current_slot - cur_slot) * SLOT_LEN + self.time_in_current_slot  # compute confirmation time
            conf_times.append(time)
            self.logger.debug(f"Newly confirmed slot: {cur_slot}, confirmation time: {time}")
            pre_slot = cur_slot  # update pre_slot 
            cur_root = nodes[cur_root]["parent_root"]  # update the cur_root with the root of its partent block
        if pre_slot - old_head_slot > 1:
            for slot in range(old_head_slot + 1, pre_slot):
                    self.__deal_with_empty_or_forked_slot(slot)
        return conf_times
        
    def __get_time_from_last_confirmed_block(self):
        """
        Return the time between the release of the confirmed head block and the current time.
        """
        time = (self.current_slot - self.confirmed_head_slot) * SLOT_LEN + self.time_in_current_slot
        self.logger.debug(f"Time between the release of the confirmed head and the current time: {time}")
        return time

