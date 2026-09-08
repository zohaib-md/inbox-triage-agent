/**
 * Inbox Triage Agent - Google Apps Script Integration
 * Target: Google Cloud Run Serverless ADK Agent
 */

const BASE_URL = "https://inbox-triage-agent-723976801056.us-central1.run.app";
const BATCH_SIZE = 5;

const LABELS = {
  PROCESSED: "Triage/Processed",
  URGENT: "Triage/Urgent",
  NEEDS_REPLY: "Triage/Needs-Reply",
  FYI: "Triage/FYI",
  SPAM: "Triage/Spam",
  NEEDS_REVIEW: "Triage/Needs-Review"
};

function triageInbox() {
  ensureLabelsExist();

  // Search inbox for unprocessed emails
  const searchQuery = `in:inbox -label:${LABELS.PROCESSED} -label:trash -label:spam`;
  const threads = GmailApp.search(searchQuery, 0, BATCH_SIZE);

  Logger.log(`Found ${threads.length} thread(s) to triage.`);

  for (const thread of threads) {
    try {
      processThread(thread);
    } catch (err) {
      Logger.log(`Error processing thread: ${err.message}`);
    }
  }
}

function processThread(thread) {
  const messages = thread.getMessages();
  const latestMessage = messages[messages.length - 1];

  const subject = latestMessage.getSubject() || "No Subject";
  const sender = latestMessage.getFrom() || "Unknown";
  const body = latestMessage.getPlainBody().substring(0, 3000);

  Logger.log(`Triaging: "${subject}" from ${sender}`);

  const triageResult = callCloudRunAgent(subject, sender, body);

  if (!triageResult) {
    Logger.log("Could not obtain valid triage result. Tagging as Needs-Review.");
    applyLabel(thread, LABELS.NEEDS_REVIEW);
    applyLabel(thread, LABELS.PROCESSED);
    return;
  }

  const category = triageResult.classification || triageResult.category || "needs_human_review";
  const draftReply = triageResult.draft_reply;
  const confidence = triageResult.confidence || 0.0;

  Logger.log(`Decision: ${category} (conf: ${confidence})`);

  // 1. Apply category label
  switch (category) {
    case "urgent":
      applyLabel(thread, LABELS.URGENT);
      thread.markImportant();
      break;
    case "needs_reply":
      applyLabel(thread, LABELS.NEEDS_REPLY);
      break;
    case "fyi":
      applyLabel(thread, LABELS.FYI);
      break;
    case "spam":
      applyLabel(thread, LABELS.SPAM);
      thread.moveToSpam();
      break;
    case "needs_human_review":
    default:
      applyLabel(thread, LABELS.NEEDS_REVIEW);
      break;
  }

  // 2. If a draft reply was generated, attach draft to thread
  if (draftReply && category !== "spam" && category !== "fyi" && category !== "needs_human_review") {
    thread.createDraftReply(draftReply);
    Logger.log(`Created draft reply for "${subject}"`);
  }

  // 3. Mark processed so it never runs twice
  applyLabel(thread, LABELS.PROCESSED);
}

function callCloudRunAgent(subject, sender, body) {
  const userId = "gmail_user";
  const sessionId = "session_" + Utilities.getUuid().substring(0, 8);

  // Step 1: Create ADK Session
  const sessionUrl = `${BASE_URL}/apps/app/users/${userId}/sessions`;
  const sessionOptions = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ session_id: sessionId }),
    muteHttpExceptions: true
  };

  try {
    const sessionResp = UrlFetchApp.fetch(sessionUrl, sessionOptions);
    if (sessionResp.getResponseCode() !== 200) {
      Logger.log(`Session creation failed (${sessionResp.getResponseCode()}): ${sessionResp.getContentText()}`);
      return null;
    }
  } catch (e) {
    Logger.log(`Session error: ${e.message}`);
    return null;
  }

  // Step 2: Send Email via /run_sse
  const promptText = `Subject: ${subject}\nFrom: ${sender}\nBody: ${body}`;
  const runPayload = {
    agent: "inbox_triage_agent",
    app_name: "app",
    user_id: userId,
    session_id: sessionId,
    new_message: {
      role: "user",
      parts: [{ text: promptText }]
    }
  };

  const runOptions = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(runPayload),
    muteHttpExceptions: true
  };

  const runResp = UrlFetchApp.fetch(`${BASE_URL}/run_sse`, runOptions);
  const responseText = runResp.getContentText();

  // Step 3: Parse SSE Stream for TriageResult
  const lines = responseText.split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("data:")) {
      try {
        const jsonChunk = JSON.parse(trimmed.substring(5).trim());
        const parts = jsonChunk.content?.parts || [];
        for (const part of parts) {
          if (part.text && (part.text.includes('"classification"') || part.text.includes('"category"'))) {
            return JSON.parse(part.text);
          }
        }
      } catch (e) {}
    }
  }
  return null;
}

function ensureLabelsExist() {
  for (const key in LABELS) {
    const labelName = LABELS[key];
    if (!GmailApp.getUserLabelByName(labelName)) {
      GmailApp.createLabel(labelName);
    }
  }
}

function applyLabel(thread, labelName) {
  const label = GmailApp.getUserLabelByName(labelName) || GmailApp.createLabel(labelName);
  thread.addLabel(label);
}
