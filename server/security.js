import { promisify } from 'node:util';
import { randomBytes, scrypt, timingSafeEqual, createHash } from 'node:crypto';

const scryptAsync = promisify(scrypt);
const PASSWORD_KEY_LENGTH = 64;

export function normalizeEmail(email) {
  return String(email || '').trim().toLowerCase();
}

export function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

export async function hashPassword(password) {
  const salt = randomBytes(16).toString('base64url');
  const derivedKey = await scryptAsync(password, salt, PASSWORD_KEY_LENGTH);

  return `scrypt$${salt}$${derivedKey.toString('base64url')}`;
}

export async function verifyPassword(password, storedHash) {
  const [algorithm, salt, key] = String(storedHash || '').split('$');

  if (algorithm !== 'scrypt' || !salt || !key) {
    return false;
  }

  const storedKey = Buffer.from(key, 'base64url');
  const derivedKey = await scryptAsync(password, salt, storedKey.length);

  if (storedKey.length !== derivedKey.length) {
    return false;
  }

  return timingSafeEqual(storedKey, derivedKey);
}

export function createToken() {
  return randomBytes(32).toString('base64url');
}

export function hashToken(token) {
  return createHash('sha256').update(token).digest('base64url');
}

export function sanitizeUser(user) {
  if (!user) {
    return null;
  }

  return {
    id: user.id,
    email: user.email,
    name: user.name,
    status: user.status,
    createdAt: user.created_at,
    lastLoginAt: user.last_login_at,
  };
}
