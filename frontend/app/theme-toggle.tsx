"use client";

import { useSyncExternalStore } from "react";

const storageKey = "transitpulse-theme";
const themeChanged = "transitpulse-theme-change";
let fallbackDark = false;

function subscribe(notify: () => void) {
  window.addEventListener("storage", notify);
  window.addEventListener(themeChanged, notify);
  return () => {
    window.removeEventListener("storage", notify);
    window.removeEventListener(themeChanged, notify);
  };
}

function readTheme() {
  try {
    return window.localStorage.getItem(storageKey) === "dark";
  } catch {
    return fallbackDark;
  }
}

export default function ThemeToggle() {
  const dark = useSyncExternalStore(subscribe, readTheme, () => false);

  function toggleTheme() {
    fallbackDark = !dark;
    try {
      window.localStorage.setItem(storageKey, dark ? "light" : "dark");
    } catch {
      // Keep the switch usable when the browser blocks storage.
    }
    window.dispatchEvent(new Event(themeChanged));
  }

  return (
    <button
      className="theme-toggle"
      type="button"
      role="switch"
      aria-label="Night mode"
      aria-checked={dark}
      onClick={toggleTheme}
    >
      <span className="theme-icon" aria-hidden="true">{dark ? "☾" : "☀"}</span>
      <span>{dark ? "Night" : "Day"}</span>
    </button>
  );
}
