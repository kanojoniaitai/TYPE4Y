import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

const popup = document.getElementById("popup")!;
const sourceText = document.getElementById("source-text")!;
const translationText = document.getElementById("translation-text")!;
const loadingIndicator = document.getElementById("loading-indicator")!;
const copyBtn = document.getElementById("copy-btn")!;

let currentTranslation = "";

const appWindow = getCurrentWindow();

async function showPopup() {
  await appWindow.show();
  await appWindow.setFocus();
}

async function hidePopup() {
  await appWindow.hide();
  sourceText.textContent = "";
  translationText.textContent = "";
  loadingIndicator.classList.add("hidden");
  popup.classList.add("hidden");
  currentTranslation = "";
  translationText.classList.remove("translating");
}

appWindow.onFocusChanged(({ payload: focused }) => {
  if (!focused) {
    hidePopup();
  }
});

listen<string>("start-translation", async (event) => {
  sourceText.textContent = event.payload;
  translationText.textContent = "";
  currentTranslation = "";
  popup.classList.remove("hidden");
  loadingIndicator.classList.remove("hidden");
  translationText.classList.remove("translating");

  try {
    await invoke("translate", { text: event.payload });
  } catch (e) {
    console.error(e);
    translationText.textContent = "Error: " + e;
    loadingIndicator.classList.add("hidden");
  }
});

listen<string>("translation-token", (event) => {
  popup.classList.remove("hidden");
  loadingIndicator.classList.add("hidden");
  translationText.classList.add("translating");
  
  currentTranslation += event.payload;
  translationText.textContent = currentTranslation;
  translationText.scrollTop = translationText.scrollHeight;
});

listen<string>("translation-done", (event) => {
  translationText.classList.remove("translating");
  currentTranslation = event.payload;
  translationText.textContent = currentTranslation;
});

listen<string>("translation-error", (event) => {
  console.error("Translation error:", event.payload);
  translationText.textContent = "Error: " + event.payload;
  popup.classList.remove("hidden");
  loadingIndicator.classList.add("hidden");
  translationText.classList.remove("translating");
});

listen<string>("model-ready", async () => {
  console.log("Model loaded and ready");
});

listen<string>("model-error", (event) => {
  console.error("Model error:", event.payload);
  translationText.textContent = "Model Error: " + event.payload;
  popup.classList.remove("hidden");
  loadingIndicator.classList.add("hidden");
  translationText.classList.remove("translating");
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

window.addEventListener("DOMContentLoaded", async () => {
  popup.classList.add("hidden");
});