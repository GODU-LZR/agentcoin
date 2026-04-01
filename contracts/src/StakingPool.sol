// SPDX-License-Identifier: GPL-3.0-or-later
pragma solidity ^0.8.24;

import {OwnableLite} from "./common/OwnableLite.sol";
import {IStakingPool} from "./interfaces/IStakingPool.sol";

contract StakingPool is OwnableLite, IStakingPool {
    struct StakeInfo {
        uint256 amount;
        uint256 lockedAmount;
        uint256 totalSlashed;
        uint64 updatedAt;
    }

    mapping(address => StakeInfo) public stakes;
    mapping(address => bool) public authorizedEscrows;

    event EscrowAuthorizationSet(address indexed escrow, bool allowed);
    event Staked(address indexed staker, uint256 amount, uint256 totalAmount);
    event Unstaked(address indexed staker, uint256 amount, address indexed recipient);
    event StakeLocked(address indexed staker, uint256 amount, address indexed escrow);
    event StakeUnlocked(address indexed staker, uint256 amount, address indexed escrow);
    event StakeSlashed(address indexed staker, uint256 amount, address indexed recipient, string reason);

    modifier onlyAuthorizedEscrow() {
        require(authorizedEscrows[msg.sender], "not escrow");
        _;
    }

    function setAuthorizedEscrow(address escrow, bool allowed) external onlyOwner {
        authorizedEscrows[escrow] = allowed;
        emit EscrowAuthorizationSet(escrow, allowed);
    }

    function stake() external payable {
        _stakeFor(msg.sender);
    }

    function stakeFor(address staker) external payable {
        require(staker != address(0), "zero staker");
        _stakeFor(staker);
    }

    function _stakeFor(address staker) internal {
        require(msg.value > 0, "no value");
        StakeInfo storage info = stakes[staker];
        info.amount += msg.value;
        info.updatedAt = uint64(block.timestamp);
        emit Staked(staker, msg.value, info.amount);
    }

    function requestUnstake(uint256 amount, address payable recipient) external {
        require(recipient != address(0), "zero recipient");
        StakeInfo storage info = stakes[msg.sender];
        require(amount > 0, "zero amount");
        require(availableStake(msg.sender) >= amount, "insufficient available stake");

        info.amount -= amount;
        info.updatedAt = uint64(block.timestamp);
        _safeTransferNative(recipient, amount);

        emit Unstaked(msg.sender, amount, recipient);
    }

    function availableStake(address staker) public view returns (uint256) {
        StakeInfo storage info = stakes[staker];
        return info.amount - info.lockedAmount;
    }

    function lockStake(address staker, uint256 amount) external onlyAuthorizedEscrow {
        require(amount > 0, "zero amount");
        StakeInfo storage info = stakes[staker];
        require(availableStake(staker) >= amount, "insufficient stake");

        info.lockedAmount += amount;
        info.updatedAt = uint64(block.timestamp);
        emit StakeLocked(staker, amount, msg.sender);
    }

    function unlockStake(address staker, uint256 amount) external onlyAuthorizedEscrow {
        require(amount > 0, "zero amount");
        StakeInfo storage info = stakes[staker];
        require(info.lockedAmount >= amount, "insufficient locked stake");

        info.lockedAmount -= amount;
        info.updatedAt = uint64(block.timestamp);
        emit StakeUnlocked(staker, amount, msg.sender);
    }

    function slashStake(
        address staker,
        uint256 amount,
        address payable recipient,
        string calldata reason
    ) external onlyAuthorizedEscrow returns (uint256) {
        require(recipient != address(0), "zero recipient");
        StakeInfo storage info = stakes[staker];
        require(amount > 0, "zero amount");
        require(info.lockedAmount > 0, "no locked stake");

        uint256 actual = amount > info.lockedAmount ? info.lockedAmount : amount;
        info.lockedAmount -= actual;
        info.amount -= actual;
        info.totalSlashed += actual;
        info.updatedAt = uint64(block.timestamp);

        _safeTransferNative(recipient, actual);
        emit StakeSlashed(staker, actual, recipient, reason);
        return actual;
    }

    function _safeTransferNative(address payable recipient, uint256 amount) internal {
        (bool ok, ) = recipient.call{value: amount}("");
        require(ok, "native transfer failed");
    }
}
