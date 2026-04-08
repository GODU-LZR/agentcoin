"use client";

type WorkspaceMessageTranslator = (
  key: string,
  values?: Record<string, string | number>,
) => string;

type WalletQueueItem = {
  id?: string;
  status?: string;
  receipt_id?: string;
  workflow_name?: string;
  attempts?: number;
  max_attempts?: number;
  next_attempt_at?: string;
  last_error?: string;
  last_relay_id?: string;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
};

type WalletCollectionItem = Record<string, unknown>;

type WalletWindowProps = {
  tWork: WorkspaceMessageTranslator;
  header: {
    localLedgerBusy: boolean;
    walletLedgerReady: boolean;
    localLedgerError: string;
    onRefreshLedger: () => void;
    onOpenNode: () => void;
  };
  summary: {
    walletReconciliationStatus: string;
    walletLastUpdated: string;
    walletRecommendedActions: string[];
    walletActionBusyKey: string;
    walletActionError: string;
    walletActionNotice: string;
    onRecommendedAction: (action: string) => void;
    getWalletRecommendedActionLabel: (action: string) => string;
  };
  receiptPanel: {
    walletReceiptIssueChallengeId: string;
    walletReceiptWorkflowName: string;
    walletReceiptIssuePayer: string;
    walletReceiptIssueTxHash: string;
    workflowTargetOptions: string[];
    walletReceiptDraft: string;
    walletReceiptResult: unknown;
    onWalletReceiptIssueChallengeIdChange: (value: string) => void;
    onWalletReceiptWorkflowNameChange: (value: string) => void;
    onWalletReceiptIssuePayerChange: (value: string) => void;
    onWalletReceiptIssueTxHashChange: (value: string) => void;
    onWalletReceiptDraftChange: (value: string) => void;
    onIssueReceipt: () => void;
    onIntrospectReceipt: () => void;
  };
  tokenPanel: {
    walletTokenWorkflowName: string;
    walletTokenServiceId: string;
    walletTokenMaxUses: string;
    walletTokenDraft: string;
    walletTokenResult: unknown;
    onWalletTokenWorkflowNameChange: (value: string) => void;
    onWalletTokenServiceIdChange: (value: string) => void;
    onWalletTokenMaxUsesChange: (value: string) => void;
    onWalletTokenDraftChange: (value: string) => void;
    onIssueToken: () => void;
    onIntrospectToken: () => void;
  };
  relayPanel: {
    walletQueueReceiptId: string;
    walletQueueStatusFilter: string;
    walletQueueDelaySeconds: string;
    walletQueueMaxAttempts: string;
    walletRelayTimeoutSeconds: string;
    walletQueueReason: string;
    walletRelayRpcUrl: string;
    walletRelayRawTransactionsDraft: string;
    walletQueueItems: WalletQueueItem[];
    walletLatestRelayDisplay: unknown;
    walletLatestFailedRelayDisplay: unknown;
    walletRelayResult: unknown;
    onWalletQueueReceiptIdChange: (value: string) => void;
    onWalletQueueStatusFilterChange: (value: string) => void;
    onWalletQueueDelaySecondsChange: (value: string) => void;
    onWalletQueueMaxAttemptsChange: (value: string) => void;
    onWalletRelayTimeoutSecondsChange: (value: string) => void;
    onWalletQueueReasonChange: (value: string) => void;
    onWalletRelayRpcUrlChange: (value: string) => void;
    onWalletRelayRawTransactionsDraftChange: (value: string) => void;
    onRelayQueueRefresh: () => void;
    onRelayLoadLatest: () => void;
    onRelayLoadLatestFailed: () => void;
    onRelayLoadReplayHelper: () => void;
    onRelayBuildProof: () => void;
    onRelayBuildRpcPlan: () => void;
    onRelayQueueSubmit: () => void;
    onRelayQueueItemAction: (action: string, item: WalletQueueItem) => void;
  };
  metrics: {
    walletRunningRelays: number;
    walletDeadLetters: number;
    walletTokenTotal: number;
    walletRemainingUses: number;
    walletRequeueCount: number;
  };
  ledger: {
    walletQueueEntries: Array<[string, unknown]>;
    walletUsageItems: WalletCollectionItem[];
    walletTokenItems: WalletCollectionItem[];
    getWalletQueueLabel: (key: string) => string;
  };
  helpers: {
    prettyJson: (value: unknown) => string;
    prettyDisplayJson: (value: unknown) => string;
  };
};

