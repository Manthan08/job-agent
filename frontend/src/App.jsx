import {
  Download,
  FileText,
  Keyboard,
  MessageSquare,
  Send,
  Upload,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, tailoredPdfUrl } from "./api";

const QUICK_PROMPTS = [
  ["Fit", "Explain my strongest match"],
  ["Gaps", "Find weak JD keywords"],
  ["STAR", "Create STAR answers"],
  ["Mock", "Start a mock interview"],
];
const MAX_CHAT_CHARS = 800;

const EMPTY_BOOTSTRAP = {
  resumes: [],
  jobs: [],
  features: { prep_pack_enabled: false, coach_ready: false },
};

const INITIAL_PROFILE = {
  name: "",
  email: "",
  target_role: "",
  location: "",
  years_experience: "",
  summary_text: "",
};

const INITIAL_JOB = {
  company_name: "",
  position: "",
  job_location: "",
  job_url: "",
  job_description: "",
  years_required: "",
};

function parseConfirmedSkills(text) {
  const seen = new Set();
  return String(text || "")
    .split(/[,;\n]+/)
    .map((item) => item.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .filter((item) => {
      const key = item.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 40);
}

const GENERIC_JOB_LINES = new Set([
  "about the job",
  "about this job",
  "description",
  "job description",
  "job summary",
  "overview",
  "responsibilities",
  "requirements",
  "the role",
  "what you will do",
  "what you'll do",
]);

function cleanMetadataValue(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 160);
}

function fieldFromLines(lines, labels) {
  for (const line of lines) {
    for (const label of labels) {
      const match = line.match(new RegExp(`^${label}\\s*[:\\-–]\\s*(.+)$`, "i"));
      if (match?.[1]) return cleanMetadataValue(match[1]);
    }
  }
  return "";
}

function stableTextHash(text) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function buildJobPayloadFromPaste(jobDescription) {
  const cleaned = jobDescription.trim();
  const lines = cleaned
    .split(/\r?\n/)
    .map(cleanMetadataValue)
    .filter(Boolean);
  const likelyTitle = lines.find(
    (line) =>
      line.length <= 100 && !GENERIC_JOB_LINES.has(line.toLowerCase().replace(/:$/, ""))
  );

  return {
    company_name: fieldFromLines(lines, ["company", "employer", "organization"]) || "Pasted JD",
    position:
      fieldFromLines(lines, ["job title", "title", "position", "role"]) ||
      likelyTitle ||
      "Pasted role",
    job_location: fieldFromLines(lines, ["location", "job location"]) || null,
    job_url: `manual://paste/${stableTextHash(cleaned)}`,
    years_required: null,
    job_description: cleaned,
  };
}

function displayResume(resume) {
  if (!resume) return "Select a resume";
  return `${resume.Name || "Unnamed"}${resume.CurrentPosition ? ` - ${resume.CurrentPosition}` : ""}`;
}

function displayJob(job) {
  if (!job) return "Select a job";
  return `${job.CompanyName || "Company"} - ${job.Position || "Role"}`;
}

function compactGapLabel(value) {
  const original = String(value || "").trim();
  let text = original
    .replace(/^gap:\s*/i, "")
    .replace(/^explicit\s+/i, "")
    .trim();

  for (const marker of [",", ";", " - ", " -- ", " (", ":"]) {
    const index = text.indexOf(marker);
    if (index > 0) text = text.slice(0, index);
  }

  text = text
    .replace(/\bexperience\b.*$/i, "")
    .replace(/\bis not\b.*$/i, "")
    .replace(/\bare not\b.*$/i, "")
    .replace(/\bnot clearly\b.*$/i, "")
    .replace(/\bas an alternative\b.*$/i, "")
    .replace(/\ba repeated\b.*$/i, "")
    .replace(/\bwith\b\s*$/i, "")
    .replace(/\s+/g, " ")
    .trim();

  const fallback = original || "Missing skill";
  const label = text || fallback;
  return label.length > 34 ? `${label.slice(0, 31)}...` : label;
}

function prepToMarkdown(pack) {
  if (!pack) return "";
  const lines = [`# Interview Prep Pack`, "", `_Overview:_ ${pack.overview || ""}`, ""];
  for (const [index, question] of (pack.questions || []).entries()) {
    lines.push(`## ${index + 1}. ${question.question}`);
    lines.push(`- Topic: ${question.topic}`);
    lines.push(`- Gap: ${question.is_gap ? "yes" : "no"}`);
    if (question.grounded_in?.length) {
      lines.push(`- Grounded in: ${question.grounded_in.join(", ")}`);
    }
    lines.push("");
    lines.push(question.suggested_answer || "");
    lines.push("");
  }
  if (pack.study_topics?.length) {
    lines.push("## Study topics", "");
    for (const topic of pack.study_topics) {
      lines.push(`- ${topic}`);
    }
  }
  return lines.join("\n");
}

function downloadText(filename, text) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function renderInlineMarkdown(text, keyPrefix = "inline") {
  const parts = String(text || "").split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts
    .filter((part) => part !== "")
    .map((part, index) => {
      const key = `${keyPrefix}-${index}`;
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={key}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return <code key={key}>{part.slice(1, -1)}</code>;
      }
      return part;
    });
}

function parseTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableDivider(line) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function isBlockStart(line, nextLine = "") {
  return (
    /^#{1,3}\s+/.test(line) ||
    /^\s*[-*]\s+/.test(line) ||
    /^\s*\d+[.)]\s+/.test(line) ||
    (line.includes("|") && isTableDivider(nextLine))
  );
}

function MarkdownMessage({ text }) {
  const lines = String(text || "").split(/\r?\n/);
  const nodes = [];
  let index = 0;
  let key = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (line.includes("|") && isTableDivider(lines[index + 1] || "")) {
      const headers = parseTableRow(line);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(parseTableRow(lines[index]));
        index += 1;
      }
      nodes.push(
        <div className="markdown-table-wrap" key={`table-${key++}`}>
          <table>
            <thead>
              <tr>
                {headers.map((header, cellIndex) => (
                  <th key={`h-${cellIndex}`}>
                    {renderInlineMarkdown(header, `table-h-${key}-${cellIndex}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`r-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`c-${cellIndex}`}>
                      {renderInlineMarkdown(cell, `table-c-${key}-${rowIndex}-${cellIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    const heading = line.match(/^#{1,3}\s+(.+)$/);
    if (heading) {
      nodes.push(
        <h3 key={`heading-${key++}`}>
          {renderInlineMarkdown(heading[1], `heading-${key}`)}
        </h3>
      );
      index += 1;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*[-*]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      nodes.push(
        <ul key={`ul-${key++}`}>
          {items.map((item, itemIndex) => (
            <li key={`li-${itemIndex}`}>
              {renderInlineMarkdown(item, `ul-${key}-${itemIndex}`)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*\d+[.)]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      nodes.push(
        <ol key={`ol-${key++}`}>
          {items.map((item, itemIndex) => (
            <li key={`li-${itemIndex}`}>
              {renderInlineMarkdown(item, `ol-${key}-${itemIndex}`)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isBlockStart(lines[index], lines[index + 1] || "")
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    nodes.push(
      <p key={`p-${key++}`}>
        {renderInlineMarkdown(paragraph.join(" "), `p-${key}`)}
      </p>
    );
  }

  return <div className="markdown-message">{nodes}</div>;
}

function App() {
  const [bootstrap, setBootstrap] = useState(EMPTY_BOOTSTRAP);
  const [pairState, setPairState] = useState(null);
  const [resumeId, setResumeId] = useState("");
  const [jobId, setJobId] = useState("");
  const [resumeMode, setResumeMode] = useState("upload");
  const [jobMode, setJobMode] = useState("paste");
  const [profile, setProfile] = useState(INITIAL_PROFILE);
  const [jobDraft, setJobDraft] = useState(INITIAL_JOB);
  const [jobUrl, setJobUrl] = useState("");
  const [resumeFile, setResumeFile] = useState(null);
  const [chatDraft, setChatDraft] = useState("");
  const [confirmedSkillsText, setConfirmedSkillsText] = useState("");
  const [chatByPair, setChatByPair] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("resume-workbench-chat") || "{}");
    } catch {
      return {};
    }
  });
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const threadRef = useRef(null);

  const resumes = bootstrap.resumes || [];
  const jobs = bootstrap.jobs || [];
  const selectedPairReady = Boolean(resumeId && jobId);
  const pairKey = selectedPairReady ? `${resumeId}:${jobId}` : "none";
  const history = chatByPair[pairKey] || [];
  const application = pairState?.application || null;
  const score = application?.MatchScorePercent;
  const prepPack = pairState?.prep_pack || null;
  const tailoring = pairState?.tailoring_recommendation || null;
  const canUseCoach = selectedPairReady && bootstrap.features?.coach_ready;

  useEffect(() => {
    let cancelled = false;
    api
      .bootstrap()
      .then((data) => {
        if (cancelled) return;
        setBootstrap(data);
        if (!resumeId && data.resumes?.[0]) setResumeId(String(data.resumes[0].Id));
        if (!jobId && data.jobs?.[0]) setJobId(String(data.jobs[0].Id));
      })
      .catch((exc) => setError(exc.message));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    localStorage.setItem("resume-workbench-chat", JSON.stringify(chatByPair));
  }, [chatByPair]);

  useEffect(() => {
    if (!selectedPairReady) {
      setPairState(null);
      return;
    }
    let cancelled = false;
    api
      .pairState(resumeId, jobId)
      .then((data) => {
        if (!cancelled) setPairState(data);
      })
      .catch((exc) => setError(exc.message));
    return () => {
      cancelled = true;
    };
  }, [resumeId, jobId, selectedPairReady]);

  useEffect(() => {
    threadRef.current?.scrollTo({
      top: threadRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [history, busy, pairKey]);

  function setPairHistory(updater) {
    setChatByPair((current) => {
      const nextHistory = updater(current[pairKey] || []);
      return { ...current, [pairKey]: nextHistory };
    });
  }

  async function runAction(label, action) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (exc) {
      setError(exc.message || String(exc));
    } finally {
      setBusy("");
    }
  }

  function applyBootstrap(data, nextResumeId = resumeId, nextJobId = jobId) {
    setBootstrap(data);
    if (nextResumeId) setResumeId(String(nextResumeId));
    if (nextJobId) setJobId(String(nextJobId));
  }

  async function handleUploadResume() {
    if (!resumeFile) return;
    await runAction("upload", async () => {
      const data = await api.uploadResume(resumeFile);
      applyBootstrap(data, data.resume_id);
      setResumeFile(null);
      setNotice("Resume saved and selected.");
    });
  }

  async function handleCreateProfile(event) {
    event.preventDefault();
    await runAction("profile", async () => {
      const data = await api.createProfileResume(profile);
      applyBootstrap(data, data.resume_id);
      setProfile(INITIAL_PROFILE);
      setNotice("Profile resume saved and selected.");
    });
  }

  async function handlePasteJob(event) {
    event.preventDefault();
    const jobDescription = jobDraft.job_description.trim();
    if (!jobDescription) return;
    await runAction("job", async () => {
      const payload = buildJobPayloadFromPaste(jobDescription);
      const data = await api.pasteJob(payload);
      applyBootstrap(data, resumeId, data.job_id);
      setJobDraft(INITIAL_JOB);
      setNotice("Job saved and selected.");
    });
  }

  async function handleImportJob() {
    if (!jobUrl.trim()) return;
    await runAction("import", async () => {
      const data = await api.importJob(jobUrl.trim());
      applyBootstrap(data, resumeId, data.job_id);
      setJobUrl("");
      setNotice("Job imported and selected.");
    });
  }

  async function handleScore() {
    if (!selectedPairReady) return;
    await runAction("score", async () => {
      const data = await api.score(Number(resumeId), Number(jobId));
      setPairState(data.pair_state);
      setNotice("Match score updated.");
    });
  }

  async function handleTailor() {
    if (!selectedPairReady) return;
    await runAction("tailor", async () => {
      const confirmedSkills = parseConfirmedSkills(confirmedSkillsText);
      const data = await api.tailor(Number(resumeId), Number(jobId), confirmedSkills);
      setPairState(data.pair_state);
      const atsScore = data.ats_coverage_score;
      setNotice(
        atsScore == null
          ? "Tailored resume generated."
          : `Tailored resume generated. ATS coverage score: ${atsScore}/100.`
      );
    });
  }

  async function handlePrep() {
    if (!selectedPairReady) return;
    await runAction("prep", async () => {
      const data = await api.prep(Number(resumeId), Number(jobId));
      setPairState(data.pair_state);
      setNotice("Prep pack generated.");
    });
  }

  async function sendCoachMessage(message) {
    const trimmed = message.trim();
    if (!trimmed || !canUseCoach) return;
    setChatDraft("");
    setPairHistory((current) => [...current, { role: "user", content: trimmed }]);
    await runAction("coach", async () => {
      const data = await api.coach(Number(resumeId), Number(jobId), trimmed);
      setPairHistory((current) => [
        ...current,
        { role: "assistant", content: data.reply },
      ]);
    });
  }

  const gapCount = application?.MissingSkills?.length || 0;
  let nextAction = "Run Score match first. Tailoring starts only after the original fit is known.";
  if (score != null && tailoring?.status === "not_recommended") {
    nextAction = "Do not apply unless you can close major must-have gaps first.";
  } else if (score != null && tailoring?.status === "stretch") {
    nextAction = "Stretch role. Tailor only around direct and honestly adjacent JD keywords.";
  } else if (score != null && gapCount > 0) {
    nextAction = pairState?.tailored_pdf_available
      ? "Ask Coach to rehearse short answers for these gaps."
      : "Tailor aggressively around supported JD keywords, then rehearse gaps.";
  } else if (score != null) {
    nextAction = pairState?.tailored_pdf_available
      ? "No major gaps listed. Use Coach for interview practice."
      : "Good base fit. Tailor toward 85+ using truthful JD wording.";
  }

  return (
    <div className="page-shell">
      <div className="app-frame">
        <Topbar />

        <main className="main">
          <div className="workspace-grid">
            <InputRail
              resumes={resumes}
              jobs={jobs}
              resumeId={resumeId}
              jobId={jobId}
              setResumeId={setResumeId}
              setJobId={setJobId}
              resumeMode={resumeMode}
              setResumeMode={setResumeMode}
              jobMode={jobMode}
              setJobMode={setJobMode}
              resumeFile={resumeFile}
              setResumeFile={setResumeFile}
              profile={profile}
              setProfile={setProfile}
              jobDraft={jobDraft}
              setJobDraft={setJobDraft}
              jobUrl={jobUrl}
              setJobUrl={setJobUrl}
              onUploadResume={handleUploadResume}
              onCreateProfile={handleCreateProfile}
              onPasteJob={handlePasteJob}
              onImportJob={handleImportJob}
              busy={busy}
            />

            <section className="work-area">
              {(notice || error) && (
                <div className={`notice ${error ? "error" : ""}`}>
                  {error || notice}
                  <button type="button" onClick={() => (error ? setError("") : setNotice(""))}>
                    Dismiss
                  </button>
                </div>
              )}

              <div className="hero-chat">
                <ChatPanel
                  selectedPairReady={selectedPairReady}
                  coachReady={bootstrap.features?.coach_ready}
                  history={history}
                  busy={busy}
                  chatDraft={chatDraft}
                  setChatDraft={setChatDraft}
                  onSend={sendCoachMessage}
                  threadRef={threadRef}
                />

                <InsightStack
                  application={application}
                  score={score}
                  nextAction={nextAction}
                  onScore={handleScore}
                  busy={busy}
                  pairReady={selectedPairReady}
                />
              </div>

              <ArtifactRow
                application={application}
                pairState={pairState}
                tailoring={tailoring}
                prepEnabled={bootstrap.features?.prep_pack_enabled}
                prepPack={prepPack}
                pairReady={selectedPairReady}
                confirmedSkillsText={confirmedSkillsText}
                setConfirmedSkillsText={setConfirmedSkillsText}
                busy={busy}
                onTailor={handleTailor}
                onPrep={handlePrep}
              />
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}

function Topbar() {
  return (
    <header className="topbar">
      <a className="brand" href="/" aria-label="Resume Buddy home">
        <span className="brand-mark" aria-hidden="true">
          <FileText size={21} />
        </span>
        <span className="brand-title">
          <span>Resume</span>
          <span>Buddy</span>
        </span>
      </a>
    </header>
  );
}

function InputRail(props) {
  const {
    resumes,
    jobs,
    resumeId,
    jobId,
    setResumeId,
    setJobId,
    resumeMode,
    setResumeMode,
    jobMode,
    setJobMode,
    resumeFile,
    setResumeFile,
    profile,
    setProfile,
    jobDraft,
    setJobDraft,
    jobUrl,
    setJobUrl,
    onUploadResume,
    onCreateProfile,
    onPasteJob,
    onImportJob,
    busy,
  } = props;
  const uploadInputId = "resume-upload-input";
  const uploadInputRef = useRef(null);
  const activeResumeLabel = displayResume(
    resumes.find((resume) => String(resume.Id) === String(resumeId)),
  );
  const activeJobLabel = displayJob(
    jobs.find((job) => String(job.Id) === String(jobId)),
  );

  function handleResumeDrop(event) {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file) setResumeFile(file);
  }

  function handleDropzoneKeyDown(event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      uploadInputRef.current?.click();
    }
  }

  return (
    <aside className="sidebar" aria-label="Inputs">
      <section className="input-card">
        <SectionTitle title="Resume" meta="required" />
        <label className="field-label">
          Active resume
          <select
            className="field context-select"
            value={resumeId}
            title={activeResumeLabel}
            onChange={(event) => setResumeId(event.target.value)}
          >
            {resumes.length === 0 && <option value="">No resumes yet</option>}
            {resumes.map((resume) => (
              <option key={resume.Id} value={resume.Id}>
                {displayResume(resume)}
              </option>
            ))}
          </select>
        </label>

        <Segmented
          value={resumeMode}
          onChange={setResumeMode}
          options={[
            ["upload", "Upload PDF"],
            ["profile", "Profile builder"],
          ]}
        />

        {resumeMode === "upload" ? (
          <form
            key="resume-upload-form"
            className="stack-form"
            onSubmit={(event) => event.preventDefault()}
          >
            <label
              className="dropzone"
              htmlFor={uploadInputId}
              role="button"
              tabIndex={0}
              onDragOver={(event) => event.preventDefault()}
              onDrop={handleResumeDrop}
              onKeyDown={handleDropzoneKeyDown}
            >
              <Upload size={30} aria-hidden="true" />
              <strong>{resumeFile ? resumeFile.name : "Drop resume here"}</strong>
              <span className="dropzone-hint">
                PDF only, or use the profile builder below.
              </span>
            </label>
            <input
              id={uploadInputId}
              className="hidden-file-input"
              ref={uploadInputRef}
              type="file"
              accept="application/pdf"
              onChange={(event) => setResumeFile(event.target.files?.[0] || null)}
            />
            {resumeFile && (
              <button
                className="button compact full"
                type="button"
                onClick={onUploadResume}
                disabled={busy === "upload"}
              >
                Save resume
              </button>
            )}
          </form>
        ) : (
          <form key="resume-profile-form" className="stack-form" onSubmit={onCreateProfile}>
            <div className="form-mode-note">
              <Keyboard size={16} />
              <span>Profile details</span>
            </div>
            <input
              className="field"
              placeholder="Name"
              value={profile.name}
              onChange={(event) => setProfile({ ...profile, name: event.target.value })}
              required
            />
            <input
              className="field"
              placeholder="Email"
              type="email"
              value={profile.email}
              onChange={(event) => setProfile({ ...profile, email: event.target.value })}
              required
            />
            <input
              className="field"
              placeholder="Target role"
              value={profile.target_role}
              onChange={(event) =>
                setProfile({ ...profile, target_role: event.target.value })
              }
            />
            <textarea
              className="textarea-field"
              placeholder="Experience, projects, education, and skills"
              value={profile.summary_text}
              onChange={(event) =>
                setProfile({ ...profile, summary_text: event.target.value })
              }
              required
            />
            <button className="button compact full" type="submit" disabled={busy === "profile"}>
              Save profile
            </button>
          </form>
        )}
      </section>

      <section className="input-card">
        <SectionTitle title="Job description" meta="URL or paste" />
        <label className="field-label">
          Active job
          <select
            className="field context-select"
            value={jobId}
            title={activeJobLabel}
            onChange={(event) => setJobId(event.target.value)}
          >
            {jobs.length === 0 && <option value="">No jobs yet</option>}
            {jobs.map((job) => (
              <option key={job.Id} value={job.Id}>
                {displayJob(job)}
              </option>
            ))}
          </select>
        </label>

        <Segmented
          value={jobMode}
          onChange={setJobMode}
          options={[
            ["paste", "Paste JD"],
            ["url", "Job URL"],
          ]}
        />

        {jobMode === "paste" ? (
          <form key="job-paste-form" className="stack-form" onSubmit={onPasteJob}>
            <textarea
              className="textarea-field tall paste-jd-box"
              placeholder="Paste the JD here. The assistant will use it for match score, tailoring, and interview prep."
              value={jobDraft.job_description}
              onChange={(event) =>
                setJobDraft({ ...jobDraft, job_description: event.target.value })
              }
              required
            />
            {jobDraft.job_description.trim() && (
              <button
                className="button compact full"
                type="submit"
                disabled={busy === "job"}
              >
                Save JD
              </button>
            )}
          </form>
        ) : (
          <div key="job-url-form" className="stack-form">
            <input
              className="field"
              placeholder="HTTPS career/job posting URL"
              value={jobUrl}
              onChange={(event) => setJobUrl(event.target.value)}
            />
            <button
              className="button compact"
              type="button"
              onClick={onImportJob}
              disabled={!jobUrl || busy === "import"}
            >
              Import from URL
            </button>
          </div>
        )}
      </section>

    </aside>
  );
}

function ChatPanel({
  selectedPairReady,
  coachReady,
  history,
  busy,
  chatDraft,
  setChatDraft,
  onSend,
  threadRef,
}) {
  function submit(event) {
    event.preventDefault();
    onSend(chatDraft);
  }
  const remainingChars = MAX_CHAT_CHARS - chatDraft.length;

  return (
    <section className="chat-panel" aria-label="Interview coach">
      <div className="chat-head">
        <div className="chat-title-row">
          <h1>Interview coach</h1>
          <span className={`coach-status ${coachReady ? "ready" : ""}`}>
            {coachReady ? "Ready" : "Offline"}
          </span>
        </div>
        <div className="quick-prompts">
          {QUICK_PROMPTS.map(([label, message]) => (
            <button
              key={label}
              type="button"
              onClick={() => onSend(message)}
              disabled={!selectedPairReady || !coachReady || busy === "coach"}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="chat-thread" ref={threadRef}>
        {history.length === 0 ? (
          <div className="chat-empty-state" aria-label="No coach messages yet">
            <MessageSquare size={24} aria-hidden="true" />
            <strong>No coach messages yet</strong>
            <span>Selected resume and JD context will stay grounded here.</span>
          </div>
        ) : (
          history.map((message, index) => (
            <Bubble key={`${message.role}-${index}`} role={message.role}>
              {message.content}
            </Bubble>
          ))
        )}

        {busy === "coach" && <Bubble role="assistant">Coach is thinking...</Bubble>}
      </div>

      <form className="composer" onSubmit={submit}>
        <input
          aria-label="Ask the coach"
          maxLength={MAX_CHAT_CHARS}
          placeholder={
            coachReady
              ? "How should I explain my RAG gap?"
              : "Coach graph is not ready yet"
          }
          value={chatDraft}
          onChange={(event) => setChatDraft(event.target.value)}
          disabled={!selectedPairReady || !coachReady || busy === "coach"}
        />
        {chatDraft.length > MAX_CHAT_CHARS * 0.75 && (
          <span className="composer-count">{remainingChars} left</span>
        )}
        <button
          className="button primary"
          type="submit"
          disabled={!chatDraft.trim() || !selectedPairReady || !coachReady}
        >
          <Send size={16} />
          Ask
        </button>
      </form>
    </section>
  );
}

function Bubble({ role, children }) {
  return (
    <div className={`bubble ${role === "user" ? "user" : ""}`}>
      {role === "assistant" ? <MarkdownMessage text={children} /> : children}
    </div>
  );
}

function InsightStack({
  application,
  score,
  nextAction,
  onScore,
  busy,
  pairReady,
}) {
  return (
    <aside className="insight-stack" aria-label="Insights">
      <section className="metric-card score-card">
        <SectionTitle title="Your ATS Score" meta={<span className="status-dot" />} />
        <button
          className="button compact full"
          type="button"
          onClick={onScore}
          disabled={!pairReady || busy === "score"}
        >
          Score match
        </button>
        <div className="metric-value">
          <strong>{score ?? "--"}</strong>
          <span>/ 100</span>
        </div>
        <GapSummary items={application?.MissingSkills || []} hasScore={score != null} />
      </section>

      <section className="metric-card">
        <SectionTitle title="Next best action" meta={<span className="status-dot gold" />} />
        <p>{nextAction}</p>
      </section>
    </aside>
  );
}

function ArtifactRow({
  application,
  pairState,
  tailoring,
  prepEnabled,
  prepPack,
  pairReady,
  confirmedSkillsText,
  setConfirmedSkillsText,
  busy,
  onTailor,
  onPrep,
}) {
  const applicationId = application?.Id;
  const canTailor = pairReady && Boolean(tailoring?.can_tailor);
  const tailoredFilename = pairState?.tailored_pdf_filename;
  const tailoredDisplayName = pairState?.tailored_pdf_display_name || tailoredFilename;

  return (
    <section className="output-row" aria-label="Generated artifacts">
      <article className="artifact-card">
        <span className="artifact-icon">
          <FileText size={22} />
        </span>
        <div>
          <h3>Tailored resume</h3>
          <p>{tailoring?.message || "Score the pair before generating a tailored PDF."}</p>
          <label className="artifact-field-label">
            Confirmed skills to add
            <textarea
              className="artifact-textarea"
              placeholder="HTML, CSS, JavaScript, AWS SQS basics"
              value={confirmedSkillsText}
              onChange={(event) => setConfirmedSkillsText(event.target.value)}
              disabled={!pairReady || busy === "tailor"}
            />
          </label>
          {pairState?.tailored_pdf_available && tailoredFilename && (
            <p className="artifact-filename" title={tailoredFilename}>
              Ready: {tailoredDisplayName}
            </p>
          )}
          <div className="button-row">
            <button
              className="button compact accent"
              type="button"
              onClick={onTailor}
              disabled={!canTailor || busy === "tailor"}
            >
              Tailor resume
            </button>
            {pairState?.tailored_pdf_available && applicationId && (
              <a className="button compact" href={tailoredPdfUrl(applicationId)}>
                <Download size={15} />
                Download PDF
              </a>
            )}
          </div>
        </div>
      </article>

      <article className="artifact-card">
        <span className="artifact-icon sage">
          <MessageSquare size={22} />
        </span>
        <div>
          <h3>Question bank</h3>
          <p>Role-specific interview questions from your story bank.</p>
          <div className="button-row">
            <button
              className="button compact"
              type="button"
              onClick={onPrep}
              disabled={!pairReady || !prepEnabled || busy === "prep"}
            >
              Generate pack
            </button>
            {prepPack && (
              <button
                className="button compact"
                type="button"
                onClick={() => downloadText("interview_prep.md", prepToMarkdown(prepPack))}
              >
                <Download size={15} />
                Download pack
              </button>
            )}
          </div>
        </div>
      </article>
    </section>
  );
}

function SectionTitle({ title, meta }) {
  return (
    <div className="section-title">
      <h2>{title}</h2>
      {typeof meta === "string" ? <small>{meta}</small> : meta}
    </div>
  );
}

function Segmented({ value, onChange, options }) {
  return (
    <div className="source-tabs">
      {options.map(([optionValue, label]) => (
        <button
          key={optionValue}
          type="button"
          className={value === optionValue ? "selected" : ""}
          onClick={() => onChange(optionValue)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function GapSummary({ items, hasScore }) {
  if (!hasScore) {
    return <p className="score-hint">Score the pair to see the missing skills.</p>;
  }
  if (!items?.length) {
    return <p className="score-hint">No major missing skills listed.</p>;
  }
  const compactItems = items.map(compactGapLabel);
  return (
    <div className="gap-summary">
      <span className="gap-label">Missing / weak</span>
      <TagList items={compactItems} tone="gap compact" limit={4} />
    </div>
  );
}

function TagList({ items, tone = "", limit = 5 }) {
  if (!items?.length) return null;
  return (
    <div className={`tag-list ${tone}`}>
      {items.slice(0, limit).map((item, index) => (
        <span key={`${item}-${index}`}>{item}</span>
      ))}
    </div>
  );
}

export default App;
