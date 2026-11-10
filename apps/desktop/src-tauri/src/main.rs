// SPDX-License-Identifier: AGPL-3.0-or-later
//! OpenChart for Windows and macOS: one window over the local stack.
//!
//! The window first shows a bundled "starting" page, then moves to the
//! local web app at http://localhost:PORT. That page gets no access to
//! Tauri's IPC (no capabilities are defined), can't navigate anywhere else,
//! and links to other sites open in the system browser.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::{Arc, Mutex};

use openchart_supervisor::{Layout, SecretStore, Stack};
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_opener::OpenerExt;

const IDENTIFIER: &str = "ai.openchart.desktop";

#[derive(Default)]
struct Running(Mutex<Option<Stack>>);

fn main() {
    let port = Arc::new(AtomicU16::new(0));
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(Running::default())
        .setup({
            let port = port.clone();
            move |app| {
                let window = open_window(app.handle(), port.clone())?;
                let handle = app.handle().clone();
                std::thread::spawn(move || start(handle, window, port));
                Ok(())
            }
        })
        .build(tauri::generate_context!())
        .expect("OpenChart couldn't start its window");

    app.run(|app, event| {
        if let RunEvent::Exit = event {
            stop(app);
        }
    });
}

fn open_window(app: &AppHandle, port: Arc<AtomicU16>) -> tauri::Result<WebviewWindow> {
    let navigation_port = port.clone();
    let navigation_app = app.clone();
    let popup_app = app.clone();
    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("OpenChart")
        .inner_size(1280.0, 820.0)
        .min_inner_size(380.0, 560.0)
        .on_navigation(move |url| {
            let allowed =
                is_bundled(url) || is_local_app(url, navigation_port.load(Ordering::SeqCst));
            if !allowed {
                open_outside(&navigation_app, url);
            }
            allowed
        })
        .on_new_window(move |url, _features| {
            open_outside(&popup_app, &url);
            NewWindowResponse::Deny
        })
        .build()
}

/// The bundled starting page (tauri://localhost, or http(s)://tauri.localhost on Windows).
fn is_bundled(url: &Url) -> bool {
    match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" | "https" => url.host_str() == Some("tauri.localhost"),
        _ => false,
    }
}

fn is_local_app(url: &Url, port: u16) -> bool {
    port != 0
        && url.scheme() == "http"
        && url.host_str() == Some("localhost")
        && url.port() == Some(port)
}

/// Web links open in the system browser; anything else is ignored.
fn open_outside(app: &AppHandle, url: &Url) {
    if matches!(url.scheme(), "http" | "https" | "mailto") {
        let _ = app.opener().open_url(url.as_str(), None::<&str>);
    }
}

fn layout(app: &AppHandle) -> Result<Layout, String> {
    let resources = app.path().resource_dir().map_err(|e| e.to_string())?;
    let data = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let api_name = format!("openchart-api{}", std::env::consts::EXE_SUFFIX);
    Ok(Layout {
        postgres: resources.join("postgres"),
        api: resources.join("api").join(api_name),
        web: resources.join("web"),
        data,
    })
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn secret_store(_layout: &Layout) -> Result<Box<dyn SecretStore>, String> {
    let keychain = openchart_supervisor::Keychain::new(IDENTIFIER).map_err(|e| e.to_string())?;
    Ok(Box::new(keychain))
}

/// Development builds on other systems only: no supported keychain there.
#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn secret_store(layout: &Layout) -> Result<Box<dyn SecretStore>, String> {
    let _ = IDENTIFIER;
    Ok(Box::new(openchart_supervisor::SecretFile(
        layout.data.join("secrets.json"),
    )))
}

