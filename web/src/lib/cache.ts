/**
 * SessionStorage cache with TTL support.
 *
 * Stores data as { data, timestamp } in sessionStorage.
 * readCache returns null if the key is missing or expired.
 * clearCache removes keys by prefix (or all keys).
 */

/** Default TTL: 10 minutes. */
export const CACHE_TTL = 10 * 60 * 1000;

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

/** Read cached data. Returns null if missing, expired, or corrupt. */
export function readCache<T>(key: string, ttl: number = CACHE_TTL): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const entry = JSON.parse(raw);
    // Reject old-format entries (raw data without {data, timestamp} wrapper)
    if (!entry || typeof entry !== "object" || !("timestamp" in entry)) {
      sessionStorage.removeItem(key);
      return null;
    }
    if (Date.now() - entry.timestamp > ttl) {
      sessionStorage.removeItem(key);
      return null;
    }
    return entry.data as T;
  } catch {
    sessionStorage.removeItem(key);
    return null;
  }
}

/** Write data to cache with current timestamp. */
export function writeCache<T>(key: string, data: T): void {
  try {
    const entry: CacheEntry<T> = { data, timestamp: Date.now() };
    sessionStorage.setItem(key, JSON.stringify(entry));
  } catch {
    // Quota exceeded — silently ignore
  }
}

/** Clear cached keys. If prefix is given, only keys starting with it. Otherwise all. */
export function clearCache(prefix?: string): void {
  if (!prefix) {
    sessionStorage.clear();
    return;
  }
  for (let i = sessionStorage.length - 1; i >= 0; i--) {
    const key = sessionStorage.key(i);
    if (key?.startsWith(prefix)) {
      sessionStorage.removeItem(key);
    }
  }
}
