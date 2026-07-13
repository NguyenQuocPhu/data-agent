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
  },
};

const normalizeBaseUrl = (baseUrl: string) => baseUrl.replace(/\/+$/, "");

const normalizeEndpoint = (endpoint: string) =>
  endpoint.startsWith("/") ? endpoint : `/${endpoint}`;

export const buildApiUrl = (
  endpoint: string,
  baseUrl: string = API_CONFIG.BACKEND_BASE_URL
) => {
  return `${normalizeBaseUrl(baseUrl)}${normalizeEndpoint(endpoint)}`;
};

export const buildApiUrlWithParams = (
  endpoint: string,
  params: Record<string, string | number | boolean | null | undefined>,
  baseUrl: string = API_CONFIG.BACKEND_BASE_URL
) => {
  const url = new URL(buildApiUrl(endpoint, baseUrl));
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    url.searchParams.set(key, String(value));
  });
  return url.toString();
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
  // Chat dùng proxy nội bộ để bypass việc Next.js tự động buffer SSE Stream
  CHAT_COMPLETIONS: "/proxy/chat/completions",
  CHAT_STOP: buildApiUrl(API_CONFIG.ENDPOINTS.CHAT_STOP),
};
