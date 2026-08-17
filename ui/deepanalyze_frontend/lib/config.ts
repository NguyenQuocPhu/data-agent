export const API_CONFIG = {
  BACKEND_BASE_URL: "/api",
  AI_API_BASE_URL: "/api",
  // Backend direct URL - dùng cho SSE streaming (Next.js proxy buffer SSE)
  BACKEND_DIRECT_URL: typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:18000`
    : "http://localhost:18000",
  WEBSOCKET_URL: "",
  ENDPOINTS: {
    CHAT_COMPLETIONS: "/chat/completions",
    CHAT_STOP: "/chat/stop",
    CONTEXT_USAGE: "/chat/context",
    CHAT_RESET: "/chat/reset",
    SKILLS: "/skills",
    WORKSPACE_FILES: "/workspace/files",
    WORKSPACE_TREE: "/workspace/tree",
    WORKSPACE_PREVIEW: "/workspace/preview",
    WORKSPACE_DOWNLOAD_BUNDLE: "/workspace/download-bundle",
    WORKSPACE_UPLOAD: "/workspace/upload",
    WORKSPACE_CLEAR: "/workspace/clear",
    WORKSPACE_DELETE_FILE: "/workspace/file",
    WORKSPACE_UPLOAD_TO: "/workspace/upload-to",
    WORKSPACE_MOVE: "/workspace/move",
    WORKSPACE_DELETE_DIR: "/workspace/dir",
    WORKSPACE_GENERATED_FILES: "/workspace/generated-files",
    EXECUTE_CODE: "/execute",
    EXPORT_REPORT: "/export/report",
    CONVERGENCE_PERSONAS: "/convergence/personas",
    CONVERGENCE_STATUS: "/convergence/status",
    CONVERGENCE_MARKDOWN: "/convergence/markdown",
    ML_HEALTH: "/ml/health",
    ML_DATASETS: "/ml/datasets",
    ML_DATASET_UPLOAD: "/ml/datasets/upload",
    ML_EXPERIMENTS: "/ml/experiments",
  },
};

const normalizeBaseUrl = (baseUrl: string) => baseUrl.replace(/\/+$/, "");

const normalizeEndpoint = (endpoint: string) =>
  endpoint.startsWith("/") ? endpoint : `/${endpoint}`;

export const buildApiUrl = (
  endpoint: string,
  baseUrl: string = API_CONFIG.BACKEND_BASE_URL
) => {
  const normalizedBase = normalizeBaseUrl(baseUrl);
  const normalizedPath = normalizeEndpoint(endpoint);

  // API_URLS entries are already fully built (for example `/api/ml/datasets`).
  // Keep the helper idempotent so callers adding query params do not accidentally
  // turn that path into `/api/api/ml/datasets`.
  if (
    normalizedBase.startsWith("/") &&
    (normalizedPath === normalizedBase || normalizedPath.startsWith(`${normalizedBase}/`))
  ) {
    return normalizedPath;
  }

  return `${normalizedBase}${normalizedPath}`;
};

export const buildApiUrlWithParams = (
  endpoint: string,
  params: Record<string, string | number | boolean | null | undefined>,
  baseUrl: string = API_CONFIG.BACKEND_BASE_URL
) => {
  const builtUrl = buildApiUrl(endpoint, baseUrl);
  const isAbsolute = /^[a-z][a-z\d+.-]*:\/\//i.test(builtUrl);
  // `new URL("/api/...")` throws because it has no origin. Use a temporary origin while
  // assembling query parameters, then return the original same-origin relative shape.
  const url = new URL(builtUrl, "http://local.invalid");
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    url.searchParams.set(key, String(value));
  });
  return isAbsolute
    ? url.toString()
    : `${url.pathname}${url.search}${url.hash}`;
};

// Helper: build direct backend URL (bypass Next.js proxy for SSE streaming)
const buildDirectUrl = (endpoint: string) => {
  const direct = typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:18000`
    : "http://localhost:18000";
  return `${direct}${normalizeEndpoint(endpoint)}`;
};

export const API_URLS = {
  WORKSPACE_FILES: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_FILES),
  WORKSPACE_TREE: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_TREE),
  WORKSPACE_PREVIEW: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_PREVIEW),
  WORKSPACE_DOWNLOAD_BUNDLE: buildApiUrl(
    API_CONFIG.ENDPOINTS.WORKSPACE_DOWNLOAD_BUNDLE
  ),
  WORKSPACE_UPLOAD: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_UPLOAD),
  WORKSPACE_CLEAR: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_CLEAR),
  WORKSPACE_DELETE_FILE: buildApiUrl(
    API_CONFIG.ENDPOINTS.WORKSPACE_DELETE_FILE
  ),
  WORKSPACE_UPLOAD_TO: "/proxy/upload-to",
  WORKSPACE_MOVE: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_MOVE),
  WORKSPACE_DELETE_DIR: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_DELETE_DIR),
  WORKSPACE_GENERATED_FILES: buildApiUrl(API_CONFIG.ENDPOINTS.WORKSPACE_GENERATED_FILES),
  EXECUTE_CODE: buildApiUrl(API_CONFIG.ENDPOINTS.EXECUTE_CODE),
  EXPORT_REPORT: buildApiUrl(API_CONFIG.ENDPOINTS.EXPORT_REPORT),
  CONVERGENCE_PERSONAS: buildApiUrl(API_CONFIG.ENDPOINTS.CONVERGENCE_PERSONAS),
  CONVERGENCE_STATUS: buildApiUrl(API_CONFIG.ENDPOINTS.CONVERGENCE_STATUS),
  CONVERGENCE_MARKDOWN: buildApiUrl(API_CONFIG.ENDPOINTS.CONVERGENCE_MARKDOWN),
  ML_HEALTH: buildApiUrl(API_CONFIG.ENDPOINTS.ML_HEALTH),
  ML_DATASETS: buildApiUrl(API_CONFIG.ENDPOINTS.ML_DATASETS),
  ML_DATASET_UPLOAD: buildApiUrl(API_CONFIG.ENDPOINTS.ML_DATASET_UPLOAD),
  ML_EXPERIMENTS: buildApiUrl(API_CONFIG.ENDPOINTS.ML_EXPERIMENTS),
  // Chat dùng proxy nội bộ để bypass việc Next.js tự động buffer SSE Stream
  CHAT_COMPLETIONS: "/proxy/chat/completions",
  CHAT_STOP: buildApiUrl(API_CONFIG.ENDPOINTS.CHAT_STOP),
  CONTEXT_USAGE: buildApiUrl(API_CONFIG.ENDPOINTS.CONTEXT_USAGE),
  CHAT_RESET: buildApiUrl(API_CONFIG.ENDPOINTS.CHAT_RESET),
  SKILLS: buildApiUrl(API_CONFIG.ENDPOINTS.SKILLS),
};
