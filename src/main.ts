import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

const popup = document.getElementById("popup")!;
const sourceText = document.getElementById("source-text")!;
const translationText = document.getElementById("translation-text")!;
const loadingIndicator = document.getElementById("loading-indicator")!;
const copyBtn = document.getElementById("copy-btn")!;

let currentTranslation = "";

async function showPopup() {
  const appWindow = getCurrentWindow();
  await appWindow.show();
  await appWindow.setFocus();
}

async function hidePopup() {
  const appWindow = getCurrentWindow();
  await appWindow.hide();
  sourceText.textContent = "";
  translationText.innerHTML = "";
  loadingIndicator.classList.add("hidden");
  popup.classList.add("hidden");
  currentTranslation = "";
}

function addCursor() {
  const existing = translationText.querySelector(".cursor");
  if (!existing) {
    const cursor = document.createElement("span");
    cursor.className = "cursor";
    translationText.appendChild(cursor);
  }
}

function removeCursor() {
  const cursor = translationText.querySelector(".cursor");
  if (cursor) cursor.remove();
}

listen<string>("translation-token", (event) => {
  popup.classList.remove("hidden");
  loadingIndicator.classList.add("hidden");
  removeCursor();
  currentTranslation += event.payload;
  translationText.textContent = currentTranslation;
  addCursor();
  translationText.scrollTop = translationText.scrollHeight;
});

listen<string>("translation-done", (event) => {
  removeCursor();
  currentTranslation = event.payload;
  translationText.textContent = currentTranslation;
});

listen<string>("model-ready", async () => {
  console.log("Model loaded and ready");
});

listen<string>("model-error", (event) => {
  console.error("Model error:", event.payload);
  translationText.textContent = "Error: " + event.payload;
  popup.classList.remove("hidden");
  loadingIndicator.classList.add("hidden");
});

copyBtn.addEventListener("click", async () => {
  if (currentTranslation) {
    try {
      await navigator.clipboard.writeText(currentTranslation);
      copyBtn.textContent = "✓";
      setTimeout(() => {
        copyBtn.innerHTML = "&#x2398;";
      }, 1500);
    } catch {
      console.error("Failed to copy");
    }
  }
});

window.addEventListener("blur", () => {
  hidePopup();
});

window.addEventListener("DOMContentLoaded", async () => {
  popup.classList.add("hidden");
});
