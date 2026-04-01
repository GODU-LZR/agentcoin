// SPDX-License-Identifier: GPL-3.0-or-later
pragma solidity ^0.8.24;

interface IAgentDIDRegistry {
    function exists(bytes32 did) external view returns (bool);
    function controllerOf(bytes32 did) external view returns (address);
    function reputationOf(bytes32 did) external view returns (uint256);
    function applyReputationDelta(bytes32 did, int256 delta, uint256 completedDelta, uint256 failedDelta) external;
}
