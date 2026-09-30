// GitHub Pages replaces this file with the API endpoint configured at build time.
// Local development intentionally defaults to the companion FastAPI process.
window.OPTIGO_API_BASE = ["localhost", "127.0.0.1"].includes(window.location.hostname)
  ? "http://127.0.0.1:8000"
  : "https://optigo-api.onrender.com";
