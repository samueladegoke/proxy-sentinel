const apiUrl = (process.env.VITE_API_URL || '').trim();

if (!apiUrl) {
  console.error('VITE_API_URL is required before running a production build.');
  process.exit(1);
}

try {
  new URL(apiUrl);
} catch {
  console.error(`VITE_API_URL must be a valid absolute URL. Received: ${apiUrl}`);
  process.exit(1);
}
