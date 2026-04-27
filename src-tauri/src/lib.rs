use std::num::NonZeroU32;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use encoding_rs::UTF_8;
use llama_cpp_2::context::params::LlamaContextParams;
use llama_cpp_2::llama_backend::LlamaBackend;
use llama_cpp_2::llama_batch::LlamaBatch;
use llama_cpp_2::model::params::LlamaModelParams;
use llama_cpp_2::model::AddBos;
use llama_cpp_2::model::LlamaModel;
use llama_cpp_2::sampling::LlamaSampler;
use serde::Deserialize;
use tauri::{AppHandle, Emitter, Manager};
use enigo::{Enigo, Keyboard, Mouse, Direction};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};

#[derive(Debug, Deserialize, Clone)]
struct AppConfig {
    model_path: String,
    n_ctx: u32,
    n_batch: u32,
    n_gpu_layers: u32,
    temperature: f32,
    max_tokens: i32,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            model_path: r"E:\Type4Y\translategemma-4b-it.Q8_0.gguf".to_string(),
            n_ctx: 1024,
            n_batch: 512,
            n_gpu_layers: 9999,
            temperature: 0.3,
            max_tokens: 512,
        }
    }
}

struct AppState {
    model: std::sync::Mutex<Option<LlamaModel>>,
    backend: std::sync::Mutex<Option<LlamaBackend>>,
    config: AppConfig,
    translating: AtomicBool,
}

const SYSTEM_PROMPT: &str = "<start_of_turn>user\nTranslate the following text. If it is in Chinese, translate it to English. If it is in English or another language, translate it to Chinese. Only output the translation result, nothing else:\n\n";

#[tauri::command]
fn get_status(state: tauri::State<'_, Arc<AppState>>) -> String {
    let model = state.model.lock().unwrap();
    if model.is_some() {
        "ready".to_string()
    } else {
        "loading".to_string()
    }
}

fn do_translate(
    app: &AppHandle,
    state: &Arc<AppState>,
    text: &str,
) -> Result<String, String> {
    let model_guard = state.model.lock().unwrap();
    let backend_guard = state.backend.lock().unwrap();
    
    let model = model_guard.as_ref().ok_or("Model not loaded")?;
    let backend = backend_guard.as_ref().ok_or("Backend not initialized")?;

    let n_ctx = NonZeroU32::new(state.config.n_ctx).ok_or("Invalid n_ctx")?;
    let ctx_params = LlamaContextParams::default()
        .with_n_ctx(Some(n_ctx))
        .with_n_batch(state.config.n_batch);

    let mut ctx = model
        .new_context(backend, ctx_params)
        .map_err(|e| format!("Context creation failed: {}", e))?;

    let system_tokens = model
        .str_to_token(SYSTEM_PROMPT, AddBos::Always)
        .map_err(|e| format!("Tokenize system prompt failed: {}", e))?;

    let user_suffix = format!("{}<end_of_turn>\n<start_of_turn>model\n", text);
    let user_tokens = model
        .str_to_token(&user_suffix, AddBos::Never)
        .map_err(|e| format!("Tokenize user text failed: {}", e))?;

    let all_tokens: Vec<_> = system_tokens.iter().chain(user_tokens.iter()).copied().collect();
    let prompt_len = all_tokens.len();

    if prompt_len as u32 >= ctx.n_ctx() {
        return Err(format!(
            "Prompt ({} tokens) exceeds context window ({})",
            prompt_len,
            ctx.n_ctx()
        ));
    }

    let n_batch = ctx.n_batch() as usize;
    for (chunk_idx, chunk) in all_tokens.chunks(n_batch).enumerate() {
        let chunk_start = chunk_idx * n_batch;
        let mut batch = LlamaBatch::new(chunk.len(), 1);
        for (i, &token) in chunk.iter().enumerate() {
            let is_last = chunk_start + i + 1 == prompt_len;
            batch
                .add(token, (chunk_start + i) as i32, &[0], is_last)
                .map_err(|e| format!("Batch add failed: {}", e))?;
        }
        ctx.decode(&mut batch)
            .map_err(|e| format!("Decode failed: {}", e))?;
    }

    let mut sampler = LlamaSampler::chain_simple([
        LlamaSampler::temp(state.config.temperature),
        LlamaSampler::greedy(),
    ]);

    sampler.accept_many(&all_tokens);

    let mut n_cur = prompt_len as i32;
    let mut output = String::new();
    let mut decoder = UTF_8.new_decoder();
    let mut logit_idx = (all_tokens.chunks(n_batch).last().map(|c| c.len()).unwrap_or(1) - 1) as i32;

    for _ in 0..state.config.max_tokens {
        let new_token = sampler.sample(&ctx, logit_idx);

        if model.is_eog_token(new_token) {
            break;
        }

        let piece = model
            .token_to_piece(new_token, &mut decoder, false, None)
            .unwrap_or_default();

        if !piece.is_empty() {
            let _ = app.emit("translation-token", &piece);
            output.push_str(&piece);
        }

        let mut next_batch = LlamaBatch::new(1, 1);
        next_batch
            .add(new_token, n_cur, &[0], true)
            .map_err(|e| format!("Batch add failed: {}", e))?;
        n_cur += 1;

        ctx.decode(&mut next_batch)
            .map_err(|e| format!("Decode failed: {}", e))?;
        logit_idx = 0;

        if n_cur as u32 >= ctx.n_ctx() {
            break;
        }
    }

    let _ = app.emit("translation-done", &output);
    Ok(output)
}

