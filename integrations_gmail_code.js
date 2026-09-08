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
  syncCalendarEvents();
  syncMedicationLogsToSheet();
  checkMedicationAlerts();
  sendApprovedDrafts();
  syncVaultDocumentsToDrive();

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

  // 1. If a draft reply was generated, attach draft to thread first to capture draft ID
  let createdDraftId = null;
  if (draftReply && category !== "spam" && category !== "fyi" && category !== "needs_human_review") {
    try {
      const draft = thread.createDraftReply(draftReply);
      createdDraftId = draft.getId();
      Logger.log(`Created draft reply for "${subject}" (Draft ID: ${createdDraftId})`);
    } catch (e) {
      Logger.log(`Could not create draft reply: ${e.message}`);
    }
  }

  // 2. Apply category label & trigger alerts
  switch (category) {
    case "urgent":
      applyLabel(thread, LABELS.URGENT);
      thread.markImportant();
      sendUrgentEmailAlert(subject, sender, draftReply, createdDraftId, thread.getId());
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

/**
 * Automatically syncs events extracted by the Voice-to-Task Agent into Google Calendar!
 */
function syncCalendarEvents() {
  try {
    const url = `${BASE_URL}/voice/records`;
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) return;

    const data = JSON.parse(resp.getContentText());
    const events = data.events || [];
    const calendar = CalendarApp.getDefaultCalendar();

    for (const ev of events) {
      if (!ev.start_time) continue;
      const startTime = new Date(ev.start_time);
      const endTime = ev.end_time ? new Date(ev.end_time) : new Date(startTime.getTime() + 60 * 60 * 1000);

      // Check if event with same title already exists in the time window
      const searchStart = new Date(startTime.getTime() - 2 * 60 * 60 * 1000);
      const searchEnd = new Date(endTime.getTime() + 2 * 60 * 60 * 1000);
      const existing = calendar.getEvents(searchStart, searchEnd, { search: ev.title });

      if (existing.length === 0) {
        calendar.createEvent(ev.title, startTime, endTime, {
          description: ev.description || "Created automatically by Voice-to-Task Agent",
          location: ev.location || ""
        });
        Logger.log(`Created Google Calendar event: "${ev.title}" at ${startTime}`);
      }
    }
  } catch (err) {
    Logger.log(`Error syncing calendar: ${err.message}`);
  }
}

/**
 * Automatically syncs medication adherence logs into a Google Sheet in Google Drive!
 */
function syncMedicationLogsToSheet() {
  try {
    const url = `${BASE_URL}/health/records`;
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) return;

    const data = JSON.parse(resp.getContentText());
    const logs = data.logs || [];
    if (logs.length === 0) return;

    const sheetName = "My Health & Medication Log";
    const files = DriveApp.getFilesByName(sheetName);
    let spreadsheet;
    if (files.hasNext()) {
      spreadsheet = SpreadsheetApp.open(files.next());
    } else {
      spreadsheet = SpreadsheetApp.create(sheetName);
      const sheet = spreadsheet.getActiveSheet();
      sheet.appendRow(["Log ID", "Date", "Medication", "Dosage", "Scheduled For", "Time Taken", "Status"]);
      sheet.getRange(1, 1, 1, 7).setFontWeight("bold").setBackground("#E8F0FE");
    }

    const sheet = spreadsheet.getActiveSheet();
    const existingData = sheet.getDataRange().getValues();
    const existingIds = new Set(existingData.map(row => row[0]));

    for (const log of logs) {
      if (!existingIds.has(log.id)) {
        const datePart = (log.taken_time || "").split(" ")[0];
        sheet.appendRow([
          log.id,
          datePart,
          log.med_name,
          log.dosage || "1 dose",
          log.scheduled_time,
          log.taken_time,
          log.status === "taken" ? "✅ Taken" : "⏰ Snoozed"
        ]);
        existingIds.add(log.id);
        Logger.log(`Appended med log to Google Sheet: ${log.med_name} (${log.status})`);
      }
    }
  } catch (err) {
    Logger.log(`Error syncing medication logs to Sheet: ${err.message}`);
  }
}

/**
 * Pushes the automated 8:00 AM Morning Briefing to your Telegram chat!
 * Setup: In Apps Script -> Triggers -> Add Trigger -> sendDailyMorningBriefing -> Time-driven -> Day timer -> 8am to 9am.
 */
function sendDailyMorningBriefing() {
  try {
    const url = `${BASE_URL}/briefing/send`;
    const resp = UrlFetchApp.fetch(url, { method: "post", muteHttpExceptions: true });
    Logger.log(`Morning Briefing broadcast response: ${resp.getContentText()}`);
  } catch (err) {
    Logger.log(`Error broadcasting morning briefing: ${err.message}`);
  }
}

