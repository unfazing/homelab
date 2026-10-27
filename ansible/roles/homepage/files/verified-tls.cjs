// Homepage 2.7.0 creates widget HTTPS agents with rejectUnauthorized:false.
// Enforce certificate verification before follow-redirects/Next.js are loaded.
// NODE_EXTRA_CA_CERTS supplies only blue's public CA; no global TLS bypass.
const https = require('node:https');
const fs = require('node:fs');
// Auth expects environment values, not HOMEPAGE_FILE_* YAML substitutions.
// Read protected mounts inside the process; secrets never enter Compose/inspect.
if (process.env.HOMEPAGE_AUTH_ENABLED === 'true') {
  process.env.HOMEPAGE_AUTH_PASSWORD = fs.readFileSync('/run/secrets/dashboard-password', 'utf8').trim();
  process.env.HOMEPAGE_AUTH_SECRET = fs.readFileSync('/run/secrets/session-secret', 'utf8').trim();
  if (!process.env.HOMEPAGE_AUTH_PASSWORD || process.env.HOMEPAGE_AUTH_SECRET.length < 32) {
    throw new Error('Native authentication secrets are missing or invalid');
  }
}
const Agent = https.Agent;
https.Agent = class VerifiedAgent extends Agent {
  constructor(options = {}) {
    super({ ...options, rejectUnauthorized: true });
  }
};
