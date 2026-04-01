// SPDX-License-Identifier: GPL-3.0-or-later
pragma solidity ^0.8.24;

interface IStakingPool {
    function availableStake(address staker) external view returns (uint256);
    function lockStake(address staker, uint256 amount) external;
    function unlockStake(address staker, uint256 amount) external;
    function slashStake(address staker, uint256 amount, address payable recipient, string calldata reason) external returns (uint256);
}
