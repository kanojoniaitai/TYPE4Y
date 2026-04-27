import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow, PhysicalPosition } from "@tauri-apps/api/window";

const popup = document.getElementById("popup")!;
const sourceText = document.getElementById("source-text")!;
const translationText = document.getElementById("translation-text")!;
const loadingIndicator = document.getElementById("loading-indicator")!;
const copyBtn = document.getElementById("copy-btn")!;
const header = document.querySelector(".popup-header")!;

let currentTranslation = "";
let isDragging = false;
let dragOffsetX = 0;
let dragOffsetY = 0;
let isTranslating = false;

const appWindow = getCurrentWindow();

async function hidePopup() {
  await appWindow.hide();
  sourceText.textContent = "";
  translationText.textContent = "";
  loadingIndicator.classList.add("hidden");
  popup.classList.add("hidden");
  currentTranslation = "";
  isTranslating = false;
  translationText.classList.remove("translating");
}

// Drag functionality
header.addEventListener("mousedown", async (e: Event) => {
  const mouseEvent = e as MouseEvent;
  if (mouseEvent.button !== 0) return;
  isDragging = true;
  const pos = await appWindow.outerPosition();
  dragOffsetX = mouseEvent.screenX - pos.x;
  dragOffsetY = mouseEvent.screenY - pos.y;
});

document.addEventListener("mousemove", async (e: Event) => {
  if (!isDragging) return;
  const mouseEvent = e as MouseEvent;
  await appWindow.setPosition(new PhysicalPosition(mouseEvent.screenX - dragOffsetX, mouseEvent.screenY - dragOffsetY));
});

document.addEventListener("mouseup", () => {
  isDragging = false;
});

// Space to confirm and replace selected text
document.addEventListener("keydown", async (e) => {
  if (e.code === "Space" && currentTranslation && !isTranslating) {
    e.preventDefault();
    try {
      await invoke("replace_selected_text", { text: currentTranslation });
      await hidePopup();
    } catch (err) {
      console.error("Failed to replace text:", err);
    }
  }
  // Escape to close
  if (e.code === "Escape") {
    await hidePopup();
  }
});

listen<string>("start-translation", async (event) => {
  sourceText.textContent = event.payload;
  translationText.textContent = "";
  currentTranslation = "";
  isTranslating = true;
  popup.classList.remove("hidden");
  loadingIndicator.classList.remove("hidden");
  translationText.classList.remove("translating");

  try {
    await invoke("translate", { text: event.payload });
  } catch (e) {
    console.error(e);
    translationText.textContent = "Error: " + e;
    loadingIndicator.classList.add("hidden");
    isTranslating = false;
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
  isTranslating = false;
});

listen<string>("translation-error", (event) => {
  console.error("Translation error:", event.payload);
  translationText.textContent = "Error: " + event.payload;
  popup.classList.remove("hidden");
  loadingIndicator.classList.add("hidden");
  translationText.classList.remove("translating");
  isTranslating = false;
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
  isTranslating = false;
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
