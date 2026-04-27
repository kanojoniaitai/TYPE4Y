use std::collections::HashMap;
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
    source_lang_code: String,
    target_lang_code: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            model_path: r"E:\Type4Y\translategemma-4b-it.Q8_0.gguf".to_string(),
            n_ctx: 2048,
            n_batch: 512,
            n_gpu_layers: 9999,
            temperature: 0.0,
            max_tokens: 1024,
            source_lang_code: "zh".to_string(),
            target_lang_code: "en".to_string(),
        }
    }
}

struct AppState {
    model: std::sync::Mutex<Option<LlamaModel>>,
    backend: std::sync::Mutex<Option<LlamaBackend>>,
    config: AppConfig,
    translating: AtomicBool,
}

static LANGUAGE_NAMES: std::sync::LazyLock<HashMap<&'static str, &'static str>> =
    std::sync::LazyLock::new(|| {
        let mut m = HashMap::new();
        m.insert("en", "English");
        m.insert("zh", "Chinese");
        m.insert("zh-CN", "Chinese");
        m.insert("zh-Hans", "Chinese");
        m.insert("zh-TW", "Chinese");
        m.insert("zh-Hant", "Chinese");
        m.insert("ja", "Japanese");
        m.insert("ko", "Korean");
        m.insert("es", "Spanish");
        m.insert("fr", "French");
        m.insert("de", "German");
        m.insert("ru", "Russian");
        m.insert("it", "Italian");
        m.insert("pt", "Portuguese");
        m.insert("ar", "Arabic");
        m.insert("hi", "Hindi");
        m.insert("th", "Thai");
        m.insert("vi", "Vietnamese");
        m.insert("tr", "Turkish");
        m.insert("pl", "Polish");
        m.insert("nl", "Dutch");
        m.insert("sv", "Swedish");
        m.insert("cs", "Czech");
        m.insert("el", "Greek");
        m.insert("he", "Hebrew");
        m.insert("id", "Indonesian");
        m.insert("ms", "Malay");
        m.insert("fa", "Persian");
        m.insert("uk", "Ukrainian");
        m.insert("ro", "Romanian");
        m.insert("hu", "Hungarian");
        m.insert("da", "Danish");
        m.insert("fi", "Finnish");
        m.insert("no", "Norwegian");
        m.insert("sk", "Slovak");
        m.insert("bg", "Bulgarian");
        m.insert("hr", "Croatian");
        m.insert("sr", "Serbian");
        m.insert("sl", "Slovenian");
        m.insert("lt", "Lithuanian");
        m.insert("lv", "Latvian");
        m.insert("et", "Estonian");
        m.insert("sq", "Albanian");
        m.insert("mk", "Macedonian");
        m.insert("bn", "Bengali");
        m.insert("ta", "Tamil");
        m.insert("te", "Telugu");
        m.insert("mr", "Marathi");
        m.insert("ur", "Urdu");
        m.insert("sw", "Swahili");
        m.insert("af", "Afrikaans");
        m.insert("am", "Amharic");
        m.insert("ne", "Nepali");
        m.insert("my", "Burmese");
        m.insert("km", "Khmer");
        m.insert("lo", "Lao");
        m.insert("pa", "Punjabi");
        m.insert("gu", "Gujarati");
        m.insert("ml", "Malayalam");
        m.insert("si", "Sinhala");
        m.insert("ka", "Georgian");
        m.insert("hy", "Armenian");
        m.insert("az", "Azerbaijani");
        m.insert("eu", "Basque");
        m.insert("ca", "Catalan");
        m.insert("gl", "Galician");
        m.insert("is", "Icelandic");
        m.insert("ga", "Irish");
        m.insert("cy", "Welsh");
        m.insert("mt", "Maltese");
        m.insert("lb", "Luxembourgish");
        m
    });

fn get_language_name(code: &str) -> String {
    LANGUAGE_NAMES
        .get(code)
        .unwrap_or(&"Unknown")
        .to_string()
}

