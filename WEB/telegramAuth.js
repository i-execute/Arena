// telegramAuth.js
//
// This is the ONLY file allowed to see BOT_TOKEN. It implements exactly the
// algorithm documented in App.js's frontend comment (and in Telegram's own
// docs: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):
//
//   1. Parse initData as a query string. Pull out `hash`, keep the rest.
//   2. Build the "data check string": sort remaining key=value pairs
//      alphabetically by key, join with "\n".
//   3. secret_key = HMAC_SHA256(key = "WebAppData", data = <bot_token>)
//   4. computed_hash = HMAC_SHA256(key = secret_key, data = <data check string>), hex.
//   5. Constant-time compare computed_hash to the `hash` field. Reject on mismatch.
//   6. Reject if auth_date is older than INITDATA_MAX_AGE_HOURS (replay protection).
//   7. Only then trust user.id / user fields from initData.

const crypto = require("crypto");

function verifyTelegramInitData(initData, botToken, maxAgeHours = 24) {
  if (!initData || typeof initData !== "string") {
    return { valid: false, reason: "missing_init_data" };
  }
  if (!botToken) {
    return { valid: false, reason: "server_misconfigured" };
  }

  let params;
  try {
    params = new URLSearchParams(initData);
  } catch {
    return { valid: false, reason: "unparseable" };
  }

  const hash = params.get("hash");
  if (!hash) return { valid: false, reason: "no_hash" };
  params.delete("hash");

  const dataCheckString = [...params.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${v}`)
    .join("\n");

  const secretKey = crypto.createHmac("sha256", "WebAppData").update(botToken).digest();
  const computedHash = crypto.createHmac("sha256", secretKey).update(dataCheckString).digest("hex");

  const a = Buffer.from(computedHash, "hex");
  const b = Buffer.from(hash, "hex");
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return { valid: false, reason: "bad_hash" };
  }

  const authDate = Number(params.get("auth_date")) * 1000;
  if (!authDate || Date.now() - authDate > maxAgeHours * 60 * 60 * 1000) {
    return { valid: false, reason: "expired" };
  }

  let user = {};
  try {
    user = JSON.parse(params.get("user") || "{}");
  } catch {
    return { valid: false, reason: "bad_user_payload" };
  }

  return { valid: true, user, authDate };
}

module.exports = { verifyTelegramInitData };