#[tauri::command]
fn translate(app: AppHandle, state: tauri::State<'_, Arc<AppState>>, text: String) -> Result<String, String> {
    if state.translating.swap(true, Ordering::SeqCst) {
        return Err("Translation already in progress".to_string());
    }

    let result = do_translate(&app, &state, &text);

    state.translating.store(false, Ordering::SeqCst);
    result
}

fn load_config() -> AppConfig {
    let cwd_path = Path::new("config.toml");
    if cwd_path.exists() {
        if let Ok(content) = std::fs::read_to_string(cwd_path) {
            if let Ok(config) = toml::from_str(&content) {
                return config;
            }
        }
    }

    let exe_dir = std::env::current_exe().unwrap_or_default();
    let config_path = exe_dir
        .parent()
        .unwrap_or(Path::new("."))
        .join("config.toml");

    if config_path.exists() {
        if let Ok(content) = std::fs::read_to_string(&config_path) {
            if let Ok(config) = toml::from_str(&content) {
                return config;
            }
        }
    }

    AppConfig::default()
}

fn get_selected_text() -> Result<String, String> {
    let mut clipboard = arboard::Clipboard::new().map_err(|e| format!("Clipboard init failed: {}", e))?;

    let original = clipboard.get_text().unwrap_or_default();

    clipboard.clear().map_err(|e| format!("Clipboard clear failed: {}", e))?;

    let mut enigo = Enigo::new(&enigo::Settings::default())
        .map_err(|e| format!("Enigo init failed: {}", e))?;

    enigo.key(enigo::Key::Control, Direction::Press)
        .map_err(|e| format!("Key press failed: {}", e))?;
    enigo.key(enigo::Key::Unicode('c'), Direction::Press)
        .map_err(|e| format!("Key press failed: {}", e))?;
    enigo.key(enigo::Key::Unicode('c'), Direction::Release)
        .map_err(|e| format!("Key release failed: {}", e))?;
    enigo.key(enigo::Key::Control, Direction::Release)
        .map_err(|e| format!("Key release failed: {}", e))?;

    let mut selected = String::new();
    for _ in 0..20 {
        std::thread::sleep(std::time::Duration::from_millis(25));
        if let Ok(text) = clipboard.get_text() {
            if !text.is_empty() {
                selected = text;
                break;
            }
        }
    }

    if !original.is_empty() {
        let _ = clipboard.set_text(original);
    } else {
        let _ = clipboard.clear();
    }

    if selected.is_empty() {
        Err("No text selected".to_string())
    } else {
        Ok(selected)
    }
}

