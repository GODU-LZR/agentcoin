// SPDX-License-Identifier: GPL-3.0-or-later
pragma solidity ^0.8.24;

import {OwnableLite} from "./common/OwnableLite.sol";
import {IAgentDIDRegistry} from "./interfaces/IAgentDIDRegistry.sol";

contract AgentDIDRegistry is OwnableLite, IAgentDIDRegistry {
    struct AgentIdentity {
        address controller;
        string metadataURI;
        string serviceEndpoint;
        bytes32 capabilitiesHash;
        uint256 reputation;
        uint256 completedJobs;
        uint256 failedJobs;
        bool active;
        uint64 createdAt;
        uint64 updatedAt;
    }

    mapping(bytes32 => AgentIdentity) private identities;
    mapping(address => bytes32[]) private controllerDids;
    mapping(address => bool) public reputationUpdaters;

    event DIDCreated(bytes32 indexed did, address indexed controller, string metadataURI, string serviceEndpoint);
    event DIDUpdated(bytes32 indexed did);
    event DIDActivationChanged(bytes32 indexed did, bool active);
    event ReputationUpdaterSet(address indexed updater, bool allowed);
    event ReputationApplied(bytes32 indexed did, int256 delta, uint256 completedDelta, uint256 failedDelta, uint256 newReputation);

    modifier onlyController(bytes32 did) {
        require(identities[did].controller == msg.sender, "not controller");
        _;
    }

    modifier onlyReputationUpdater() {
        require(reputationUpdaters[msg.sender], "not reputation updater");
        _;
    }

    function createDID(
        bytes32 did,
        string calldata metadataURI,
        string calldata serviceEndpoint,
        bytes32 capabilitiesHash
    ) external {
        require(did != bytes32(0), "zero did");
        require(identities[did].controller == address(0), "did exists");

        identities[did] = AgentIdentity({
            controller: msg.sender,
            metadataURI: metadataURI,
            serviceEndpoint: serviceEndpoint,
            capabilitiesHash: capabilitiesHash,
            reputation: 100,
            completedJobs: 0,
            failedJobs: 0,
            active: true,
            createdAt: uint64(block.timestamp),
            updatedAt: uint64(block.timestamp)
        });
        controllerDids[msg.sender].push(did);

        emit DIDCreated(did, msg.sender, metadataURI, serviceEndpoint);
    }

    function updateMetadata(bytes32 did, string calldata metadataURI) external onlyController(did) {
        identities[did].metadataURI = metadataURI;
        identities[did].updatedAt = uint64(block.timestamp);
        emit DIDUpdated(did);
    }

    function updateServiceEndpoint(bytes32 did, string calldata serviceEndpoint) external onlyController(did) {
        identities[did].serviceEndpoint = serviceEndpoint;
        identities[did].updatedAt = uint64(block.timestamp);
        emit DIDUpdated(did);
    }

    function updateCapabilitiesHash(bytes32 did, bytes32 capabilitiesHash) external onlyController(did) {
        identities[did].capabilitiesHash = capabilitiesHash;
        identities[did].updatedAt = uint64(block.timestamp);
        emit DIDUpdated(did);
    }

    function setActive(bytes32 did, bool active) external onlyController(did) {
        identities[did].active = active;
        identities[did].updatedAt = uint64(block.timestamp);
        emit DIDActivationChanged(did, active);
    }

    function setReputationUpdater(address updater, bool allowed) external onlyOwner {
        reputationUpdaters[updater] = allowed;
        emit ReputationUpdaterSet(updater, allowed);
    }

    function applyReputationDelta(
        bytes32 did,
        int256 delta,
        uint256 completedDelta,
        uint256 failedDelta
    ) external onlyReputationUpdater {
        AgentIdentity storage identity = identities[did];
        require(identity.controller != address(0), "unknown did");

        uint256 reputation = identity.reputation;
        if (delta < 0) {
            uint256 decrease = uint256(-delta);
            identity.reputation = decrease >= reputation ? 0 : reputation - decrease;
        } else {
            identity.reputation = reputation + uint256(delta);
        }

        identity.completedJobs += completedDelta;
        identity.failedJobs += failedDelta;
        identity.updatedAt = uint64(block.timestamp);

        emit ReputationApplied(did, delta, completedDelta, failedDelta, identity.reputation);
    }

    function resolve(bytes32 did) external view returns (AgentIdentity memory) {
        return identities[did];
    }

    function didsOf(address controller) external view returns (bytes32[] memory) {
        return controllerDids[controller];
    }

    function exists(bytes32 did) external view returns (bool) {
        return identities[did].controller != address(0);
    }

    function controllerOf(bytes32 did) external view returns (address) {
        return identities[did].controller;
    }

    function reputationOf(bytes32 did) external view returns (uint256) {
        return identities[did].reputation;
    }
}
