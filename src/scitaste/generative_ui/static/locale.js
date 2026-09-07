export const supportedLocales = Object.freeze(new Set(["en", "zh-CN"]));

export function normalizeLocale(value, fallback = "en") {
  return supportedLocales.has(value) ? value : fallback;
}

export function localeFromHash(hash) {
  const marker = hash.indexOf("?");
  if (marker === -1) {
    return null;
  }
  const parameters = new URLSearchParams(hash.slice(marker + 1));
  const requested = parameters.getAll("lang");
  if (requested.length === 0) {
    return null;
  }
  if (requested.length !== 1) {
    return "en";
  }
  return normalizeLocale(requested[0]);
}

export function routeFromHash(hash) {
  const marker = hash.indexOf("?");
  return marker === -1 ? hash : hash.slice(0, marker);
}

export function withLocale(hash, locale) {
  const route = routeFromHash(hash) || "#/";
  return `${route}?lang=${encodeURIComponent(normalizeLocale(locale))}`;
}

export function translateMessage(catalogs, locale, key, values = {}) {
  const template = catalogs[normalizeLocale(locale)]?.[key] ?? catalogs.en?.[key] ?? key;
  return template.replace(/\{([a-z_]+)\}/g, (match, name) => (
    Object.hasOwn(values, name) ? String(values[name]) : match
  ));
}

export function validateCatalogs(catalogs) {
  const englishKeys = Object.keys(catalogs.en || {}).sort();
  if (englishKeys.length === 0) {
    throw new Error("The English locale catalog is empty.");
  }
  for (const locale of supportedLocales) {
    const catalog = catalogs[locale];
    if (!catalog || Array.isArray(catalog) || typeof catalog !== "object") {
      throw new Error(`Locale catalog ${locale} is invalid.`);
    }
    if (JSON.stringify(Object.keys(catalog).sort()) !== JSON.stringify(englishKeys)) {
      throw new Error(`Locale catalog ${locale} does not match the English contract.`);
    }
    for (const [key, value] of Object.entries(catalog)) {
      if (typeof value !== "string" || value.length === 0) {
        throw new Error(`Locale catalog ${locale} has an invalid value for ${key}.`);
      }
    }
  }
}
