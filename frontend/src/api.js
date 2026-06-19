const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

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
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
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
    const response = await fetch(`${API_BASE}/api/resumes/upload`, {
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
