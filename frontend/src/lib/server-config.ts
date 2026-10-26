/** Server-only configuration for the backend-for-frontend (BFF) routes. */
export const API_URL = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const TOKEN_COOKIE = "sh_session";