export default function WalletWindow({
  tWork,
  header,
  summary,
  receiptPanel,
  tokenPanel,
  relayPanel,
  metrics,
  ledger,
  helpers,
}: WalletWindowProps) {
  const actionBusy = summary.walletActionBusyKey !== "";

  const getQueueStatusLabel = (status: unknown) => {
    const rawStatus = String(status || "").trim();
    const normalizedStatus = rawStatus.toLowerCase();

    switch (normalizedStatus) {
      case "queued":
      case "pending":
        return tWork("wallet_queue_status_queued");
      case "running":
      case "processing":
      case "leased":
        return tWork("wallet_queue_status_running");
      case "retrying":
        return tWork("wallet_queue_status_retrying");
      case "paused":
        return tWork("wallet_queue_status_paused");
      case "dead-letter":
      case "dead_letter":
        return tWork("wallet_queue_status_dead_letter");
      case "completed":
        return tWork("wallet_queue_status_completed");
      case "failed":
        return tWork("wallet_queue_status_failed");
      case "canceled":
      case "cancelled":
        return tWork("wallet_queue_status_canceled");
      default:
        return rawStatus || tWork("wallet_value_unknown");
    }
  };

  return (
    <div className="h-full">
      <div className="border-2 border-foreground bg-foreground/[0.03] relative flex h-full flex-col p-4 pt-10 shadow-[0_0_28px_rgba(255,255,255,0.05)]">
        <div className="absolute top-0 left-0 bg-foreground text-background px-3 py-1 text-xs font-bold flex justify-between w-full items-center z-10">
          <span>{tWork("window_wallet")}</span>
          <button
            onClick={header.onRefreshLedger}
            disabled={header.localLedgerBusy}
            className="hover:underline opacity-80 hover:opacity-100 disabled:opacity-50"
          >
            {tWork("wallet_refresh")}
          </button>
        </div>

        <div className="mt-2 flex min-h-0 flex-1 flex-col overflow-y-auto custom-scrollbar pr-1">
          {header.walletLedgerReady ? (
            <div className="space-y-4">
              <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3 animate-[fade-in_0.2s_ease-out]">
                <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("wallet_ledger_title")}</div>
                    <div className="mt-2 text-sm leading-6 opacity-85">{tWork("wallet_ledger_live")}</div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-[0.14em] opacity-75">
                    <span className="border border-foreground/15 bg-black/20 px-2 py-1">{tWork("wallet_reconciliation_label")}: {summary.walletReconciliationStatus}</span>
                    {summary.walletLastUpdated && <span className="border border-foreground/15 bg-black/20 px-2 py-1">{tWork("wallet_reconciliation_updated_label")}: {summary.walletLastUpdated}</span>}
                  </div>
                </div>

                {header.localLedgerError && (
                  <div className="border border-foreground bg-foreground text-background px-3 py-2 text-[10px] normal-case tracking-normal font-bold">
                    {header.localLedgerError}
                  </div>
                )}

                {summary.walletRecommendedActions.length > 0 && (
                  <div className="border border-foreground/20 bg-black/20 p-3 space-y-2">
                    <div className="text-[10px] uppercase tracking-[0.16em] opacity-60">{tWork("wallet_actions_label")}</div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {summary.walletRecommendedActions.map((action, index) => (
                        <button
                          key={`${action}-${index}`}
                          className="border border-foreground/10 bg-foreground/5 px-3 py-2 text-left text-xs leading-6 opacity-85 transition-colors hover:border-foreground/30 hover:bg-foreground/10 disabled:opacity-50"
                          onClick={() => summary.onRecommendedAction(action)}
                          disabled={actionBusy}
                        >
                          <div className="font-bold">{summary.getWalletRecommendedActionLabel(action)}</div>
                          <div className="text-[10px] uppercase tracking-[0.14em] opacity-50">{action}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                  <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
                    <div>
                      <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("wallet_receipt_panel_title")}</div>
                      <div className="mt-2 text-xs leading-6 opacity-75">{tWork("wallet_receipt_panel_hint")}</div>
                    </div>
                    <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("wallet_receipt_admin_hint")}</div>
                  </div>

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("workflow_payment_challenge_id_label")}</span>
                      <input
                        type="text"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={receiptPanel.walletReceiptIssueChallengeId}
                        onChange={(e) => receiptPanel.onWalletReceiptIssueChallengeIdChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("wallet_workflow_name_label")}</span>
                      <input
                        type="text"
                        list="wallet-workflow-options"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={receiptPanel.walletReceiptWorkflowName}
                        onChange={(e) => receiptPanel.onWalletReceiptWorkflowNameChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("workflow_payment_payer")}</span>
                      <input
                        type="text"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={receiptPanel.walletReceiptIssuePayer}
                        onChange={(e) => receiptPanel.onWalletReceiptIssuePayerChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("workflow_payment_tx_hash")}</span>
                      <input
                        type="text"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={receiptPanel.walletReceiptIssueTxHash}
                        onChange={(e) => receiptPanel.onWalletReceiptIssueTxHashChange(e.target.value)}
                      />
                    </label>
                  </div>

                  <datalist id="wallet-workflow-options">
                    {receiptPanel.workflowTargetOptions.map((option) => (
                      <option key={option} value={option} />
                    ))}
                  </datalist>

                  <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                    <span>{tWork("wallet_receipt_json_label")}</span>
                    <textarea
                      className="min-h-32 resize-y bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                      value={receiptPanel.walletReceiptDraft}
                      onChange={(e) => receiptPanel.onWalletReceiptDraftChange(e.target.value)}
                      placeholder={tWork("wallet_receipt_json_placeholder")}
                    />
                  </label>

                  <div className="flex flex-wrap gap-2">
                    <button
                      className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50"
                      onClick={receiptPanel.onIssueReceipt}
                      disabled={actionBusy}
                    >
                      {tWork("workflow_receipt_issue")}
                    </button>
                    <button
                      className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50"
                      onClick={receiptPanel.onIntrospectReceipt}
                      disabled={actionBusy}
                    >
                      {tWork("wallet_receipt_introspect")}
                    </button>
                  </div>

                  {receiptPanel.walletReceiptResult != null && (
                    <div className="border border-foreground/10 bg-black/20 p-3">
                      <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("workflow_result_title")}</div>
                      <pre className="mt-2 max-h-52 overflow-y-auto whitespace-pre-wrap break-words text-[10px] normal-case tracking-normal opacity-90 m-0 custom-scrollbar">{helpers.prettyDisplayJson(receiptPanel.walletReceiptResult)}</pre>
                    </div>
                  )}
                </div>

                <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("wallet_token_panel_title")}</div>
                    <div className="mt-2 text-xs leading-6 opacity-75">{tWork("wallet_token_panel_hint")}</div>
                  </div>

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("wallet_workflow_name_label")}</span>
                      <input
                        type="text"
                        list="wallet-workflow-options"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={tokenPanel.walletTokenWorkflowName}
                        onChange={(e) => tokenPanel.onWalletTokenWorkflowNameChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("wallet_token_service_label")}</span>
                      <input
                        type="text"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={tokenPanel.walletTokenServiceId}
                        onChange={(e) => tokenPanel.onWalletTokenServiceIdChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80 sm:col-span-2">
                      <span>{tWork("wallet_token_max_uses_label")}</span>
                      <input
                        type="number"
                        min="1"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={tokenPanel.walletTokenMaxUses}
                        onChange={(e) => tokenPanel.onWalletTokenMaxUsesChange(e.target.value)}
                      />
                    </label>
                  </div>

                  <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                    <span>{tWork("wallet_token_json_label")}</span>
                    <textarea
                      className="min-h-32 resize-y bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                      value={tokenPanel.walletTokenDraft}
                      onChange={(e) => tokenPanel.onWalletTokenDraftChange(e.target.value)}
                      placeholder={tWork("wallet_token_json_placeholder")}
                    />
                  </label>

                  <div className="flex flex-wrap gap-2">
                    <button
                      className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50"
                      onClick={tokenPanel.onIssueToken}
                      disabled={actionBusy}
                    >
                      {tWork("workflow_renter_token_issue")}
                    </button>
                    <button
                      className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50"
                      onClick={tokenPanel.onIntrospectToken}
                      disabled={actionBusy}
                    >
                      {tWork("wallet_token_introspect")}
                    </button>
                  </div>

                  {tokenPanel.walletTokenResult != null && (
                    <div className="border border-foreground/10 bg-black/20 p-3">
                      <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("workflow_result_title")}</div>
                      <pre className="mt-2 max-h-52 overflow-y-auto whitespace-pre-wrap break-words text-[10px] normal-case tracking-normal opacity-90 m-0 custom-scrollbar">{helpers.prettyDisplayJson(tokenPanel.walletTokenResult)}</pre>
                    </div>
                  )}
                </div>
              </div>

              {(summary.walletActionError || summary.walletActionNotice) && (
                <div className={`border px-3 py-2 text-[10px] normal-case tracking-normal font-bold ${summary.walletActionError ? "border-foreground bg-foreground text-background" : "border-foreground/20 bg-foreground/5 opacity-85"}`}>
                  {summary.walletActionError || summary.walletActionNotice}
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)]">
                <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("wallet_relay_panel_title")}</div>
                    <div className="mt-2 text-xs leading-6 opacity-75">{tWork("wallet_relay_panel_hint")}</div>
                  </div>

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("wallet_relay_receipt_id_label")}</span>
                      <input
                        type="text"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={relayPanel.walletQueueReceiptId}
                        onChange={(e) => relayPanel.onWalletQueueReceiptIdChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("wallet_relay_status_filter_label")}</span>
                      <select
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={relayPanel.walletQueueStatusFilter}
                        onChange={(e) => relayPanel.onWalletQueueStatusFilterChange(e.target.value)}
                      >
                        <option value="">{tWork("wallet_relay_status_all")}</option>
                        <option value="queued">queued</option>
                        <option value="paused">paused</option>
                        <option value="running">running</option>
                        <option value="retrying">retrying</option>
                        <option value="completed">completed</option>
                        <option value="dead-letter">dead-letter</option>
                      </select>
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("wallet_relay_delay_seconds_label")}</span>
                      <input
                        type="number"
                        min="0"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={relayPanel.walletQueueDelaySeconds}
                        onChange={(e) => relayPanel.onWalletQueueDelaySecondsChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("wallet_relay_max_attempts_label")}</span>
                      <input
                        type="number"
                        min="1"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={relayPanel.walletQueueMaxAttempts}
                        onChange={(e) => relayPanel.onWalletQueueMaxAttemptsChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("wallet_relay_timeout_seconds_label")}</span>
                      <input
                        type="number"
                        min="0.1"
                        step="0.1"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={relayPanel.walletRelayTimeoutSeconds}
                        onChange={(e) => relayPanel.onWalletRelayTimeoutSecondsChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                      <span>{tWork("wallet_relay_reason_label")}</span>
                      <input
                        type="text"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={relayPanel.walletQueueReason}
                        onChange={(e) => relayPanel.onWalletQueueReasonChange(e.target.value)}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80 sm:col-span-2">
                      <span>{tWork("wallet_relay_rpc_url_label")}</span>
                      <input
                        type="text"
                        className="bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                        value={relayPanel.walletRelayRpcUrl}
                        onChange={(e) => relayPanel.onWalletRelayRpcUrlChange(e.target.value)}
                      />
                    </label>
                  </div>

                  <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.14em] opacity-80">
                    <span>{tWork("wallet_relay_raw_transactions_label")}</span>
                    <textarea
                      className="min-h-32 resize-y bg-foreground/5 border border-foreground/30 p-2 outline-none focus:border-foreground transition-colors normal-case tracking-normal text-xs"
                      value={relayPanel.walletRelayRawTransactionsDraft}
                      onChange={(e) => relayPanel.onWalletRelayRawTransactionsDraftChange(e.target.value)}
                      placeholder={tWork("wallet_relay_raw_transactions_placeholder")}
                    />
                  </label>

                  <div className="flex flex-wrap gap-2">
                    <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={relayPanel.onRelayQueueRefresh} disabled={actionBusy}>{tWork("wallet_relay_fetch_queue")}</button>
                    <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={relayPanel.onRelayLoadLatest} disabled={actionBusy}>{tWork("wallet_relay_fetch_latest")}</button>
                    <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={relayPanel.onRelayLoadLatestFailed} disabled={actionBusy}>{tWork("wallet_relay_fetch_latest_failed")}</button>
                    <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={relayPanel.onRelayLoadReplayHelper} disabled={actionBusy}>{tWork("wallet_relay_fetch_helper")}</button>
                    <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={relayPanel.onRelayBuildProof} disabled={actionBusy}>{tWork("wallet_relay_build_proof")}</button>
                    <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={relayPanel.onRelayBuildRpcPlan} disabled={actionBusy}>{tWork("wallet_relay_build_rpc_plan")}</button>
                    <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={relayPanel.onRelayQueueSubmit} disabled={actionBusy}>{tWork("wallet_relay_queue_submit")}</button>
                  </div>

                  {relayPanel.walletQueueItems.length > 0 ? (
                    <div className="space-y-2">
                      {relayPanel.walletQueueItems.map((item) => {
                        const itemId = String(item?.id || "").trim();
                        const rawStatus = String(item?.status || "").trim();
                        const normalizedStatus = rawStatus.toLowerCase();
                        const statusLabel = getQueueStatusLabel(rawStatus);
                        const autoRequeueDisabled = Boolean(item?.payload?._auto_requeue_disabled);
                        const canPause = normalizedStatus === "queued" || normalizedStatus === "retrying";
                        const canResume = normalizedStatus === "paused";
                        const canCancel = normalizedStatus === "queued" || normalizedStatus === "paused" || normalizedStatus === "retrying";
                        const canRequeue = normalizedStatus === "dead-letter" || normalizedStatus === "dead_letter";
                        const canReplayHelper = canRequeue || Boolean(item?.last_relay_id);

                        return (
                          <div key={itemId || rawStatus || tWork("wallet_value_unknown")} className="border border-foreground/10 bg-black/20 p-3 space-y-3">
                            <div className="flex flex-col gap-2 xl:flex-row xl:items-start xl:justify-between">
                              <div className="min-w-0">
                                <div className="text-sm font-bold break-all">{itemId || tWork("wallet_value_unknown")}</div>
                                <div className="mt-1 text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("wallet_relay_receipt_id_label")}: {String(item?.receipt_id || tWork("wallet_value_unknown"))}</div>
                                <div className="mt-1 text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("wallet_workflow_name_label")}: {String(item?.workflow_name || tWork("wallet_value_unknown"))}</div>
                              </div>
                              <div className="grid grid-cols-2 gap-2 text-[10px] uppercase tracking-[0.14em] opacity-75 xl:min-w-[280px]">
                                <div className="border border-foreground/10 bg-foreground/5 p-2">
                                  <div className="opacity-55">{tWork("local_runtime_status_label")}</div>
                                  <div className="mt-1 normal-case tracking-normal opacity-100">{statusLabel}</div>
                                </div>
                                <div className="border border-foreground/10 bg-foreground/5 p-2">
                                  <div className="opacity-55">{tWork("wallet_relay_attempts_label")}</div>
                                  <div className="mt-1 normal-case tracking-normal opacity-100">{String(item?.attempts || 0)} / {String(item?.max_attempts || 0)}</div>
                                </div>
                              </div>
                            </div>

                            <div className="grid grid-cols-1 gap-2 text-[10px] uppercase tracking-[0.14em] opacity-75 sm:grid-cols-2">
                              <div className="border border-foreground/10 bg-foreground/5 p-2">
                                <div className="opacity-55">{tWork("wallet_relay_next_attempt_label")}</div>
                                <div className="mt-1 normal-case tracking-normal opacity-100 break-words">{String(item?.next_attempt_at || tWork("wallet_value_unknown"))}</div>
                              </div>
                              <div className="border border-foreground/10 bg-foreground/5 p-2">
                                <div className="opacity-55">{tWork("wallet_relay_last_error_label")}</div>
                                <div className="mt-1 normal-case tracking-normal opacity-100 break-words">{String(item?.last_error || tWork("wallet_value_unknown"))}</div>
                              </div>
                            </div>

                            <div className="flex flex-wrap gap-2">
                              {canPause && <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={() => relayPanel.onRelayQueueItemAction("pause", item)} disabled={actionBusy}>{tWork("wallet_queue_pause")}</button>}
                              {canResume && <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={() => relayPanel.onRelayQueueItemAction("resume", item)} disabled={actionBusy}>{tWork("wallet_queue_resume")}</button>}
                              {canRequeue && <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={() => relayPanel.onRelayQueueItemAction("requeue", item)} disabled={actionBusy}>{tWork("wallet_queue_requeue")}</button>}
                              {canCancel && <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={() => relayPanel.onRelayQueueItemAction("cancel", item)} disabled={actionBusy}>{tWork("wallet_queue_cancel")}</button>}
                              <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={() => relayPanel.onRelayQueueItemAction("delete", item)} disabled={actionBusy}>{tWork("wallet_queue_delete")}</button>
                              <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={() => relayPanel.onRelayQueueItemAction(autoRequeueDisabled ? "enable-auto-requeue" : "disable-auto-requeue", item)} disabled={actionBusy}>{autoRequeueDisabled ? tWork("wallet_queue_enable_auto_requeue") : tWork("wallet_queue_disable_auto_requeue")}</button>
                              {canReplayHelper && <button className="border border-foreground/20 px-3 py-2 text-[10px] uppercase tracking-widest hover:bg-foreground/10 disabled:opacity-50" onClick={() => relayPanel.onRelayQueueItemAction("replay-helper", item)} disabled={actionBusy}>{tWork("wallet_queue_replay_helper")}</button>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("wallet_relay_queue_empty")}</div>
                  )}
                </div>

                <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("wallet_relay_operator_result_title")}</div>

                  <div className="space-y-3">
                    <div className="border border-foreground/10 bg-black/20 p-3">
                      <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("wallet_relay_latest_title")}</div>
                      {relayPanel.walletLatestRelayDisplay != null ? (
                        <pre className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-words text-[10px] normal-case tracking-normal opacity-90 m-0 custom-scrollbar">{helpers.prettyDisplayJson(relayPanel.walletLatestRelayDisplay)}</pre>
                      ) : (
                        <div className="mt-2 text-xs opacity-70">{tWork("wallet_relay_result_empty")}</div>
                      )}
                    </div>

                    <div className="border border-foreground/10 bg-black/20 p-3">
                      <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("wallet_relay_latest_failed_title")}</div>
                      {relayPanel.walletLatestFailedRelayDisplay != null ? (
                        <pre className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-words text-[10px] normal-case tracking-normal opacity-90 m-0 custom-scrollbar">{helpers.prettyDisplayJson(relayPanel.walletLatestFailedRelayDisplay)}</pre>
                      ) : (
                        <div className="mt-2 text-xs opacity-70">{tWork("wallet_relay_result_empty")}</div>
                      )}
                    </div>

                    <div className="border border-foreground/10 bg-black/20 p-3">
                      <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("wallet_relay_operator_result_title")}</div>
                      {relayPanel.walletRelayResult != null ? (
                        <pre className="mt-2 max-h-[28rem] overflow-y-auto whitespace-pre-wrap break-words text-[10px] normal-case tracking-normal opacity-90 m-0 custom-scrollbar">{helpers.prettyDisplayJson(relayPanel.walletRelayResult)}</pre>
                      ) : (
                        <div className="mt-2 text-xs opacity-70">{tWork("wallet_relay_result_empty")}</div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                  <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("wallet_metric_relays")}</div>
                  <div className="mt-2 text-2xl font-bold">{metrics.walletRunningRelays}</div>
                </div>
                <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                  <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("wallet_metric_dead_letter")}</div>
                  <div className="mt-2 text-2xl font-bold">{metrics.walletDeadLetters}</div>
                </div>
                <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                  <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("wallet_metric_tokens")}</div>
                  <div className="mt-2 text-2xl font-bold">{metrics.walletTokenTotal}</div>
                </div>
                <div className="border border-foreground/20 bg-foreground/5 p-3 rounded-sm">
                  <div className="text-[10px] uppercase tracking-[0.16em] opacity-55">{tWork("wallet_metric_remaining_uses")}</div>
                  <div className="mt-2 text-2xl font-bold">{metrics.walletRemainingUses}</div>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
                <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("wallet_queue_label")}</div>
                  {ledger.walletQueueEntries.length > 0 ? (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {ledger.walletQueueEntries.map(([key, value]) => (
                        <div key={key} className="border border-foreground/10 bg-black/20 p-3">
                          <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{ledger.getWalletQueueLabel(key)}</div>
                          <div className="mt-2 text-sm font-bold break-words">{String(value)}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("wallet_empty_queue")}</div>
                  )}
                </div>

                <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                  <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em] opacity-70">
                    <span>{tWork("wallet_usage_label")}</span>
                    <span>{tWork("wallet_usage_remaining_label")}: {metrics.walletRemainingUses}</span>
                  </div>
                  {ledger.walletUsageItems.length > 0 ? (
                    <div className="space-y-2">
                      {ledger.walletUsageItems.slice(0, 5).map((item, index) => (
                        <div key={String(item?.service_id || item?.service_name || item?.id || index)} className="border border-foreground/10 bg-black/20 p-3">
                          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                            <div className="min-w-0">
                              <div className="text-sm font-bold truncate">{String(item?.service_id || item?.service_name || item?.service || item?.id || tWork("wallet_value_unknown"))}</div>
                              <div className="mt-1 text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("wallet_usage_count_label")}: {String(item?.usage_count || item?.count || item?.completed || item?.calls || 0)}</div>
                            </div>
                            <div className="text-[10px] uppercase tracking-[0.14em] opacity-70 sm:text-right">
                              <div>{tWork("wallet_usage_remaining_label")}</div>
                              <div className="mt-1 text-sm font-bold normal-case tracking-normal opacity-100">{String(item?.remaining_uses || item?.remaining || item?.available_uses || tWork("wallet_value_unknown"))}</div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : metrics.walletTokenTotal > 0 || metrics.walletRemainingUses > 0 ? (
                    <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("wallet_usage_aggregate_only")}</div>
                  ) : (
                    <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("wallet_empty_usage")}</div>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
                <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] opacity-70">{tWork("wallet_reconciliation_label")}</div>
                  <div className="border border-foreground/10 bg-black/20 p-3 space-y-2">
                    <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("local_runtime_status_label")}</div>
                    <div className="text-sm font-bold">{summary.walletReconciliationStatus}</div>
                    <div className="text-[10px] uppercase tracking-[0.14em] opacity-55">{tWork("wallet_actions_label")}</div>
                    <div className="text-xs leading-6 opacity-80">
                      {summary.walletRecommendedActions.length > 0 ? summary.walletRecommendedActions.join(" / ") : tWork("wallet_reconciliation_none")}
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[10px] uppercase tracking-[0.14em] opacity-75">
                    <div className="border border-foreground/10 bg-black/20 p-3">
                      <div className="opacity-55">{tWork("wallet_queue_requeue_label")}</div>
                      <div className="mt-2 text-lg font-bold opacity-100">{metrics.walletRequeueCount}</div>
                    </div>
                    <div className="border border-foreground/10 bg-black/20 p-3">
                      <div className="opacity-55">{tWork("wallet_queue_dead_letter_label")}</div>
                      <div className="mt-2 text-lg font-bold opacity-100">{metrics.walletDeadLetters}</div>
                    </div>
                  </div>
                </div>

                <div className="border border-foreground/20 bg-foreground/5 p-4 rounded-sm space-y-3">
                  <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em] opacity-70">
                    <span>{tWork("wallet_renter_tokens_label")}</span>
                    <span>{metrics.walletTokenTotal}</span>
                  </div>
                  {ledger.walletTokenItems.length > 0 ? (
                    <div className="space-y-2">
                      {ledger.walletTokenItems.slice(0, 5).map((item, index) => (
                        <div key={String(item?.token_id || item?.id || item?.subject || index)} className="border border-foreground/10 bg-black/20 p-3">
                          <div className="text-sm font-bold break-all">{String(item?.token_id || item?.id || item?.token || item?.subject || `${tWork("wallet_renter_tokens_label")} ${index + 1}`)}</div>
                          <div className="mt-2 grid grid-cols-1 gap-2 text-[10px] uppercase tracking-[0.14em] opacity-75 sm:grid-cols-3">
                            <div>
                              <div className="opacity-55">{tWork("wallet_token_service_label")}</div>
                              <div className="mt-1 normal-case tracking-normal opacity-100 break-words">{String(item?.service_id || item?.service || item?.service_name || tWork("wallet_value_unknown"))}</div>
                            </div>
                            <div>
                              <div className="opacity-55">{tWork("wallet_token_remaining_label")}</div>
                              <div className="mt-1 normal-case tracking-normal opacity-100">{String(item?.remaining_uses || item?.remaining || item?.available_uses || tWork("wallet_value_unknown"))}</div>
                            </div>
                            <div>
                              <div className="opacity-55">{tWork("wallet_token_subject_label")}</div>
                              <div className="mt-1 normal-case tracking-normal opacity-100 break-words">{String(item?.subject || item?.principal || item?.owner || tWork("wallet_value_unknown"))}</div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : metrics.walletTokenTotal > 0 ? (
                    <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("wallet_tokens_aggregate_only")}</div>
                  ) : (
                    <div className="border border-foreground/10 bg-black/20 p-3 text-xs opacity-75">{tWork("wallet_empty_tokens")}</div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center">
              <div className="max-w-xl border-2 border-foreground bg-foreground/[0.03] px-6 py-8 text-center shadow-[0_0_30px_rgba(255,255,255,0.08)]">
                <div className="text-[10px] uppercase tracking-[0.22em] opacity-60">{tWork("window_wallet")}</div>
                <div className="mt-4 text-lg font-bold tracking-[0.08em]">{tWork("wallet_empty_title")}</div>
                <p className="mt-4 text-sm leading-7 opacity-80">{tWork("wallet_empty_body")}</p>

                {header.localLedgerError && (
                  <div className="mt-6 border border-foreground bg-foreground text-background px-4 py-3 text-left text-xs leading-6 font-bold normal-case tracking-normal">
                    {header.localLedgerError}
                  </div>
                )}

                <div className="mt-6 flex flex-wrap justify-center gap-3">
                  <button
                    onClick={header.onOpenNode}
                    className="border border-foreground/20 px-4 py-2 text-[10px] uppercase tracking-[0.18em] hover:bg-foreground hover:text-background transition-none"
                  >
                    {tWork("wallet_open_node")}
                  </button>
                  <button
                    onClick={header.onRefreshLedger}
                    disabled={header.localLedgerBusy}
                    className="bg-foreground text-background px-4 py-2 text-[10px] uppercase tracking-[0.18em] hover:opacity-80 disabled:opacity-50"
                  >
                    {tWork("wallet_refresh")}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}