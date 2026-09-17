const keyFor = (base: string) =>
  "rpi360-token:" + base.trim().replace(/\/+$/, "");

/** Browser-local opt-in persistence; existing v2 session tokens remain readable. */
export function savedPairing(base: string): {
  token: string;
  remembered: boolean;
} {
  const key = keyFor(base);
  try {
    const token = localStorage.getItem(key);
    if (token) return { token, remembered: true };
  } catch {
    /* Storage may be disabled; a tab-only session can still work. */
  }
  try {
    return { token: sessionStorage.getItem(key) ?? "", remembered: false };
  } catch {
    return { token: "", remembered: false };
  }
}

/** Call only after successful authentication and the user's storage choice. */
export function savePairing(base: string, token: string, remember: boolean) {
  const key = keyFor(base);
  // Write the destination before removing the old copy to avoid losing a valid token.
  if (remember) {
    localStorage.setItem(key, token);
    sessionStorage.removeItem(key);
  } else {
    sessionStorage.setItem(key, token);
    localStorage.removeItem(key);
  }
}

export function forgetPairing(base: string) {
  const key = keyFor(base);
  try {
    localStorage.removeItem(key);
  } finally {
    sessionStorage.removeItem(key);
  }
}
