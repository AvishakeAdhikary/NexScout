// Plain-language application states (backend: domain/state_machines.py ApplicationStatus).
export const APPLICATION_STATUS: Record<string, string> = {
  discovered: "Discovered",
  shortlisted: "Shortlisted",
  researching: "Researching",
  preparing: "Preparing",
  awaiting_review: "Waiting for your approval",
  approved: "Approved",
  submitting: "Submitting…",
  submitted: "Submitted",
  submission_uncertain: "Submission not confirmed",
  tracking: "Waiting for a reply",
  completed: "Completed",
  paused: "Paused",
  needs_user_action: "Needs you",
  failed: "Failed",
  cancelled: "Cancelled",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

// Wording for the manual status buttons.
export const STATUS_ACTION: Record<string, string> = {
  preparing: "Back to preparing",
  submitted: "I submitted it myself",
  tracking: "Waiting for a reply",
  completed: "Mark completed (offer or accepted)",
  rejected: "Mark rejected",
  withdrawn: "Withdraw",
  cancelled: "Cancel application",
  paused: "Pause",
};

export function statusLabel(status: string): string {
  return APPLICATION_STATUS[status] ?? status;
}