#[tauri::command]
fn trigger_translate(app: AppHandle, state: tauri::State<'_, Arc<AppState>>) -> Result<String, String> {
    let text = get_selected_text()?;
    translate(app, state, text)
}

fn show_translation_popup(app: &AppHandle, source: &str) {
    let window = app.get_webview_window("popup").unwrap();
    let _ = window.emit("show-translation", source);
    let _ = window.show();
    let _ = window.set_focus();
}

fn trigger_translation_flow(app: &AppHandle) {
    let app_clone = app.clone();
    std::thread::spawn(move || {
        let mut enigo = Enigo::new(&enigo::Settings::default()).unwrap();
        let (x, y) = enigo.location().unwrap_or((0, 0));
        
        if let Some(window) = app_clone.get_webview_window("popup") {
            let _ = window.set_position(tauri::Position::Physical(tauri::PhysicalPosition::new(x + 15, y + 15)));
            
            match get_selected_text() {
                Ok(text) => {
                    let _ = window.emit("start-translation", text);
                }
                Err(e) => {
                    let _ = window.emit("translation-error", format!("Failed to get text: {}", e));
                }
            }
            
            let _ = window.show();
            let _ = window.set_focus();
        }
    });
}

use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, Modifiers, Code, ShortcutState};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let config = load_config();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new()
            .with_handler(|app, shortcut, event| {
                if event.state == ShortcutState::Pressed {
                    if shortcut.matches(Modifiers::CONTROL, Code::KeyY) {
                        trigger_translation_flow(app);
                    }
                }
            })
            .build())
        .manage(Arc::new(AppState {
            model: std::sync::Mutex::new(None),
            backend: std::sync::Mutex::new(None),
            config: config.clone(),
            translating: AtomicBool::new(false),
        }))
        .setup(|app| {
            let app_handle = app.handle().clone();
            let state: Arc<AppState> = app.state::<Arc<AppState>>().inner().clone();
            let config = state.config.clone();

            let quit_i = MenuItem::with_id(app.handle(), "quit", "Exit", true, None::<&str>)?;
            let menu = Menu::with_items(app.handle(), &[&quit_i])?;
            
            let tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Type4Y Translate - Loading...")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { .. } = event {
                        let app = tray.app_handle();
                        trigger_translation_flow(app);
                    }
                })
                .build(app.handle())?;

            let ctrl_y = Shortcut::new(Some(Modifiers::CONTROL), Code::KeyY);
            if let Err(e) = app.global_shortcut().register(ctrl_y) {
                eprintln!("Failed to register shortcut: {}", e);
            }

            std::thread::spawn(move || {
                let backend = match LlamaBackend::init() {
                    Ok(b) => b,
                    Err(e) => {
                        eprintln!("Backend init failed: {}", e);
                        let _ = app_handle.emit("model-error", format!("Backend init failed: {}", e));
                        return;
                    }
                };

                if !backend.supports_gpu_offload() {
                    eprintln!("Warning: GPU offload not supported, falling back to CPU");
                }

                let model_params = LlamaModelParams::default()
                    .with_n_gpu_layers(config.n_gpu_layers);

                let model = match LlamaModel::load_from_file(
                    &backend,
                    Path::new(&config.model_path),
                    &model_params,
                ) {
                    Ok(m) => m,
                    Err(e) => {
                        eprintln!("Model load failed: {}", e);
                        let _ = app_handle.emit("model-error", format!("Model load failed: {}", e));
                        return;
                    }
                };

                {
                    let mut model_guard = state.model.lock().unwrap();
                    let mut backend_guard = state.backend.lock().unwrap();
                    *model_guard = Some(model);
                    *backend_guard = Some(backend);
                }

                let _ = app_handle.emit("model-ready", ());
                let _ = tray.set_tooltip(Some("Type4Y Translate - Ready"));
                eprintln!("Model loaded successfully!");
            });

            let window = app.get_webview_window("popup").unwrap();
            let _ = window.hide();

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_status, translate, trigger_translate])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