fn start(app: AppHandle, window: WebviewWindow, port: Arc<AtomicU16>) {
    let result = layout(&app).and_then(|layout| {
        let store = secret_store(&layout)?;
        Stack::start(&layout, store.as_ref()).map_err(|e| match e.log {
            Some(_) => e.to_string(),
            None => format!("{e} (logs are in {})", layout.logs().display()),
        })
    });
    match result {
        Ok(stack) => {
            port.store(stack.port, Ordering::SeqCst);
            let url = stack.start_url();
            *app.state::<Running>().0.lock().unwrap() = Some(stack);
            if let Ok(url) = Url::parse(&url) {
                let _ = window.navigate(url);
            }
            check_for_update(app);
        }
        Err(message) => show_error(&window, &message),
    }
}

/// Tell the starting page what went wrong. It reads the message from the
/// URL fragment, so no IPC is needed.
fn show_error(window: &WebviewWindow, message: &str) {
    if let Ok(mut url) = window.url() {
        let encoded: String = url_encode(message);
        url.set_fragment(Some(&format!("error={encoded}")));
        let _ = window.navigate(url);
    }
}

fn url_encode(text: &str) -> String {
    text.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                (b as char).to_string()
            }
            _ => format!("%{b:02X}"),
        })
        .collect()
}

fn stop(app: &AppHandle) {
    if let Some(stack) = app.state::<Running>().0.lock().unwrap().take() {
        stack.stop();
    }
}

/// Updates are offered only when this build was given an update key
/// (see docs/guides/desktop.md); each one is checked against it.
fn check_for_update(app: AppHandle) {
    let configured = app
        .config()
        .plugins
        .0
        .get("updater")
        .and_then(|u| u.get("pubkey"))
        .and_then(|k| k.as_str())
        .is_some_and(|k| !k.is_empty());
    if !configured {
        return;
    }
    tauri::async_runtime::spawn(async move {
        use tauri_plugin_updater::UpdaterExt;
        if app
            .plugin(tauri_plugin_updater::Builder::new().build())
            .is_err()
        {
            return;
        }
        let Ok(updater) = app.updater() else { return };
        let Ok(Some(update)) = updater.check().await else {
            return;
        };
        let question = format!(
            "OpenChart {} is available (you have {}). Install it and restart?",
            update.version, update.current_version
        );
        let (tx, rx) = std::sync::mpsc::channel();
        app.dialog()
            .message(question)
            .title("Update available")
            .kind(MessageDialogKind::Info)
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Install".into(),
                "Later".into(),
            ))
            .show(move |yes| {
                let _ = tx.send(yes);
            });
        if !matches!(
            tauri::async_runtime::spawn_blocking(move || rx.recv()).await,
            Ok(Ok(true))
        ) {
            return;
        }
        let Ok(bytes) = update.download(|_, _| {}, || {}).await else {
            app.dialog()
                .message("The update couldn't be downloaded. OpenChart will try again next time.")
                .show(|_| {});
            return;
        };
        // The installer replaces files the stack is using: stop it first,
        // then restart into whichever version is installed.
        stop(&app);
        let _ = update.install(bytes);
        app.restart();
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(text: &str) -> Url {
        Url::parse(text).unwrap()
    }

    #[test]
    fn only_the_local_app_and_starting_page_load_in_the_window() {
        assert!(is_local_app(&url("http://localhost:4100/#desktop=x"), 4100));
        assert!(is_bundled(&url("tauri://localhost/index.html#error=x")));
        assert!(is_bundled(&url("http://tauri.localhost/index.html")));
        for other in [
            "http://localhost:4101/",
            "https://localhost:4100/",
            "http://127.0.0.1:4100/",
            "http://localhost.evil.example:4100/",
            "https://github.com/Jamireoicgamer/Opencharts",
            "file:///etc/passwd",
        ] {
            let other = url(other);
            assert!(
                !is_local_app(&other, 4100) && !is_bundled(&other),
                "{other}"
            );
        }
        // Before the stack is up, no port is allowed.
        assert!(!is_local_app(&url("http://localhost:0/"), 0));
    }

    #[test]
    fn error_text_is_encoded_for_the_fragment() {
        assert_eq!(url_encode("a b&c#é"), "a%20b%26c%23%C3%A9");
    }
}