fn detect_language(text: &str) -> String {
    let has_chinese = text.chars().any(|c| {
        (c >= '\u{4e00}' && c <= '\u{9fff}')
            || (c >= '\u{3400}' && c <= '\u{4dbf}')
            || (c >= '\u{2e80}' && c <= '\u{2eff}')
    });
    let has_japanese = text.chars().any(|c| {
        (c >= '\u{3040}' && c <= '\u{309f}') || (c >= '\u{30a0}' && c <= '\u{30ff}')
    });
    let has_korean = text
        .chars()
        .any(|c| c >= '\u{ac00}' && c <= '\u{d7af}');
    let has_cyrillic = text
        .chars()
        .any(|c| c >= '\u{0400}' && c <= '\u{04ff}');
    let has_arabic = text
        .chars()
        .any(|c| c >= '\u{0600}' && c <= '\u{06ff}');
    let has_thai = text
        .chars()
        .any(|c| c >= '\u{0e00}' && c <= '\u{0e7f}');
    let has_hindi = text
        .chars()
        .any(|c| c >= '\u{0900}' && c <= '\u{097f}');

    if has_chinese && !has_japanese && !has_korean {
        "zh".to_string()
    } else if has_japanese {
        "ja".to_string()
    } else if has_korean {
        "ko".to_string()
    } else if has_cyrillic {
        "ru".to_string()
    } else if has_arabic {
        "ar".to_string()
    } else if has_thai {
        "th".to_string()
    } else if has_hindi {
        "hi".to_string()
    } else {
        "en".to_string()
    }
}

fn build_translategemma_prompt(
    text: &str,
    source_lang_code: &str,
    target_lang_code: &str,
) -> String {
    let source_lang = get_language_name(source_lang_code);
    let target_lang = get_language_name(target_lang_code);

    format!(
        "You are a professional {} ({}) to {} ({}) translator. Your goal is to accurately convey the meaning and nuances of the original {} text while adhering to {} grammar, vocabulary, and cultural sensitivities.\n\
         Produce only the {} translation, without any additional explanations or commentary. Please translate the following {} text into {}:\n\n\n\n\
         {}",
        source_lang, source_lang_code,
        target_lang, target_lang_code,
        source_lang,
        target_lang,
        target_lang,
        source_lang,
        target_lang,
        text
    )
}

fn build_gemma_chat_prompt(user_prompt: &str) -> String {
    format!(
        "<start_of_turn>user\n{}<end_of_turn>\n<start_of_turn>model\n",
        user_prompt
    )
}

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

    let detected_source = detect_language(text);
    let (source_lang, target_lang) = if detected_source == state.config.source_lang_code {
        (state.config.source_lang_code.clone(), state.config.target_lang_code.clone())
    } else {
        (detected_source, state.config.source_lang_code.clone())
    };

    let n_ctx = NonZeroU32::new(state.config.n_ctx).ok_or("Invalid n_ctx")?;
    let ctx_params = LlamaContextParams::default()
        .with_n_ctx(Some(n_ctx))
        .with_n_batch(state.config.n_batch);

    let mut ctx = model
        .new_context(backend, ctx_params)
        .map_err(|e| format!("Context creation failed: {}", e))?;

    let translategemma_prompt = build_translategemma_prompt(text, &source_lang, &target_lang);
    let full_prompt = build_gemma_chat_prompt(&translategemma_prompt);

    let all_tokens = model
        .str_to_token(&full_prompt, AddBos::Always)
        .map_err(|e| format!("Tokenize prompt failed: {}", e))?;

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
fn replace_selected_text(text: String) -> Result<(), String> {
    let mut clipboard = arboard::Clipboard::new().map_err(|e| format!("Clipboard init failed: {}", e))?;
    clipboard.set_text(text).map_err(|e| format!("Clipboard set failed: {}", e))?;

    let mut enigo = Enigo::new(&enigo::Settings::default())
        .map_err(|e| format!("Enigo init failed: {}", e))?;

    enigo.key(enigo::Key::Control, Direction::Press)
        .map_err(|e| format!("Key press failed: {}", e))?;
    enigo.key(enigo::Key::Unicode('v'), Direction::Press)
        .map_err(|e| format!("Key press failed: {}", e))?;
    enigo.key(enigo::Key::Unicode('v'), Direction::Release)
        .map_err(|e| format!("Key release failed: {}", e))?;
    enigo.key(enigo::Key::Control, Direction::Release)
        .map_err(|e| format!("Key release failed: {}", e))?;

    Ok(())
}

#[tauri::command]
fn trigger_translate(app: AppHandle, state: tauri::State<'_, Arc<AppState>>) -> Result<String, String> {
    let text = get_selected_text()?;
    translate(app, state, text)
}

fn trigger_translation_flow(app: &AppHandle) {
    let app_clone = app.clone();
    std::thread::spawn(move || {
        let enigo = Enigo::new(&enigo::Settings::default()).unwrap();
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
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "quit" => {
                        let _ = app.exit(0);
                        std::process::exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    match event {
                        TrayIconEvent::Click { button: tauri::tray::MouseButton::Left, button_state: tauri::tray::MouseButtonState::Up, .. } => {
                            let app = tray.app_handle();
                            trigger_translation_flow(app);
                        }
                        _ => {}
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
        .invoke_handler(tauri::generate_handler![get_status, translate, trigger_translate, replace_selected_text])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