/**
 * Checks for pending medication doses and pings Telegram with interactive buttons.
 */
function checkMedicationAlerts() {
  try {
    const url = `${BASE_URL}/health/remind`;
    const resp = UrlFetchApp.fetch(url, { method: "post", muteHttpExceptions: true });
    Logger.log(`Medication reminder response: ${resp.getContentText()}`);
  } catch (err) {
    Logger.log(`Error checking medication alerts: ${err.message}`);
  }
}

/**
 * Pushes an urgent alert to Telegram with 1-tap Send button when a high-priority email is triaged.
 */
function sendUrgentEmailAlert(subject, sender, draftReply, draftId, threadId) {
  try {
    const url = `${BASE_URL}/telegram/broadcast/urgent-email`;
    const payload = JSON.stringify({
      subject: subject,
      sender: sender,
      draft_reply: draftReply || null,
      draft_id: draftId || null,
      thread_id: threadId || null
    });
    UrlFetchApp.fetch(url, {
      method: "post",
      contentType: "application/json",
      payload: payload,
      muteHttpExceptions: true
    });
    Logger.log(`Sent urgent email alert with 1-tap send button for: "${subject}" (draft: ${draftId})`);
  } catch (err) {
    Logger.log(`Error sending urgent email alert to Telegram: ${err.message}`);
  }
}

/**
 * Checks for email drafts approved by you on Telegram and sends them via Gmail immediately!
 */
function sendApprovedDrafts() {
  try {
    const url = `${BASE_URL}/email/pending-sends`;
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) return;

    const data = JSON.parse(resp.getContentText());
    const pendingDrafts = data.pending_drafts || [];
    if (pendingDrafts.length === 0) return;

    Logger.log(`Found ${pendingDrafts.length} approved draft(s) to send via Gmail.`);

    for (const item of pendingDrafts) {
      const draftId = item.draft_id;
      if (!draftId) continue;

      try {
        const draft = GmailApp.getDraft(draftId);
        if (draft) {
          draft.send();
          Logger.log(`🚀 Successfully sent approved draft ${draftId} from Gmail!`);

          // Notify backend so Telegram message updates in place
          UrlFetchApp.fetch(`${BASE_URL}/email/mark-sent`, {
            method: "post",
            contentType: "application/json",
            payload: JSON.stringify({ draft_id: draftId }),
            muteHttpExceptions: true
          });
        } else {
          Logger.log(`Draft ${draftId} not found in Gmail drafts.`);
        }
      } catch (sendErr) {
        Logger.log(`Error sending draft ${draftId}: ${sendErr.message}`);
      }
    }
  } catch (err) {
    Logger.log(`Error checking approved drafts: ${err.message}`);
  }
}

/**
 * Automatically syncs vaulted documents and catalog to Google Drive!
 */
function syncVaultDocumentsToDrive() {
  try {
    const url = `${BASE_URL}/vault/records`;
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) return;

    const data = JSON.parse(resp.getContentText());
    const docs = data.documents || [];
    if (docs.length === 0) return;

    const folderName = "My AI Document Vault";
    const folders = DriveApp.getFoldersByName(folderName);
    let folder;
    if (folders.hasNext()) {
      folder = folders.next();
    } else {
      folder = DriveApp.createFolder(folderName);
      Logger.log(`Created new Google Drive folder: "${folderName}"`);
    }

    const sheetName = "Vault Catalog & Index";
    const files = folder.getFilesByName(sheetName);
    let spreadsheet;
    if (files.hasNext()) {
      spreadsheet = SpreadsheetApp.open(files.next());
    } else {
      spreadsheet = SpreadsheetApp.create(sheetName);
      const file = DriveApp.getFileById(spreadsheet.getId());
      folder.addFile(file);
      DriveApp.getRootFolder().removeFile(file);

      const sheet = spreadsheet.getActiveSheet();
      sheet.appendRow(["Doc ID", "Document Name", "Category", "Ingested Date", "Summary", "Highlights"]);
      sheet.getRange(1, 1, 1, 6).setFontWeight("bold").setBackground("#E8F0FE");
    }

    const sheet = spreadsheet.getActiveSheet();
    const existingData = sheet.getDataRange().getValues();
    const existingIds = new Set(existingData.map(row => row[0]));

    for (const doc of docs) {
      if (!existingIds.has(doc.doc_id)) {
        const hlStr = (doc.highlights || []).join("; ");
        sheet.appendRow([
          doc.doc_id,
          doc.filename,
          doc.doc_type,
          doc.upload_date,
          doc.summary,
          hlStr
        ]);
        existingIds.add(doc.doc_id);
        Logger.log(`Synced vaulted document to Google Drive catalog: ${doc.filename}`);
      }
    }
  } catch (err) {
    Logger.log(`Error syncing vault documents to Drive: ${err.message}`);
  }
}

