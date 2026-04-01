// SPDX-License-Identifier: GPL-3.0-or-later
pragma solidity ^0.8.24;

import {OwnableLite} from "./common/OwnableLite.sol";
import {IAgentDIDRegistry} from "./interfaces/IAgentDIDRegistry.sol";
import {IStakingPool} from "./interfaces/IStakingPool.sol";

contract BountyEscrow is OwnableLite {
    enum JobStatus {
        Funded,
        Assigned,
        Submitted,
        Challenged,
        Completed,
        Rejected,
        Refunded,
        Slashed
    }

    struct Job {
        uint256 id;
        address client;
        address evaluator;
        address worker;
        bytes32 workerDid;
        uint256 rewardAmount;
        uint256 stakeRequired;
        uint256 minReputation;
        uint256 score;
        uint64 deadline;
        uint64 challengeDeadline;
        uint64 createdAt;
        uint64 updatedAt;
        JobStatus status;
        bytes32 specHash;
        bytes32 submissionHash;
        string resultURI;
        string receiptURI;
    }

    IAgentDIDRegistry public immutable registry;
    IStakingPool public immutable stakingPool;

    uint256 public nextJobId = 1;
    uint64 public challengeWindow = 1 days;

    mapping(uint256 => Job) public jobs;

    event ChallengeWindowUpdated(uint64 challengeWindow);
    event JobCreated(uint256 indexed jobId, address indexed client, uint256 rewardAmount, uint256 stakeRequired, bytes32 specHash);
    event JobAccepted(uint256 indexed jobId, address indexed worker, bytes32 indexed workerDid);
    event WorkSubmitted(uint256 indexed jobId, bytes32 indexed submissionHash, string resultURI);
    event JobChallenged(uint256 indexed jobId, address indexed challenger, bytes32 evidenceHash);
    event JobCompleted(uint256 indexed jobId, address indexed worker, uint256 score, string receiptURI);
    event JobRejected(uint256 indexed jobId, string receiptURI);
    event JobRefunded(uint256 indexed jobId);
    event JobSlashed(uint256 indexed jobId, uint256 slashAmount, address indexed recipient, string reason, string receiptURI);

    constructor(address registryAddress, address stakingPoolAddress) {
        require(registryAddress != address(0), "zero registry");
        require(stakingPoolAddress != address(0), "zero staking pool");
        registry = IAgentDIDRegistry(registryAddress);
        stakingPool = IStakingPool(stakingPoolAddress);
    }

    function setChallengeWindow(uint64 newChallengeWindow) external onlyOwner {
        require(newChallengeWindow > 0, "zero window");
        challengeWindow = newChallengeWindow;
        emit ChallengeWindowUpdated(newChallengeWindow);
    }

    function createJob(
        address evaluator,
        uint256 stakeRequired,
        uint256 minReputation,
        uint64 deadline,
        bytes32 specHash
    ) external payable returns (uint256 jobId) {
        require(msg.value > 0, "no reward");
        require(deadline > block.timestamp, "invalid deadline");

        jobId = nextJobId++;
        jobs[jobId] = Job({
            id: jobId,
            client: msg.sender,
            evaluator: evaluator,
            worker: address(0),
            workerDid: bytes32(0),
            rewardAmount: msg.value,
            stakeRequired: stakeRequired,
            minReputation: minReputation,
            score: 0,
            deadline: deadline,
            challengeDeadline: 0,
            createdAt: uint64(block.timestamp),
            updatedAt: uint64(block.timestamp),
            status: JobStatus.Funded,
            specHash: specHash,
            submissionHash: bytes32(0),
            resultURI: "",
            receiptURI: ""
        });

        emit JobCreated(jobId, msg.sender, msg.value, stakeRequired, specHash);
    }

    function acceptJob(uint256 jobId, bytes32 workerDid) external {
        Job storage job = jobs[jobId];
        require(job.status == JobStatus.Funded, "job not funded");
        require(block.timestamp <= job.deadline, "job expired");
        require(registry.exists(workerDid), "unknown did");
        require(registry.controllerOf(workerDid) == msg.sender, "did/controller mismatch");
        require(registry.reputationOf(workerDid) >= job.minReputation, "insufficient reputation");
        require(stakingPool.availableStake(msg.sender) >= job.stakeRequired, "insufficient stake");

        if (job.stakeRequired > 0) {
            stakingPool.lockStake(msg.sender, job.stakeRequired);
        }

        job.worker = msg.sender;
        job.workerDid = workerDid;
        job.status = JobStatus.Assigned;
        job.updatedAt = uint64(block.timestamp);

        emit JobAccepted(jobId, msg.sender, workerDid);
    }

    function submitWork(uint256 jobId, bytes32 submissionHash, string calldata resultURI) external {
        Job storage job = jobs[jobId];
        require(job.status == JobStatus.Assigned, "job not assigned");
        require(job.worker == msg.sender, "not worker");
        require(block.timestamp <= job.deadline, "submission expired");
        require(submissionHash != bytes32(0), "zero submission hash");

        job.submissionHash = submissionHash;
        job.resultURI = resultURI;
        job.challengeDeadline = uint64(block.timestamp + challengeWindow);
        job.status = JobStatus.Submitted;
        job.updatedAt = uint64(block.timestamp);

        emit WorkSubmitted(jobId, submissionHash, resultURI);
    }

    function challengeJob(uint256 jobId, bytes32 evidenceHash) external {
        Job storage job = jobs[jobId];
        require(job.status == JobStatus.Submitted, "job not submitted");
        require(block.timestamp <= job.challengeDeadline, "challenge expired");
        require(evidenceHash != bytes32(0), "zero evidence");

        job.status = JobStatus.Challenged;
        job.updatedAt = uint64(block.timestamp);

        emit JobChallenged(jobId, msg.sender, evidenceHash);
    }

    function completeJob(uint256 jobId, uint256 score, string calldata receiptURI) external {
        Job storage job = jobs[jobId];
        require(_isReviewer(job), "not reviewer");
        require(job.status == JobStatus.Submitted || job.status == JobStatus.Challenged, "job not reviewable");
        require(job.worker != address(0), "missing worker");

        job.score = score;
        job.receiptURI = receiptURI;
        job.status = JobStatus.Completed;
        job.updatedAt = uint64(block.timestamp);

        if (job.stakeRequired > 0) {
            stakingPool.unlockStake(job.worker, job.stakeRequired);
        }
        registry.applyReputationDelta(job.workerDid, int256(10), 1, 0);
        _safeTransferNative(payable(job.worker), job.rewardAmount);

        emit JobCompleted(jobId, job.worker, score, receiptURI);
    }

    function rejectJob(uint256 jobId, string calldata receiptURI) external {
        Job storage job = jobs[jobId];
        require(_isReviewer(job), "not reviewer");
        require(job.status == JobStatus.Submitted || job.status == JobStatus.Challenged, "job not reviewable");

        job.receiptURI = receiptURI;
        job.status = JobStatus.Rejected;
        job.updatedAt = uint64(block.timestamp);

        if (job.worker != address(0)) {
            if (job.stakeRequired > 0) {
                stakingPool.unlockStake(job.worker, job.stakeRequired);
            }
            registry.applyReputationDelta(job.workerDid, -int256(5), 0, 1);
        }
        _safeTransferNative(payable(job.client), job.rewardAmount);

        emit JobRejected(jobId, receiptURI);
    }

    function refundExpiredJob(uint256 jobId) external {
        Job storage job = jobs[jobId];
        require(
            job.status == JobStatus.Funded || job.status == JobStatus.Assigned,
            "job not refundable"
        );
        require(block.timestamp > job.deadline, "deadline not reached");

        job.status = JobStatus.Refunded;
        job.updatedAt = uint64(block.timestamp);

        if (job.worker != address(0) && job.stakeRequired > 0) {
            stakingPool.unlockStake(job.worker, job.stakeRequired);
        }
        _safeTransferNative(payable(job.client), job.rewardAmount);

        emit JobRefunded(jobId);
    }

    function slashJob(
        uint256 jobId,
        uint256 slashAmount,
        address payable recipient,
        string calldata reason,
        string calldata receiptURI
    ) external {
        Job storage job = jobs[jobId];
        require(_isReviewer(job), "not reviewer");
        require(job.status == JobStatus.Submitted || job.status == JobStatus.Challenged, "job not slashable");
        require(job.worker != address(0), "missing worker");

        address payable slashRecipient = recipient == address(0) ? payable(job.client) : recipient;
        uint256 actualSlashed = 0;
        if (job.stakeRequired > 0) {
            actualSlashed = stakingPool.slashStake(job.worker, slashAmount, slashRecipient, reason);
        }

        job.receiptURI = receiptURI;
        job.status = JobStatus.Slashed;
        job.updatedAt = uint64(block.timestamp);

        registry.applyReputationDelta(job.workerDid, -int256(20), 0, 1);
        _safeTransferNative(payable(job.client), job.rewardAmount);

        emit JobSlashed(jobId, actualSlashed, slashRecipient, reason, receiptURI);
    }

    function _isReviewer(Job storage job) internal view returns (bool) {
        address reviewer = job.evaluator == address(0) ? job.client : job.evaluator;
        return msg.sender == reviewer || msg.sender == owner;
    }

    function _safeTransferNative(address payable recipient, uint256 amount) internal {
        (bool ok, ) = recipient.call{value: amount}("");
        require(ok, "native transfer failed");
    }
}
