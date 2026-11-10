// SPDX-License-Identifier: AGPL-3.0-or-later
//! Runs the desktop app's stack without a window, for the smoke test and
//! development:
//!
//!     openchart-stack --postgres DIR --api EXE --web DIR --data DIR [--secrets-file FILE]
//!
//! Prints one JSON line with the address once it's up, then runs until
//! standard input closes. Without --secrets-file, keys go to the system
//! keychain, as in the app.

use std::io::Read;
use std::path::PathBuf;
use std::process::ExitCode;

use openchart_supervisor::{Layout, SecretFile, SecretStore, Stack};

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("openchart-stack: {message}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let (mut postgres, mut api, mut web, mut data, mut secrets_file) =
        (None, None, None, None, None);
    while let Some(flag) = args.next() {
        let value = args
            .next()
            .map(PathBuf::from)
            .ok_or(format!("{flag} needs a value"))?;
        match flag.as_str() {
            "--postgres" => postgres = Some(value),
            "--api" => api = Some(value),
            "--web" => web = Some(value),
            "--data" => data = Some(value),
            "--secrets-file" => secrets_file = Some(value),
            _ => return Err(format!("unknown option {flag}")),
        }
    }
    let need = |v: Option<PathBuf>, name: &str| v.ok_or(format!("{name} is required"));
    let layout = Layout {
        postgres: need(postgres, "--postgres")?,
        api: need(api, "--api")?,
        web: need(web, "--web")?,
        data: need(data, "--data")?,
    };
    let store: Box<dyn SecretStore> = match secrets_file {
        Some(path) => Box::new(SecretFile(path)),
        None => keychain()?,
    };
    let stack = Stack::start(&layout, store.as_ref()).map_err(|e| e.to_string())?;
    println!(
        "{}",
        serde_json::json!({
            "origin": stack.origin(),
            "port": stack.port,
            "start_url": stack.start_url(),
            "desktop_token": stack.desktop_token,
        })
    );
    let mut sink = Vec::new();
    let _ = std::io::stdin().read_to_end(&mut sink);
    stack.stop();
    println!("{}", serde_json::json!({"stopped": true}));
    Ok(())
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn keychain() -> Result<Box<dyn SecretStore>, String> {
    let keychain = openchart_supervisor::Keychain::new("ai.openchart.desktop.dev")
        .map_err(|e| e.to_string())?;
    Ok(Box::new(keychain))
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn keychain() -> Result<Box<dyn SecretStore>, String> {
    Err("no supported keychain here; pass --secrets-file".into())
}
