export const UI_CONTRACT = "1.0";
const factories = new Map();
let defaultName = "filament-v1";

function major(value) {
  const match = String(value || "").match(/(\d+)/);
  return match ? Number(match[1]) : NaN;
}

export function register(factory) {
  if (!factory || !factory.name || !factory.version || major(factory.contract) !== major(UI_CONTRACT)) {
    return false;
  }
  const key = `${factory.name}@${major(factory.version)}`;
  const current = factories.get(key);
  if (!current || String(factory.version).localeCompare(String(current.version), undefined, { numeric: true }) > 0) {
    factories.set(key, Object.freeze(factory));
  }
  return true;
}

export function resolve(requested = defaultName) {
  const [name, requestedMajor] = String(requested || defaultName).split("@");
  const candidates = [...factories.values()].filter((factory) =>
    factory.name === name && (!requestedMajor || major(factory.version) === Number(requestedMajor))
  );
  candidates.sort((a, b) => String(b.version).localeCompare(String(a.version), undefined, { numeric: true }));
  if (candidates[0]) return candidates[0];
  const defaults = [...factories.values()].filter((factory) => factory.name === defaultName);
  defaults.sort((a, b) => String(b.version).localeCompare(String(a.version), undefined, { numeric: true }));
  return defaults[0] || factories.get("fallback-ring@1");
}

export function listRenderers() {
  return [...factories.values()].map(({ name, version, contract, capabilities }) => ({ name, version, contract, capabilities }));
}

export function setDefaultRenderer(name) {
  defaultName = String(name || "filament-v1");
}
