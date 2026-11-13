const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

// Without a timeout a hung backend leaves the UI spinning forever. These bound
// the wait and surface a clear error instead. Tailoring runs several 120b LLM
// passes whose latency varies a lot on the free NVIDIA tier (measured 170–290s
// end-to-end), so it gets a generous ceiling — tight enough to catch a true hang,
// loose enough not to abort a legitimately slow run. The real cure for the slow
// runs is moving the fast-tier calls (keyword/rescore) to a nano model.
const DEFAULT_TIMEOUT_MS = 120000;
const TAILOR_TIMEOUT_MS = 300000;

async function fetchWithTimeout(url, options = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s. ` +
          "The server may be busy — please try again in a moment."
      );
    }
    // A failed fetch (server unreachable, dropped connection) surfaces as a
    // cryptic "Failed to fetch" / "Load failed". Give the user something human.
    if (err instanceof TypeError) {
      throw new Error(
        "Couldn't reach the server — check your connection and try again."
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function parseResponse(response) {
  if (response.ok) {
    const contentType = response.headers.get("content-type") || "";
    return contentType.includes("application/json") ? response.json() : response.text();
  }

  let message = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    message = body.detail || message;
  } catch {
    // Keep the HTTP status message.
  }
  throw new Error(message);
}

async function request(path, options = {}) {
  const { timeoutMs, ...fetchOptions } = options;
  const response = await fetchWithTimeout(
    `${API_BASE}${path}`,
    {
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(fetchOptions.headers || {}),
      },
      ...fetchOptions,
    },
    timeoutMs
  );
  return parseResponse(response);
}

export function tailoredPdfUrl(applicationId) {
  return `${API_BASE}/api/applications/${applicationId}/tailored-pdf`;
}

export const api = {
  bootstrap: () => request("/api/bootstrap"),
  pairState: (resumeId, jobId) => request(`/api/pairs/${resumeId}/${jobId}`),
  createProfileResume: (payload) =>
    request("/api/resumes/profile", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadResume: async (file) => {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetchWithTimeout(`${API_BASE}/api/resumes/upload`, {
      method: "POST",
      credentials: "include",
      body: formData,
    });
    return parseResponse(response);
  },
  pasteJob: (payload) =>
    request("/api/jobs/paste", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  importJob: (pageUrl) =>
    request("/api/jobs/import", {
      method: "POST",
      body: JSON.stringify({ page_url: pageUrl }),
    }),
  score: (resumeId, jobId) =>
    request("/api/score", {
      method: "POST",
      body: JSON.stringify({ resume_id: resumeId, job_id: jobId }),
    }),
  tailor: (resumeId, jobId, confirmedSkills = []) =>
    request("/api/tailor", {
      method: "POST",
      timeoutMs: TAILOR_TIMEOUT_MS,
      body: JSON.stringify({
        resume_id: resumeId,
        job_id: jobId,
        confirmed_skills: confirmedSkills,
      }),
    }),
  prep: (resumeId, jobId) =>
    request("/api/prep", {
      method: "POST",
      body: JSON.stringify({ resume_id: resumeId, job_id: jobId }),
    }),
  coach: (resumeId, jobId, message) =>
    request("/api/coach", {
      method: "POST",
      body: JSON.stringify({ resume_id: resumeId, job_id: jobId, message }),
    }),
};
