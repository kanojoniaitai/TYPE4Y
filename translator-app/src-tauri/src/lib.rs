#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().with_handler(|app, shortcut, event| {
            if event.state() == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                let app_handle = app.clone();
                std::thread::spawn(move || {
                    use enigo::{Enigo, Key, KeyboardControllable};
                    use tauri_plugin_clipboard_manager::ClipboardExt;
                    use tauri::Emitter;

                    std::thread::sleep(std::time::Duration::from_millis(50));
                    let mut enigo = Enigo::new();
                    
                    #[cfg(target_os = "macos")]
                    enigo.key_down(Key::Meta);
                    #[cfg(not(target_os = "macos"))]
                    enigo.key_down(Key::Control);

                    enigo.key_click(Key::Layout('c'));

                    #[cfg(target_os = "macos")]
                    enigo.key_up(Key::Meta);
                    #[cfg(not(target_os = "macos"))]
                    enigo.key_up(Key::Control);

                    std::thread::sleep(std::time::Duration::from_millis(100));

                    if let Ok(text) = app_handle.clipboard().read_text() {
                        use tauri::Manager;
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                        let _ = app_handle.emit("text-selected", text);
                    }
                });
            }
        }).build())
        .setup(|app| {
            use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};
            use std::str::FromStr;
            let shortcut = Shortcut::from_str("CommandOrControl+Y").unwrap();
            app.global_shortcut().register(shortcut)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
